import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from garmin_sync import (
    SyncError,
    activities_needing_splits,
    app_environment,
    current_london_day,
    docker_host_url,
    embedded_count,
    is_foot_activity,
    normalize_activities,
    normalize_daily_health,
    normalize_laps,
    normalize_steps,
    session_for_sync,
    store_splits,
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

    def test_keeps_consumed_calories_from_linked_food_logging(self) -> None:
        rows = normalize_daily_health(
            [
                {
                    "calendarDate": "2026-09-28",
                    "totalKilocalories": 2345.6,
                    "consumedKilocalories": 1134.0,
                }
            ],
            "user-1",
            "2026-09-28T12:00:00+00:00",
        )

        self.assertEqual(rows[0]["consumed_calories_kcal"], 1134)

    def test_consumed_calories_are_null_before_food_logging_was_linked(self) -> None:
        rows = normalize_daily_health(
            [
                {
                    "calendarDate": "2026-09-27",
                    "totalKilocalories": 2345.6,
                    "consumedKilocalories": None,
                }
            ],
            "user-1",
            "2026-09-27T12:00:00+00:00",
        )

        self.assertIsNone(rows[0]["consumed_calories_kcal"])

    def test_keeps_the_calorie_goal_set_in_linked_food_logging(self) -> None:
        rows = normalize_daily_health(
            [
                {
                    "calendarDate": "2026-09-28",
                    "consumedKilocalories": 1134.0,
                    "netCalorieGoal": 2500.0,
                }
            ],
            "user-1",
            "2026-09-28T12:00:00+00:00",
        )

        self.assertEqual(rows[0]["calorie_goal_kcal"], 2500)

    def test_calorie_goal_is_null_before_food_logging_was_linked(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-27", "totalKilocalories": 2345.6}],
            "user-1",
            "2026-09-27T12:00:00+00:00",
        )

        self.assertIsNone(rows[0]["calorie_goal_kcal"])

    def test_a_calorie_goal_alone_does_not_keep_a_day(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-28", "netCalorieGoal": 2500.0}],
            "user-1",
            "2026-09-28T12:00:00+00:00",
        )

        self.assertEqual(rows, [])

    def test_keeps_a_day_when_only_consumed_calories_are_available(self) -> None:
        rows = normalize_daily_health(
            [{"calendarDate": "2026-09-28", "consumedKilocalories": 1134.0}],
            "user-1",
            "2026-09-28T12:00:00+00:00",
        )

        self.assertEqual(rows[0]["consumed_calories_kcal"], 1134)

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
                    }
                }
            },
            max_metrics_by_day={
                "2026-09-06": [{"generic": {"vo2MaxValue": 51.0}}]
            },
        )

        self.assertEqual(rows[0]["resting_heart_rate_bpm"], 52)
        self.assertEqual(rows[0]["total_sleep_seconds"], 27000)
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


class IsFootActivityTests(unittest.TestCase):
    def test_matches_the_type_keys_garmin_uses_for_pace_based_activities(self) -> None:
        for key in ("running", "trail_running", "treadmill_running", "walking", "hiking"):
            self.assertTrue(is_foot_activity(key), key)

    def test_rejects_activities_read_as_speed_or_not_distance_based(self) -> None:
        for key in ("cycling", "strength_training", "lap_swimming", "other"):
            self.assertFalse(is_foot_activity(key), key)


def _lap(**overrides: object) -> dict[str, object]:
    lap: dict[str, object] = {
        "lapIndex": 1,
        "distance": 1000.0,
        "duration": 330.4,
        "averageHR": 148.4,
        "elevationGain": 6.2,
        "elevationLoss": 3.1,
        "startLatitude": 51.5,
        "startLongitude": -0.1,
        "endLatitude": 51.51,
        "endLongitude": -0.11,
    }
    lap.update(overrides)
    return lap


class NormalizeLapsTests(unittest.TestCase):
    def test_keeps_the_agreed_fields_in_order_without_coordinates(self) -> None:
        rows = normalize_laps(
            {"activityId": 1, "lapDTOs": [_lap(), _lap(lapIndex=2, duration=340.0)]}
        )

        self.assertEqual(
            rows[0],
            {
                "position": 0,
                "distance_meters": 1000.0,
                "duration_seconds": 330.4,
                "average_heart_rate_bpm": 148,
                "elevation_gain_meters": 6.2,
                "elevation_loss_meters": 3.1,
            },
        )
        self.assertEqual([row["position"] for row in rows], [0, 1])
        self.assertEqual(rows[1]["duration_seconds"], 340.0)
        for row in rows:
            self.assertFalse([key for key in row if "atitude" in key or "ongitude" in key])

    def test_missing_measurements_stay_missing_instead_of_becoming_zero(self) -> None:
        absent, invalid = normalize_laps(
            {
                "lapDTOs": [
                    {"duration": 300.0},
                    _lap(averageHR=0, elevationGain=None, elevationLoss="n/a", distance=True),
                ]
            }
        )

        unreported = {
            "distance_meters": None,
            "average_heart_rate_bpm": None,
            "elevation_gain_meters": None,
            "elevation_loss_meters": None,
        }
        self.assertEqual(absent, {"position": 0, "duration_seconds": 300.0, **unreported})
        self.assertEqual(invalid, {"position": 1, "duration_seconds": 330.4, **unreported})

    def test_drops_a_lap_with_no_usable_duration_and_keeps_positions_contiguous(self) -> None:
        rows = normalize_laps(
            {
                "lapDTOs": [
                    _lap(duration=None),
                    _lap(duration=0),
                    _lap(duration=-5),
                    "not a lap",
                    _lap(duration=310.0),
                ]
            }
        )

        self.assertEqual([(row["position"], row["duration_seconds"]) for row in rows], [(0, 310.0)])

    def test_an_activity_without_laps_has_no_rows(self) -> None:
        self.assertEqual(normalize_laps({"activityId": 1}), [])
        self.assertEqual(normalize_laps({"lapDTOs": None}), [])
        self.assertEqual(normalize_laps({"lapDTOs": []}), [])

    def test_rejects_an_unexpected_provider_response(self) -> None:
        with self.assertRaises(SyncError):
            normalize_laps([])
        with self.assertRaises(SyncError):
            normalize_laps({"lapDTOs": "oops"})


class ActivitiesNeedingSplitsTests(unittest.TestCase):
    def test_selects_foot_activities_that_have_no_stored_laps(self) -> None:
        rows = [
            {"external_id": "1", "activity_type": "running", "laps": 0},
            {"external_id": "2", "activity_type": "running", "laps": 5},
            {"external_id": "3", "activity_type": "cycling", "laps": 0},
            {"external_id": "4", "activity_type": "trail_running", "laps": 0},
        ]

        self.assertEqual(activities_needing_splits(rows), ["1", "4"])

    def test_ignores_an_id_garmin_cannot_look_up(self) -> None:
        rows = [
            {"external_id": "abc", "activity_type": "running", "laps": 0},
            {"external_id": "12 3", "activity_type": "running", "laps": 0},
        ]

        self.assertEqual(activities_needing_splits(rows), [])


class EmbeddedCountTests(unittest.TestCase):
    def test_reads_the_count_postgrest_embeds(self) -> None:
        self.assertEqual(embedded_count([{"count": 7}]), 7)
        self.assertEqual(embedded_count([{"count": 0}]), 0)

    def test_treats_anything_unexpected_as_no_laps(self) -> None:
        for value in (None, [], {}, "3", [{"count": "x"}], [{"count": True}]):
            self.assertEqual(embedded_count(value), 0, value)


class _FakeGarmin:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.requested: list[str] = []

    def get_activity_splits(self, activity_id: str) -> object:
        self.requested.append(activity_id)
        payload = self.payloads[activity_id]
        if isinstance(payload, Exception):
            raise payload
        return payload


class _FakeSupabase:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.stored: dict[str, list[dict[str, object]]] = {}
        self.fail_for = fail_for or set()

    def replace_laps(
        self, external_id: str, laps: list[dict[str, object]], session: dict[str, object]
    ) -> None:
        if external_id in self.fail_for:
            raise SyncError("Supabase request failed (500): boom")
        self.stored[external_id] = laps


class StoreSplitsTests(unittest.TestCase):
    def test_stores_each_activity_and_survives_one_failing(self) -> None:
        garmin = _FakeGarmin(
            {
                "1": {"lapDTOs": [_lap()]},
                "2": RuntimeError("Garmin rate limit"),
                "3": {"lapDTOs": [_lap(), _lap(lapIndex=2)]},
                "4": {"lapDTOs": []},
                "5": {"lapDTOs": [_lap()]},
            }
        )
        supabase = _FakeSupabase(fail_for={"5"})

        with patch("sys.stderr"):
            result = store_splits(
                garmin, supabase, {"access_token": "t"}, ["1", "2", "3", "4", "5"], pause_seconds=0
            )

        self.assertEqual(garmin.requested, ["1", "2", "3", "4", "5"])
        self.assertEqual(sorted(supabase.stored), ["1", "3"])
        self.assertEqual(len(supabase.stored["3"]), 2)
        self.assertEqual((result.stored, result.failed), (2, 2))

    def test_an_empty_list_asks_garmin_for_nothing(self) -> None:
        garmin = _FakeGarmin({})

        result = store_splits(garmin, _FakeSupabase(), {}, [], pause_seconds=0)

        self.assertEqual(garmin.requested, [])
        self.assertEqual((result.stored, result.failed), (0, 0))


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


class SessionForSyncTests(unittest.TestCase):
    class FakeSupabase:
        def __init__(self) -> None:
            self.login_calls = []
            self.active_calls = 0

        def login(self, email: str, password: str) -> dict:
            self.login_calls.append((email, password))
            return {"user": {"id": "user-1"}}

        def active(self) -> dict:
            self.active_calls += 1
            return {"user": {"id": "cached-user"}}

    def test_logs_in_afresh_when_runtime_credentials_are_configured(self) -> None:
        supabase = self.FakeSupabase()
        with patch.dict(
            "os.environ",
            {
                "PERSONAL_OBSERVABILITY_APP_EMAIL": "person@example.com",
                "PERSONAL_OBSERVABILITY_APP_PASSWORD": "secret",
            },
            clear=True,
        ):
            session = session_for_sync(supabase)

        self.assertEqual(session["user"]["id"], "user-1")
        self.assertEqual(supabase.login_calls, [("person@example.com", "secret")])
        self.assertEqual(supabase.active_calls, 0)

    def test_uses_the_cached_session_when_runtime_credentials_are_absent(self) -> None:
        supabase = self.FakeSupabase()
        with patch.dict("os.environ", {}, clear=True):
            session = session_for_sync(supabase)

        self.assertEqual(session["user"]["id"], "cached-user")
        self.assertEqual(supabase.login_calls, [])
        self.assertEqual(supabase.active_calls, 1)

    def test_rejects_a_partial_runtime_configuration(self) -> None:
        supabase = self.FakeSupabase()
        with patch.dict(
            "os.environ",
            {"PERSONAL_OBSERVABILITY_APP_EMAIL": "person@example.com"},
            clear=True,
        ):
            with self.assertRaisesRegex(SyncError, "must be configured together"):
                session_for_sync(supabase)


if __name__ == "__main__":
    unittest.main()
