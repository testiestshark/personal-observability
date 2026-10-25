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
from dataclasses import dataclass, field
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
# Failures this many in a row mean Garmin is rate-limiting or down: stop asking.
MAX_CONSECUTIVE_SPLIT_FAILURES = 5
ACTIVITIES_PAGE_SIZE = 500
FOOT_ACTIVITY_PATTERN = re.compile(r"running|walking|hiking")
# "treadmill_running" matches the foot pattern but has no outdoor weather.
INDOOR_ACTIVITY_PATTERN = re.compile(r"treadmill|indoor|virtual")
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_SOURCE = "open-meteo-archive"
WEATHER_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
)
# Open-Meteo's grid is coarser than this, and a one-decimal area (about 11 km)
# cannot be traced back to a start position (docs/adr/0001).
WEATHER_COORDINATE_DECIMALS = 1
# Weather is an extra: a few failures in a row mean it is down or rate-limiting.
MAX_CONSECUTIVE_WEATHER_FAILURES = 3


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

    A copy of isFootActivity in src/lib/health/garmin-activity.ts, which is
    what decides how the app reads the activity: change both together. Garmin's
    type keys vary ("trail_running", "treadmill_running"), so it matches on the
    word.
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


def has_embedded_rows(value: Any) -> bool:
    """Whether PostgREST embedded at least one row of a child table."""
    return isinstance(value, list) and len(value) > 0


def is_garmin_activity_id(value: Any) -> bool:
    """Whether a value is a plain number Garmin's lookup accepts.

    ASCII only: str.isdigit() also accepts "\u00b2", which Garmin's integer
    parse rejects. The id goes into a query string, so nothing else gets in.
    """
    return isinstance(value, str) and value.isascii() and value.isdecimal()


def activities_needing_splits(rows: list[dict[str, Any]]) -> list[str]:
    """External ids of foot activities that have no stored laps yet.

    Takes `{"external_id", "activity_type", "has_laps"}` rows.
    """
    return [
        row["external_id"]
        for row in rows
        if is_garmin_activity_id(row.get("external_id"))
        and is_foot_activity(str(row.get("activity_type") or ""))
        and row.get("has_laps") is False
    ]


@dataclass
class SplitsResult:
    """How many activities got laps stored, and how many failed along the way."""

    stored: int = 0
    failed: int = 0
    stopped_early: bool = False


def store_splits(
    garmin: Any,
    supabase: Any,
    session: dict[str, Any],
    external_ids: list[str],
    pause_seconds: float = SPLITS_PAUSE_SECONDS,
    max_stored: int | None = None,
    max_consecutive_failures: int = MAX_CONSECUTIVE_SPLIT_FAILURES,
) -> SplitsResult:
    """Fetch and store the laps of each activity, one failure at a time.

    Splits are an extra on top of data the run has already stored, so a failed
    lookup or write is a warning for that activity, not a failed sync: it is
    retried on the next run while the activity is still in the window (or by a
    backfill). An activity Garmin reports no laps for is left alone.

    `max_stored` stops once that many activities have laps, so activities with
    none do not use up a limit. A run of `max_consecutive_failures` failures
    stops the loop: that is a rate limit or an outage, and more requests only
    make it worse.
    """
    result = SplitsResult()
    consecutive_failures = 0
    for index, external_id in enumerate(external_ids):
        if max_stored is not None and result.stored >= max_stored:
            break
        if index and pause_seconds:
            time.sleep(pause_seconds)
        try:
            laps = normalize_laps(garmin.get_activity_splits(external_id))
            if laps:
                supabase.replace_laps(external_id, laps, session)
                result.stored += 1
            consecutive_failures = 0
        except Exception as error:  # Garmin's exception hierarchy changes between releases.
            result.failed += 1
            consecutive_failures += 1
            print(
                f"Warning: splits for Garmin activity {external_id} were unavailable: {error}",
                file=sys.stderr,
            )
            if consecutive_failures >= max_consecutive_failures:
                result.stopped_early = True
                print(
                    f"Warning: {consecutive_failures} splits lookups failed in a row; "
                    "stopping. The remaining activities are retried on the next run.",
                    file=sys.stderr,
                )
                break
    return result


@dataclass(frozen=True)
class RunStart:
    """Where and when an outdoor run began, rounded, for one weather request.

    The coordinate is kept out of repr so that printing or logging one cannot
    leak it. It is used in memory for the request and never stored.
    """

    external_id: str
    started_at: datetime
    latitude: float = field(repr=False)
    longitude: float = field(repr=False)


def _coordinate(value: Any, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or abs(value) > limit:
        return None
    return float(value)


def outdoor_run_starts(rows: Any) -> list[RunStart]:
    """Start points of outdoor foot activities, rounded for the weather request.

    Indoor activities are told apart by what Garmin leaves out: a treadmill run
    has no start coordinate at all, and a 0,0 one is a watch without a fix. The
    type key is a second guard. Anything else is skipped rather than guessed.
    """
    if not isinstance(rows, list):
        return []
    starts: dict[str, RunStart] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        activity_id = item.get("activityId")
        if isinstance(activity_id, bool) or not isinstance(activity_id, (int, str)):
            continue
        external_id = str(activity_id).strip()
        if not is_garmin_activity_id(external_id):
            continue

        activity_type = item.get("activityType")
        if not isinstance(activity_type, dict):
            activity_type = item.get("activityTypeDTO")
        type_key = _text(activity_type.get("typeKey")) if isinstance(activity_type, dict) else None
        if not type_key or not is_foot_activity(type_key):
            continue
        if INDOOR_ACTIVITY_PATTERN.search(type_key):
            continue

        latitude = _coordinate(item.get("startLatitude"), 90)
        longitude = _coordinate(item.get("startLongitude"), 180)
        if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
            continue

        started_at = _provider_utc_timestamp(item.get("startTimeGMT"))
        if not started_at:
            continue
        starts[external_id] = RunStart(
            external_id=external_id,
            started_at=datetime.fromisoformat(started_at),
            latitude=round(latitude, WEATHER_COORDINATE_DECIMALS),
            longitude=round(longitude, WEATHER_COORDINATE_DECIMALS),
        )
    return sorted(starts.values(), key=lambda start: start.started_at)


def weather_request_url(start: RunStart) -> str:
    """The archive request for the UTC day a run started in, in UTC and mph."""
    day = start.started_at.astimezone(timezone.utc).date().isoformat()
    return OPEN_METEO_ARCHIVE_URL + "?" + urlencode(
        {
            "latitude": start.latitude,
            "longitude": start.longitude,
            "start_date": day,
            "end_date": day,
            "hourly": ",".join(WEATHER_VARIABLES),
            "wind_speed_unit": "mph",
            "timezone": "UTC",
        }
    )


def map_run_weather(
    payload: Any, started_at: datetime, fetched_at: str
) -> dict[str, Any] | None:
    """The weather row for the hour a run started in, or None if not available yet.

    The hour is found in UTC (the request asks for UTC), so it does not matter
    whether the clocks were on BST or GMT: 00:30 and 01:30 UTC on the night they
    go back are different hours, as they are in the archive. None means the
    archive has no complete value for that hour (it can lag real time), which is
    retried on a later sync rather than stored half-empty.
    """
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return None
    hour = started_at.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        index = hourly["time"].index(hour.strftime("%Y-%m-%dT%H:%M"))
    except ValueError:
        return None

    values: dict[str, float] = {}
    for variable in WEATHER_VARIABLES:
        series = hourly.get(variable)
        value = series[index] if isinstance(series, list) and index < len(series) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            return None
        values[variable] = float(value)
    if not 0 <= values["relative_humidity_2m"] <= 100:
        return None
    if values["wind_speed_10m"] < 0 or values["precipitation"] < 0:
        return None

    return {
        "hour_start": hour.isoformat().replace("+00:00", "Z"),
        "temperature_c": values["temperature_2m"],
        "apparent_temperature_c": values["apparent_temperature"],
        "relative_humidity_percent": values["relative_humidity_2m"],
        "wind_speed_mph": values["wind_speed_10m"],
        "precipitation_mm": values["precipitation"],
        "source": WEATHER_SOURCE,
        "fetched_at": fetched_at,
    }


def fetch_open_meteo(url: str) -> Any:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def _describe_failure(error: Exception) -> str:
    """A failure in words that cannot carry the request URL, and so the coordinate."""
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}"
    return type(error).__name__


@dataclass
class WeatherResult:
    """How many runs got weather, how many are not covered yet, how many failed."""

    stored: int = 0
    not_yet: int = 0
    failed: int = 0
    stopped_early: bool = False


def store_run_weather(
    starts: list[RunStart],
    supabase: Any,
    session: dict[str, Any],
    fetch: Any = fetch_open_meteo,
    max_consecutive_failures: int = MAX_CONSECUTIVE_WEATHER_FAILURES,
) -> WeatherResult:
    """Fetch and store weather once for each run that has none.

    A run already holding weather is not asked about again (the value is not
    revised). One the archive does not cover yet is left without a row, so a
    later sync finds it again. Failures are warnings, as for splits. Only the
    run's Garmin id is ever printed.
    """
    result = WeatherResult()
    if not starts:
        return result

    activity_ids = supabase.fitness_activity_ids([start.external_id for start in starts], session)
    already_stored = supabase.run_weather_activity_ids(list(activity_ids.values()), session)
    consecutive_failures = 0
    for start in starts:
        activity_id = activity_ids.get(start.external_id)
        if activity_id is None or activity_id in already_stored:
            continue
        try:
            payload = fetch(weather_request_url(start))
            row = map_run_weather(payload, start.started_at, datetime.now(timezone.utc).isoformat())
            consecutive_failures = 0
            if row is None:
                result.not_yet += 1
                continue
            supabase.insert_run_weather({**row, "fitness_activity_id": activity_id}, session)
            result.stored += 1
        except Exception as error:  # a weather failure must not fail a sync that has stored
            result.failed += 1
            consecutive_failures += 1
            print(
                f"Warning: weather for Garmin activity {start.external_id} was unavailable: "
                f"{_describe_failure(error)}",
                file=sys.stderr,
            )
            if consecutive_failures >= max_consecutive_failures:
                result.stopped_early = True
                print(
                    f"Warning: {consecutive_failures} weather lookups failed in a row; "
                    "stopping. The remaining runs are retried on the next sync.",
                    file=sys.stderr,
                )
                break
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

    def record_sync_run(self, succeeded_at: str, session: dict[str, Any]) -> None:
        """Stamp this owner's Garmin heartbeat; only a fully successful run calls this."""
        user = session.get("user")
        user_id = user.get("id") if isinstance(user, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise SyncError("The cached app session has no user id. Run setup again.")
        self._request(
            "POST",
            "/rest/v1/sync_runs?" + urlencode({"on_conflict": "user_id,source"}),
            {"user_id": user_id, "source": SOURCE, "last_succeeded_at": succeeded_at},
            access_token=self._access_token(session),
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def garmin_activities(
        self, session: dict[str, Any], external_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Garmin activities and whether laps are stored for each, newest first.

        Pass `external_ids` to look only at those; None reads them all, a page at
        a time. Row Level Security limits this to the signed-in user's rows. One
        embedded lap is enough to answer "has laps", and avoids PostgREST
        aggregates, which a hosted project can have switched off.
        """
        if external_ids is not None:
            external_ids = [value for value in external_ids if is_garmin_activity_id(value)]
            if not external_ids:
                return []
        access_token = self._access_token(session)
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            query = {
                "select": "external_id,activity_type,fitness_activity_laps(id)",
                "fitness_activity_laps.limit": "1",
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
                    "has_laps": has_embedded_rows(item.get("fitness_activity_laps")),
                }
                for item in page
                if isinstance(item, dict)
            )
            if len(page) < ACTIVITIES_PAGE_SIZE:
                return rows
            offset += ACTIVITIES_PAGE_SIZE

    def fitness_activity_ids(
        self, external_ids: list[str], session: dict[str, Any]
    ) -> dict[str, str]:
        """Row ids of stored Garmin activities, by provider id."""
        external_ids = [value for value in external_ids if is_garmin_activity_id(value)]
        if not external_ids:
            return {}
        page = self._request(
            "GET",
            "/rest/v1/fitness_activities?"
            + urlencode(
                {
                    "select": "id,external_id",
                    "source": "eq.garmin",
                    "external_id": f"in.({','.join(external_ids)})",
                }
            ),
            access_token=self._access_token(session),
        )
        if not isinstance(page, list):
            raise SyncError("Supabase returned an unexpected activities response.")
        return {
            item["external_id"]: item["id"]
            for item in page
            if isinstance(item, dict)
            and isinstance(item.get("external_id"), str)
            and isinstance(item.get("id"), str)
        }

    def run_weather_activity_ids(
        self, activity_ids: list[str], session: dict[str, Any]
    ) -> set[str]:
        """Which of these activities already have weather stored."""
        if not activity_ids:
            return set()
        page = self._request(
            "GET",
            "/rest/v1/run_weather?"
            + urlencode(
                {
                    "select": "fitness_activity_id",
                    "fitness_activity_id": f"in.({','.join(activity_ids)})",
                }
            ),
            access_token=self._access_token(session),
            extra_headers={"Accept-Profile": "weather"},
        )
        if not isinstance(page, list):
            raise SyncError("Supabase returned an unexpected weather response.")
        return {
            item["fitness_activity_id"]
            for item in page
            if isinstance(item, dict) and isinstance(item.get("fitness_activity_id"), str)
        }

    def insert_run_weather(self, row: dict[str, Any], session: dict[str, Any]) -> None:
        """Store one run's weather; a run that already has some is left alone."""
        self._request(
            "POST",
            "/rest/v1/run_weather?" + urlencode({"on_conflict": "fitness_activity_id"}),
            row,
            access_token=self._access_token(session),
            extra_headers={
                "Content-Profile": "weather",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
        )

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
        pending = activities_needing_splits(supabase.garmin_activities(session, foot_ids))
    except Exception as error:  # a timeout or bad JSON must not fail a sync that has stored
        print(f"Warning: stored splits could not be checked: {error}", file=sys.stderr)
        pending = []
    if pending:
        splits = store_splits(garmin, supabase, session, pending)
        print(f"Stored splits for {splits.stored} of {len(pending)} activity/activities.")

    # The summaries just fetched carry each run's start point, so weather costs
    # no Garmin request. A failure here is a warning: the run is retried while
    # it is still in the window.
    try:
        weather = store_run_weather(outdoor_run_starts(raw_activities), supabase, session)
        print(
            f"Stored weather for {weather.stored} run(s); "
            f"{weather.not_yet} not in Open-Meteo's archive yet."
        )
    except Exception as error:
        print(f"Warning: run weather was skipped: {_describe_failure(error)}", file=sys.stderr)

    # Reached only when the health and activity writes succeeded: a failed run
    # must leave the heartbeat old, and a run that found nothing new must still
    # advance it.
    supabase.record_sync_run(synced_at, session)


def backfill_splits(limit: int | None) -> None:
    """One-off: fetch splits for every stored foot activity that has none yet.

    Safe to repeat: activities that already have laps are skipped, so a run cut
    short by --limit, a rate limit or a failure is continued by running it
    again. Newest activities come first. `--limit` counts activities that got
    laps, not lookups, so activities Garmin has no laps for cannot use it up.
    """
    if limit is not None and limit < 1:
        raise SyncError("--limit must be at least 1.")

    supabase, token_store = configuration()
    session = session_for_sync(supabase)
    garmin = Garmin()
    garmin.login(str(token_store))

    pending = activities_needing_splits(supabase.garmin_activities(session))
    if not pending:
        print("No stored Garmin foot activities are missing splits.")
        return

    print(f"Fetching splits for {len(pending)} activity/activities missing them.")
    splits = store_splits(garmin, supabase, session, pending, max_stored=limit)
    print(
        f"Stored splits for {splits.stored} activity/activities "
        f"({splits.failed} failed). {len(pending) - splits.stored} still without splits."
    )
    if splits.stopped_early:
        print("Stopped early after repeated failures; run it again later to continue.")


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
        "--limit", type=int, default=None, help="Store splits for at most this many activities, newest first."
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
