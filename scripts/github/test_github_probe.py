import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from github_probe import (
    EXPIRY_HEADER,
    AccountSpec,
    ProbeError,
    RawResponse,
    SCOPES_HEADER,
    classify_commit_window,
    classify_halves,
    direct_fetch_audit,
    exposure_audit,
    graphql_verdict,
    inclusive_to,
    iso_z,
    load_env_file,
    london_day_of,
    london_day_window,
    named,
    parse_scopes,
    parse_target,
    probe_account,
    rest_verdict,
    scope_lines,
    scrub,
    specs_from,
    utc_day_window,
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


class UtcDayWindowTests(unittest.TestCase):
    def test_utc_day_is_always_24_hours_even_when_london_changes_clocks(self):
        for day in (date(2026, 3, 29), date(2026, 10, 25), date(2026, 7, 1)):
            start, end = utc_day_window(day)
            self.assertEqual(end - start, timedelta(hours=24))
            self.assertEqual(iso_z(start), f"{day.isoformat()}T00:00:00Z")

    def test_a_london_summer_day_straddles_two_utc_dates(self):
        # The 2026-10-10 probe finding: this one London day touches two UTC dates, so a
        # London-day query returned both dates' counts together.
        start, end = london_day_window(date(2026, 7, 1))
        self.assertEqual(start.date(), date(2026, 6, 30))
        self.assertEqual((end - timedelta(seconds=1)).date(), date(2026, 7, 1))


class ProbeDayBucketTests(unittest.TestCase):
    def test_whole_date_buckets_are_reported_as_day_granular_with_matching_straddle(self):
        def by_utc_date(start, end):
            # GitHub's behaviour: any window returns every UTC date it touches, whole.
            per_date = {}
            day = start.date()
            total = 0
            while day <= end.date():
                total += 5
                day += timedelta(days=1)
            return total

        client = FakeClient(commits_by_window=by_utc_date)
        lines, ok = probe_account(client, AccountSpec("B", "tok", "alice", "counts_only"), NOW)
        self.assertTrue(ok)
        report = "\n".join(lines)
        self.assertIn("first-half=5 second-half=5 -> day_granular", report)
        self.assertIn("matches (UTC date buckets)", report)


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

    def test_null_entries_are_counted_as_hidden_not_a_crash(self):
        # Regression: a real run died with AttributeError on a null node (items the
        # token may not see come back as null), which also lost the whole audit.
        class NullNodes(AuditClient):
            def query(self, query, variables=None):
                if "pullRequestContributions" in query:
                    node = {"pullRequest": {"title": "Secret PR title", "repository": {"isPrivate": True}}}
                    nodes = [None, node, None]
                    return {"viewer": {"contributionsCollection": {"pullRequestContributions": {"nodes": nodes}}}}, {}
                return super().query(query, variables)

        lines, _ = exposure_audit(NullNodes(), NOW)
        report = "\n".join(lines)
        self.assertIn("pull request contributions: 3 listed, 1 in private repos, title readable on 1, 2 hidden", report)
        self.assertNotIn("Secret PR title", report)

    def test_an_unexpected_exception_in_one_check_is_contained(self):
        class Broken(AuditClient):
            def rest_get(self, path):
                if path == "/user":
                    raise ValueError("boom")
                return super().rest_get(path)

        lines, _ = exposure_audit(Broken(), NOW)
        report = "\n".join(lines)
        self.assertIn("REST /user: not available (unexpected response shape: ValueError)", report)
        self.assertIn("REST /user/emails: HTTP 404", report)

    def test_named_only_accepts_real_strings(self):
        self.assertTrue(named("x"))
        self.assertFalse(named(None))
        self.assertFalse(named("   "))
        self.assertFalse(named(5))


PRIVATE_IDS = {
    "GITHUB_PROBE_PR": "alice/acme-secret-repo#12",
    "GITHUB_PROBE_ISSUE": "alice/acme-secret-repo#7",
    "GITHUB_PROBE_COMMIT": "alice/acme-secret-repo@" + "ab" * 20,
    "GITHUB_PROBE_FILE": "alice/acme-secret-repo:src/payroll/secret-plan.md@main",
}
PRIVATE_FRAGMENTS = ["acme", "alice", "secret", "payroll", "abab"]


def rest_reply(status, headers=None):
    return RawResponse(status, headers or {}, {"title": "Secret PR title"} if status == 200 else None)


def graphql_reply(node=None, error_types=(), status=200):
    errors = [{"type": t, "message": "Could not resolve to a Repository named acme-secret-repo"} for t in error_types]
    payload = {"data": {"repository": node}, "errors": errors} if errors else {"data": {"repository": node}}
    return RawResponse(status, {}, payload)


class DirectFetchClient:
    """Answers each route with a fixed reply. `readable` ids come back 200 / non-null."""

    def __init__(self, rest=None, graphql=None):
        self.rest = rest if rest is not None else rest_reply(404)
        self.graphql = graphql if graphql is not None else graphql_reply(None, ["NOT_FOUND"])
        self.requests = []

    def fetch_rest(self, path):
        self.requests.append(("rest", path))
        return self.rest

    def fetch_graphql(self, query, variables):
        self.requests.append(("graphql", query, variables))
        return self.graphql


READABLE = DirectFetchClient(
    rest=rest_reply(200),
    graphql=RawResponse(200, {}, {"data": {"repository": {"pullRequest": {"id": "PR_x"}, "object": {"oid": "ab"}, "issue": {"id": "I_x"}}}}),
)


class ParseTargetTests(unittest.TestCase):
    def test_each_kind_parses_to_its_rest_path(self):
        pr = parse_target("pull request", PRIVATE_IDS["GITHUB_PROBE_PR"])
        self.assertEqual(pr.rest_path(), "/repos/alice/acme-secret-repo/pulls/12")
        issue = parse_target("issue", PRIVATE_IDS["GITHUB_PROBE_ISSUE"])
        self.assertEqual(issue.rest_path(), "/repos/alice/acme-secret-repo/issues/7")
        commit = parse_target("commit", PRIVATE_IDS["GITHUB_PROBE_COMMIT"])
        self.assertEqual(commit.rest_path(), "/repos/alice/acme-secret-repo/commits/" + "ab" * 20)
        file = parse_target("file", PRIVATE_IDS["GITHUB_PROBE_FILE"])
        self.assertEqual(file.rest_path(), "/repos/alice/acme-secret-repo/contents/src/payroll/secret-plan.md?ref=main")

    def test_a_file_without_a_ref_uses_the_default_branch(self):
        file = parse_target("file", "alice/acme-secret-repo:README.md")
        self.assertEqual(file.rest_path(), "/repos/alice/acme-secret-repo/contents/README.md")
        _, variables, _ = file.graphql()
        self.assertEqual(variables["expression"], "HEAD:README.md")

    def test_a_malformed_id_is_rejected_without_echoing_it(self):
        for kind, text in [
            ("pull request", "alice/acme-secret-repo/12"),
            ("pull request", "alice/acme-secret-repo#0"),
            ("commit", "alice/acme-secret-repo@abc123"),  # abbreviated: GraphQL needs the full id
            ("file", "alice/acme-secret-repo:../../etc/passwd"),
            ("issue", "alice/../admin#3"),
        ]:
            with self.assertRaises(ProbeError) as raised:
                parse_target(kind, text)
            self.assertNotIn("acme", str(raised.exception))
            self.assertNotIn("alice", str(raised.exception))


class RestVerdictTests(unittest.TestCase):
    def test_200_is_exposed(self):
        self.assertEqual(rest_verdict(rest_reply(200)), "exposed")

    def test_404_and_a_plain_403_are_refused(self):
        self.assertEqual(rest_verdict(rest_reply(404)), "refused")
        self.assertEqual(rest_verdict(rest_reply(403)), "refused")

    def test_a_rate_limited_403_is_not_a_refusal(self):
        # GitHub answers a rate limit with 403 too; that must never read as a pass.
        self.assertEqual(rest_verdict(rest_reply(403, {"x-ratelimit-remaining": "0"})), "inconclusive")
        self.assertEqual(rest_verdict(rest_reply(403, {"retry-after": "60"})), "inconclusive")

    def test_auth_failures_server_errors_and_unreachable_are_inconclusive(self):
        for status in (401, 429, 500, 502, 0):
            self.assertEqual(rest_verdict(rest_reply(status)), "inconclusive", status)


class GraphqlVerdictTests(unittest.TestCase):
    PATH = ("repository", "pullRequest")

    def test_a_returned_node_is_exposed(self):
        reply = graphql_reply({"pullRequest": {"id": "PR_x"}})
        self.assertEqual(graphql_verdict(reply, self.PATH), "exposed")

    def test_not_found_forbidden_and_insufficient_scopes_are_refused(self):
        for kind in ("NOT_FOUND", "FORBIDDEN", "INSUFFICIENT_SCOPES"):
            self.assertEqual(graphql_verdict(graphql_reply(None, [kind]), self.PATH), "refused", kind)

    def test_a_null_node_with_no_error_is_refused(self):
        self.assertEqual(graphql_verdict(graphql_reply({"pullRequest": None}), self.PATH), "refused")

    def test_any_other_error_type_is_inconclusive(self):
        for kind in ("RATE_LIMITED", "MAX_NODE_LIMIT_EXCEEDED", "SERVICE_UNAVAILABLE", ""):
            self.assertEqual(graphql_verdict(graphql_reply(None, [kind]), self.PATH), "inconclusive", kind)

    def test_a_bad_status_or_empty_payload_is_inconclusive(self):
        self.assertEqual(graphql_verdict(RawResponse(401, {}, None), self.PATH), "inconclusive")
        self.assertEqual(graphql_verdict(RawResponse(200, {}, {}), self.PATH), "inconclusive")
        self.assertEqual(graphql_verdict(RawResponse(0, {}, None), self.PATH), "inconclusive")


class DirectFetchAuditTests(unittest.TestCase):
    def test_everything_refused_is_a_pass_that_admits_it_could_not_confirm_the_ids(self):
        lines, exposed, inconclusive = direct_fetch_audit(DirectFetchClient(), PRIVATE_IDS)
        report = "\n".join(lines)
        self.assertEqual((exposed, inconclusive), (0, 0))
        self.assertIn("pull request: REFUSED", report)
        self.assertIn("file: REFUSED", report)
        self.assertIn("RESULT: every item was refused", report)
        self.assertIn("no control token", report)

    def test_a_readable_item_is_exposed(self):
        lines, exposed, _ = direct_fetch_audit(READABLE, PRIVATE_IDS)
        self.assertEqual(exposed, 4)
        self.assertTrue(lines[-1].startswith("RESULT: EXPOSED"))

    def test_one_route_answering_is_enough_to_be_exposed(self):
        leaky = DirectFetchClient(rest=rest_reply(404), graphql=READABLE.graphql)
        _, exposed, _ = direct_fetch_audit(leaky, PRIVATE_IDS)
        self.assertEqual(exposed, 4)

    def test_nothing_in_the_report_names_a_private_item(self):
        for client in (DirectFetchClient(), READABLE, DirectFetchClient(rest=rest_reply(500))):
            lines, _, _ = direct_fetch_audit(client, PRIVATE_IDS)
            report = "\n".join(lines).lower()
            for fragment in PRIVATE_FRAGMENTS:
                self.assertNotIn(fragment, report)

    def test_a_missing_id_is_inconclusive_never_a_pass(self):
        values = {k: v for k, v in PRIVATE_IDS.items() if k != "GITHUB_PROBE_FILE"}
        lines, exposed, inconclusive = direct_fetch_audit(DirectFetchClient(), values)
        report = "\n".join(lines)
        self.assertEqual((exposed, inconclusive), (0, 1))
        self.assertIn("file: not configured (set GITHUB_PROBE_FILE)", report)
        self.assertTrue(lines[-1].startswith("RESULT: inconclusive"))

    def test_a_malformed_id_is_inconclusive_and_not_echoed(self):
        values = {**PRIVATE_IDS, "GITHUB_PROBE_COMMIT": "alice/acme-secret-repo@short"}
        lines, _, inconclusive = direct_fetch_audit(DirectFetchClient(), values)
        report = "\n".join(lines)
        self.assertEqual(inconclusive, 1)
        self.assertIn("commit: not usable", report)
        self.assertNotIn("acme", report)

    def test_a_failing_token_is_inconclusive_not_clean(self):
        dead = DirectFetchClient(rest=rest_reply(401), graphql=RawResponse(401, {}, None))
        _, exposed, inconclusive = direct_fetch_audit(dead, PRIVATE_IDS)
        self.assertEqual((exposed, inconclusive), (0, 4))

    def test_a_control_token_that_can_read_the_items_confirms_the_refusals(self):
        lines, exposed, inconclusive = direct_fetch_audit(DirectFetchClient(), PRIVATE_IDS, control=READABLE)
        report = "\n".join(lines)
        self.assertEqual((exposed, inconclusive), (0, 0))
        self.assertIn("control token can read it", report)
        self.assertIn("control token confirmed each one exists", lines[-1])

    def test_a_control_token_that_cannot_read_an_item_means_the_id_may_be_wrong(self):
        # A mistyped id is also a 404, so without this a typo would look like a pass.
        lines, exposed, inconclusive = direct_fetch_audit(DirectFetchClient(), PRIVATE_IDS, control=DirectFetchClient())
        self.assertEqual((exposed, inconclusive), (0, 4))
        self.assertIn("control token could not read it", "\n".join(lines))

    def test_exposure_still_wins_when_the_control_cannot_read_the_item(self):
        _, exposed, _ = direct_fetch_audit(READABLE, PRIVATE_IDS, control=DirectFetchClient())
        self.assertEqual(exposed, 4)

    def test_one_item_failing_unexpectedly_does_not_hide_the_others(self):
        class Flaky(DirectFetchClient):
            def fetch_rest(self, path):
                if "/pulls/" in path:
                    raise ValueError("boom")
                return super().fetch_rest(path)

        lines, _, inconclusive = direct_fetch_audit(Flaky(), PRIVATE_IDS)
        report = "\n".join(lines)
        self.assertEqual(inconclusive, 1)
        self.assertIn("pull request: not available (unexpected response shape: ValueError)", report)
        self.assertIn("issue: REFUSED", report)


if __name__ == "__main__":
    unittest.main()
