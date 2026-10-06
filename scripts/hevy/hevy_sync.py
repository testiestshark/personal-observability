"""Hevy workout sync for Personal Observability.

The worker deliberately authenticates to Supabase as the app user. Its writes
therefore pass through the same Row Level Security policies as browser requests;
it never receives the service-role key. It only ever reads from Hevy: the key can
also overwrite the owner's real training log, so no other HTTP method is sent.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SOURCE = "hevy"
PROVIDER = "hevy_public_api"
ACTIVITY_TYPE = "strength_training"
HEVY_BASE_URL = "https://api.hevyapp.com"
PAGE_SIZE = 10
SYNC_WINDOW = timedelta(days=7)
LONDON = ZoneInfo("Europe/London")


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


def sync_since(now: datetime) -> str:
    """The start of the hourly run's window, in the form Hevy documents."""
    since = (now - SYNC_WINDOW).astimezone(timezone.utc)
    return since.strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(value: Any) -> datetime | None:
    """Parse a Hevy ISO 8601 timestamp as an aware UTC instant.

    Hevy uses `+00:00` for start/end times and `Z` with milliseconds for
    created/updated times, so neither suffix is assumed.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    """Return a finite non-negative number, or None when missing or invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in {float("inf"), float("-inf")} or value < 0:
        return None
    return float(value)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _sets(workout: dict[str, Any]) -> list[dict[str, Any]]:
    exercises = workout.get("exercises")
    if not isinstance(exercises, list):
        return []
    sets: list[dict[str, Any]] = []
    for exercise in exercises:
        if not isinstance(exercise, dict) or not isinstance(exercise.get("sets"), list):
            continue
        sets.extend(item for item in exercise["sets"] if isinstance(item, dict))
    return sets


def _in_hevy_order(items: Any) -> list[dict[str, Any]]:
    """The dict items of a Hevy list, ordered by their `index` (list order if absent)."""
    if not isinstance(items, list):
        return []
    entries = [item for item in items if isinstance(item, dict)]
    return sorted(
        entries,
        key=lambda item: (
            item["index"]
            if isinstance(item.get("index"), int) and not isinstance(item["index"], bool)
            else float("inf")
        ),
    )


def _planned_set(position: int, item: dict[str, Any]) -> dict[str, Any]:
    reps = _number(item.get("reps"))
    # An unknown type is passed on untouched: the database rejects the workout
    # rather than the worker silently guessing what a new Hevy set type means.
    set_type = _text(item.get("type")) or "normal"
    return {
        "position": position,
        "type": set_type,
        "weight_kg": _number(item.get("weight_kg")),
        "reps": None if reps is None else round(reps),
        "rpe": _number(item.get("rpe")),
        "distance_meters": _number(item.get("distance_meters")),
        "duration_seconds": _number(item.get("duration_seconds")),
        "custom_metric": _number(item.get("custom_metric")),
    }


def _planned_exercises(workout: dict[str, Any]) -> list[dict[str, Any]]:
    """Exercises and sets with gap-free positions; `set.index` restarts per exercise."""
    exercises: list[dict[str, Any]] = []
    for position, exercise in enumerate(_in_hevy_order(workout.get("exercises"))):
        superset_id = exercise.get("superset_id")
        exercises.append({
            "position": position,
            "title": _text(exercise.get("title")),
            "exercise_template_id": _text(exercise.get("exercise_template_id")),
            "notes": exercise["notes"] if isinstance(exercise.get("notes"), str) else None,
            "superset_id": (
                superset_id
                if isinstance(superset_id, int) and not isinstance(superset_id, bool)
                else None
            ),
            "sets": [
                _planned_set(set_position, item)
                for set_position, item in enumerate(_in_hevy_order(exercise.get("sets")))
            ],
        })
    return exercises


def _fitness_activity(
    workout: Any, user_id: str, synced_at: str
) -> dict[str, Any] | None:
    if not isinstance(workout, dict):
        return None
    external_id = _text(workout.get("id"))
    started = _instant(workout.get("start_time"))
    if not external_id or not started:
        return None

    ended = _instant(workout.get("end_time"))
    duration = (ended - started).total_seconds() if ended else None
    if duration is not None and duration < 0:
        duration = None

    sets = _sets(workout)
    working_sets = [item for item in sets if item.get("type") != "warmup"]
    total_reps = 0.0
    total_volume = 0.0
    for item in working_sets:
        reps = _number(item.get("reps"))
        weight = _number(item.get("weight_kg"))
        if reps is not None:
            total_reps += reps
            if weight is not None:
                total_volume += weight * reps

    return {
        "user_id": user_id,
        "source": SOURCE,
        "provider": PROVIDER,
        "external_id": external_id,
        "activity_name": _text(workout.get("title")),
        "activity_type": ACTIVITY_TYPE,
        "local_day": started.astimezone(LONDON).date().isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": duration,
        "calories_kcal": None,
        "average_heart_rate_bpm": None,
        "maximum_heart_rate_bpm": None,
        "total_sets": len(sets),
        "active_sets": len(working_sets),
        "total_reps": round(total_reps),
        "total_volume_kg": total_volume,
        "synced_at": synced_at,
        "exercises": _planned_exercises(workout),
    }


def plan_operations(
    events: Any, user_id: str, synced_at: str
) -> list[dict[str, Any]]:
    """Turn Hevy workout events into ordered write operations.

    A `replace` operation's activity is the fitness activity plus its nested
    `exercises` and `sets`; the database replaces them as one unit.

    Hevy lists events newest first, so they are applied oldest first: a delete
    after an update wins, and so does an update after a delete. A workout that
    repeats keeps only its latest operation. An `updated` event becomes
    `{"op": "replace", "activity": row}` and a `deleted` event becomes
    `{"op": "delete", "external_id": id}`. The local day is the London calendar
    day of `start_time`, never `created_at`: most of the history shares one
    bulk-import creation time.
    """
    if not isinstance(events, list):
        raise SyncError("Hevy returned an unexpected workout events response.")

    latest: dict[str, dict[str, Any]] = {}
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "updated":
            row = _fitness_activity(event.get("workout"), user_id, synced_at)
            if row:
                operation = {"op": "replace", "activity": row}
                external_id = row["external_id"]
            else:
                continue
        elif event.get("type") == "deleted":
            external_id = _text(event.get("id"))
            if not external_id:
                continue
            operation = {"op": "delete", "external_id": external_id}
        else:
            continue
        # Re-insert so the surviving operation sits at its own event's position.
        latest.pop(external_id, None)
        latest[external_id] = operation

    return list(latest.values())


class HevyClient:
    """A GET-only client for Hevy's public API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = HEVY_BASE_URL,
        open_url: Callable[..., Any] = urlopen,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._open_url = open_url

    def _scrub(self, text: str) -> str:
        return text.replace(self._api_key, "[redacted]") if self._api_key else text

    def _get(self, path: str, query: dict[str, Any]) -> Any:
        request = Request(
            f"{self._base_url}{path}?{urlencode(query)}",
            headers={"api-key": self._api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._open_url(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()[:200]
            raise SyncError(
                f"Hevy request failed ({error.code}): {self._scrub(detail)}"
            ) from None
        except URLError as error:
            raise SyncError(
                f"Could not reach Hevy: {self._scrub(str(error.reason))}"
            ) from None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise SyncError("Hevy returned a response that is not JSON.") from None

    def workout_events(self, since: str) -> list[Any]:
        """Read every page of workout events updated or deleted since `since`."""
        events: list[Any] = []
        page = 1
        while True:
            body = self._get(
                "/v1/workouts/events",
                {"since": since, "page": page, "pageSize": PAGE_SIZE},
            )
            page_count = body.get("page_count") if isinstance(body, dict) else None
            page_events = body.get("events") if isinstance(body, dict) else None
            if (
                isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or not isinstance(page_events, list)
            ):
                raise SyncError("Hevy returned an unexpected workout events page.")
            events.extend(page_events)
            if page >= page_count:
                return events
            page += 1


def hevy_api_key() -> str:
    key = os.getenv("HEVY_API_KEY", "").strip()
    if not key:
        raise SyncError("HEVY_API_KEY is required in .env.local or Railway variables.")
    return key


def validate_railway_volume(session_path: Path) -> None:
    """Refuse a Railway run that would lose the app session after the container exits."""
    if not os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return

    raw_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if not raw_mount:
        raise SyncError("Railway requires a persistent volume mounted at /data.")

    mount = Path(raw_mount).resolve()
    try:
        session_path.resolve().relative_to(mount)
    except ValueError as error:
        message = f"SUPABASE_SESSION_FILE must be stored below the Railway volume at {mount}."
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
            raise SyncError("App session is missing. Run the Hevy setup command first.")
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

    def _access_token(self, session: dict[str, Any]) -> str:
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SyncError("The cached app access token is missing. Run setup again.")
        return access_token

    def delete_activity(self, external_id: str, session: dict[str, Any]) -> None:
        """Hard-delete one Hevy workout. Exercises and sets cascade; a missing row is fine."""
        query = urlencode(
            {
                "source": f"eq.{SOURCE}",
                "external_id": f"eq.{external_id}",
                "user_id": f"eq.{self._user_id(session)}",
            }
        )
        self._request(
            "DELETE",
            f"/rest/v1/fitness_activities?{query}",
            access_token=self._access_token(session),
            extra_headers={"Prefer": "return=minimal"},
        )

    @staticmethod
    def _user_id(session: dict[str, Any]) -> str:
        user = session.get("user")
        user_id = user.get("id") if isinstance(user, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise SyncError("The cached app session has no user id. Run setup again.")
        return user_id

    def replace_workout(self, row: dict[str, Any], session: dict[str, Any]) -> None:
        """Store one workout, its exercises and its sets in a single transaction."""
        access_token = self._access_token(session)
        self._request(
            "POST",
            "/rest/v1/rpc/replace_fitness_workout",
            {"payload": row},
            access_token=access_token,
        )


def configuration() -> SupabaseSession:
    raw_url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not raw_url or not key:
        raise SyncError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required in .env.local.")

    in_docker = os.getenv("HEVY_SYNC_IN_DOCKER", "").lower() == "true"
    base_url = docker_host_url(raw_url, in_docker)
    session_path = Path(os.getenv("SUPABASE_SESSION_FILE", "/data/supabase-session.json"))
    validate_railway_volume(session_path)
    return SupabaseSession(base_url, key, session_path)


def app_environment() -> str:
    value = os.getenv("PERSONAL_OBSERVABILITY_ENVIRONMENT", "local").strip().lower()
    return value if value in {"local", "live"} else "configured"


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


def setup() -> None:
    supabase = configuration()
    print(f"Sign in to the {app_environment()} Personal Observability app account.")
    app_email = input("App email: ").strip()
    app_password = getpass.getpass("App password: ")
    try:
        session = supabase.login(app_email, app_password)
    finally:
        del app_password

    user = session.get("user")
    identity = user.get("email") if isinstance(user, dict) else app_email
    key_state = "configured" if os.getenv("HEVY_API_KEY", "").strip() else "missing"
    print(f"Setup complete for {identity}.")
    print(f"Hevy API key: {key_state}.")


def sync() -> None:
    supabase = configuration()
    hevy = HevyClient(hevy_api_key())
    session = session_for_sync(supabase)
    user = session.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise SyncError("The cached app session has no user id. Run setup again.")

    now = datetime.now(timezone.utc)
    events = hevy.workout_events(sync_since(now))
    operations = plan_operations(events, user_id, now.isoformat())
    replaced = deleted = 0
    failures: list[str] = []
    for operation in operations:
        try:
            if operation["op"] == "replace":
                supabase.replace_workout(operation["activity"], session)
                replaced += 1
            else:
                supabase.delete_activity(operation["external_id"], session)
                deleted += 1
        except SyncError as error:
            # One bad workout must not hold back the rest; the run still fails.
            external_id = operation.get("external_id") or operation["activity"]["external_id"]
            failures.append(f"workout {external_id}: {error}")
    print(
        f"Synced {replaced} Hevy workout(s) and removed {deleted} "
        f"from {len(events)} event(s)."
    )
    if failures:
        raise SyncError("Some workouts were not stored.\n" + "\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Hevy workouts into Personal Observability."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup", help="Sign in once to the app and store its session.")
    subcommands.add_parser("sync", help="Replace workouts updated in the last 7 days, with their exercises and sets.")
    subcommands.add_parser("test", help="Run the worker unit tests.")
    args = parser.parse_args()

    try:
        if args.command == "setup":
            setup()
        elif args.command == "sync":
            sync()
        else:
            suite = unittest.defaultTestLoader.discover(
                str(Path(__file__).parent), pattern="test_hevy_sync.py"
            )
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    except (SyncError, KeyboardInterrupt) as error:
        message = "Cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except Exception as error:
        # Name the failure without its message, which could quote a request.
        print(f"Hevy sync failed unexpectedly: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
