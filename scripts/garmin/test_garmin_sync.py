import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from garmin_sync import (
    SyncError,
    app_environment,
    current_london_day,
    docker_host_url,
    normalize_steps,
)


class NormalizeStepsTests(unittest.TestCase):
    def test_normalizes_known_garmin_payload_variants(self) -> None:
        rows = normalize_steps(
            [
                {"calendarDate": "2026-09-05", "totalSteps": 12345},
                {"date": "2026-09-06", "steps": 6789},
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual([row["steps"] for row in rows], [12345, 6789])
        self.assertEqual(rows[0]["external_id"], "garmin:2026-09-05")
        self.assertTrue(all(row["user_id"] == "user-1" for row in rows))

    def test_skips_missing_or_invalid_values_instead_of_inventing_zero(self) -> None:
        rows = normalize_steps(
            [
                {"calendarDate": "2026-09-05"},
                {"calendarDate": "not-a-date", "totalSteps": 100},
                {"calendarDate": "2026-09-06", "totalSteps": -1},
                {"calendarDate": "2026-09-06", "totalSteps": True},
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual(rows, [])

    def test_rejects_a_non_list_provider_response(self) -> None:
        with self.assertRaises(SyncError):
            normalize_steps({}, "user-1", "2026-09-06T12:00:00+00:00")

    def test_deduplicates_and_sorts_provider_days_for_one_upsert(self) -> None:
        rows = normalize_steps(
            [
                {"calendarDate": "2026-09-06", "totalSteps": 100},
                {"calendarDate": "2026-09-05", "totalSteps": 200},
                {"calendarDate": "2026-09-06", "totalSteps": 300},
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual([(row["day"], row["steps"]) for row in rows], [
            ("2026-09-05", 200),
            ("2026-09-06", 300),
        ])


class DockerHostUrlTests(unittest.TestCase):
    def test_rewrites_localhost_for_a_container(self) -> None:
        self.assertEqual(
            docker_host_url("http://127.0.0.1:54321", True),
            "http://host.docker.internal:54321",
        )

    def test_leaves_hosted_urls_unchanged(self) -> None:
        self.assertEqual(
            docker_host_url("https://example.supabase.co/", True),
            "https://example.supabase.co",
        )


class LondonDayTests(unittest.TestCase):
    def test_uses_the_next_london_day_during_bst(self) -> None:
        instant = datetime(2026, 8, 1, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(current_london_day(instant).isoformat(), "2026-08-02")

    def test_rejects_a_timezone_naive_instant(self) -> None:
        with self.assertRaises(ValueError):
            current_london_day(datetime(2026, 8, 1, 23, 30))


class AppEnvironmentTests(unittest.TestCase):
    def test_defaults_to_local(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(app_environment(), "local")

    def test_reports_live_profile(self) -> None:
        with patch.dict("os.environ", {"PERSONAL_OBSERVABILITY_ENVIRONMENT": "LIVE"}):
            self.assertEqual(app_environment(), "live")

    def test_does_not_echo_an_arbitrary_environment_value(self) -> None:
        with patch.dict(
            "os.environ", {"PERSONAL_OBSERVABILITY_ENVIRONMENT": "sensitive-value"}
        ):
            self.assertEqual(app_environment(), "configured")

if __name__ == "__main__":
    unittest.main()
