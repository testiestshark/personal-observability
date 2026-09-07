import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from garmin_sync import (
    SyncError,
    app_environment,
    current_london_day,
    docker_host_url,
    normalize_activities,
    normalize_daily_health,
    normalize_steps,
    validate_railway_volume,
    _vo2_max,
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


class NormalizeDailyHealthTests(unittest.TestCase):
    def test_keeps_active_and_total_calories_distinct(self) -> None:
        rows = normalize_daily_health(
            [
                {
                    "calendarDate": "2026-09-06",
                    "totalSteps": 6789,
                    "activeKilocalories": 456.4,
                    "totalKilocalories": 2345.6,
                }
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual(rows[0]["steps"], 6789)
        self.assertEqual(rows[0]["active_calories_kcal"], 456)
        self.assertEqual(rows[0]["total_calories_kcal"], 2346)

    def test_keeps_a_day_when_only_calories_are_available(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-06", "activeKilocalories": 321}],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertIsNone(rows[0]["steps"])
        self.assertEqual(rows[0]["active_calories_kcal"], 321)

    def test_skips_a_day_with_no_valid_measurements(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-06", "totalSteps": True, "totalKilocalories": -1}],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual(rows, [])

    def test_adds_the_agreed_sleep_heart_and_vo2_fields(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-06", "restingHeartRate": 52}],
            "user-1",
            "2026-09-06T12:00:00+00:00",
            sleep_by_day={
                "2026-09-06": {
                    "dailySleepDTO": {
                        "sleepStartTimestampGMT": 1788649200000,
                        "sleepEndTimestampGMT": 1788678000000,
                        "sleepTimeSeconds": 27000,
                        "sleepScores": {"overall": {"value": 84}},
                    }
                }
            },
            max_metrics_by_day={
                "2026-09-06": [{"generic": {"vo2MaxValue": 51.0}}]
            },
        )

        self.assertEqual(rows[0]["resting_heart_rate_bpm"], 52)
        self.assertEqual(rows[0]["total_sleep_seconds"], 27000)
        self.assertEqual(rows[0]["sleep_score"], 84)
        self.assertEqual(rows[0]["vo2_max"], 51.0)
        self.assertTrue(rows[0]["sleep_start_at"].endswith("+00:00"))
        self.assertTrue(rows[0]["sleep_end_at"].endswith("+00:00"))

    def test_extracts_most_recent_vo2_between_calculation_days(self) -> None:
        self.assertEqual(
            _vo2_max(
                {
                    "mostRecentVO2Max": {
                        "generic": {"vo2MaxValue": 50.0},
                        "cycling": None,
                    }
                }
            ),
            50.0,
        )


class NormalizeActivitiesTests(unittest.TestCase):
    def test_normalizes_activity_summary_without_coordinates(self) -> None:
        rows = normalize_activities(
            [
                {
                    "activityId": 12345,
                    "activityName": "Morning Run",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-09-06 07:30:00",
                    "startTimeGMT": "2026-09-06 06:30:00",
                    "duration": 1800.5,
                    "distance": 5020.2,
                    "calories": 401.2,
                    "averageHR": 151,
                    "startLatitude": 51.5,
                    "startLongitude": -0.1,
                }
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual(rows[0]["external_id"], "12345")
        self.assertEqual(rows[0]["activity_type"], "running")
        self.assertEqual(rows[0]["local_day"], "2026-09-06")
        self.assertEqual(rows[0]["distance_meters"], 5020.2)
        self.assertNotIn("startLatitude", rows[0])
        self.assertNotIn("startLongitude", rows[0])

    def test_skips_activity_without_stable_id_or_start_time(self) -> None:
        rows = normalize_activities(
            [
                {"activityName": "No id", "startTimeGMT": "2026-09-06 06:30:00"},
                {"activityId": 12345, "activityName": "No time"},
            ],
            "user-1",
            "2026-09-06T12:00:00+00:00",
        )

        self.assertEqual(rows, [])


class RailwayVolumeTests(unittest.TestCase):
    def test_requires_a_volume_on_railway(self) -> None:
        environment = {"RAILWAY_ENVIRONMENT_NAME": "production"}
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(SyncError, "persistent volume"):
                validate_railway_volume(Path("/data/session.json"), Path("/data/garmin"))

    def test_accepts_both_sessions_inside_the_volume(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAILWAY_ENVIRONMENT_NAME": "production",
                "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            },
            clear=True,
        ):
            validate_railway_volume(Path("/data/session.json"), Path("/data/garmin"))

    def test_rejects_a_session_outside_the_volume(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAILWAY_ENVIRONMENT_NAME": "production",
                "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(SyncError, "SUPABASE_SESSION_FILE"):
                validate_railway_volume(Path("/tmp/session.json"), Path("/data/garmin"))


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
