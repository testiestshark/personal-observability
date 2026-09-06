"""Automatic Garmin Connect steps sync for Personal Observability.

The worker deliberately authenticates to Supabase as the app user. Its writes
therefore pass through the same Row Level Security policies as browser requests;
it never receives the service-role key.
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

    def upsert(self, rows: list[dict[str, Any]], session: dict[str, Any]) -> None:
        if not rows:
            return
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SyncError("The cached app access token is missing. Run setup again.")
        self._request(
            "POST",
            "/rest/v1/daily_health_metrics?" + urlencode({"on_conflict": "user_id,day,source"}),
            rows,
            access_token=access_token,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
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
    session = supabase.active()
    user = session.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise SyncError("The cached app session has no user id. Run setup again.")

    garmin = Garmin()
    garmin.login(str(token_store))

    end = current_london_day()
    start = end - timedelta(days=days - 1)
    raw_rows = garmin.get_daily_steps(start.isoformat(), end.isoformat())
    synced_at = datetime.now(timezone.utc).isoformat()
    rows = normalize_steps(raw_rows, user_id, synced_at)
    if not rows:
        raise SyncError("Garmin returned no usable step records for the requested range.")

    supabase.upsert(rows, session)
    print(f"Synced {len(rows)} Garmin step day(s), {rows[0]['day']} to {rows[-1]['day']}.")


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
    parser = argparse.ArgumentParser(description="Sync Garmin steps into Personal Observability.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup", help="Authenticate once to the app and Garmin Connect.")
    subcommands.add_parser(
        "setup-app", help="Authenticate only to the app while reusing cached Garmin tokens."
    )
    sync_parser = subcommands.add_parser("sync", help="Fetch and upsert recent step totals.")
    sync_parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
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
