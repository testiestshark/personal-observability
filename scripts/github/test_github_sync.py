import io
import json
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from github_sync import (
    BACKFILL_START,
    COMMIT_HISTORY_QUERY,
    COMMITS_QUERY,
    COUNTS_QUERY,
    IDENTITY_QUERY,
    TRAILING_DAYS,
    AccountConfig,
    GitHubClient,
    RateLimited,
    RestrictedGitHub,
    SupabaseSession,
    SyncError,
    accounts_from_env,
    backfill_days,
    configuration,
    docker_host_url,
    main,
    plan_commit_rows,
    plan_daily_rows,
    queries_for,
    run_sync,
    session_for_sync,
    sync_account,
    trailing_days,
    utc_day_window,
    validate_railway_volume,
)


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class DayWindowTests(unittest.TestCase):
    def test_a_window_is_exactly_one_utc_date(self) -> None:
        self.assertEqual(
            utc_day_window(date(2026, 10, 10)),
            ("2026-10-10T00:00:00Z", "2026-10-10T23:59:59Z"),
        )

    def test_adjacent_windows_never_overlap_and_leave_no_gap_but_the_inclusive_second(self) -> None:
        # `to` is inclusive in the API, so the next window must start one second after it.
        for day in (date(2026, 3, 28), date(2026, 10, 24), date(2026, 12, 31), date(2026, 2, 28)):
            _, end = utc_day_window(day)
            next_start, _ = utc_day_window(day + timedelta(days=1))
            self.assertEqual(instant(next_start) - instant(end), timedelta(seconds=1))

    def test_a_window_stays_on_one_utc_date_when_london_changes_its_clocks(self) -> None:
        # A London-day window on these dates would be 23h or 25h and span two UTC dates,
        # which GitHub sums (probe, 2026-10-10). The UTC window never does.
        for day in (date(2026, 3, 29), date(2026, 10, 25)):
            start, end = utc_day_window(day)
            self.assertEqual(instant(start).date(), day)
            self.assertEqual(instant(end).date(), day)
            self.assertEqual(instant(end) - instant(start), timedelta(hours=23, minutes=59, seconds=59))


class DayListTests(unittest.TestCase):
    def test_trailing_days_are_today_and_the_thirteen_before_it_oldest_first(self) -> None:
        days = trailing_days(date(2026, 10, 10))
        self.assertEqual(len(days), TRAILING_DAYS)
        self.assertEqual(TRAILING_DAYS, 14)
        self.assertEqual(days[0], date(2026, 9, 27))
        self.assertEqual(days[-1], date(2026, 10, 10))

    def test_trailing_days_cross_a_year_boundary(self) -> None:
        days = trailing_days(date(2027, 1, 3))
        self.assertEqual(days[0], date(2026, 12, 21))
        self.assertEqual(days[-1], date(2027, 1, 3))

    def test_backfill_starts_on_the_first_of_january_2026(self) -> None:
        self.assertEqual(BACKFILL_START, date(2026, 1, 1))
        days = backfill_days(date(2026, 1, 4))
        self.assertEqual(days, [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)])

    def test_backfill_before_its_start_date_is_empty(self) -> None:
        self.assertEqual(backfill_days(date(2025, 12, 31)), [])

    def test_the_trailing_window_is_inside_the_backfill_range(self) -> None:
        today = date(2026, 10, 10)
        self.assertTrue(set(trailing_days(today)) <= set(backfill_days(today)))


def selected_fields(query: str) -> set[str]:
    """Every field a GraphQL document selects. Variables and argument lists are dropped."""
    body = re.sub(r"\$\w+", "", query)
    body = re.sub(r"\([^)]*\)", "", body)
    return set(re.findall(r"[A-Za-z_]\w*", body)) - {"query"}


# Everything a counts_only account's queries may select. A new field here is a privacy
# decision, not a refactor: add it only after deciding it names no repository, message,
# URL or author. (#76 privacy contract.)
COUNTS_ONLY_FIELDS = {
    "viewer",
    "id",
    "login",
    "databaseId",
    "contributionsCollection",
    "totalCommitContributions",
    "totalPullRequestContributions",
    "totalPullRequestReviewContributions",
    "totalIssueContributions",
    "restrictedContributionsCount",
}


class PrivacyContractTests(unittest.TestCase):
    def test_a_counts_only_account_selects_only_counts_and_its_own_identity(self) -> None:
        queries = queries_for("counts_only")
        self.assertTrue(queries)
        for query in queries:
            extra = selected_fields(query) - COUNTS_ONLY_FIELDS
            self.assertEqual(extra, set(), f"counts_only query selects unapproved field(s): {extra}")

    def test_the_counts_query_names_no_repository_message_url_or_author(self) -> None:
        fields = {f.lower() for f in selected_fields(COUNTS_QUERY)}
        for forbidden in (
            "repository", "repositories", "nameWithOwner", "name", "message",
            "messageHeadline", "url", "resourcePath", "author", "history", "title", "email",
        ):
            self.assertNotIn(forbidden.lower(), fields)

    def test_the_selection_check_would_catch_a_field_added_to_the_counts_query(self) -> None:
        tampered = COUNTS_QUERY.replace(
            "restrictedContributionsCount",
            "restrictedContributionsCount commitContributionsByRepository { repository { nameWithOwner } }",
        )
        self.assertIn("nameWithOwner", selected_fields(tampered) - COUNTS_ONLY_FIELDS)

    def test_only_a_full_account_may_run_the_commit_queries(self) -> None:
        counts_only = set(queries_for("counts_only"))
        full = set(queries_for("full"))
        self.assertTrue(counts_only < full)
        self.assertTrue(any("history" in query for query in full - counts_only))
        self.assertFalse(any("history" in query for query in counts_only))

    def test_an_unknown_detail_level_gets_no_queries_rather_than_all_of_them(self) -> None:
        with self.assertRaises(SyncError):
            queries_for("everything")

    def test_the_allow_list_is_enforced_where_queries_are_sent_not_only_in_tests(self) -> None:
        github = FakeGitHub()
        guarded = RestrictedGitHub(github, queries_for("counts_only"))

        guarded.query(IDENTITY_QUERY)
        with self.assertRaises(SyncError):
            guarded.query(COMMITS_QUERY, {"id": "U_1", "since": "x", "until": "y", "after": None})
        with self.assertRaises(SyncError):
            guarded.query("query { viewer { repositories(first: 1) { nodes { name } } } }")
        self.assertEqual([document for document, _ in github.queries], [IDENTITY_QUERY])

    def test_a_full_account_may_send_the_commit_queries(self) -> None:
        github = FakeGitHub(repos=[])
        guarded = RestrictedGitHub(github, queries_for("full"))
        guarded.query(COMMITS_QUERY, {"id": "U_1", "since": "x", "until": "y", "after": None})
        self.assertEqual(len(github.sent(COMMITS_QUERY)), 1)


def counts_response(commit=0, pr=0, review=0, issue=0, unsplit=0):
    return {
        "viewer": {
            "contributionsCollection": {
                "totalCommitContributions": commit,
                "totalPullRequestContributions": pr,
                "totalPullRequestReviewContributions": review,
                "totalIssueContributions": issue,
                "restrictedContributionsCount": unsplit,
            }
        }
    }


class PlanDailyRowsTests(unittest.TestCase):
    def rows(self, response, day=date(2026, 10, 10)):
        return plan_daily_rows("user-1", "acct-1", day, response, "2026-10-10T12:00:00+00:00")

    def test_one_row_per_kind_with_the_five_counts(self) -> None:
        rows = self.rows(counts_response(commit=7, pr=2, review=3, issue=1, unsplit=4))
        self.assertEqual(
            {row["kind"]: row["count"] for row in rows},
            {"commit": 7, "pull_request": 2, "review": 3, "issue": 1, "unsplit": 4},
        )

    def test_rows_carry_ownership_day_and_sync_time(self) -> None:
        for row in self.rows(counts_response(commit=1)):
            self.assertEqual(row["user_id"], "user-1")
            self.assertEqual(row["account_id"], "acct-1")
            self.assertEqual(row["local_day"], "2026-10-10")
            self.assertEqual(row["synced_at"], "2026-10-10T12:00:00+00:00")
            self.assertEqual(set(row), {"user_id", "account_id", "local_day", "kind", "count", "synced_at"})

    def test_a_quiet_day_still_stores_zeros_so_quiet_is_not_mistaken_for_unsynced(self) -> None:
        rows = self.rows(counts_response())
        self.assertEqual(len(rows), 5)
        self.assertEqual({row["count"] for row in rows}, {0})

    def test_a_malformed_response_is_an_error_not_a_day_of_zeros(self) -> None:
        for bad in (
            {},
            {"viewer": None},
            {"viewer": {"contributionsCollection": {"totalCommitContributions": 1}}},
            counts_response(commit=-1),
            counts_response(commit="7"),
            counts_response(commit=True),
        ):
            with self.assertRaises(SyncError, msg=str(bad)):
                self.rows(bad)


def commit(oid="a" * 40, authored="2026-10-10T12:00:00Z", raw=None, headline="Fix the thing"):
    return {
        "oid": oid,
        "messageHeadline": headline,
        "authoredDate": authored,
        "author": {"date": raw if raw is not None else authored},
    }


def repo(commits, node_id="R_1", name="alice/widgets", private=False, branch=True):
    history = {"nodes": commits, "pageInfo": {"hasNextPage": False, "endCursor": None}}
    ref = {"target": {"history": history}} if branch else None
    return {
        "id": node_id,
        "nameWithOwner": name,
        "isPrivate": private,
        "pushedAt": "2026-10-10T12:00:00Z",
        "defaultBranchRef": ref,
    }


class PlanCommitRowsTests(unittest.TestCase):
    FIRST, LAST = date(2026, 6, 1), date(2026, 10, 10)

    def rows(self, repos):
        return plan_commit_rows(
            "user-1", "acct-1", repos, "2026-10-10T12:00:00+00:00", self.FIRST, self.LAST
        )

    def test_a_row_carries_the_repo_the_headline_and_the_ownership_columns(self) -> None:
        [row] = self.rows([repo([commit(oid="abc", headline="Add the widget")], private=True)])
        self.assertEqual(
            row,
            {
                "user_id": "user-1",
                "account_id": "acct-1",
                "repo_node_id": "R_1",
                "repo_name_with_owner": "alice/widgets",
                "repo_is_private": True,
                "oid": "abc",
                "message_headline": "Add the widget",
                "authored_at": "2026-10-10T12:00:00+00:00",
                "author_date_raw": "2026-10-10T12:00:00Z",
                "local_day": "2026-10-10",
                "synced_at": "2026-10-10T12:00:00+00:00",
            },
        )

    def test_commits_at_2330z_and_0030z_land_on_different_utc_dates(self) -> None:
        rows = self.rows([repo([
            commit(oid="late", authored="2026-10-09T23:30:00Z"),
            commit(oid="early", authored="2026-10-10T00:30:00Z"),
        ])])
        self.assertEqual({row["oid"]: row["local_day"] for row in rows},
                         {"late": "2026-10-09", "early": "2026-10-10"})

    def test_a_bst_commit_just_after_london_midnight_belongs_to_the_utc_date_before(self) -> None:
        # 00:30 BST on 1 July is 23:30Z on 30 June. GitHub buckets by UTC date, so the
        # count for 30 June includes it and this row has to agree with that count.
        [row] = self.rows([repo([commit(
            authored="2026-06-30T23:30:00Z", raw="2026-07-01T00:30:00+01:00",
        )])])
        self.assertEqual(row["local_day"], "2026-06-30")
        self.assertEqual(row["authored_at"], "2026-06-30T23:30:00+00:00")
        # The original offset is kept so a later "bucket by the commit's own day" is possible.
        self.assertEqual(row["author_date_raw"], "2026-07-01T00:30:00+01:00")

    def test_an_authored_date_with_an_offset_is_converted_to_utc_before_bucketing(self) -> None:
        [row] = self.rows([repo([commit(authored="2026-07-01T00:30:00+01:00")])])
        self.assertEqual(row["local_day"], "2026-06-30")
        self.assertEqual(row["authored_at"], "2026-06-30T23:30:00+00:00")

    def test_only_the_headline_is_stored_never_a_body(self) -> None:
        [row] = self.rows([repo([commit(headline="Fix it\n\nLong body about secret-project")])])
        self.assertEqual(row["message_headline"], "Fix it")
        self.assertNotIn("secret-project", str(row))
        self.assertNotIn("\n", row["message_headline"])

    def test_any_line_separator_ends_the_headline_not_just_a_newline(self) -> None:
        for headline in ("Fix it\r\nbody", "Fix it\rbody", "Fix it body", "Fix it\x0bbody"):
            [row] = self.rows([repo([commit(headline=headline)])])
            self.assertEqual(row["message_headline"], "Fix it", repr(headline))

    def test_commits_outside_the_synced_dates_are_left_out(self) -> None:
        rows = self.rows([repo([
            commit(oid="before", authored="2026-05-31T23:59:59Z"),
            commit(oid="inside", authored="2026-06-01T00:00:00Z"),
            commit(oid="after", authored="2026-10-11T00:00:00Z"),
        ])])
        self.assertEqual([row["oid"] for row in rows], ["inside"])

    def test_the_same_commit_twice_is_stored_once(self) -> None:
        rows = self.rows([repo([commit(oid="same"), commit(oid="same")])])
        self.assertEqual(len(rows), 1)

    def test_the_same_oid_in_two_repositories_is_two_rows(self) -> None:
        rows = self.rows([
            repo([commit(oid="same")], node_id="R_1"),
            repo([commit(oid="same")], node_id="R_2", name="alice/other"),
        ])
        self.assertEqual(sorted(row["repo_node_id"] for row in rows), ["R_1", "R_2"])

    def test_an_empty_repository_and_null_nodes_are_skipped_not_a_crash(self) -> None:
        empty = repo([], branch=False)
        odd = repo([None, {"oid": None}, {"oid": "x"}, commit(oid="ok")])
        rows = self.rows([empty, None, odd])
        self.assertEqual([row["oid"] for row in rows], ["ok"])


# ── orchestration, with fakes at the GitHub and Supabase boundaries ───────────

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 10)
SESSION = {"user": {"id": "user-1"}, "access_token": "app-token"}
EXPIRY = "2026-11-01 12:00:00 UTC"


def account_config(slot="A", login="alice", detail="full", label="Personal", order=0, token="ghp_secret"):
    return AccountConfig(slot, token, login, label, detail, order)


def stored_account(**overrides):
    row = {
        "id": "acct-9", "user_id": "user-1", "github_user_id": 101, "github_node_id": "U_1",
        "login": "alice", "label": "Personal", "detail": "full", "display_order": 0,
        "token_expires_at": None, "last_synced_at": None,
    }
    return {**row, **overrides}


class FakeGitHub:
    """Stands in for the GraphQL API and records every document and variable set sent."""

    def __init__(
        self, login="alice", database_id=101, node_id="U_1", counts=None, repos=None,
        repo_pages=None, histories=None, expiry=EXPIRY, rate_limit_after=None,
    ):
        self.rate_limit_after = rate_limit_after
        self.login, self.database_id, self.node_id, self.expiry = login, database_id, node_id, expiry
        self.counts = counts or {}  # "2026-10-10" -> counts_response kwargs
        # Repository pages by `after` cursor; `repos` alone is a single page.
        self.repo_pages = repo_pages or {None: {"nodes": repos or [], "next": None}}
        # Continuation history pages by (repository id, `after` cursor).
        self.histories = histories or {}
        self.queries: list[tuple[str, dict]] = []

    def query(self, document, variables=None):
        self.queries.append((document, dict(variables or {})))
        if document == IDENTITY_QUERY:
            headers = {"github-authentication-token-expiration": self.expiry} if self.expiry else {}
            viewer = {"id": self.node_id, "login": self.login, "databaseId": self.database_id}
            return {"viewer": viewer}, headers
        if document == COUNTS_QUERY:
            if self.rate_limit_after is not None and len(self.sent(COUNTS_QUERY)) > self.rate_limit_after:
                self.queries.pop()
                raise RateLimited("GitHub rate limit reached; rerun after it resets to resume.")
            return counts_response(**self.counts.get(variables["from"][:10], {})), {}
        if document == COMMITS_QUERY:
            page = self.repo_pages[variables["after"]]
            info = {"hasNextPage": page["next"] is not None, "endCursor": page["next"]}
            return {"viewer": {"repositories": {"pageInfo": info, "nodes": page["nodes"]}}}, {}
        if document == COMMIT_HISTORY_QUERY:
            history = self.histories[(variables["repo"], variables["after"])]
            ref = {"target": {"history": history}}
            return {"node": {"defaultBranchRef": ref}}, {}
        raise AssertionError("unexpected query sent to GitHub")

    def sent(self, document):
        return [variables for sent, variables in self.queries if sent == document]


class FakeSupabase:
    """In-memory github_* tables behind the worker's Supabase interface."""

    def __init__(self, accounts=None):
        self.accounts = {a["id"]: dict(a) for a in (accounts or [])}
        self.daily: dict[tuple[str, str, str], dict] = {}
        self.commits: dict[tuple[str, str, str], dict] = {}
        self.calls: list[str] = []

    def find_account(self, login, session):
        self.calls.append("find_account")
        for row in self.accounts.values():
            if row["login"].lower() == login.lower():
                return dict(row)
        return None

    def find_account_by_github_user_id(self, github_user_id, session):
        self.calls.append("find_account_by_github_user_id")
        for row in self.accounts.values():
            if row["github_user_id"] == github_user_id:
                return dict(row)
        return None

    def create_account(self, row, session):
        self.calls.append("create_account")
        created = {**row, "id": f"acct-{len(self.accounts) + 1}", "last_synced_at": None, "token_expires_at": None}
        self.accounts[created["id"]] = created
        return dict(created)

    def update_account(self, account_id, fields, session):
        self.calls.append("update_account")
        self.accounts[account_id].update(fields)

    def stored_days(self, account_id, first, last, session):
        self.calls.append("stored_days")
        return {
            date.fromisoformat(day)
            for (acct, day, _kind) in self.daily
            if acct == account_id and first.isoformat() <= day <= last.isoformat()
        }

    def upsert_daily_rows(self, rows, session):
        self.calls.append("upsert_daily_rows")
        for row in rows:
            self.daily[(row["account_id"], row["local_day"], row["kind"])] = dict(row)

    def upsert_commit_rows(self, rows, session):
        self.calls.append("upsert_commit_rows")
        for row in rows:
            self.commits[(row["account_id"], row["repo_node_id"], row["oid"])] = dict(row)

    def delete_commits(self, account_id, session):
        self.calls.append("delete_commits")
        self.commits = {k: v for k, v in self.commits.items() if k[0] != account_id}

    def daily_for(self, account_id):
        return {k[1:]: v["count"] for k, v in self.daily.items() if k[0] == account_id}


def sync(supabase, github, account=None, days=None):
    account = account or account_config()
    days = days if days is not None else trailing_days(TODAY)
    window = (days[0], days[-1]) if days else (TODAY, TODAY)
    return sync_account(supabase, github, SESSION, account, days, window, NOW)


class SyncAccountIdentityTests(unittest.TestCase):
    def test_the_first_run_registers_the_account_from_configuration_and_the_viewer(self) -> None:
        supabase, github = FakeSupabase(), FakeGitHub()
        sync(supabase, github, account_config(label="Personal", detail="full", order=0))

        [row] = supabase.accounts.values()
        self.assertEqual(
            {k: row[k] for k in ("user_id", "github_user_id", "github_node_id", "login", "label", "detail", "display_order")},
            {"user_id": "user-1", "github_user_id": 101, "github_node_id": "U_1", "login": "alice",
             "label": "Personal", "detail": "full", "display_order": 0},
        )

    def test_a_token_for_a_different_login_is_refused_before_anything_is_read_or_written(self) -> None:
        supabase, github = FakeSupabase(), FakeGitHub(login="someone-else")
        with self.assertRaises(SyncError) as raised:
            sync(supabase, github, account_config(login="alice"))

        self.assertEqual(github.sent(COUNTS_QUERY), [])
        self.assertEqual(supabase.accounts, {})
        self.assertEqual(supabase.daily, {})
        self.assertNotIn("ghp_secret", str(raised.exception))

    def test_login_matching_ignores_case(self) -> None:
        sync(FakeSupabase(), FakeGitHub(login="Alice"), account_config(login="alice"))

    def test_a_stored_row_with_another_github_user_id_is_refused(self) -> None:
        # Same login, different underlying account: the login was released and re-claimed.
        supabase, github = FakeSupabase([stored_account(github_user_id=999)]), FakeGitHub(database_id=101)
        with self.assertRaises(SyncError):
            sync(supabase, github)

        self.assertEqual(supabase.daily, {})
        self.assertEqual(github.sent(COUNTS_QUERY), [])

    def test_an_existing_row_is_reused_and_brought_in_line_with_configuration(self) -> None:
        stored = stored_account(label="Old label", detail="counts_only", display_order=5)
        supabase = FakeSupabase([stored])
        sync(supabase, FakeGitHub(), account_config(label="Personal", detail="full", order=0))

        self.assertEqual(len(supabase.accounts), 1)
        self.assertNotIn("create_account", supabase.calls)
        row = supabase.accounts["acct-9"]
        self.assertEqual((row["label"], row["detail"], row["display_order"]), ("Personal", "full", 0))

    def test_a_renamed_login_adopts_the_row_with_the_same_github_user_id(self) -> None:
        # The owner renamed the account on GitHub and updated GITHUB_LOGIN_A. The token
        # still belongs to the same user (same databaseId), so this is not a new account
        # and must not trip the (user_id, github_user_id) unique key.
        supabase = FakeSupabase([stored_account(login="old-alice", github_user_id=101)])
        sync(supabase, FakeGitHub(login="alice", database_id=101), account_config(login="alice"))

        self.assertEqual(len(supabase.accounts), 1)
        self.assertNotIn("create_account", supabase.calls)
        self.assertEqual(supabase.accounts["acct-9"]["login"], "alice")

    def test_a_login_that_is_new_to_the_database_and_to_the_row_ids_creates_an_account(self) -> None:
        supabase = FakeSupabase([stored_account(login="other", github_user_id=555)])
        sync(supabase, FakeGitHub(login="alice", database_id=101), account_config(login="alice"))

        self.assertEqual(len(supabase.accounts), 2)
        self.assertIn("create_account", supabase.calls)


class SyncAccountCountsTests(unittest.TestCase):
    def test_a_run_writes_the_five_kinds_for_each_of_the_trailing_dates(self) -> None:
        supabase = FakeSupabase()
        github = FakeGitHub(counts={"2026-10-10": {"commit": 4, "pr": 1, "review": 2, "issue": 0, "unsplit": 0}})
        result = sync(supabase, github)

        [acct] = supabase.accounts
        counts = supabase.daily_for(acct)
        self.assertEqual(len(counts), TRAILING_DAYS * 5)
        self.assertEqual(counts[("2026-10-10", "commit")], 4)
        self.assertEqual(counts[("2026-10-10", "pull_request")], 1)
        self.assertEqual(counts[("2026-10-10", "review")], 2)
        self.assertEqual(counts[("2026-09-27", "commit")], 0)
        self.assertEqual(result.days_written, TRAILING_DAYS)

    def test_a_rerun_overwrites_rather_than_duplicates(self) -> None:
        supabase = FakeSupabase()
        sync(supabase, FakeGitHub(counts={"2026-10-10": {"commit": 4}}))
        sync(supabase, FakeGitHub(counts={"2026-10-10": {"commit": 6}}))

        self.assertEqual(len(supabase.accounts), 1)
        self.assertEqual(len(supabase.daily), TRAILING_DAYS * 5)
        [acct] = supabase.accounts
        self.assertEqual(supabase.daily_for(acct)[("2026-10-10", "commit")], 6)

    def test_every_count_window_is_exactly_one_utc_date_and_none_overlap(self) -> None:
        github = FakeGitHub()
        sync(FakeSupabase(), github)

        windows = github.sent(COUNTS_QUERY)
        self.assertEqual(len(windows), TRAILING_DAYS)
        for window in windows:
            self.assertEqual(window["from"][:10], window["to"][:10])
            self.assertTrue(window["from"].endswith("T00:00:00Z"))
            self.assertTrue(window["to"].endswith("T23:59:59Z"))
        starts = [instant(w["from"]) for w in windows]
        ends = [instant(w["to"]) for w in windows]
        for end, next_start in zip(ends, starts[1:]):
            self.assertLess(end, next_start)

    def test_a_successful_run_stamps_last_synced_and_the_token_expiry(self) -> None:
        supabase = FakeSupabase()
        sync(supabase, FakeGitHub())

        [row] = supabase.accounts.values()
        self.assertEqual(row["last_synced_at"], NOW.isoformat())
        self.assertEqual(row["token_expires_at"], "2026-11-01T12:00:00+00:00")

    def test_a_missing_expiry_header_leaves_the_stored_expiry_alone(self) -> None:
        stored = stored_account(token_expires_at="2026-12-01T00:00:00+00:00")
        supabase = FakeSupabase([stored])
        sync(supabase, FakeGitHub(expiry=""))

        self.assertEqual(supabase.accounts["acct-9"]["token_expires_at"], "2026-12-01T00:00:00+00:00")
        self.assertEqual(supabase.accounts["acct-9"]["last_synced_at"], NOW.isoformat())


def page_info(next_cursor=None):
    return {"hasNextPage": next_cursor is not None, "endCursor": next_cursor}


def history_of(commits, next_cursor=None):
    return {"nodes": commits, "pageInfo": page_info(next_cursor)}


class FullAccountCommitTests(unittest.TestCase):
    def test_commits_are_stored_on_their_utc_date_matching_the_daily_counts(self) -> None:
        repos = [repo([
            commit(oid="late", authored="2026-10-09T23:30:00Z", headline="Late one"),
            commit(oid="early", authored="2026-10-10T00:30:00Z", headline="Early one"),
        ], private=True)]
        supabase, github = FakeSupabase(), FakeGitHub(repos=repos)
        result = sync(supabase, github)

        by_oid = {k[2]: v for k, v in supabase.commits.items()}
        self.assertEqual(by_oid["late"]["local_day"], "2026-10-09")
        self.assertEqual(by_oid["early"]["local_day"], "2026-10-10")
        self.assertEqual(by_oid["late"]["message_headline"], "Late one")
        self.assertTrue(by_oid["late"]["repo_is_private"])
        self.assertEqual(by_oid["late"]["user_id"], "user-1")
        self.assertEqual(result.commits_written, 2)

    def test_the_history_query_is_scoped_to_the_viewer_and_the_synced_dates(self) -> None:
        github = FakeGitHub(repos=[repo([commit()])], node_id="U_alice")
        sync(FakeSupabase(), github)

        [variables] = github.sent(COMMITS_QUERY)
        self.assertEqual(variables["id"], "U_alice")
        self.assertEqual(variables["since"], "2026-09-27T00:00:00Z")
        self.assertEqual(variables["until"], "2026-10-10T23:59:59Z")

    def test_a_rerun_does_not_duplicate_commits(self) -> None:
        supabase = FakeSupabase()
        repos = [repo([commit(oid="a"), commit(oid="b")])]
        sync(supabase, FakeGitHub(repos=repos))
        sync(supabase, FakeGitHub(repos=repos))
        self.assertEqual(len(supabase.commits), 2)

    def test_a_sync_only_adds_commits_it_never_deletes_ones_it_no_longer_sees(self) -> None:
        # The spec says "upsert". Deleting on an incomplete read would lose data that a
        # later, shorter window could not bring back, so a force-pushed commit lingers.
        supabase = FakeSupabase([stored_account()])
        supabase.commits[("acct-9", "R_1", "rewritten")] = {
            "local_day": "2026-10-05", "synced_at": "2026-10-09T12:00:00+00:00"}
        sync(supabase, FakeGitHub(repos=[repo([commit(oid="current")])]))

        self.assertEqual(sorted(k[2] for k in supabase.commits), ["current", "rewritten"])

    def test_a_repository_with_more_than_a_page_of_history_is_read_to_the_end(self) -> None:
        first = repo([commit(oid="c1")])
        first["defaultBranchRef"]["target"]["history"] = history_of([commit(oid="c1")], "H1")
        github = FakeGitHub(
            repos=[first],
            histories={
                ("R_1", "H1"): history_of([commit(oid="c2")], "H2"),
                ("R_1", "H2"): history_of([commit(oid="c3")]),
            },
        )
        supabase = FakeSupabase()
        sync(supabase, github)

        self.assertEqual(sorted(k[2] for k in supabase.commits), ["c1", "c2", "c3"])

    def test_repositories_are_paged_until_one_was_last_pushed_before_the_window(self) -> None:
        recent = repo([commit(oid="new")], node_id="R_new")
        stale = repo([], node_id="R_stale")
        stale["pushedAt"] = "2026-08-01T00:00:00Z"
        github = FakeGitHub(repo_pages={
            None: {"nodes": [recent, stale], "next": "P2"},
            "P2": {"nodes": [repo([commit(oid="never")], node_id="R_never")], "next": None},
        })
        supabase = FakeSupabase()
        sync(supabase, github)

        self.assertEqual(len(github.sent(COMMITS_QUERY)), 1)
        self.assertEqual([k[2] for k in supabase.commits], ["new"])

    def test_a_second_page_of_repositories_is_read_when_all_are_recent(self) -> None:
        github = FakeGitHub(repo_pages={
            None: {"nodes": [repo([commit(oid="one")], node_id="R_1")], "next": "P2"},
            "P2": {"nodes": [repo([commit(oid="two")], node_id="R_2")], "next": None},
        })
        supabase = FakeSupabase()
        sync(supabase, github)
        self.assertEqual(sorted(k[2] for k in supabase.commits), ["one", "two"])

    def test_unsplit_on_a_full_account_is_stored_and_reported_not_an_error(self) -> None:
        # A's token cannot see some repositories; that undercount is surfaced, not hidden.
        github = FakeGitHub(counts={"2026-10-10": {"commit": 3, "unsplit": 2}})
        supabase = FakeSupabase()
        result = sync(supabase, github)

        [acct] = supabase.accounts
        self.assertEqual(supabase.daily_for(acct)[("2026-10-10", "unsplit")], 2)
        self.assertEqual(result.unsplit_days, 1)


class CountsOnlyAccountTests(unittest.TestCase):
    B = dict(slot="B", login="bob", detail="counts_only", label="Work", order=1, token="ghp_b")

    def test_commits_stored_before_an_account_became_counts_only_are_removed(self) -> None:
        # The insert policy stops new rows for a counts_only account; it cannot remove old
        # ones, so the worker does (GITHUB_MULTI_ACCOUNT.md, Schema).
        supabase = FakeSupabase([stored_account(login="bob", detail="full")])
        supabase.commits[("acct-9", "R_1", "old")] = {
            "local_day": "2026-03-01", "synced_at": "2026-04-01T12:00:00+00:00"}
        sync(supabase, FakeGitHub(login="bob"), account_config(**self.B))

        self.assertEqual(supabase.commits, {})

    def test_a_counts_only_account_never_asks_for_or_writes_commits(self) -> None:
        # B's token cannot read names, but the worker must not even try: the contract is
        # about what is requested and stored, not about what the token would allow.
        repos = [repo([commit()])]
        supabase, github = FakeSupabase(), FakeGitHub(login="bob", repos=repos)
        sync(supabase, github, account_config(**self.B))

        self.assertEqual(github.sent(COMMITS_QUERY), [])
        self.assertNotIn("upsert_commit_rows", supabase.calls)
        self.assertEqual(supabase.commits, {})
        for document, _ in github.queries:
            self.assertIn(document, queries_for("counts_only"))

    def test_unsplit_contributions_on_a_counts_only_account_mean_the_token_lost_its_scope(self) -> None:
        # Normal for B is unsplit == 0 (read:user splits private work by type). A lump
        # means the token no longer has that scope: refuse, and keep the stored counts.
        stored = stored_account(login="bob", label="Work", detail="counts_only", display_order=1,
                                last_synced_at="2026-10-09T12:00:00+00:00")
        supabase = FakeSupabase([stored])
        supabase.daily[("acct-9", "2026-10-10", "commit")] = {
            "account_id": "acct-9", "local_day": "2026-10-10", "kind": "commit", "count": 5}
        github = FakeGitHub(login="bob", counts={"2026-10-10": {"commit": 0, "unsplit": 5}})

        with self.assertRaises(SyncError) as raised:
            sync(supabase, github, account_config(**self.B))

        self.assertIn("scope", str(raised.exception))
        self.assertEqual(supabase.daily[("acct-9", "2026-10-10", "commit")]["count"], 5)
        self.assertNotIn(("acct-9", "2026-10-10", "unsplit"), supabase.daily)
        self.assertEqual(supabase.accounts["acct-9"]["last_synced_at"], "2026-10-09T12:00:00+00:00")


def quiet(_message: str) -> None:
    pass


def run(supabase, github, accounts=None, backfill=False, log=quiet):
    return run_sync(
        supabase, lambda _account: github, SESSION, accounts or [account_config()], NOW,
        backfill=backfill, log=log,
    )


class BackfillTests(unittest.TestCase):
    def test_backfill_asks_for_every_utc_date_from_the_first_of_january_once(self) -> None:
        github = FakeGitHub()
        run(FakeSupabase(), github, backfill=True)

        asked = [w["from"][:10] for w in github.sent(COUNTS_QUERY)]
        self.assertEqual(asked, [d.isoformat() for d in backfill_days(TODAY)])
        self.assertEqual(asked[0], "2026-01-01")

    def test_backfill_reads_commits_for_the_whole_range_not_just_the_trailing_dates(self) -> None:
        github = FakeGitHub(repos=[repo([commit(oid="january", authored="2026-01-15T09:00:00Z")])])
        supabase = FakeSupabase()
        run(supabase, github, backfill=True)

        [variables] = github.sent(COMMITS_QUERY)
        self.assertEqual(variables["since"], "2026-01-01T00:00:00Z")
        self.assertEqual([k[2] for k in supabase.commits], ["january"])

    def test_a_rate_limit_keeps_what_was_written_and_a_rerun_resumes_after_it(self) -> None:
        supabase = FakeSupabase()
        with self.assertRaises(SyncError):
            run(supabase, FakeGitHub(rate_limit_after=10), backfill=True)

        [acct] = supabase.accounts
        stored = {day for (day, _kind) in supabase.daily_for(acct)}
        self.assertEqual(stored, {d.isoformat() for d in backfill_days(TODAY)[:10]})
        self.assertIsNone(supabase.accounts[acct]["last_synced_at"])

        github = FakeGitHub()
        run(supabase, github, backfill=True)
        resumed = [w["from"][:10] for w in github.sent(COUNTS_QUERY)]
        self.assertEqual(resumed, [d.isoformat() for d in backfill_days(TODAY)[10:]])
        self.assertEqual(len(supabase.daily), len(backfill_days(TODAY)) * 5)

    def test_resuming_still_refetches_the_trailing_dates_even_when_they_are_stored(self) -> None:
        supabase = FakeSupabase()
        run(supabase, FakeGitHub(), backfill=True)

        github = FakeGitHub()
        run(supabase, github, backfill=True)
        refetched = [w["from"][:10] for w in github.sent(COUNTS_QUERY)]
        self.assertEqual(refetched, [d.isoformat() for d in trailing_days(TODAY)])


class RunSyncTests(unittest.TestCase):
    A = dict(slot="A", login="alice", detail="full", label="Personal", order=0, token="ghp_a")
    B = dict(slot="B", login="bob", detail="counts_only", label="Work", order=1, token="ghp_b")

    def clients(self, **by_slot):
        return lambda account: by_slot[account.slot]

    def test_a_failing_account_does_not_stop_the_other_but_the_run_still_fails(self) -> None:
        supabase = FakeSupabase()
        github_a = FakeGitHub(login="not-alice")
        github_b = FakeGitHub(login="bob", database_id=202, node_id="U_2")
        with self.assertRaises(SyncError) as raised:
            run_sync(
                supabase, self.clients(A=github_a, B=github_b), SESSION,
                [account_config(**self.A), account_config(**self.B)], NOW, log=quiet,
            )

        self.assertIn("A", str(raised.exception))
        self.assertEqual([row["login"] for row in supabase.accounts.values()], ["bob"])
        self.assertEqual(len(supabase.daily), TRAILING_DAYS * 5)

    def test_a_successful_run_returns_a_result_per_account(self) -> None:
        results = run_sync(
            FakeSupabase(),
            self.clients(A=FakeGitHub(repos=[repo([commit()])]), B=FakeGitHub(login="bob", database_id=202, node_id="U_2")),
            SESSION, [account_config(**self.A), account_config(**self.B)], NOW, log=quiet,
        )
        self.assertEqual(results["A"].days_written, TRAILING_DAYS)
        self.assertEqual(results["A"].commits_written, 1)
        self.assertEqual(results["B"].commits_written, 0)

    def test_the_log_carries_counts_and_timings_only(self) -> None:
        secret_repo = repo([commit(headline="Rotate the acme-prod-secret keys")], name="alice/acme-secret-repo")
        lines: list[str] = []
        run_sync(
            FakeSupabase(),
            self.clients(A=FakeGitHub(repos=[secret_repo], counts={"2026-10-10": {"commit": 3}})),
            SESSION, [account_config(**self.A)], NOW, log=lines.append,
        )

        text = "\n".join(lines)
        self.assertTrue(lines)
        self.assertRegex(text, r"\b14 day")
        self.assertRegex(text, r"\d+(\.\d+)?s")
        for secret in ("ghp_a", "alice", "Personal", "acme", "Rotate", "U_1", "acct-"):
            self.assertNotIn(secret, text)

    def test_an_unexpected_exception_is_reported_by_type_never_by_message(self) -> None:
        class Leaky:
            def query(self, document, variables=None):
                raise ValueError("request failed for token ghp_a")

        lines: list[str] = []
        with self.assertRaises(SyncError) as raised:
            run_sync(
                FakeSupabase(), self.clients(A=Leaky()), SESSION,
                [account_config(**self.A)], NOW, log=lines.append,
            )

        everything = "\n".join(lines) + str(raised.exception)
        self.assertIn("ValueError", everything)
        self.assertNotIn("ghp_a", everything)


# ── the GitHub HTTP client ────────────────────────────────────────────────────

TOKEN = "ghp_SuperSecretTokenValue"


class FakeResponse:
    def __init__(self, body, headers=None):
        self._raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body=b"", headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError("https://api.github.com/graphql", code, "error", message, io.BytesIO(body))


class RecordingOpener:
    """An `open_url` that replays queued responses (or raises queued exceptions)."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def ok(data, **headers):
    return FakeResponse({"data": data}, headers)


class GitHubClientTests(unittest.TestCase):
    def test_a_query_is_a_post_to_graphql_with_the_token_and_returns_data_and_lowercase_headers(self) -> None:
        opener = RecordingOpener(ok({"viewer": {"login": "alice"}}, **{"GitHub-Authentication-Token-Expiration": EXPIRY}))
        data, headers = GitHubClient(TOKEN, open_url=opener).query("query { viewer { login } }", {"a": 1})

        [request] = opener.requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://api.github.com/graphql")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(json.loads(request.data), {"query": "query { viewer { login } }", "variables": {"a": 1}})
        self.assertEqual(data, {"viewer": {"login": "alice"}})
        self.assertEqual(headers["github-authentication-token-expiration"], EXPIRY)

    def test_the_token_is_scrubbed_from_a_connection_failure(self) -> None:
        opener = RecordingOpener(URLError(f"failed talking to host with {TOKEN}"))
        with self.assertRaises(SyncError) as raised:
            GitHubClient(TOKEN, open_url=opener).query("query { viewer { id } }")
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_an_http_error_reports_the_status_but_never_the_response_body(self) -> None:
        opener = RecordingOpener(http_error(401, f'{{"message": "Bad credentials {TOKEN}"}}'.encode()))
        with self.assertRaises(SyncError) as raised:
            GitHubClient(TOKEN, open_url=opener).query("query { viewer { id } }")
        self.assertIn("401", str(raised.exception))
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertNotIsInstance(raised.exception, RateLimited)

    def test_graphql_errors_are_reported_by_type_not_message(self) -> None:
        body = {"errors": [{"type": "FORBIDDEN", "message": "Resource not accessible: acme/secret-repo"}]}
        opener = RecordingOpener(FakeResponse(body))
        with self.assertRaises(SyncError) as raised:
            GitHubClient(TOKEN, open_url=opener).query("query { viewer { id } }")
        self.assertIn("FORBIDDEN", str(raised.exception))
        self.assertNotIn("secret-repo", str(raised.exception))

    def test_a_response_that_is_not_json_is_an_error(self) -> None:
        opener = RecordingOpener(FakeResponse(b"<html>gateway</html>"))
        with self.assertRaises(SyncError):
            GitHubClient(TOKEN, open_url=opener).query("query { viewer { id } }")

    def test_a_nearly_spent_budget_stops_the_next_request_without_sending_it(self) -> None:
        opener = RecordingOpener(ok({"viewer": {}}, **{"x-ratelimit-remaining": "3", "x-ratelimit-reset": "1791633600"}))
        client = GitHubClient(TOKEN, open_url=opener)
        client.query("query { viewer { id } }")  # the data already fetched is still returned

        with self.assertRaises(RateLimited):
            client.query("query { viewer { id } }")
        self.assertEqual(len(opener.requests), 1)

    def test_a_healthy_budget_keeps_going(self) -> None:
        opener = RecordingOpener(ok({"a": 1}, **{"x-ratelimit-remaining": "4000"}), ok({"a": 2}))
        client = GitHubClient(TOKEN, open_url=opener)
        client.query("query { viewer { id } }")
        self.assertEqual(client.query("query { viewer { id } }")[0], {"a": 2})

    def test_a_secondary_limit_response_is_a_rate_limit_not_a_generic_failure(self) -> None:
        for code, headers in ((403, {"retry-after": "60"}), (429, {}), (403, {"x-ratelimit-remaining": "0"})):
            opener = RecordingOpener(http_error(code, b"{}", headers))
            with self.assertRaises(RateLimited, msg=f"{code} {headers}"):
                GitHubClient(TOKEN, open_url=opener).query("query { viewer { id } }")


class AccountsFromEnvTests(unittest.TestCase):
    def test_a_configured_account_reads_token_login_label_and_detail(self) -> None:
        [account] = accounts_from_env({
            "GITHUB_TOKEN_A": "t", "GITHUB_LOGIN_A": "alice", "GITHUB_LABEL_A": "Personal", "GITHUB_DETAIL_A": "full",
        })
        self.assertEqual(account, AccountConfig("A", "t", "alice", "Personal", "full", 0))

    def test_detail_defaults_to_counts_only_so_a_missing_setting_never_stores_names(self) -> None:
        [account] = accounts_from_env({"GITHUB_TOKEN_B": "t", "GITHUB_LOGIN_B": "bob"})
        self.assertEqual(account.detail, "counts_only")
        self.assertEqual(account.display_order, 1)
        self.assertEqual(account.label, "Account B")

    def test_an_account_prints_without_its_token_login_or_label(self) -> None:
        # A repr ends up in assertion diffs and tracebacks, so it must not carry secrets.
        [account] = accounts_from_env({
            "GITHUB_TOKEN_A": "ghp_SuperSecretTokenValue", "GITHUB_LOGIN_A": "alice-private",
            "GITHUB_LABEL_A": "Quiet Label",
        })
        shown = repr(account) + str(account)
        for secret in ("ghp_SuperSecretTokenValue", "alice-private", "Quiet Label"):
            self.assertNotIn(secret, shown)

    def test_both_accounts_come_back_in_display_order(self) -> None:
        accounts = accounts_from_env({
            "GITHUB_TOKEN_B": "tb", "GITHUB_LOGIN_B": "bob", "GITHUB_TOKEN_A": "ta", "GITHUB_LOGIN_A": "alice",
        })
        self.assertEqual([a.slot for a in accounts], ["A", "B"])

    def test_a_token_without_its_expected_login_is_refused(self) -> None:
        with self.assertRaises(SyncError) as raised:
            accounts_from_env({"GITHUB_TOKEN_A": "t"})
        self.assertIn("GITHUB_LOGIN_A", str(raised.exception))

    def test_an_unknown_detail_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(SyncError):
            accounts_from_env({"GITHUB_TOKEN_A": "t", "GITHUB_LOGIN_A": "alice", "GITHUB_DETAIL_A": "everything"})

    def test_a_login_that_is_not_a_github_login_is_refused(self) -> None:
        for bad in ("al ice", "alice,bob", "a*", "x" * 40):
            with self.assertRaises(SyncError, msg=bad):
                accounts_from_env({"GITHUB_TOKEN_A": "t", "GITHUB_LOGIN_A": bad})

    def test_no_accounts_is_an_error_not_a_silent_success(self) -> None:
        with self.assertRaises(SyncError):
            accounts_from_env({})

    def test_blank_values_count_as_unset(self) -> None:
        with self.assertRaises(SyncError):
            accounts_from_env({"GITHUB_TOKEN_A": "  ", "GITHUB_LOGIN_A": "alice"})


# ── the Supabase REST client ──────────────────────────────────────────────────

APP_SESSION = {"access_token": "app-token", "user": {"id": "user-1"}}


def recording_supabase(*bodies):
    """(SupabaseSession, requests, patcher): each request is answered with the next body."""
    requests = []
    queued = list(bodies) or [b""]

    def open_url(request, timeout):
        requests.append(request)
        body = queued.pop(0) if len(queued) > 1 else queued[0]
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))

    return SupabaseSession("http://db", "pub-key", Path("/tmp/s.json")), requests, patch("github_sync.urlopen", open_url)


def query_of(request):
    return parse_qs(urlsplit(request.full_url).query)


class SupabaseSessionTests(unittest.TestCase):
    def test_requests_carry_the_publishable_key_and_the_app_users_token(self) -> None:
        supabase, requests, opener = recording_supabase([])
        with opener:
            supabase.find_account("alice", APP_SESSION)

        [request] = requests
        self.assertEqual(request.get_header("Apikey"), "pub-key")
        self.assertEqual(request.get_header("Authorization"), "Bearer app-token")

    def test_find_account_filters_by_owner_and_login_and_returns_the_row_or_none(self) -> None:
        supabase, requests, opener = recording_supabase([{"id": "acct-1", "login": "alice"}], [])
        with opener:
            found = supabase.find_account("alice", APP_SESSION)
            missing = supabase.find_account("alice", APP_SESSION)

        self.assertEqual(found, {"id": "acct-1", "login": "alice"})
        self.assertIsNone(missing)
        url = urlsplit(requests[0].full_url)
        self.assertEqual(url.path, "/rest/v1/github_accounts")
        self.assertEqual(query_of(requests[0])["login"], ["ilike.alice"])
        self.assertEqual(query_of(requests[0])["user_id"], ["eq.user-1"])

    def test_create_account_posts_the_row_and_returns_what_was_stored(self) -> None:
        row = {"user_id": "user-1", "login": "alice", "detail": "counts_only"}
        supabase, requests, opener = recording_supabase([{**row, "id": "acct-1"}])
        with opener:
            created = supabase.create_account(row, APP_SESSION)

        [request] = requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), row)
        self.assertIn("return=representation", request.get_header("Prefer"))
        self.assertEqual(created["id"], "acct-1")

    def test_update_account_patches_only_that_row(self) -> None:
        supabase, requests, opener = recording_supabase()
        with opener:
            supabase.update_account("acct-1", {"label": "Work"}, APP_SESSION)

        [request] = requests
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(query_of(request), {"id": ["eq.acct-1"]})
        self.assertEqual(json.loads(request.data), {"label": "Work"})

    def test_stored_days_reads_one_row_per_date_so_a_year_fits_one_page(self) -> None:
        supabase, requests, opener = recording_supabase([{"local_day": "2026-01-01"}, {"local_day": "2026-01-02"}])
        with opener:
            days = supabase.stored_days("acct-1", date(2026, 1, 1), date(2026, 10, 10), APP_SESSION)

        self.assertEqual(days, {date(2026, 1, 1), date(2026, 1, 2)})
        query = query_of(requests[0])
        self.assertEqual(query["account_id"], ["eq.acct-1"])
        self.assertEqual(query["kind"], ["eq.commit"])
        self.assertEqual(query["limit"], ["1000"])
        self.assertIn("gte.2026-01-01", query["local_day"])
        self.assertIn("lte.2026-10-10", query["local_day"])

    def test_daily_rows_are_upserted_on_the_unique_key_in_one_request(self) -> None:
        rows = plan_daily_rows("user-1", "acct-1", date(2026, 10, 10), counts_response(commit=2), "2026-10-10T12:00:00+00:00")
        supabase, requests, opener = recording_supabase()
        with opener:
            supabase.upsert_daily_rows(rows, APP_SESSION)

        [request] = requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(urlsplit(request.full_url).path, "/rest/v1/github_daily_contributions")
        self.assertEqual(query_of(request), {"on_conflict": ["user_id,account_id,local_day,kind"]})
        self.assertIn("merge-duplicates", request.get_header("Prefer"))
        self.assertEqual(json.loads(request.data), rows)

    def test_commit_rows_are_upserted_in_batches_on_the_unique_key(self) -> None:
        rows = [{"oid": str(n), "repo_node_id": "R_1"} for n in range(450)]
        supabase, requests, opener = recording_supabase()
        with opener:
            supabase.upsert_commit_rows(rows, APP_SESSION)

        self.assertEqual([len(json.loads(r.data)) for r in requests], [200, 200, 50])
        self.assertEqual(urlsplit(requests[0].full_url).path, "/rest/v1/github_commits")
        self.assertEqual(
            query_of(requests[0]), {"on_conflict": ["user_id,account_id,repo_node_id,oid"]}
        )

    def test_delete_commits_removes_one_accounts_rows_only(self) -> None:
        supabase, requests, opener = recording_supabase()
        with opener:
            supabase.delete_commits("acct-1", APP_SESSION)

        [request] = requests
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(urlsplit(request.full_url).path, "/rest/v1/github_commits")
        self.assertEqual(query_of(request), {"account_id": ["eq.acct-1"]})

    def test_find_account_by_github_user_id_filters_by_owner_and_the_stable_id(self) -> None:
        supabase, requests, opener = recording_supabase([{"id": "acct-1", "github_user_id": 101}])
        with opener:
            found = supabase.find_account_by_github_user_id(101, APP_SESSION)

        self.assertEqual(found["id"], "acct-1")
        query = query_of(requests[0])
        self.assertEqual(query["github_user_id"], ["eq.101"])
        self.assertEqual(query["user_id"], ["eq.user-1"])

    def test_an_error_body_without_a_message_is_never_echoed(self) -> None:
        # PostgREST puts the offending row in `details`; for this schema that is a repo
        # name or a commit headline, and the text ends up in the run log.
        def open_url(request, timeout):
            body = json.dumps({"code": "23514", "details": "Failing row contains (acme-secret-repo, Rotate keys)"})
            raise HTTPError(request.full_url, 400, "Bad", Message(), io.BytesIO(body.encode("utf-8")))

        supabase = SupabaseSession("http://db", "pub-key", Path("/tmp/s.json"))
        with patch("github_sync.urlopen", open_url):
            with self.assertRaises(SyncError) as raised:
                supabase.upsert_commit_rows([{"oid": "a"}], APP_SESSION)

        self.assertIn("400", str(raised.exception))
        self.assertNotIn("acme-secret-repo", str(raised.exception))
        self.assertNotIn("Rotate", str(raised.exception))

    def test_a_rejected_request_surfaces_supabases_message_and_is_not_retried(self) -> None:
        attempts = []

        def open_url(request, timeout):
            attempts.append(request)
            body = json.dumps({"message": "new row violates row-level security policy"}).encode("utf-8")
            raise HTTPError(request.full_url, 403, "Forbidden", Message(), io.BytesIO(body))

        supabase = SupabaseSession("http://db", "pub-key", Path("/tmp/s.json"))
        with patch("github_sync.urlopen", open_url):
            with self.assertRaisesRegex(SyncError, "row-level security"):
                supabase.upsert_daily_rows([{"kind": "commit"}], APP_SESSION)
        self.assertEqual(len(attempts), 1)

    def test_a_dropped_connection_is_retried_then_succeeds(self) -> None:
        attempts = []

        def open_url(request, timeout):
            attempts.append(request)
            if len(attempts) < 3:
                raise URLError(OSError(101, "Network is unreachable"))
            return FakeResponse(b"")

        supabase = SupabaseSession("http://db", "pub-key", Path("/tmp/s.json"))
        with patch("github_sync.urlopen", open_url), patch("github_sync.sleep") as sleeper:
            supabase.update_account("acct-1", {"label": "x"}, APP_SESSION)

        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_it_gives_up_after_a_few_attempts_with_a_clear_message(self) -> None:
        def open_url(request, timeout):
            raise URLError(OSError(101, "Network is unreachable"))

        supabase = SupabaseSession("http://db", "pub-key", Path("/tmp/s.json"))
        with patch("github_sync.urlopen", open_url), patch("github_sync.sleep"):
            with self.assertRaisesRegex(SyncError, "Could not reach Supabase"):
                supabase.update_account("acct-1", {"label": "x"}, APP_SESSION)


class SessionStorageTests(unittest.TestCase):
    def test_a_login_stores_the_session_and_a_valid_cached_one_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "session.json"
            supabase = SupabaseSession("http://db", "pub-key", path)
            session = {"access_token": "a", "refresh_token": "r", "expires_at": 9999999999, "user": {"id": "u"}}
            opener = lambda request, timeout: FakeResponse(json.dumps(session).encode("utf-8"))  # noqa: E731
            with patch("github_sync.urlopen", opener):
                supabase.login("me@example.com", "pw")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["refresh_token"], "r")
            self.assertEqual(supabase.active()["access_token"], "a")

    def test_an_expired_session_is_refreshed_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text(json.dumps({"access_token": "old", "refresh_token": "r", "expires_at": 1}), encoding="utf-8")
            refreshed = {"access_token": "new", "refresh_token": "r2", "expires_at": 9999999999}
            opener = lambda request, timeout: FakeResponse(json.dumps(refreshed).encode("utf-8"))  # noqa: E731
            with patch("github_sync.urlopen", opener):
                session = SupabaseSession("http://db", "pub-key", path).active()
            self.assertEqual(session["access_token"], "new")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["access_token"], "new")

    def test_a_missing_session_asks_for_setup(self) -> None:
        supabase = SupabaseSession("http://db", "pub-key", Path("/nonexistent/session.json"))
        with self.assertRaisesRegex(SyncError, "setup"):
            supabase.active()


class CommandLineTests(unittest.TestCase):
    def test_sync_runs_the_trailing_dates_and_backfill_runs_since_january(self) -> None:
        for command, expect_backfill in (("sync", False), ("backfill", True)):
            with patch("github_sync.run_from_environment") as run_it:
                self.assertEqual(main([command]), 0)
            run_it.assert_called_once_with(backfill=expect_backfill)

    def test_a_failed_run_exits_non_zero_and_prints_the_actionable_message(self) -> None:
        stderr = io.StringIO()
        error = SyncError("GitHub sync failed for account(s): B.")
        with patch("github_sync.run_from_environment", side_effect=error), patch("sys.stderr", stderr):
            self.assertEqual(main(["sync"]), 1)
        self.assertIn("account(s): B", stderr.getvalue())

    def test_an_unexpected_exception_prints_its_type_and_never_its_message(self) -> None:
        stderr = io.StringIO()
        leaky = ValueError("Bearer ghp_SuperSecretTokenValue rejected")
        with patch("github_sync.run_from_environment", side_effect=leaky), patch("sys.stderr", stderr):
            self.assertEqual(main(["sync"]), 1)
        self.assertIn("ValueError", stderr.getvalue())
        self.assertNotIn("ghp_", stderr.getvalue())


class DeploymentConfigurationTests(unittest.TestCase):
    def test_localhost_is_rewritten_only_inside_docker(self) -> None:
        self.assertEqual(docker_host_url("http://127.0.0.1:54321/", True), "http://host.docker.internal:54321")
        self.assertEqual(docker_host_url("http://127.0.0.1:54321/", False), "http://127.0.0.1:54321")
        self.assertEqual(docker_host_url("https://abc.supabase.co", True), "https://abc.supabase.co")

    def test_configuration_requires_the_supabase_url_and_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(SyncError, "SUPABASE_URL"):
                configuration()

    def test_railway_needs_the_session_on_the_volume(self) -> None:
        on_railway = {"RAILWAY_ENVIRONMENT_NAME": "production"}
        with patch.dict("os.environ", on_railway, clear=True):
            with self.assertRaisesRegex(SyncError, "persistent volume"):
                validate_railway_volume(Path("/data/session.json"))
        with patch.dict("os.environ", {**on_railway, "RAILWAY_VOLUME_MOUNT_PATH": "/data"}, clear=True):
            validate_railway_volume(Path("/data/session.json"))
            with self.assertRaisesRegex(SyncError, "SUPABASE_SESSION_FILE"):
                validate_railway_volume(Path("/tmp/session.json"))
        with patch.dict("os.environ", {}, clear=True):
            validate_railway_volume(Path("/tmp/session.json"))

    def test_runtime_credentials_log_in_afresh_and_must_come_as_a_pair(self) -> None:
        class FakeLogin:
            def __init__(self):
                self.calls = []

            def login(self, email, password):
                self.calls.append((email, password))
                return {"user": {"id": "u"}}

            def active(self):
                return {"user": {"id": "cached"}}

        paired = {"PERSONAL_OBSERVABILITY_APP_EMAIL": "me@example.com", "PERSONAL_OBSERVABILITY_APP_PASSWORD": "pw"}
        with patch.dict("os.environ", paired, clear=True):
            fake = FakeLogin()
            self.assertEqual(session_for_sync(fake)["user"]["id"], "u")
            self.assertEqual(fake.calls, [("me@example.com", "pw")])
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(session_for_sync(FakeLogin())["user"]["id"], "cached")
        with patch.dict("os.environ", {"PERSONAL_OBSERVABILITY_APP_EMAIL": "me@example.com"}, clear=True):
            with self.assertRaisesRegex(SyncError, "configured together"):
                session_for_sync(FakeLogin())


if __name__ == "__main__":
    unittest.main()
