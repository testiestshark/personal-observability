import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from garmin_sync import (
    SyncError,
    activities_needing_splits,
    app_environment,
    current_london_day,
    docker_host_url,
    has_embedded_rows,
    is_foot_activity,
    is_garmin_activity_id,
    normalize_activities,
    normalize_daily_health,
    normalize_laps,
    normalize_steps,
    map_run_weather,
    outdoor_run_starts,
    session_for_sync,
    store_run_weather,
    store_splits,
    validate_railway_volume,
    weather_request_url,
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
            {"external_id": "1", "activity_type": "running", "has_laps": False},
            {"external_id": "2", "activity_type": "running", "has_laps": True},
            {"external_id": "3", "activity_type": "cycling", "has_laps": False},
            {"external_id": "4", "activity_type": "trail_running", "has_laps": False},
        ]

        self.assertEqual(activities_needing_splits(rows), ["1", "4"])

    def test_ignores_an_id_garmin_cannot_look_up(self) -> None:
        rows = [
            {"external_id": "abc", "activity_type": "running", "has_laps": False},
            {"external_id": "12 3", "activity_type": "running", "has_laps": False},
        ]

        self.assertEqual(activities_needing_splits(rows), [])


class IsGarminActivityIdTests(unittest.TestCase):
    def test_accepts_plain_ascii_numbers(self) -> None:
        self.assertTrue(is_garmin_activity_id("12345678901"))

    def test_rejects_anything_garmin_could_not_look_up_or_that_would_alter_a_query(self) -> None:
        # "²" and Arabic-Indic digits are str.isdigit() but not integers Garmin accepts.
        for value in ("", "abc", "12 3", "1,2", "1)", "²", "١٢", "-5", None, 12):
            self.assertFalse(is_garmin_activity_id(value), repr(value))


class HasEmbeddedRowsTests(unittest.TestCase):
    def test_is_true_when_postgrest_embedded_a_row(self) -> None:
        self.assertTrue(has_embedded_rows([{"id": "abc"}]))

    def test_treats_nothing_or_anything_unexpected_as_no_laps(self) -> None:
        for value in (None, [], {}, "3", {"id": "abc"}):
            self.assertFalse(has_embedded_rows(value), repr(value))


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

    def test_stops_after_repeated_failures_in_a_row_instead_of_hammering_garmin(self) -> None:
        # Seven activities, all failing: the likeliest cause is a rate limit, and
        # more requests would only make it worse.
        garmin = _FakeGarmin({str(n): RuntimeError("429") for n in range(7)})

        with patch("sys.stderr"):
            result = store_splits(
                garmin,
                _FakeSupabase(),
                {},
                [str(n) for n in range(7)],
                pause_seconds=0,
                max_consecutive_failures=3,
            )

        self.assertEqual(garmin.requested, ["0", "1", "2"])
        self.assertEqual((result.stored, result.failed, result.stopped_early), (0, 3, True))

    def test_a_success_between_failures_resets_the_streak(self) -> None:
        garmin = _FakeGarmin(
            {
                "0": RuntimeError("x"),
                "1": RuntimeError("x"),
                "2": {"lapDTOs": [_lap()]},
                "3": RuntimeError("x"),
                "4": RuntimeError("x"),
            }
        )

        with patch("sys.stderr"):
            result = store_splits(
                garmin,
                _FakeSupabase(),
                {},
                ["0", "1", "2", "3", "4"],
                pause_seconds=0,
                max_consecutive_failures=3,
            )

        self.assertEqual(len(garmin.requested), 5)
        self.assertFalse(result.stopped_early)

    def test_a_limit_counts_activities_stored_so_empty_ones_do_not_use_it_up(self) -> None:
        # Activities Garmin reports no laps for would otherwise sit at the top of a
        # newest-first list and starve older runs on every limited backfill.
        garmin = _FakeGarmin(
            {
                "0": {"lapDTOs": []},
                "1": {"lapDTOs": [_lap()]},
                "2": {"lapDTOs": []},
                "3": {"lapDTOs": [_lap()]},
                "4": {"lapDTOs": [_lap()]},
            }
        )
        supabase = _FakeSupabase()

        result = store_splits(
            garmin, supabase, {}, ["0", "1", "2", "3", "4"], pause_seconds=0, max_stored=2
        )

        self.assertEqual(garmin.requested, ["0", "1", "2", "3"])
        self.assertEqual(sorted(supabase.stored), ["1", "3"])
        self.assertEqual(result.stored, 2)

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


# A start point nobody could confuse with a rounded one, so a leak is visible.
RAW_LAT = 51.48123
RAW_LON = -0.12345


def _outdoor(**overrides: object) -> dict[str, object]:
    return {
        "activityId": 9001,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-10-20 07:05:19",
        "startLatitude": RAW_LAT,
        "startLongitude": RAW_LON,
        **overrides,
    }


def _archive(day: str, hours: dict[int, dict[str, object]] | None = None) -> dict[str, object]:
    """An Open-Meteo archive payload for a UTC day; hours not given are null."""
    variables = (
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "wind_speed_10m",
        "precipitation",
    )
    payload: dict[str, object] = {
        "hourly": {"time": [f"{day}T{hour:02d}:00" for hour in range(24)]}
    }
    defaults = dict(zip(variables, (11.2, 9.1, 78, 8.4, 0.0)))
    for variable in variables:
        payload["hourly"][variable] = [  # type: ignore[index]
            ({**defaults, **hours[hour]}[variable] if hours and hour in hours else None)
            for hour in range(24)
        ]
    return payload


class OutdoorRunStartsTests(unittest.TestCase):
    def test_rounds_the_start_point_to_one_decimal_place(self) -> None:
        (start,) = outdoor_run_starts([_outdoor()])

        self.assertEqual((start.latitude, start.longitude), (51.5, -0.1))
        self.assertEqual(start.external_id, "9001")
        self.assertEqual(start.started_at, datetime(2026, 10, 20, 7, 5, 19, tzinfo=timezone.utc))

    def test_leaves_out_a_treadmill_run_which_has_no_coordinate_keys_at_all(self) -> None:
        treadmill = _outdoor(activityType={"typeKey": "treadmill_running"})
        del treadmill["startLatitude"], treadmill["startLongitude"]

        self.assertEqual(outdoor_run_starts([treadmill]), [])

    def test_leaves_out_an_indoor_type_even_if_it_carries_a_coordinate(self) -> None:
        for type_key in ("treadmill_running", "indoor_walking", "virtual_run"):
            self.assertEqual(
                outdoor_run_starts([_outdoor(activityType={"typeKey": type_key})]), [], type_key
            )

    def test_leaves_out_missing_null_zero_or_impossible_coordinates(self) -> None:
        for overrides in (
            {"startLatitude": None},
            {"startLongitude": None},
            {"startLatitude": 0, "startLongitude": 0},
            {"startLatitude": "51.5"},
            {"startLatitude": 91},
            {"startLongitude": -181},
            {"startLatitude": float("nan")},
        ):
            self.assertEqual(outdoor_run_starts([_outdoor(**overrides)]), [], overrides)

    def test_keeps_a_coordinate_with_one_zero_axis(self) -> None:
        self.assertEqual(len(outdoor_run_starts([_outdoor(startLongitude=0.04)])), 1)

    def test_leaves_out_non_foot_activities_and_unusable_rows(self) -> None:
        rows = [
            _outdoor(activityType={"typeKey": "cycling"}),
            _outdoor(activityId=None),
            _outdoor(activityId="12x"),
            _outdoor(startTimeGMT=None),
            "not a dict",
        ]

        self.assertEqual(outdoor_run_starts(rows), [])
        self.assertEqual(outdoor_run_starts(None), [])

    def test_accepts_walks_hikes_and_trail_runs(self) -> None:
        rows = [
            _outdoor(activityId=index, activityType={"typeKey": key})
            for index, key in enumerate(("walking", "hiking", "trail_running"), start=1)
        ]

        self.assertEqual(len(outdoor_run_starts(rows)), 3)

    def test_the_coordinate_is_not_in_the_printed_form(self) -> None:
        (start,) = outdoor_run_starts([_outdoor()])

        for text in (repr(start), str(start)):
            self.assertNotIn("51.5", text)
            self.assertNotIn("0.1", text)


class WeatherRequestUrlTests(unittest.TestCase):
    def test_asks_for_the_utc_day_in_utc_and_mph_at_the_rounded_point(self) -> None:
        (start,) = outdoor_run_starts([_outdoor()])

        query = parse_qs(urlsplit(weather_request_url(start)).query)

        self.assertEqual(query["start_date"], ["2026-10-20"])
        self.assertEqual(query["end_date"], ["2026-10-20"])
        self.assertEqual(query["timezone"], ["UTC"])
        self.assertEqual(query["wind_speed_unit"], ["mph"])
        self.assertEqual(query["latitude"], ["51.5"])
        self.assertEqual(query["longitude"], ["-0.1"])
        self.assertEqual(
            query["hourly"],
            ["temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,precipitation"],
        )

    def test_the_unrounded_point_is_not_in_the_request(self) -> None:
        (start,) = outdoor_run_starts([_outdoor()])

        url = weather_request_url(start)

        self.assertNotIn("51.48", url)
        self.assertNotIn("0.12", url)


class MapRunWeatherTests(unittest.TestCase):
    FETCHED = "2026-10-22T08:00:00+00:00"

    def test_maps_the_hour_the_run_started_in(self) -> None:
        payload = _archive("2026-10-20", {7: {"temperature_2m": 12.4, "precipitation": 0.3}})

        row = map_run_weather(payload, datetime(2026, 10, 20, 7, 59, tzinfo=timezone.utc), self.FETCHED)

        self.assertEqual(
            row,
            {
                "hour_start": "2026-10-20T07:00:00Z",
                "temperature_c": 12.4,
                "apparent_temperature_c": 9.1,
                "relative_humidity_percent": 78.0,
                "wind_speed_mph": 8.4,
                "precipitation_mm": 0.3,
                "source": "open-meteo-archive",
                "fetched_at": self.FETCHED,
            },
        )

    def test_the_utc_hour_is_right_either_side_of_the_clocks_going_back(self) -> None:
        # On 2026-10-25 BST ends at 01:00 UTC, so local 01:30 happens twice:
        # 00:30 UTC (BST) and 01:30 UTC (GMT). They are different archive hours.
        payload = _archive(
            "2026-10-25", {0: {"temperature_2m": 10.0}, 1: {"temperature_2m": 8.0}}
        )

        bst = map_run_weather(payload, datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), self.FETCHED)
        gmt = map_run_weather(payload, datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc), self.FETCHED)

        self.assertEqual((bst["hour_start"], bst["temperature_c"]), ("2026-10-25T00:00:00Z", 10.0))
        self.assertEqual((gmt["hour_start"], gmt["temperature_c"]), ("2026-10-25T01:00:00Z", 8.0))

    def test_the_utc_hour_is_right_when_the_clocks_go_forward(self) -> None:
        # 2026-03-29: GMT ends at 01:00 UTC; local 02:00-03:00 does not exist.
        payload = _archive("2026-03-29", {0: {"temperature_2m": 4.0}, 1: {"temperature_2m": 5.0}})

        before = map_run_weather(payload, datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc), self.FETCHED)
        after = map_run_weather(payload, datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc), self.FETCHED)

        self.assertEqual((before["temperature_c"], after["temperature_c"]), (4.0, 5.0))

    def test_an_offset_start_is_converted_to_utc_first(self) -> None:
        payload = _archive("2026-07-01", {6: {"temperature_2m": 15.5}})
        start = datetime(2026, 7, 1, 7, 10, tzinfo=timezone(timedelta(hours=1)))

        self.assertEqual(map_run_weather(payload, start, self.FETCHED)["temperature_c"], 15.5)

    def test_zero_rain_is_a_value_not_a_gap(self) -> None:
        payload = _archive("2026-10-20", {7: {"precipitation": 0}})

        row = map_run_weather(payload, datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc), self.FETCHED)

        self.assertEqual(row["precipitation_mm"], 0.0)

    def test_an_hour_the_archive_has_no_values_for_yet_is_none(self) -> None:
        payload = _archive("2026-10-20", {6: {}})

        self.assertIsNone(
            map_run_weather(payload, datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc), self.FETCHED)
        )

    def test_a_single_missing_value_is_none_rather_than_a_half_empty_row(self) -> None:
        payload = _archive("2026-10-20", {7: {}})
        payload["hourly"]["wind_speed_10m"][7] = None  # type: ignore[index]

        self.assertIsNone(
            map_run_weather(payload, datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc), self.FETCHED)
        )

    def test_a_day_the_response_does_not_contain_is_none(self) -> None:
        payload = _archive("2026-10-19", {7: {}})

        self.assertIsNone(
            map_run_weather(payload, datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc), self.FETCHED)
        )

    def test_unexpected_shapes_and_impossible_values_are_none(self) -> None:
        start = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc)
        for payload in (None, [], {}, {"hourly": []}, {"hourly": {"time": "x"}}):
            self.assertIsNone(map_run_weather(payload, start, self.FETCHED), repr(payload))
        for bad in ({"relative_humidity_2m": 140}, {"wind_speed_10m": -1}, {"precipitation": -0.1}):
            self.assertIsNone(
                map_run_weather(_archive("2026-10-20", {7: bad}), start, self.FETCHED), repr(bad)
            )


class _WeatherSupabase:
    def __init__(self, ids: dict[str, str], have: set[str] | None = None, fail: bool = False) -> None:
        self.ids = ids
        self.have = have or set()
        self.fail = fail
        self.inserted: list[dict[str, object]] = []

    def fitness_activity_ids(self, external_ids: list[str], session: dict[str, object]) -> dict[str, str]:
        return {key: value for key, value in self.ids.items() if key in external_ids}

    def run_weather_activity_ids(self, activity_ids: list[str], session: dict[str, object]) -> set[str]:
        return {value for value in activity_ids if value in self.have}

    def insert_run_weather(self, row: dict[str, object], session: dict[str, object]) -> None:
        if self.fail:
            raise SyncError("Supabase request failed (500): boom")
        self.inserted.append(row)


def _starts(*ids: int) -> list:
    return outdoor_run_starts([_outdoor(activityId=value) for value in ids])


class StoreRunWeatherTests(unittest.TestCase):
    SESSION = {"access_token": "t"}

    def test_stores_a_row_for_a_run_the_archive_covers(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1"})
        urls: list[str] = []

        def fetch(url: str) -> object:
            urls.append(url)
            return _archive("2026-10-20", {7: {"temperature_2m": 12.0}})

        result = store_run_weather(_starts(1), supabase, self.SESSION, fetch=fetch)

        self.assertEqual((result.stored, result.not_yet, result.failed), (1, 0, 0))
        self.assertEqual(len(urls), 1)
        (row,) = supabase.inserted
        self.assertEqual(row["fitness_activity_id"], "uuid-1")
        self.assertEqual(row["temperature_c"], 12.0)

    def test_a_run_too_recent_for_the_archive_gets_its_row_on_a_later_sync(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1"})

        first = store_run_weather(
            _starts(1), supabase, self.SESSION, fetch=lambda url: _archive("2026-10-20")
        )
        self.assertEqual((first.stored, first.not_yet), (0, 1))
        self.assertEqual(supabase.inserted, [])

        later = store_run_weather(
            _starts(1), supabase, self.SESSION, fetch=lambda url: _archive("2026-10-20", {7: {}})
        )
        self.assertEqual((later.stored, later.not_yet), (1, 0))
        self.assertEqual(len(supabase.inserted), 1)

    def test_a_run_that_already_has_weather_is_not_asked_about_again(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1", "2": "uuid-2"}, have={"uuid-1"})
        urls: list[str] = []

        def fetch(url: str) -> object:
            urls.append(url)
            return _archive("2026-10-20", {7: {}})

        result = store_run_weather(_starts(1, 2), supabase, self.SESSION, fetch=fetch)

        self.assertEqual(result.stored, 1)
        self.assertEqual(len(urls), 1)
        self.assertEqual(supabase.inserted[0]["fitness_activity_id"], "uuid-2")

    def test_a_run_not_stored_yet_is_skipped(self) -> None:
        supabase = _WeatherSupabase({})

        result = store_run_weather(
            _starts(1), supabase, self.SESSION, fetch=lambda url: self.fail("no request expected")
        )

        self.assertEqual(result.stored, 0)

    def test_survives_one_failure_and_stops_after_several_in_a_row(self) -> None:
        supabase = _WeatherSupabase({str(n): f"uuid-{n}" for n in range(1, 8)})
        calls: list[str] = []

        def fetch(url: str) -> object:
            calls.append(url)
            if len(calls) == 1:
                return _archive("2026-10-20", {7: {}})
            raise URLError("network down")

        with patch("sys.stderr"):
            result = store_run_weather(_starts(*range(1, 8)), supabase, self.SESSION, fetch=fetch)

        self.assertEqual((result.stored, result.failed, result.stopped_early), (1, 3, True))
        self.assertEqual(len(calls), 4)

    def test_no_runs_makes_no_requests(self) -> None:
        supabase = _WeatherSupabase({})
        supabase.fitness_activity_ids = lambda *args: self.fail("no lookup expected")  # type: ignore[method-assign]

        self.assertEqual(store_run_weather([], supabase, self.SESSION).stored, 0)


class CoordinateNeverLeavesTests(unittest.TestCase):
    """The start point is used for the request and then gone (docs/adr/0001)."""

    LEAKS = ("51.48", "0.12", "51.4812", "0.1234")

    def _assert_clean(self, text: str, where: str) -> None:
        for leak in self.LEAKS:
            self.assertNotIn(leak, text, f"{leak} found in {where}")

    def test_no_stored_row_holds_the_coordinate(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1"})

        store_run_weather(
            _starts(1),
            supabase,
            {"access_token": "t"},
            fetch=lambda url: _archive("2026-10-20", {7: {}}),
        )

        self._assert_clean(json.dumps(supabase.inserted), "the stored row")
        # The rounded form is the request's, not a stored one either.
        self.assertNotIn("51.5", json.dumps(supabase.inserted))

    def test_no_output_holds_the_coordinate_even_when_the_error_carries_the_url(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1", "2": "uuid-2"})

        def fetch(url: str) -> object:
            # Library errors can quote the request, so the worker must not print them.
            raise RuntimeError(f"failed fetching {url}")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            store_run_weather(_starts(1, 2), supabase, {"access_token": "t"}, fetch=fetch)
            print(_starts(1, 2))

        self.assertTrue(err.getvalue())
        for text, where in ((out.getvalue(), "stdout"), (err.getvalue(), "stderr")):
            self._assert_clean(text, where)
            self.assertNotIn("51.5", text, where)

    def test_a_failed_http_request_is_reported_by_status_only(self) -> None:
        supabase = _WeatherSupabase({"1": "uuid-1"})

        def fetch(url: str) -> object:
            raise HTTPError(url, 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            store_run_weather(_starts(1), supabase, {"access_token": "t"}, fetch=fetch)

        self.assertIn("HTTP 429", err.getvalue())
        self.assertNotIn("latitude", err.getvalue())


if __name__ == "__main__":
    unittest.main()
