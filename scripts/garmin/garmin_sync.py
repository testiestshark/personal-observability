"""Automatic Garmin Connect daily-health sync for Personal Observability.

The worker deliberately authenticates to Supabase as the app user. Its writes
therefore pass through the same Row Level Security policies as browser requests;
it never receives the service-role key.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import sys
import time
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from garminconnect import Garmin


SOURCE = "garmin"
PROVIDER = "garmin_connect_unofficial"
DEFAULT_DAYS = 7
LONDON = ZoneInfo("Europe/London")
# Splits cost one Garmin request per activity, so requests are spaced out: a
# backfill of a long history would otherwise be a burst against an undocumented API.
SPLITS_PAUSE_SECONDS = 1.0
ACTIVITIES_PAGE_SIZE = 500
FOOT_ACTIVITY_PATTERN = re.compile(r"running|walking|hiking")


class SyncError(RuntimeError):
    """An actionable sync failure safe to print without leaking secrets."""


def docker_host_url(value: str, in_docker: bool) -> str:
    """Make a host-local Supabase URL reachable from the worker container."""
    if not in_docker:
        return value.rstrip("/")

    parsed = urlsplit(value)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return value.rstrip("/")

    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(
        (parsed.scheme, f"host.docker.internal{port}", parsed.path, parsed.query, parsed.fragment)
    ).rstrip("/")


def current_london_day(now: datetime | None = None) -> date:
    """Return the product's calendar day, including the BST boundary."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(LONDON).date()


def normalize_steps(rows: Any, user_id: str, synced_at: str) -> list[dict[str, Any]]:
    """Translate Garmin's range payload into idempotent database rows.

    Missing measurements remain missing: they are skipped rather than silently
    becoming zero. Garmin has used both totalSteps and steps in payload variants,
    so the provider boundary accepts either while exposing one canonical field.
    """
    if not isinstance(rows, list):
        raise SyncError("Garmin returned an unexpected daily-steps response.")

    normalized_by_day: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue

        day = item.get("calendarDate") or item.get("date")
        steps = item.get("totalSteps")
        if steps is None:
            steps = item.get("steps")

        if not isinstance(day, str) or not isinstance(steps, int) or isinstance(steps, bool):
            continue
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        if steps < 0:
            continue

        normalized_by_day[day] = {
            "user_id": user_id,
            "day": day,
            "steps": steps,
            "source": SOURCE,
            "provider": PROVIDER,
            "external_id": f"garmin:{day}",
            "synced_at": synced_at,
        }

    return [normalized_by_day[day] for day in sorted(normalized_by_day)]


def _whole_non_negative(value: Any) -> int | None:
    """Return a provider measurement as a whole number, or None when invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return round(value)


def _number_non_negative(value: Any) -> float | None:
    """Return a finite non-negative provider number, or None when invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return float(value)


def _provider_utc_timestamp(value: Any) -> str | None:
    """Normalize Garmin GMT timestamps, which vary between epoch-ms and text."""
    instant: datetime
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            instant = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        candidate = value.strip().replace(" ", "T")
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            instant = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        else:
            instant = instant.astimezone(timezone.utc)
    else:
        return None
    return instant.isoformat()


def _sleep_fields(payload: Any) -> dict[str, Any]:
    """Extract only the agreed nightly sleep summary from Garmin's response."""
    if not isinstance(payload, dict):
        return {}
    sleep = payload.get("dailySleepDTO")
    if not isinstance(sleep, dict):
        return {}

    return {
        "sleep_start_at": _provider_utc_timestamp(
            sleep.get("sleepStartTimestampGMT")
        ),
        "sleep_end_at": _provider_utc_timestamp(sleep.get("sleepEndTimestampGMT")),
        "total_sleep_seconds": _whole_non_negative(sleep.get("sleepTimeSeconds")),
    }


def _vo2_max(payload: Any) -> float | None:
    """Extract Garmin's running VO2 max, accepting its list/object variants."""
    if isinstance(payload, list):
        for entry in payload:
            value = _vo2_max(entry)
            if value is not None:
                return value
        return None
    candidate = payload
    if not isinstance(candidate, dict):
        return None

    most_recent = candidate.get("mostRecentVO2Max")
    if most_recent is not None:
        value = _vo2_max(most_recent)
        if value is not None:
            return value

    generic = candidate.get("generic")
    if isinstance(generic, dict):
        value = generic.get("vo2MaxValue")
        if value is None:
            value = generic.get("vo2MaxPreciseValue")
    else:
        value = candidate.get("vo2MaxValue")
        if value is None:
            value = candidate.get("vo2MaxPreciseValue")
    normalized = _number_non_negative(value)
    return normalized if normalized and normalized > 0 else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_activities(
    rows: Any, user_id: str, synced_at: str
) -> list[dict[str, Any]]:
    """Translate Garmin activity summaries without retaining route coordinates."""
    if not isinstance(rows, list):
        raise SyncError("Garmin returned an unexpected activities response.")

    normalized_by_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        activity_id = item.get("activityId")
        if isinstance(activity_id, bool) or not isinstance(activity_id, (int, str)):
            continue
        external_id = str(activity_id).strip()
        if not external_id:
            continue

        started_at = _provider_utc_timestamp(item.get("startTimeGMT"))
        if not started_at:
            continue
        local_start = _text(item.get("startTimeLocal"))
        local_day = local_start[:10] if local_start else started_at[:10]
        try:
            date.fromisoformat(local_day)
        except ValueError:
            continue

        activity_type = item.get("activityType")
        if not isinstance(activity_type, dict):
            activity_type = item.get("activityTypeDTO")
        type_key = (
            _text(activity_type.get("typeKey"))
            if isinstance(activity_type, dict)
            else None
        )
        if not type_key:
            type_key = "other"

        normalized_by_id[external_id] = {
            "user_id": user_id,
            "source": SOURCE,
            "provider": PROVIDER,
            "external_id": external_id,
            "activity_name": _text(item.get("activityName")),
            "activity_type": type_key,
            "local_day": local_day,
            "started_at": started_at,
            "duration_seconds": _number_non_negative(item.get("duration")),
            "moving_duration_seconds": _number_non_negative(
                item.get("movingDuration")
            ),
            "elapsed_duration_seconds": _number_non_negative(
                item.get("elapsedDuration")
            ),
            "distance_meters": _number_non_negative(item.get("distance")),
            "calories_kcal": _whole_non_negative(item.get("calories")),
            "average_heart_rate_bpm": _whole_non_negative(item.get("averageHR")),
            "maximum_heart_rate_bpm": _whole_non_negative(item.get("maxHR")),
            "elevation_gain_meters": _number_non_negative(item.get("elevationGain")),
            "elevation_loss_meters": _number_non_negative(item.get("elevationLoss")),
            "average_speed_mps": _number_non_negative(item.get("averageSpeed")),
            "maximum_speed_mps": _number_non_negative(item.get("maxSpeed")),
            "average_cadence_spm": _number_non_negative(
                item.get("averageRunningCadenceInStepsPerMinute")
            ),
            "maximum_cadence_spm": _number_non_negative(
                item.get("maxRunningCadenceInStepsPerMinute")
            ),
            "average_power_watts": _number_non_negative(item.get("avgPower")),
            "maximum_power_watts": _number_non_negative(item.get("maxPower")),
            "normalized_power_watts": _number_non_negative(item.get("normPower")),
            "aerobic_training_effect": _number_non_negative(
                item.get("aerobicTrainingEffect")
            ),
            "anaerobic_training_effect": _number_non_negative(
                item.get("anaerobicTrainingEffect")
            ),
            "training_load": _number_non_negative(item.get("activityTrainingLoad")),
            "training_effect_label": _text(item.get("trainingEffectLabel")),
            "total_sets": _whole_non_negative(item.get("totalSets")),
            "active_sets": _whole_non_negative(item.get("activeSets")),
            "total_reps": _whole_non_negative(item.get("totalReps")),
            "total_volume_kg": _number_non_negative(item.get("totalVolume")),
            "synced_at": synced_at,
        }

    return sorted(normalized_by_id.values(), key=lambda row: row["started_at"])


def is_foot_activity(activity_type: str) -> bool:
    """Whether an activity is read as pace, which is where splits are kept.

    Mirrors isFootActivity in src/lib/health/garmin-activity.ts: Garmin's type
    keys vary ("trail_running", "treadmill_running"), so it matches on the word.
    """
    return FOOT_ACTIVITY_PATTERN.search(activity_type) is not None


def normalize_laps(payload: Any) -> list[dict[str, Any]]:
    """Translate Garmin's per-activity splits into lap rows, in recorded order.

    Each measurement is copied by name, so the start and end coordinates Garmin
    returns with every lap are never carried (route maps are a recorded
    non-goal). A lap without a usable duration says nothing and is dropped;
    positions stay contiguous. Missing measurements remain missing.
    """
    if not isinstance(payload, dict):
        raise SyncError("Garmin returned an unexpected splits response.")
    laps = payload.get("lapDTOs")
    if laps is None:
        return []
    if not isinstance(laps, list):
        raise SyncError("Garmin returned an unexpected splits response.")

    rows: list[dict[str, Any]] = []
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        duration = _number_non_negative(lap.get("duration"))
        if not duration:
            continue
        heart_rate = _whole_non_negative(lap.get("averageHR"))
        if heart_rate is not None and not 1 <= heart_rate <= 300:
            heart_rate = None
        rows.append(
            {
                "position": len(rows),
                "distance_meters": _number_non_negative(lap.get("distance")),
                "duration_seconds": duration,
                "average_heart_rate_bpm": heart_rate,
                "elevation_gain_meters": _number_non_negative(lap.get("elevationGain")),
                "elevation_loss_meters": _number_non_negative(lap.get("elevationLoss")),
            }
        )
    return rows


def embedded_count(value: Any) -> int:
    """Read the `[{"count": n}]` PostgREST returns for an embedded count."""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        count = value[0].get("count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    return 0


def activities_needing_splits(rows: list[dict[str, Any]]) -> list[str]:
    """External ids of foot activities that have no stored laps yet.

    Takes `{"external_id", "activity_type", "laps"}` rows. An id that is not a
    plain number is skipped: Garmin's lookup needs an integer, and the id goes
    into a query string.
    """
    return [
        row["external_id"]
        for row in rows
        if isinstance(row.get("external_id"), str)
        and row["external_id"].isdigit()
        and is_foot_activity(str(row.get("activity_type") or ""))
        and row.get("laps") == 0
    ]


@dataclass
class SplitsResult:
    """How many activities got laps stored, and how many failed along the way."""

    stored: int = 0
    failed: int = 0


def store_splits(
    garmin: Any,
    supabase: Any,
    session: dict[str, Any],
    external_ids: list[str],
    pause_seconds: float = SPLITS_PAUSE_SECONDS,
) -> SplitsResult:
    """Fetch and store the laps of each activity, one failure at a time.

    Splits are an extra on top of data the run has already stored, so a failed
    lookup or write is a warning for that activity, not a failed sync: it is
    retried on the next run while the activity is still in the window (or by a
    backfill). An activity Garmin reports no laps for is left alone.
    """
    result = SplitsResult()
    for index, external_id in enumerate(external_ids):
        if index and pause_seconds:
            time.sleep(pause_seconds)
        try:
            laps = normalize_laps(garmin.get_activity_splits(external_id))
            if laps:
                supabase.replace_laps(external_id, laps, session)
                result.stored += 1
        except Exception as error:  # Garmin's exception hierarchy changes between releases.
            result.failed += 1
            print(
                f"Warning: splits for Garmin activity {external_id} were unavailable: {error}",
                file=sys.stderr,
            )
    return result


def normalize_daily_health(
    rows: Any,
    user_id: str,
    synced_at: str,
    sleep_by_day: dict[str, Any] | None = None,
    max_metrics_by_day: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Translate Garmin daily summaries into the product's canonical fields.

    Total calories include resting metabolism. Active calories are the useful
    movement-only value, so both are retained instead of presenting one
    ambiguous "calories burned" number. Consumed calories are food intake that a
    linked food logger (MyFitnessPal) sends to Garmin; they are null until that
    link exists. The calorie goal is the logger's daily target as it stood that
    day. It is a setting, not a measurement, so it never keeps a day on its own.
    """
    if not isinstance(rows, list):
        raise SyncError("Garmin returned an unexpected daily-health response.")

    normalized_by_day: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue

        day = item.get("calendarDate") or item.get("date")
        if not isinstance(day, str):
            continue
        try:
            date.fromisoformat(day)
        except ValueError:
            continue

        steps = _whole_non_negative(item.get("totalSteps", item.get("steps")))
        active_calories = _whole_non_negative(item.get("activeKilocalories"))
        total_calories = _whole_non_negative(item.get("totalKilocalories"))
        consumed_calories = _whole_non_negative(item.get("consumedKilocalories"))
        calorie_goal = _whole_non_negative(item.get("netCalorieGoal"))
        resting_heart_rate = _whole_non_negative(item.get("restingHeartRate"))
        if resting_heart_rate is not None and not 1 <= resting_heart_rate <= 300:
            resting_heart_rate = None
        sleep = _sleep_fields((sleep_by_day or {}).get(day))
        vo2_max = _vo2_max((max_metrics_by_day or {}).get(day))
        if (
            steps is None
            and active_calories is None
            and total_calories is None
            and consumed_calories is None
            and resting_heart_rate is None
            and not sleep
            and vo2_max is None
        ):
            continue

        normalized_by_day[day] = {
            "user_id": user_id,
            "day": day,
            "steps": steps,
            "active_calories_kcal": active_calories,
            "total_calories_kcal": total_calories,
            "consumed_calories_kcal": consumed_calories,
            "calorie_goal_kcal": calorie_goal,
            "resting_heart_rate_bpm": resting_heart_rate,
            "vo2_max": vo2_max,
            "source_synced_at": _provider_utc_timestamp(
                item.get("lastSyncTimestampGMT")
            ),
            **sleep,
            "source": SOURCE,
            "provider": PROVIDER,
            "external_id": f"garmin:{day}",
            "synced_at": synced_at,
        }

    return [normalized_by_day[day] for day in sorted(normalized_by_day)]


def validate_railway_volume(session_path: Path, token_store: Path) -> None:
    """Refuse a Railway run that would lose bearer tokens after the container exits."""
    if not os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return

    raw_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if not raw_mount:
        raise SyncError("Railway requires a persistent volume mounted at /data.")

    mount = Path(raw_mount).resolve()
    session_paths = (
        ("SUPABASE_SESSION_FILE", session_path),
        ("GARMIN_TOKEN_STORE", token_store),
    )
    for label, path in session_paths:
        try:
            path.resolve().relative_to(mount)
        except ValueError as error:
            message = f"{label} must be stored below the Railway volume at {mount}."
            raise SyncError(message) from error


class SupabaseSession:
    def __init__(self, base_url: str, publishable_key: str, session_file: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.publishable_key = publishable_key
        self.session_file = session_file

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        access_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"apikey": self.publishable_key, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if extra_headers:
            headers.update(extra_headers)

        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("message") or parsed.get("msg") or parsed.get("error_description") or detail
            except json.JSONDecodeError:
                pass
            raise SyncError(f"Supabase request failed ({error.code}): {detail}") from error
        except URLError as error:
            raise SyncError(f"Could not reach Supabase at {self.base_url}: {error.reason}") from error

        return json.loads(raw) if raw else None

    def _save(self, session: dict[str, Any]) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.session_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(session), encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(self.session_file)

    def login(self, email: str, password: str) -> dict[str, Any]:
        session = self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            {"email": email, "password": password},
        )
        if not isinstance(session, dict) or not session.get("refresh_token"):
            raise SyncError("Supabase login succeeded without returning a reusable session.")
        self._save(session)
        return session

    def load(self) -> dict[str, Any]:
        if not self.session_file.exists():
            raise SyncError("App session is missing. Run the Garmin setup command first.")
        try:
            session = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SyncError("The cached app session is unreadable. Run setup again.") from error
        if not isinstance(session, dict):
            raise SyncError("The cached app session is invalid. Run setup again.")
        return session

    def active(self) -> dict[str, Any]:
        session = self.load()
        expires_at = session.get("expires_at", 0)
        if isinstance(expires_at, (int, float)) and expires_at > time.time() + 60:
            return session

        refresh_token = session.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise SyncError("The app refresh token is missing. Run setup again.")
        refreshed = self._request(
            "POST",
            "/auth/v1/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        )
        if not isinstance(refreshed, dict):
            raise SyncError("Supabase did not return a valid refreshed session.")
        self._save(refreshed)
        return refreshed

    @staticmethod
    def _access_token(session: dict[str, Any]) -> str:
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SyncError("The cached app access token is missing. Run setup again.")
        return access_token

    def upsert(self, rows: list[dict[str, Any]], session: dict[str, Any]) -> None:
        if not rows:
            return
        access_token = self._access_token(session)
        self._request(
            "POST",
            "/rest/v1/daily_health_metrics?" + urlencode({"on_conflict": "user_id,day,source"}),
            rows,
            access_token=access_token,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def upsert_activities(
        self, rows: list[dict[str, Any]], session: dict[str, Any]
    ) -> None:
        if not rows:
            return
        access_token = self._access_token(session)
        self._request(
            "POST",
            "/rest/v1/fitness_activities?"
            + urlencode({"on_conflict": "user_id,source,external_id"}),
            rows,
            access_token=access_token,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def activity_lap_counts(
        self, session: dict[str, Any], external_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Garmin activities with how many laps are stored for each, newest first.

        Pass `external_ids` to look only at those; None reads them all, a page at
        a time. Row Level Security limits this to the signed-in user's rows.
        """
        if external_ids is not None:
            # The ids go into a query string, so only plain numbers are let through.
            external_ids = [value for value in external_ids if value.isdigit()]
            if not external_ids:
                return []
        access_token = self._access_token(session)
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            query = {
                "select": "external_id,activity_type,fitness_activity_laps(count)",
                "source": "eq.garmin",
                "order": "started_at.desc,id.asc",
                "limit": str(ACTIVITIES_PAGE_SIZE),
                "offset": str(offset),
            }
            if external_ids is not None:
                query["external_id"] = f"in.({','.join(external_ids)})"
            page = self._request(
                "GET",
                "/rest/v1/fitness_activities?" + urlencode(query),
                access_token=access_token,
            )
            if not isinstance(page, list):
                raise SyncError("Supabase returned an unexpected activities response.")
            rows.extend(
                {
                    "external_id": item.get("external_id"),
                    "activity_type": item.get("activity_type"),
                    "laps": embedded_count(item.get("fitness_activity_laps")),
                }
                for item in page
                if isinstance(item, dict)
            )
            if len(page) < ACTIVITIES_PAGE_SIZE:
                return rows
            offset += ACTIVITIES_PAGE_SIZE

    def replace_laps(
        self, external_id: str, laps: list[dict[str, Any]], session: dict[str, Any]
    ) -> None:
        """Replace one Garmin activity's laps as a unit, through the database function."""
        self._request(
            "POST",
            "/rest/v1/rpc/replace_fitness_activity_laps",
            {"p_source": SOURCE, "p_external_id": external_id, "p_laps": laps},
            access_token=self._access_token(session),
        )


def configuration() -> tuple[SupabaseSession, Path]:
    raw_url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not raw_url or not key:
        raise SyncError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required in .env.local.")

    in_docker = os.getenv("GARMIN_SYNC_IN_DOCKER", "").lower() == "true"
    base_url = docker_host_url(raw_url, in_docker)
    session_path = Path(os.getenv("SUPABASE_SESSION_FILE", "/data/supabase-session.json"))
    token_store = Path(os.getenv("GARMIN_TOKEN_STORE", "/data/garmin"))
    validate_railway_volume(session_path, token_store)
    return SupabaseSession(base_url, key, session_path), token_store


def app_environment() -> str:
    value = os.getenv("PERSONAL_OBSERVABILITY_ENVIRONMENT", "local").strip().lower()
    return value if value in {"local", "live"} else "configured"


def authenticate_app(supabase: SupabaseSession) -> tuple[dict[str, Any], str]:
    environment = app_environment()
    print(f"Sign in to the {environment} Personal Observability app account.")
    app_email = input("App email: ").strip()
    app_password = getpass.getpass("App password: ")
    try:
        session = supabase.login(app_email, app_password)
    finally:
        del app_password

    user = session.get("user") if isinstance(session, dict) else None
    identity = user.get("email") if isinstance(user, dict) else app_email
    return session, identity


def session_for_sync(supabase: SupabaseSession) -> dict[str, Any]:
    """Use dedicated runtime credentials when configured, otherwise reuse the cache."""
    app_email = os.getenv("PERSONAL_OBSERVABILITY_APP_EMAIL", "").strip()
    app_password = os.getenv("PERSONAL_OBSERVABILITY_APP_PASSWORD", "")
    if bool(app_email) != bool(app_password):
        raise SyncError(
            "PERSONAL_OBSERVABILITY_APP_EMAIL and "
            "PERSONAL_OBSERVABILITY_APP_PASSWORD must be configured together."
        )
    if app_email and app_password:
        return supabase.login(app_email, app_password)
    return supabase.active()


def setup_app() -> None:
    supabase, token_store = configuration()
    _, app_identity = authenticate_app(supabase)
    token_file = token_store / "garmin_tokens.json"
    garmin_state = "present and will be reused" if token_file.exists() else "missing"
    print(f"App setup complete for {app_identity}.")
    print(f"Garmin session: {garmin_state}.")


def setup() -> None:
    supabase, token_store = configuration()
    _, app_identity = authenticate_app(supabase)

    print("\nSign in to Garmin Connect. Credentials are sent to Garmin and are not stored.")
    garmin_email = input("Garmin email: ").strip()
    garmin_password = getpass.getpass("Garmin password: ")
    token_store.mkdir(parents=True, exist_ok=True)
    token_store.chmod(stat.S_IRWXU)
    garmin = Garmin(
        garmin_email,
        garmin_password,
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )
    garmin.login(str(token_store))
    del garmin_password

    print(f"Setup complete for {app_identity}. Tokens are under .garmin-sync/ (gitignored).")


def sync(days: int) -> None:
    if days < 1 or days > 365:
        raise SyncError("--days must be between 1 and 365.")

    supabase, token_store = configuration()
    session = session_for_sync(supabase)
    user = session.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise SyncError("The cached app session has no user id. Run setup again.")

    garmin = Garmin()
    garmin.login(str(token_store))

    end = current_london_day()
    start = end - timedelta(days=days - 1)
    raw_rows = []
    sleep_by_day: dict[str, Any] = {}
    max_metrics_by_day: dict[str, Any] = {}
    for offset in range(days):
        requested_day = (start + timedelta(days=offset)).isoformat()
        summary = garmin.get_stats(requested_day)
        if isinstance(summary, dict) and not summary.get("calendarDate"):
            summary = {**summary, "calendarDate": requested_day}
        raw_rows.append(summary)
        try:
            sleep_by_day[requested_day] = garmin.get_sleep_data(requested_day)
        except Exception as error:
            print(
                f"Warning: Garmin sleep was unavailable for {requested_day}: {error}",
                file=sys.stderr,
            )
        try:
            max_metrics_by_day[requested_day] = garmin.get_max_metrics(requested_day)
        except Exception as error:
            print(
                f"Warning: Garmin VO2 max was unavailable for {requested_day}: {error}",
                file=sys.stderr,
            )

    end_day = end.isoformat()
    if _vo2_max(max_metrics_by_day.get(end_day)) is None:
        try:
            max_metrics_by_day[end_day] = garmin.get_training_status(end_day)
        except Exception as error:
            print(
                f"Warning: Garmin's latest VO2 max was unavailable: {error}",
                file=sys.stderr,
            )

    try:
        raw_activities = garmin.get_activities_by_date(
            start.isoformat(), end.isoformat(), sortorder="asc"
        )
    except Exception as error:
        print(f"Warning: Garmin activities were unavailable: {error}", file=sys.stderr)
        raw_activities = []

    synced_at = datetime.now(timezone.utc).isoformat()
    rows = normalize_daily_health(
        raw_rows,
        user_id,
        synced_at,
        sleep_by_day=sleep_by_day,
        max_metrics_by_day=max_metrics_by_day,
    )
    activities = normalize_activities(raw_activities, user_id, synced_at)
    if not rows:
        raise SyncError(
            "Garmin returned no usable daily-health records for the requested range."
        )

    supabase.upsert(rows, session)
    supabase.upsert_activities(activities, session)
    print(
        f"Synced {len(rows)} Garmin health day(s), "
        f"{rows[0]['day']} to {rows[-1]['day']}, "
        f"plus {len(activities)} recorded activity/activities."
    )

    # The window's activities are revisited every run, but their splits are
    # asked for only while none are stored: one request per new activity, not
    # one per activity per run.
    foot_ids = [
        row["external_id"] for row in activities if is_foot_activity(row["activity_type"])
    ]
    try:
        pending = activities_needing_splits(supabase.activity_lap_counts(session, foot_ids))
    except SyncError as error:
        print(f"Warning: stored splits could not be checked: {error}", file=sys.stderr)
        pending = []
    if pending:
        splits = store_splits(garmin, supabase, session, pending)
        print(f"Stored splits for {splits.stored} of {len(pending)} activity/activities.")


def backfill_splits(limit: int | None) -> None:
    """One-off: fetch splits for every stored foot activity that has none yet.

    Safe to repeat: activities that already have laps are skipped, so a run cut
    short by --limit or a Garmin rate limit is continued by running it again.
    Newest activities come first.
    """
    if limit is not None and limit < 1:
        raise SyncError("--limit must be at least 1.")

    supabase, token_store = configuration()
    session = session_for_sync(supabase)
    garmin = Garmin()
    garmin.login(str(token_store))

    pending = activities_needing_splits(supabase.activity_lap_counts(session))
    total = len(pending)
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        print("No stored Garmin foot activities are missing splits.")
        return

    print(f"Fetching splits for {len(pending)} of {total} activity/activities missing them.")
    splits = store_splits(garmin, supabase, session, pending)
    remaining = total - splits.stored
    print(
        f"Stored splits for {splits.stored} activity/activities "
        f"({splits.failed} failed). {remaining} still without splits."
    )


def status() -> None:
    supabase, token_store = configuration()
    email = None
    app_state = "missing"
    if supabase.session_file.exists():
        try:
            session = supabase.load()
            user = session.get("user")
            email = user.get("email") if isinstance(user, dict) else None
            app_state = "present" if email else "invalid"
        except SyncError:
            app_state = "invalid"
    token_file = token_store / "garmin_tokens.json"
    print(f"Environment: {app_environment()}")
    print(f"App session: {app_state}{f' ({email})' if email else ''}")
    print(f"Garmin session: {'present' if token_file.exists() else 'missing'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Garmin daily health into Personal Observability."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup", help="Authenticate once to the app and Garmin Connect.")
    subcommands.add_parser(
        "setup-app", help="Authenticate only to the app while reusing cached Garmin tokens."
    )
    sync_parser = subcommands.add_parser(
        "sync", help="Fetch and upsert recent health and recorded activities."
    )
    sync_parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    backfill_parser = subcommands.add_parser(
        "backfill-splits",
        help="Fetch splits for stored runs and walks that have none (one-off, repeatable).",
    )
    backfill_parser.add_argument(
        "--limit", type=int, default=None, help="Fetch at most this many, newest first."
    )
    subcommands.add_parser("status", help="Check whether both cached sessions exist.")
    subcommands.add_parser("test", help="Run the worker unit tests.")
    args = parser.parse_args()

    try:
        if args.command == "setup":
            setup()
        elif args.command == "setup-app":
            setup_app()
        elif args.command == "sync":
            sync(args.days)
        elif args.command == "backfill-splits":
            backfill_splits(args.limit)
        elif args.command == "status":
            status()
        else:
            suite = unittest.defaultTestLoader.discover(".", pattern="test_garmin_sync.py")
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    except (SyncError, KeyboardInterrupt) as error:
        message = "Cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except Exception as error:  # Garmin's exception hierarchy changes between releases.
        print(f"Garmin sync failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
