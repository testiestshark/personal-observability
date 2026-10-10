import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from github_probe import (
    EXPIRY_HEADER,
    AccountSpec,
    ProbeError,
    SCOPES_HEADER,
    classify_commit_window,
    classify_halves,
    exposure_audit,
    inclusive_to,
    iso_z,
    load_env_file,
    london_day_of,
    london_day_window,
    named,
    parse_scopes,
    probe_account,
    scope_lines,
    scrub,
    specs_from,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class LondonDayWindowTests(unittest.TestCase):
    def test_ordinary_summer_day_is_24_hours_and_starts_an_hour_early_in_utc(self):
        start, end = london_day_window(date(2026, 7, 1))
        self.assertEqual(iso_z(start), "2026-06-30T23:00:00Z")
        self.assertEqual(end - start, timedelta(hours=24))

    def test_ordinary_winter_day_matches_utc(self):
        start, end = london_day_window(date(2026, 1, 15))
        self.assertEqual(iso_z(start), "2026-01-15T00:00:00Z")
        self.assertEqual(end - start, timedelta(hours=24))

    def test_spring_forward_day_is_23_hours(self):
        start, end = london_day_window(date(2026, 3, 29))
        self.assertEqual(end - start, timedelta(hours=23))

    def test_autumn_back_day_is_25_hours(self):
        start, end = london_day_window(date(2026, 10, 25))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_commit_after_midnight_bst_belongs_to_the_london_day_not_utc(self):
        # 00:30 BST on 24 Sep is 23:30 UTC on 23 Sep.
        instant = datetime(2026, 9, 23, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(london_day_of(instant), date(2026, 9, 24))

    def test_commit_before_midnight_gmt_stays_on_the_same_day(self):
        instant = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(london_day_of(instant), date(2026, 1, 15))

    def test_inclusive_to_steps_back_one_second_so_windows_do_not_overlap(self):
        start, end = london_day_window(date(2026, 1, 15))
        self.assertEqual(iso_z(inclusive_to(end)), "2026-01-15T23:59:59Z")


class ClassifierTests(unittest.TestCase):
    def test_halves_that_partition_the_day_mean_windows_are_honoured(self):
        self.assertEqual(classify_halves(day=5, first=3, second=2), "honoured")

    def test_each_half_returning_the_whole_day_means_day_granular(self):
        self.assertEqual(classify_halves(day=4, first=4, second=4), "day_granular")

    def test_all_commits_in_one_half_is_inconclusive_not_a_pass(self):
        self.assertEqual(classify_halves(day=3, first=3, second=0), "inconclusive")

    def test_empty_day_is_inconclusive(self):
        self.assertEqual(classify_halves(day=0, first=0, second=0), "inconclusive")

    def test_halves_that_do_not_add_up_are_flagged(self):
        self.assertEqual(classify_halves(day=5, first=4, second=4), "unexpected")

    def test_commit_window_hit_and_miss_is_honoured(self):
        self.assertEqual(classify_commit_window(inside=1, outside=0, day=5), "honoured")

    def test_commit_window_missing_a_known_commit_means_day_granular(self):
        self.assertEqual(classify_commit_window(inside=0, outside=0, day=5), "day_granular")

    def test_neighbouring_commit_in_the_after_window_is_inconclusive(self):
        self.assertEqual(classify_commit_window(inside=1, outside=1, day=5), "inconclusive")


class EnvAndScrubTests(unittest.TestCase):
    def test_load_env_file_skips_comments_and_strips_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env.local"
            path.write_text('# note\nGITHUB_LOGIN_A="alice"\n\nGITHUB_TOKEN_A=abc=def\n', encoding="utf-8")
            values = load_env_file(path)
        self.assertEqual(values, {"GITHUB_LOGIN_A": "alice", "GITHUB_TOKEN_A": "abc=def"})

    def test_missing_env_file_is_empty(self):
        self.assertEqual(load_env_file(Path("does-not-exist.env")), {})

    def test_an_account_needs_both_token_and_login(self):
        specs = specs_from(
            {"GITHUB_TOKEN_A": "t", "GITHUB_LOGIN_A": "alice", "GITHUB_TOKEN_B": "t2"}
        )
        self.assertEqual([s.label for s in specs], ["A"])
        self.assertEqual(specs[0].detail, "full")

    def test_scrub_removes_the_token_from_text(self):
        self.assertEqual(scrub("bad credentials for sekret", ["sekret"]), "bad credentials for [token]")


class ScopeTests(unittest.TestCase):
    def test_no_header_means_a_fine_grained_token(self):
        self.assertIsNone(parse_scopes({}))
        self.assertIn("fine-grained", scope_lines(None)[0])

    def test_scopes_are_split_trimmed_and_sorted(self):
        self.assertEqual(parse_scopes({SCOPES_HEADER: "repo, read:user"}), ["read:user", "repo"])

    def test_empty_header_is_a_classic_token_with_no_scopes(self):
        self.assertEqual(parse_scopes({SCOPES_HEADER: ""}), [])

    def test_exactly_read_user_passes(self):
        lines = scope_lines(["read:user"])
        self.assertIn("exactly what B needs", lines[-1])

    def test_repo_scope_is_flagged_as_code_access(self):
        lines = scope_lines(["read:user", "repo"])
        self.assertTrue(any("EXTRA scope(s)" in line and "repo" in line for line in lines))
        self.assertTrue(any("change or read code" in line for line in lines))

    def test_probe_reports_scopes_next_to_identity(self):
        client = FakeClient(scopes="read:user")
        lines, ok = probe_account(client, AccountSpec("B", "tok", "alice", "counts_only"), NOW)
        self.assertTrue(ok)
        self.assertIn("token type: classic; scopes: read:user", lines)


class FakeClient:
    """Stands in for GitHub. Records every query so tests can assert on what was asked."""

    def __init__(self, login="alice", commits_by_window=None, expiry="2026-11-01 12:00:00 UTC", scopes=None):
        self.login = login
        self.expiry = expiry
        self.scopes = scopes
        self.queries: list[str] = []
        self.commits_by_window = commits_by_window or (lambda start, end: 0)

    def query(self, query, variables=None):
        self.queries.append(query)
        if "viewer { id login" in query:
            headers = {EXPIRY_HEADER: self.expiry} if self.expiry else {}
            if self.scopes is not None:
                headers[SCOPES_HEADER] = self.scopes
            return {"viewer": {"id": "U_1", "login": self.login, "databaseId": 1}}, headers
        if "contributionsCollection" in query:
            start = datetime.fromisoformat(variables["from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(variables["to"].replace("Z", "+00:00"))
            commits = self.commits_by_window(start, end)
            return {
                "viewer": {
                    "contributionsCollection": {
                        "totalCommitContributions": commits,
                        "totalPullRequestContributions": 0,
                        "totalPullRequestReviewContributions": 0,
                        "totalIssueContributions": 0,
                        "restrictedContributionsCount": 0,
                    }
                }
            }, {}
        if "repositories" in query:
            newest = NOW - timedelta(days=2)
            return {
                "viewer": {
                    "repositories": {
                        "nodes": [
                            {
                                "defaultBranchRef": {
                                    "target": {
                                        "history": {"nodes": [{"authoredDate": iso_z(newest)}]}
                                    }
                                }
                            }
                        ]
                    }
                }
            }, {}
        raise AssertionError(f"unexpected query: {query}")


def one_commit_per_day_at(commit_time):
    """A GitHub that honours sub-day windows: counts the commit only if its window holds it."""

    def count(start, end):
        return 1 if start <= commit_time <= end else 0

    return count


class ProbeAccountTests(unittest.TestCase):
    def spec(self, label="B", detail="counts_only", login="alice"):
        return AccountSpec(label, "tok", login, detail)

    def test_wrong_login_stops_before_reading_anything(self):
        client = FakeClient(login="someone-else")
        lines, ok = probe_account(client, self.spec(), NOW)
        self.assertFalse(ok)
        self.assertEqual(len(client.queries), 1)
        self.assertIn("stopping", lines[-1])

    def test_counts_only_account_is_never_asked_about_repositories(self):
        # The privacy contract for B: no repository field appears in any query it makes.
        client = FakeClient(commits_by_window=lambda s, e: 1)
        probe_account(client, self.spec(detail="counts_only"), NOW)
        self.assertTrue(client.queries)
        for query in client.queries:
            self.assertNotIn("repositories", query)
            self.assertNotIn("nameWithOwner", query)
            self.assertNotIn("message", query)

    def test_full_account_reads_commit_times_but_never_names_or_messages(self):
        commit_time = NOW - timedelta(days=2)
        client = FakeClient(commits_by_window=one_commit_per_day_at(commit_time))
        lines, ok = probe_account(client, self.spec("A", "full"), NOW)
        self.assertTrue(ok)
        history_queries = [q for q in client.queries if "repositories" in q]
        self.assertEqual(len(history_queries), 1)
        for forbidden in ("nameWithOwner", "name ", "url", "message", "headline"):
            self.assertNotIn(forbidden, history_queries[0])
        self.assertTrue(any("commit-level windows" in line and "honoured" in line for line in lines))

    def test_missing_expiry_header_is_reported_not_hidden(self):
        client = FakeClient(expiry="", commits_by_window=lambda s, e: 0)
        lines, _ = probe_account(client, self.spec(), NOW)
        self.assertIn("token expiry header: ABSENT", lines)

    def test_http_failure_is_reported_as_a_failed_account_without_the_token(self):
        class Boom:
            def query(self, query, variables=None):
                raise ProbeError("GitHub answered HTTP 401")

        lines, ok = probe_account(Boom(), self.spec(), NOW)
        self.assertFalse(ok)
        self.assertEqual(lines[-1], "FAILED: GitHub answered HTTP 401")


SECRET_NAMES = ["acme-secret-repo", "Secret PR title", "Secret issue title", "secret-org"]


class AuditClient:
    """A GitHub whose answers carry real-looking names, so tests can prove none leak out."""

    def __init__(self, names_visible=True, failing=()):
        self.names_visible = names_visible
        self.failing = set(failing)

    def _name(self, value):
        return value if self.names_visible else None

    def query(self, query, variables=None):
        for marker in self.failing:
            if marker in query:
                raise ProbeError("GraphQL error type(s): FORBIDDEN")
        if "commitContributionsByRepository" in query:
            repo = {"isPrivate": True, "nameWithOwner": self._name("alice/acme-secret-repo")}
            body = {"commitContributionsByRepository": [{"repository": repo, "contributions": {"totalCount": 9}}]}
            return {"viewer": {"contributionsCollection": body}}, {}
        if "pullRequestContributions" in query:
            node = {"pullRequest": {"title": self._name("Secret PR title"), "repository": {"isPrivate": True}}}
            return {"viewer": {"contributionsCollection": {"pullRequestContributions": {"nodes": [node]}}}}, {}
        if "issueContributions" in query:
            node = {"issue": {"title": self._name("Secret issue title"), "repository": {"isPrivate": False}}}
            return {"viewer": {"contributionsCollection": {"issueContributions": {"nodes": [node]}}}}, {}
        if "privacy: PRIVATE" in query:
            nodes = [{"nameWithOwner": self._name("alice/acme-secret-repo")}]
            return {"viewer": {"repositories": {"totalCount": 3, "nodes": nodes}}}, {}
        if "organizations" in query:
            nodes = [{"login": self._name("secret-org")}]
            return {"viewer": {"organizations": {"totalCount": 1, "nodes": nodes}}}, {}
        raise AssertionError(f"unexpected query: {query}")

    def rest_get(self, path):
        if path == "/user":
            return 200, {"login": "alice", "total_private_repos": 3}
        if path.startswith("/user/repos"):
            return 200, [{"full_name": self._name("alice/acme-secret-repo")}] if self.names_visible else []
        if path == "/user/emails":
            return 404, None
        raise AssertionError(f"unexpected path: {path}")


class ExposureAuditTests(unittest.TestCase):
    def test_names_are_counted_but_never_printed(self):
        lines, places = exposure_audit(AuditClient(names_visible=True), NOW)
        report = "\n".join(lines)
        for secret in SECRET_NAMES + ["acme", "alice/"]:
            self.assertNotIn(secret, report)
        self.assertGreater(places, 0)
        self.assertIn("RESULT: names ARE readable", report)
        self.assertIn("repo name readable on 1", report)

    def test_unreadable_names_give_a_clean_result(self):
        lines, places = exposure_audit(AuditClient(names_visible=False), NOW)
        self.assertEqual(places, 0)
        self.assertTrue(lines[-1].startswith("RESULT: no repository, organisation, PR or issue name"))

    def test_private_work_is_counted_without_naming_it(self):
        lines, _ = exposure_audit(AuditClient(names_visible=False), NOW)
        report = "\n".join(lines)
        self.assertIn("1 repos listed, 1 private, repo name readable on 0", report)
        self.assertIn("1 in private repos, title readable on 0", report)

    def test_one_failing_check_does_not_hide_the_others(self):
        lines, _ = exposure_audit(AuditClient(failing=["organizations"]), NOW)
        report = "\n".join(lines)
        self.assertIn("organisations: not available (GraphQL error type(s): FORBIDDEN)", report)
        self.assertIn("commit breakdown by repository:", report)
        self.assertIn("REST /user/emails: HTTP 404", report)

    def test_rest_profile_reports_presence_of_private_fields_not_their_values(self):
        lines, _ = exposure_audit(AuditClient(), NOW)
        report = "\n".join(lines)
        self.assertIn("private profile fields present: yes", report)

    def test_named_only_accepts_real_strings(self):
        self.assertTrue(named("x"))
        self.assertFalse(named(None))
        self.assertFalse(named("   "))
        self.assertFalse(named(5))


if __name__ == "__main__":
    unittest.main()
