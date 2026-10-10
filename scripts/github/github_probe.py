"""One-off probe for #74: what do the two GitHub tokens actually return?

Answers the open facts in docs/integrations/GITHUB_MULTI_ACCOUNT.md before any schema
or worker is built:

  1. Do per-type totals include private-repo work at the token's permission level?
  2. Are sub-day from/to windows honoured for commit contributions?
  3. Does the response carry the token-expiry header?
  4. Does the account's profile setting change what B's totals show? (recorded, asked
     by the wizard; the probe only reports what it sees)
  5. Is A's restricted (unsplit) count zero?
  6. Which OAuth scopes does a classic token really carry? (B needs read:user and
     nothing else; the header names every scope, so a stray `repo` is caught.)
  7. With `--audit-exposure`: can this token read any repository, organisation, PR or
     issue NAME? Answered as counts and yes/no, never as the names themselves.

Privacy: this script prints counts, booleans and timestamps only. The probe proper
never selects a repository name, commit message, URL or author field, and the
counts-only account (B) is never asked about repositories at all. The exposure audit
is the one deliberate exception: it asks for names so it can say whether they are
readable, keeps only "was a non-empty string returned", and discards the value at once.
Standard library only, like the Hevy worker.

Run via scripts/github/token-wizard.sh, or directly:
    python scripts/github/github_probe.py --env-file .env.local [--audit-exposure]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"
EXPIRY_HEADER = "github-authentication-token-expiration"
# Classic tokens list their scopes here; fine-grained tokens send no such header.
SCOPES_HEADER = "x-oauth-scopes"
# B's classic token must carry exactly this and nothing else (#20, 2026-10-10).
EXPECTED_SCOPES = frozenset({"read:user"})
# #20: backfill starts here, and one contributionsCollection call spans at most a year.
BACKFILL_START = datetime(2026, 1, 1, tzinfo=LONDON)
RECENT_DAYS = 30

IDENTITY_QUERY = "query { viewer { id login databaseId } }"

TOTALS_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      restrictedContributionsCount
    }
  }
}
"""

# Only for the full-detail account. Selects timestamps and nothing else: no names.
RECENT_COMMITS_QUERY = """
query($id: ID!, $since: GitTimestamp!) {
  viewer {
    repositories(first: 30, orderBy: {field: PUSHED_AT, direction: DESC}, ownerAffiliations: [OWNER]) {
      nodes {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 10, author: {id: $id}, since: $since) {
                nodes { authoredDate }
              }
            }
          }
        }
      }
    }
  }
}
"""


# ── exposure audit queries ────────────────────────────────────────────────────
# These DO select name fields, on purpose: the point is to learn whether this token can
# read them. Only "was a non-empty string returned" is kept; see exposure_audit().

AUDIT_COMMITS_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate nameWithOwner }
        contributions { totalCount }
      }
    }
  }
}
"""

AUDIT_PULL_REQUESTS_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      pullRequestContributions(first: 50) {
        nodes { pullRequest { title repository { isPrivate } } }
      }
    }
  }
}
"""

AUDIT_ISSUES_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      issueContributions(first: 50) {
        nodes { issue { title repository { isPrivate } } }
      }
    }
  }
}
"""

AUDIT_PRIVATE_REPOS_QUERY = """
query {
  viewer {
    repositories(first: 50, privacy: PRIVATE, ownerAffiliations: [OWNER]) {
      totalCount
      nodes { nameWithOwner }
    }
  }
}
"""

AUDIT_ORGANISATIONS_QUERY = """
query {
  viewer {
    organizations(first: 50) {
      totalCount
      nodes { login }
    }
  }
}
"""


class ProbeError(Exception):
    """A failure with a message that is safe to print."""


@dataclass(frozen=True)
class Totals:
    commit: int = 0
    pull_request: int = 0
    review: int = 0
    issue: int = 0
    unsplit: int = 0

    @property
    def typed(self) -> int:
        return self.commit + self.pull_request + self.review + self.issue


@dataclass(frozen=True)
class AccountSpec:
    label: str  # "A" or "B"
    token: str
    expected_login: str
    detail: str  # "full" or "counts_only"


class GraphQLClient(Protocol):
    def query(self, query: str, variables: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]: ...


class AuditClient(GraphQLClient, Protocol):
    def rest_get(self, path: str) -> tuple[int, Any]: ...


# ── pure helpers (unit-tested) ────────────────────────────────────────────────


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def iso_z(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def london_day_window(day: date) -> tuple[datetime, datetime]:
    """UTC instants [start, end) of one London calendar day. 23 or 25 hours on DST days."""
    start = datetime.combine(day, time.min, tzinfo=LONDON).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LONDON).astimezone(timezone.utc)
    return start, end


def utc_day_window(day: date) -> tuple[datetime, datetime]:
    """UTC instants [start, end) of one UTC calendar date.

    GitHub buckets contribution counts by UTC date (probe run 2026-10-10: a London-day
    window spanning two UTC dates returned the sum of both). Always 24 hours, so there
    are no DST edge cases.
    """
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def london_day_of(instant: datetime) -> date:
    return instant.astimezone(LONDON).date()


def inclusive_to(end_exclusive: datetime) -> datetime:
    """The API's `to` is inclusive; a half-open [start, end) window ends a second early."""
    return end_exclusive - timedelta(seconds=1)


def classify_halves(day: int, first: int, second: int) -> str:
    """Split one London day into two halves and see whether the counts partition it."""
    if day == 0:
        return "inconclusive"
    if first == day and second == day:
        return "day_granular"
    if first + second == day and first < day and second < day:
        return "honoured"
    if first + second == day:
        return "inconclusive"  # every commit fell in one half: consistent, uninformative
    return "unexpected"


def classify_commit_window(inside: int, outside: int, day: int) -> str:
    """A tiny window around a known commit, against one just after it."""
    if inside >= 1 and outside == 0:
        return "honoured"
    if inside == 0 and day >= 1:
        return "day_granular"
    if inside >= 1 and outside >= 1 and inside == day and outside == day:
        return "day_granular"
    return "inconclusive"


def scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[token]")
    return text


def parse_scopes(headers: dict[str, str]) -> list[str] | None:
    """The token's OAuth scopes, or None for a token that sends no scopes header."""
    raw = headers.get(SCOPES_HEADER)
    if raw is None:
        return None
    return sorted(part.strip() for part in raw.split(",") if part.strip())


def scope_lines(scopes: list[str] | None) -> list[str]:
    if scopes is None:
        return ["token type: fine-grained or app token (no OAuth scopes header)"]
    shown = ", ".join(scopes) if scopes else "none"
    extra = sorted(set(scopes) - EXPECTED_SCOPES)
    lines = [f"token type: classic; scopes: {shown}"]
    if not extra:
        lines.append("scope check: exactly what B needs, nothing more")
        return lines
    lines.append(f"scope check: EXTRA scope(s) beyond read:user: {', '.join(extra)}")
    if any(s == "repo" or s.startswith("repo:") or s.startswith("write:") for s in extra):
        lines.append("  a leaked token could change or read code: remake it with read:user only")
    else:
        lines.append("  remake the token with read:user only")
    return lines


def named(value: Any) -> bool:
    """Whether a name field came back as a real string. The value itself is dropped."""
    return isinstance(value, str) and value.strip() != ""


# ── GitHub ────────────────────────────────────────────────────────────────────


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._token = token

    def query(self, query: str, variables: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = Request(
            GRAPHQL_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "personal-observability-github-probe",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise ProbeError(f"GitHub answered HTTP {error.code}") from None
        except URLError as error:
            raise ProbeError(f"could not reach GitHub ({type(error.reason).__name__})") from None
        if payload.get("errors"):
            kinds = sorted({str(e.get("type", "UNKNOWN")) for e in payload["errors"]})
            raise ProbeError("GraphQL error type(s): " + ", ".join(kinds))
        return payload["data"], headers

    def rest_get(self, path: str) -> tuple[int, Any]:
        """(HTTP status, parsed JSON or None). A 4xx is an answer here, not an error."""
        request = Request(
            REST_URL + path,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "personal-observability-github-probe",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, None
        except URLError as error:
            raise ProbeError(f"could not reach GitHub ({type(error.reason).__name__})") from None


def fetch_totals(client: GraphQLClient, start: datetime, end_exclusive: datetime) -> Totals:
    data, _ = client.query(
        TOTALS_QUERY, {"from": iso_z(start), "to": iso_z(inclusive_to(end_exclusive))}
    )
    cc = data["viewer"]["contributionsCollection"]
    return Totals(
        commit=cc["totalCommitContributions"],
        pull_request=cc["totalPullRequestContributions"],
        review=cc["totalPullRequestReviewContributions"],
        issue=cc["totalIssueContributions"],
        unsplit=cc["restrictedContributionsCount"],
    )


def recent_commit_times(client: GraphQLClient, viewer_id: str, since: datetime) -> list[datetime]:
    data, _ = client.query(RECENT_COMMITS_QUERY, {"id": viewer_id, "since": iso_z(since)})
    times: list[datetime] = []
    for repo in data["viewer"]["repositories"]["nodes"]:
        target = (repo.get("defaultBranchRef") or {}).get("target") or {}
        for node in (target.get("history") or {}).get("nodes", []):
            times.append(datetime.fromisoformat(node["authoredDate"].replace("Z", "+00:00")))
    return times


# ── the probe ─────────────────────────────────────────────────────────────────


def probe_account(client: GraphQLClient, spec: AccountSpec, now: datetime) -> tuple[list[str], bool]:
    """Returns (report lines, ok). `ok` is False only when the account could not be read."""
    lines = [f"== Account {spec.label} ({spec.detail}) =="]
    try:
        identity, headers = client.query(IDENTITY_QUERY)
        viewer = identity["viewer"]
        matches = viewer["login"].lower() == spec.expected_login.lower()
        lines.append(f"token belongs to the expected login: {'yes' if matches else 'NO'}")
        if not matches:
            lines.append("stopping: this token is for a different account than the wizard was told")
            return lines, False

        lines.extend(scope_lines(parse_scopes(headers)))
        expiry = headers.get(EXPIRY_HEADER)
        lines.append(f"token expiry header: {'present, ' + expiry if expiry else 'ABSENT'}")

        totals = fetch_totals(client, BACKFILL_START, now)
        lines.append(
            "totals since 2026-01-01: "
            f"commits={totals.commit} prs={totals.pull_request} "
            f"reviews={totals.review} issues={totals.issue} unsplit={totals.unsplit}"
        )
        if totals.typed > 0:
            lines.append("typed totals visible at this permission level: yes")
        else:
            lines.append("typed totals visible at this permission level: NO (all zero)")
        if totals.unsplit > 0:
            lines.append(
                f"unsplit is {totals.unsplit}: the token cannot see into some repositories"
            )
        else:
            lines.append("unsplit is 0: nothing hidden from this token")

        # Check 2, day level, on UTC dates (GitHub's own buckets): the busiest of the last
        # RECENT_DAYS dates, in halves, then a 24h window straddling midnight against the
        # two dates it touches. Whole-date buckets give first == second == day and
        # straddle == previous + day.
        today = now.astimezone(timezone.utc).date()
        counts: dict[date, int] = {}
        for offset in range(RECENT_DAYS):
            day = today - timedelta(days=offset)
            start, end = utc_day_window(day)
            counts[day] = fetch_totals(client, start, end).commit
        busiest_day = max(counts, key=lambda d: counts[d])
        busiest = counts[busiest_day]
        if busiest <= 0:
            lines.append(f"day-level windows: no commits in the last {RECENT_DAYS} days (inconclusive)")
        else:
            start, end = utc_day_window(busiest_day)
            midday = start + timedelta(hours=12)
            first = fetch_totals(client, start, midday).commit
            second = fetch_totals(client, midday, end).commit
            verdict = classify_halves(busiest, first, second)
            lines.append(
                f"day-level windows (UTC dates): day={busiest} first-half={first} "
                f"second-half={second} -> {verdict}"
            )
            previous = busiest_day - timedelta(days=1)
            prev_count = counts.get(previous)
            if prev_count is None:
                p_start, p_end = utc_day_window(previous)
                prev_count = fetch_totals(client, p_start, p_end).commit
            straddle = fetch_totals(client, start - timedelta(hours=12), midday).commit
            expected = prev_count + busiest
            lines.append(
                f"midnight-straddling window: {straddle} vs previous date {prev_count} + "
                f"date {busiest} = {expected} -> "
                f"{'matches (UTC date buckets)' if straddle == expected else 'DIFFERENT'}"
            )

        # Check 2, commit level: only for the full-detail account, which may read history.
        if spec.detail == "full":
            times = recent_commit_times(client, viewer["id"], now - timedelta(days=RECENT_DAYS))
            if not times:
                lines.append("commit-level windows: no recent default-branch commits (inconclusive)")
            else:
                newest = max(times)
                inside = fetch_totals(
                    client, newest - timedelta(seconds=30), newest + timedelta(seconds=31)
                ).commit
                outside = fetch_totals(
                    client, newest + timedelta(seconds=60), newest + timedelta(seconds=121)
                ).commit
                day_start, day_end = utc_day_window(newest.astimezone(timezone.utc).date())
                day_total = fetch_totals(client, day_start, day_end).commit
                verdict = classify_commit_window(inside, outside, day_total)
                lines.append(
                    f"commit-level windows: inside={inside} just-after={outside} "
                    f"that-day={day_total} -> {verdict}"
                )
        return lines, True
    except ProbeError as error:
        lines.append(f"FAILED: {scrub(str(error), [spec.token])}")
        return lines, False


def exposure_audit(client: AuditClient, now: datetime) -> tuple[list[str], int]:
    """What can this token read BY NAME? Returns (report lines, places names were readable).

    Every check is isolated: a failure in one is reported and the rest still run. The
    names themselves are reduced to a count of non-empty strings and never stored or
    printed, so the report is safe to paste anywhere.
    """
    lines = ["-- exposure audit: can this token read names? (values never shown) --"]
    window = {"from": iso_z(BACKFILL_START), "to": iso_z(now)}
    readable_in: list[str] = []

    def record(label: str, summary: str, readable: int) -> None:
        lines.append(f"{label}: {summary}")
        if readable:
            readable_in.append(label)

    def guarded(label: str, run: Any) -> None:
        try:
            run()
        except ProbeError as error:
            lines.append(f"{label}: not available ({error})")
        except Exception as error:  # a check must never take the whole audit down
            lines.append(f"{label}: not available (unexpected response shape: {type(error).__name__})")

    def present(entries: list[Any] | None) -> list[dict[str, Any]]:
        """GitHub returns null entries for items the token may not see; count them apart."""
        return [e for e in (entries or []) if isinstance(e, dict)]

    def commits() -> None:
        data, _ = client.query(AUDIT_COMMITS_QUERY, window)
        raw = data["viewer"]["contributionsCollection"]["commitContributionsByRepository"] or []
        items = present(raw)
        private = sum(1 for i in items if (i.get("repository") or {}).get("isPrivate"))
        readable = sum(1 for i in items if named((i.get("repository") or {}).get("nameWithOwner")))
        capped = " (list capped at 100)" if len(raw) >= 100 else ""
        record(
            "commit breakdown by repository",
            f"{len(raw)} repos listed{capped}, {private} private, repo name readable on {readable}, "
            f"{len(raw) - len(items)} hidden",
            readable,
        )

    def nodes_check(label: str, query: str, field: str, inner: str) -> None:
        data, _ = client.query(query, window)
        raw = data["viewer"]["contributionsCollection"][field]["nodes"] or []
        nodes = present(raw)
        private = sum(
            1 for n in nodes if ((n.get(inner) or {}).get("repository") or {}).get("isPrivate")
        )
        readable = sum(1 for n in nodes if named((n.get(inner) or {}).get("title")))
        record(
            label,
            f"{len(raw)} listed, {private} in private repos, title readable on {readable}, "
            f"{len(raw) - len(nodes)} hidden",
            readable,
        )

    def private_repos() -> None:
        data, _ = client.query(AUDIT_PRIVATE_REPOS_QUERY)
        block = data["viewer"]["repositories"]
        readable = sum(1 for n in present(block["nodes"]) if named(n.get("nameWithOwner")))
        record(
            "private repositories (GraphQL)",
            f"total {block['totalCount']}, name readable on {readable}",
            readable,
        )

    def organisations() -> None:
        data, _ = client.query(AUDIT_ORGANISATIONS_QUERY)
        block = data["viewer"]["organizations"]
        readable = sum(1 for n in present(block["nodes"]) if named(n.get("login")))
        record("organisations", f"total {block['totalCount']}, name readable on {readable}", readable)

    def rest_profile() -> None:
        status, body = client.rest_get("/user")
        fields = isinstance(body, dict) and "total_private_repos" in body
        record("REST /user", f"HTTP {status}, private profile fields present: {'yes' if fields else 'no'}", 0)

    def rest_private_repos() -> None:
        status, body = client.rest_get("/user/repos?visibility=private&per_page=50")
        items = [i for i in body if isinstance(i, dict)] if isinstance(body, list) else []
        readable = sum(1 for i in items if named(i.get("full_name")) or named(i.get("name")))
        record("REST /user/repos (private)", f"HTTP {status}, {len(items)} returned, name readable on {readable}", readable)

    def rest_emails() -> None:
        status, _ = client.rest_get("/user/emails")
        record("REST /user/emails", f"HTTP {status}", 0)

    guarded("commit breakdown by repository", commits)
    guarded(
        "pull request contributions",
        lambda: nodes_check(
            "pull request contributions", AUDIT_PULL_REQUESTS_QUERY, "pullRequestContributions", "pullRequest"
        ),
    )
    guarded(
        "issue contributions",
        lambda: nodes_check("issue contributions", AUDIT_ISSUES_QUERY, "issueContributions", "issue"),
    )
    guarded("private repositories (GraphQL)", private_repos)
    guarded("organisations", organisations)
    guarded("REST /user", rest_profile)
    guarded("REST /user/repos (private)", rest_private_repos)
    guarded("REST /user/emails", rest_emails)

    if readable_in:
        lines.append("RESULT: names ARE readable by this token in: " + "; ".join(readable_in))
    else:
        lines.append("RESULT: no repository, organisation, PR or issue name was readable by this token")
    return lines, len(readable_in)


def specs_from(values: dict[str, str]) -> list[AccountSpec]:
    specs = []
    for label, detail in (("A", "full"), ("B", "counts_only")):
        token = values.get(f"GITHUB_TOKEN_{label}", "").strip()
        login = values.get(f"GITHUB_LOGIN_{label}", "").strip()
        if token and login:
            specs.append(AccountSpec(label, token, login, detail))
    return specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env.local", type=Path)
    parser.add_argument(
        "--b-private-setting",
        choices=["on", "off", "unknown"],
        default="unknown",
        help="B's 'Private contributions' profile setting, recorded in the report (check 4)",
    )
    parser.add_argument(
        "--audit-exposure",
        action="store_true",
        help="also report whether each token can read repo/org/PR/issue names (yes/no, never the names)",
    )
    args = parser.parse_args(argv)

    values = {**load_env_file(args.env_file), **os.environ}
    specs = specs_from(values)
    if not specs:
        print(
            "No accounts configured: set GITHUB_TOKEN_A / GITHUB_LOGIN_A "
            f"(and the B pair) in {args.env_file}.",
            file=sys.stderr,
        )
        return 2

    now = datetime.now(timezone.utc)
    print(f"GitHub probe, {iso_z(now)}. Counts and booleans only.")
    print(f"B 'Private contributions' profile setting (as reported by you): {args.b_private_setting}")
    all_ok = True
    for spec in specs:
        client = GitHubClient(spec.token)
        lines, ok = probe_account(client, spec, now)
        print()
        print("\n".join(lines))
        all_ok = all_ok and ok
        if args.audit_exposure and ok:
            try:
                audit_lines, _ = exposure_audit(client, now)
            except ProbeError as error:
                audit_lines = [f"exposure audit FAILED: {scrub(str(error), [spec.token])}"]
            print()
            print("\n".join(scrub(line, [spec.token]) for line in audit_lines))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
