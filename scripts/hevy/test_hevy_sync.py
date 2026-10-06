import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from hevy_sync import (
    HevyClient,
    SupabaseSession,
    SyncError,
    app_environment,
    configuration,
    hevy_api_key,
    plan_operations,
    session_for_sync,
    sync_since,
    validate_railway_volume,
)


SYNCED_AT = "2026-09-30T12:00:00+00:00"


def workout(**overrides):
    """A workout trimmed from a real Hevy events payload (2026-09-29 probe)."""
    base = {
        "id": "b459cba5-cd6d-463c-abd6-54f8eafcadcb",
        "title": "Push 💪",
        "routine_id": "b459cba5-cd6d-463c-abd6-54f8eafcadcc",
        "description": "",
        "start_time": "2026-09-29T17:02:11+00:00",
        "end_time": "2026-09-29T18:10:41+00:00",
        "updated_at": "2026-09-29T18:11:02.518Z",
        "created_at": "2026-09-29T18:11:02.518Z",
        "exercises": [
            {
                "index": 0,
                "title": "Bench Press (Barbell)",
                "notes": "",
                "exercise_template_id": "79D0BB3A",
                "superset_id": None,
                "sets": [
                    {"index": 0, "type": "warmup", "weight_kg": 40, "reps": 10,
                     "distance_meters": None, "duration_seconds": None, "rpe": None,
                     "custom_metric": None},
                    {"index": 1, "type": "normal", "weight_kg": 80, "reps": 8,
                     "distance_meters": None, "duration_seconds": None, "rpe": 8,
                     "custom_metric": None},
                    {"index": 2, "type": "failure", "weight_kg": 80, "reps": 6,
                     "distance_meters": None, "duration_seconds": None, "rpe": 10,
                     "custom_metric": None},
                ],
            },
            {
                "index": 1,
                "title": "Triceps Dip",
                "notes": "",
                "exercise_template_id": "6575F52D",
                "superset_id": 0,
                "sets": [
                    {"index": 0, "type": "normal", "weight_kg": None, "reps": 12,
                     "distance_meters": None, "duration_seconds": None, "rpe": None,
                     "custom_metric": None},
                    {"index": 1, "type": "dropset", "weight_kg": 10.5, "reps": None,
                     "distance_meters": None, "duration_seconds": None, "rpe": None,
                     "custom_metric": None},
                ],
            },
        ],
    }
    return {**base, **overrides}


def updated(**overrides):
    return {"type": "updated", "workout": workout(**overrides)}


def deleted(workout_id="gone", deleted_at="2026-09-29T10:00:00.000Z"):
    return {"type": "deleted", "id": workout_id, "deleted_at": deleted_at}


def operations(events):
    return plan_operations(events, "user-1", SYNCED_AT)


def plan(events):
    """The fitness activity rows of the planned replace operations."""
    return [op["activity"] for op in operations(events) if op["op"] == "replace"]


class PlanOperationsTests(unittest.TestCase):
    def test_turns_an_updated_event_into_a_fitness_activity(self) -> None:
        [row] = plan([updated()])

        self.assertEqual(row["user_id"], "user-1")
        self.assertEqual(row["source"], "hevy")
        self.assertEqual(row["provider"], "hevy_public_api")
        self.assertEqual(row["external_id"], "b459cba5-cd6d-463c-abd6-54f8eafcadcb")
        self.assertEqual(row["activity_name"], "Push 💪")
        self.assertEqual(row["activity_type"], "strength_training")
        self.assertEqual(row["synced_at"], SYNCED_AT)
        self.assertIsNone(row["calories_kcal"])
        self.assertIsNone(row["average_heart_rate_bpm"])
        self.assertIsNone(row["maximum_heart_rate_bpm"])

    def test_an_empty_event_list_plans_nothing(self) -> None:
        self.assertEqual(plan([]), [])

    def test_started_at_is_utc(self) -> None:
        [row] = plan([updated(start_time="2026-09-29T17:02:11+00:00")])
        self.assertEqual(row["started_at"], "2026-09-29T17:02:11+00:00")

    def test_duration_is_end_minus_start(self) -> None:
        [row] = plan([updated()])
        self.assertEqual(row["duration_seconds"], 68 * 60 + 30)

    def test_duration_is_null_without_an_end_time(self) -> None:
        [row] = plan([updated(end_time=None)])
        self.assertIsNone(row["duration_seconds"])

    def test_totals_count_every_set_but_reps_and_volume_skip_warmups(self) -> None:
        [row] = plan([updated()])

        self.assertEqual(row["total_sets"], 5)
        self.assertEqual(row["active_sets"], 4)
        # 8 + 6 + 12, with the dropset's missing reps contributing nothing.
        self.assertEqual(row["total_reps"], 26)
        # 80×8 + 80×6; the dip has no weight and the dropset has no reps.
        self.assertEqual(row["total_volume_kg"], 1120.0)

    def test_a_workout_without_exercises_has_zero_totals(self) -> None:
        [row] = plan([updated(exercises=None)])

        self.assertEqual(
            (row["total_sets"], row["active_sets"], row["total_reps"], row["total_volume_kg"]),
            (0, 0, 0, 0.0),
        )

    def test_tolerates_missing_set_and_exercise_fields(self) -> None:
        [row] = plan([updated(exercises=[{"sets": [{}, {"type": "warmup"}, "junk"]}, {}])])

        self.assertEqual(row["total_sets"], 2)
        self.assertEqual(row["active_sets"], 1)
        self.assertEqual(row["total_reps"], 0)

    def test_skips_a_workout_without_an_id_or_start_time(self) -> None:
        events = [
            updated(id=None),
            updated(start_time=None),
            updated(start_time="not a time"),
            {"type": "updated"},
            {"type": "updated", "workout": "junk"},
            "junk",
        ]
        self.assertEqual(plan(events), [])

    def test_a_missing_title_leaves_the_name_null(self) -> None:
        [row] = plan([updated(title=None)])
        self.assertIsNone(row["activity_name"])

    def test_keeps_the_newest_event_when_a_workout_repeats(self) -> None:
        # The API lists events newest first; a repeat across pages must not
        # let the older state win, or reach one upsert batch twice.
        rows = plan([updated(title="Newer"), updated(title="Older")])
        self.assertEqual([row["activity_name"] for row in rows], ["Newer"])

    def test_orders_operations_oldest_first(self) -> None:
        # The API lists events newest first.
        ops = operations([
            updated(id="newer"),
            deleted("middle"),
            updated(id="older"),
        ])
        self.assertEqual(
            [(op["op"], op.get("external_id") or op["activity"]["external_id"]) for op in ops],
            [("replace", "older"), ("delete", "middle"), ("replace", "newer")],
        )


class DeletionTests(unittest.TestCase):
    def test_a_delete_only_window_plans_delete_operations_by_workout_id(self) -> None:
        ops = operations([deleted("b"), deleted("a")])
        self.assertEqual(
            ops,
            [{"op": "delete", "external_id": "a"}, {"op": "delete", "external_id": "b"}],
        )

    def test_a_delete_after_an_update_wins(self) -> None:
        # Newest first: the delete is the later event.
        ops = operations([deleted("w1"), updated(id="w1")])
        self.assertEqual(ops, [{"op": "delete", "external_id": "w1"}])

    def test_an_update_after_a_delete_wins(self) -> None:
        ops = operations([updated(id="w1", title="Back"), deleted("w1")])
        self.assertEqual([op["op"] for op in ops], ["replace"])
        self.assertEqual(ops[0]["activity"]["activity_name"], "Back")

    def test_a_delete_of_an_unknown_id_is_still_planned(self) -> None:
        # The worker treats a missing row as success.
        self.assertEqual(
            operations([deleted("never-synced")]),
            [{"op": "delete", "external_id": "never-synced"}],
        )

    def test_skips_a_deleted_event_without_an_id(self) -> None:
        self.assertEqual(operations([{"type": "deleted"}, {"type": "deleted", "id": " "}]), [])

    def test_ignores_unknown_event_types(self) -> None:
        self.assertEqual(operations([{"type": "mystery", "id": "x"}]), [])


class PlanExercisesAndSetsTests(unittest.TestCase):
    def test_nests_exercises_and_sets_under_the_workout(self) -> None:
        [row] = plan([updated()])

        bench, dip = row["exercises"]
        self.assertEqual(
            {key: bench[key] for key in
             ("position", "title", "exercise_template_id", "notes", "superset_id")},
            {"position": 0, "title": "Bench Press (Barbell)",
             "exercise_template_id": "79D0BB3A", "notes": "", "superset_id": None},
        )
        self.assertEqual([item["type"] for item in bench["sets"]],
                         ["warmup", "normal", "failure"])
        self.assertEqual(bench["sets"][1], {
            "position": 1, "type": "normal", "weight_kg": 80.0, "reps": 8, "rpe": 8.0,
            "distance_meters": None, "duration_seconds": None, "custom_metric": None,
        })
        self.assertEqual(dip["position"], 1)
        self.assertEqual(len(dip["sets"]), 2)

    def test_set_positions_restart_for_every_exercise(self) -> None:
        [row] = plan([updated()])
        self.assertEqual(
            [[item["position"] for item in exercise["sets"]] for exercise in row["exercises"]],
            [[0, 1, 2], [0, 1]],
        )

    def test_a_superset_id_is_kept_and_a_missing_one_is_null(self) -> None:
        [row] = plan([updated()])
        self.assertEqual([item["superset_id"] for item in row["exercises"]], [None, 0])

    def test_missing_optional_set_fields_become_null(self) -> None:
        [row] = plan([updated(exercises=[{"index": 0, "sets": [{"index": 0, "type": "normal"}]}])])

        [exercise] = row["exercises"]
        self.assertEqual(exercise["sets"], [{
            "position": 0, "type": "normal", "weight_kg": None, "reps": None, "rpe": None,
            "distance_meters": None, "duration_seconds": None, "custom_metric": None,
        }])
        self.assertIsNone(exercise["title"])
        self.assertIsNone(exercise["exercise_template_id"])

    def test_a_set_without_a_type_is_a_normal_set(self) -> None:
        [row] = plan([updated(exercises=[{"sets": [{"reps": 5}]}])])
        self.assertEqual(row["exercises"][0]["sets"][0]["type"], "normal")

    def test_an_unknown_set_type_is_passed_on_for_the_database_to_reject(self) -> None:
        [row] = plan([updated(exercises=[{"sets": [{"type": "amrap"}]}])])
        self.assertEqual(row["exercises"][0]["sets"][0]["type"], "amrap")

    def test_reps_are_whole_numbers(self) -> None:
        [row] = plan([updated(exercises=[{"sets": [{"reps": 8.0}]}])])
        self.assertIsInstance(row["exercises"][0]["sets"][0]["reps"], int)

    def test_follows_hevys_order_and_numbers_positions_without_gaps(self) -> None:
        [row] = plan([updated(exercises=[
            {"index": 5, "title": "Second", "sets": [{"index": 9}, {"index": 4}]},
            {"index": 2, "title": "First", "sets": []},
            "junk",
        ])])

        self.assertEqual([(item["position"], item["title"]) for item in row["exercises"]],
                         [(0, "First"), (1, "Second")])
        self.assertEqual([item["position"] for item in row["exercises"][1]["sets"]], [0, 1])

    def test_a_workout_without_exercises_has_an_empty_list(self) -> None:
        [row] = plan([updated(exercises=None)])
        self.assertEqual(row["exercises"], [])


class ReplaceWorkoutTests(unittest.TestCase):
    def test_writes_each_workout_through_the_replace_function(self) -> None:
        captured = []

        def fake_open(request, timeout):
            captured.append(request)
            return FakeResponse(b'"activity-id"')

        session = SupabaseSession("http://db.test", "pub", Path("unused"))
        payload = {"external_id": "w1", "exercises": []}
        with patch("hevy_sync.urlopen", fake_open):
            session.replace_workout(payload, {"access_token": "tok"})

        [request] = captured
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://db.test/rest/v1/rpc/replace_fitness_workout")
        self.assertEqual(json.loads(request.data), {"payload": payload})
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")

    def test_requires_an_access_token(self) -> None:
        session = SupabaseSession("http://db.test", "pub", Path("unused"))
        with self.assertRaises(SyncError):
            session.replace_workout({}, {})


class LocalDayTests(unittest.TestCase):
    def local_day(self, start_time: str) -> str:
        [row] = plan([updated(start_time=start_time, end_time=None)])
        return row["local_day"]

    def test_just_after_midnight_in_bst_belongs_to_the_next_day(self) -> None:
        self.assertEqual(self.local_day("2026-09-29T23:05:00+00:00"), "2026-09-30")

    def test_just_after_midnight_in_gmt_belongs_to_that_day(self) -> None:
        self.assertEqual(self.local_day("2026-11-10T00:05:00+00:00"), "2026-11-10")

    def test_the_night_the_clocks_go_back(self) -> None:
        # BST ends at 01:00 UTC on 2026-10-25.
        self.assertEqual(self.local_day("2026-10-24T23:30:00+00:00"), "2026-10-25")
        self.assertEqual(self.local_day("2026-10-25T23:30:00+00:00"), "2026-10-25")

    def test_the_night_the_clocks_go_forward(self) -> None:
        # BST starts at 01:00 UTC on 2026-03-29.
        self.assertEqual(self.local_day("2026-03-28T23:30:00+00:00"), "2026-03-28")
        self.assertEqual(self.local_day("2026-03-29T23:30:00+00:00"), "2026-03-30")

    def test_never_uses_created_at(self) -> None:
        # Most of the history shares one bulk-import created_at.
        [row] = plan([updated(
            start_time="2023-04-12T18:00:00+00:00",
            created_at="2025-01-05T09:00:00.000Z",
        )])
        self.assertEqual(row["local_day"], "2023-04-12")


class TimestampFormatTests(unittest.TestCase):
    def test_parses_z_with_milliseconds(self) -> None:
        [row] = plan([updated(
            start_time="2026-09-29T17:02:11.250Z",
            end_time="2026-09-29T17:32:11.750Z",
        )])

        self.assertEqual(row["started_at"], "2026-09-29T17:02:11.250000+00:00")
        self.assertEqual(row["duration_seconds"], 1800.5)
        self.assertEqual(row["local_day"], "2026-09-29")

    def test_parses_plus_zero_offset(self) -> None:
        [row] = plan([updated(start_time="2026-09-29T23:30:00+00:00", end_time=None)])
        self.assertEqual(row["local_day"], "2026-09-30")

    def test_converts_a_non_utc_offset_to_utc(self) -> None:
        [row] = plan([updated(start_time="2026-09-30T00:30:00+01:00", end_time=None)])
        self.assertEqual(row["started_at"], "2026-09-29T23:30:00+00:00")
        self.assertEqual(row["local_day"], "2026-09-30")


class SyncSinceTests(unittest.TestCase):
    def test_requests_the_last_seven_days_in_utc(self) -> None:
        now = datetime(2026, 9, 30, 12, 34, 56, 789, tzinfo=timezone.utc)
        self.assertEqual(sync_since(now), "2026-09-23T12:34:56Z")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class HevyClientTests(unittest.TestCase):
    def test_reads_every_page_with_get_and_the_api_key_header(self) -> None:
        requests = []
        pages = {
            "1": {"page": 1, "page_count": 2, "events": [updated(id="a")]},
            "2": {"page": 2, "page_count": 2, "events": [updated(id="b")]},
        }

        def open_url(request, timeout):
            requests.append(request)
            query = parse_qs(urlsplit(request.full_url).query)
            return FakeResponse(json.dumps(pages[query["page"][0]]).encode())

        events = HevyClient("secret-key", open_url=open_url).workout_events(
            "2026-09-23T12:00:00Z"
        )

        self.assertEqual([event["workout"]["id"] for event in events], ["a", "b"])
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Api-key"), "secret-key")
            url = urlsplit(request.full_url)
            self.assertEqual(url.netloc, "api.hevyapp.com")
            self.assertEqual(url.path, "/v1/workouts/events")
            query = parse_qs(url.query)
            self.assertEqual(query["since"], ["2026-09-23T12:00:00Z"])
            self.assertEqual(query["pageSize"], ["10"])

    def test_stops_after_one_request_when_there_are_no_events(self) -> None:
        calls = []

        def open_url(request, timeout):
            calls.append(request)
            return FakeResponse(b'{"page": 1, "page_count": 0, "events": []}')

        self.assertEqual(HevyClient("k", open_url=open_url).workout_events("x"), [])
        self.assertEqual(len(calls), 1)

    def test_an_invalid_key_fails_without_echoing_the_key(self) -> None:
        def open_url(request, timeout):
            raise HTTPError(
                request.full_url, 401, "Unauthorized", {},
                io.BytesIO(b"InvalidApiKey secret-key"),
            )

        with self.assertRaises(SyncError) as raised:
            HevyClient("secret-key", open_url=open_url).workout_events("x")

        message = str(raised.exception)
        self.assertIn("401", message)
        self.assertIn("InvalidApiKey", message)
        self.assertNotIn("secret-key", message)

    def test_rejects_an_unexpected_response_shape(self) -> None:
        def open_url(request, timeout):
            return FakeResponse(b'{"page": 1}')

        with self.assertRaises(SyncError):
            HevyClient("k", open_url=open_url).workout_events("x")


class DeleteActivityTests(unittest.TestCase):
    def test_deletes_by_owner_source_and_external_id(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append(request)
            return FakeResponse(b"")

        supabase = SupabaseSession("http://db", "pub", Path("/tmp/s.json"))
        session = {"access_token": "tok", "user": {"id": "user-1"}}
        with patch("hevy_sync.urlopen", open_url):
            supabase.delete_activity("w1", session)

        [request] = requests
        self.assertEqual(request.get_method(), "DELETE")
        url = urlsplit(request.full_url)
        self.assertEqual(url.path, "/rest/v1/fitness_activities")
        self.assertEqual(
            parse_qs(url.query),
            {"source": ["eq.hevy"], "external_id": ["eq.w1"], "user_id": ["eq.user-1"]},
        )


class HevyApiKeyTests(unittest.TestCase):
    def test_requires_the_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(SyncError, "HEVY_API_KEY"):
                hevy_api_key()

    def test_strips_whitespace(self) -> None:
        with patch.dict("os.environ", {"HEVY_API_KEY": " abc \n"}, clear=True):
            self.assertEqual(hevy_api_key(), "abc")


class RailwayVolumeTests(unittest.TestCase):
    def test_requires_a_volume_on_railway(self) -> None:
        environment = {"RAILWAY_ENVIRONMENT_NAME": "production"}
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(SyncError, "persistent volume"):
                validate_railway_volume(Path("/data/session.json"))

    def test_accepts_the_session_inside_the_volume(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAILWAY_ENVIRONMENT_NAME": "production",
                "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            },
            clear=True,
        ):
            validate_railway_volume(Path("/data/session.json"))

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
                validate_railway_volume(Path("/tmp/session.json"))

    def test_skips_the_check_off_railway(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            validate_railway_volume(Path("/tmp/session.json"))


class ConfigurationTests(unittest.TestCase):
    def test_requires_the_supabase_url_and_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(SyncError, "SUPABASE_URL"):
                configuration()

    def test_rewrites_localhost_inside_docker(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "http://127.0.0.1:54321",
                "SUPABASE_PUBLISHABLE_KEY": "publishable",
                "HEVY_SYNC_IN_DOCKER": "true",
            },
            clear=True,
        ):
            supabase = configuration()

        self.assertEqual(supabase.base_url, "http://host.docker.internal:54321")


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
