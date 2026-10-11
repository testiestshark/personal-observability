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
  8. With `--audit-direct-fetch` (#103): is a known private PR, issue, commit and file,
     requested by exact ID, refused? Listings coming back empty (7) is not the same
     test. Answered as refused / exposed / inconclusive per item, never the IDs.

Privacy: this script prints counts, booleans and timestamps only. The probe proper
never selects a repository name, commit message, URL or author field, and the
counts-only account (B) is never asked about repositories at all. The exposure audit
is the one deliberate exception: it asks for names so it can say whether they are
readable, keeps only "was a non-empty string returned", and discards the value at once.
The direct-fetch audit selects opaque IDs only, and its inputs (the IDs of private
items) come from the environment or the gitignored env file, never from this repo.
Standard library only, like the Hevy worker.

Run via scripts/github/token-wizard.sh, or directly:
    python scripts/github/github_probe.py --env-file .env.local [--audit-exposure]
    python scripts/github/github_probe.py --env-file .env.local --audit-direct-fetch

Direct-fetch inputs (account B only; all four are needed for a full pass):
    GITHUB_PROBE_PR       owner/repo#123
    GITHUB_PROBE_ISSUE    owner/repo#45
    GITHUB_PROBE_COMMIT   owner/repo@<full 40-character sha>
    GITHUB_PROBE_FILE     owner/repo:path/to/file[@ref]
    GITHUB_PROBE_CONTROL_TOKEN   optional: a token that CAN read them. A mistyped ID is
                                 also a 404, so without it a "refused" may be a typo.
Exit code: 0 clean, 1 something was exposed (or a token check failed), 2 not configured,
3 nothing exposed but at least one item could not be judged. Inconclusive is not a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
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


# ── direct-fetch audit queries (#103) ─────────────────────────────────────────
# One known private item, requested by exact ID. They select opaque IDs only: no title,
# name, message or body, so even an "exposed" answer carries nothing readable.

FETCH_PULL_REQUEST_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { id } }
}
"""

FETCH_ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""

FETCH_COMMIT_QUERY = """
query($owner: String!, $name: String!, $oid: GitObjectID!) {
  repository(owner: $owner, name: $name) { object(oid: $oid) { oid } }
}
"""

FETCH_FILE_QUERY = """
query($owner: String!, $name: String!, $expression: String!) {
  repository(owner: $owner, name: $name) { object(expression: $expression) { oid } }
}
"""

FETCH_KINDS = ("pull request", "issue", "commit", "file")
FETCH_ENV = {
    "pull request": "GITHUB_PROBE_PR",
    "issue": "GITHUB_PROBE_ISSUE",
    "commit": "GITHUB_PROBE_COMMIT",
    "file": "GITHUB_PROBE_FILE",
}
FETCH_FORMS = {
    "pull request": "owner/repo#number",
    "issue": "owner/repo#number",
    "commit": "owner/repo@<full 40-character sha>",
    "file": "owner/repo:path[@ref]",
}
CONTROL_ENV = "GITHUB_PROBE_CONTROL_TOKEN"

REFUSED, EXPOSED, INCONCLUSIVE = "refused", "exposed", "inconclusive"
# GraphQL error types that mean "this token may not see that". Anything else (rate limit,
# server trouble, a missing type) says nothing about access and must not read as a pass.
GRAPHQL_REFUSALS = frozenset({"NOT_FOUND", "FORBIDDEN", "INSUFFICIENT_SCOPES"})

_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_REPO = r"[A-Za-z0-9_.-]{1,100}"
_NUMBERED_ID = re.compile(rf"^({_OWNER})/({_REPO})#([1-9][0-9]{{0,8}})$")
_COMMIT_ID = re.compile(rf"^({_OWNER})/({_REPO})@([0-9a-fA-F]{{40}})$")
_FILE_ID = re.compile(rf"^({_OWNER})/({_REPO}):([A-Za-z0-9_.+/-]+)(?:@([A-Za-z0-9_./-]+))?$")


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


class FetchClient(Protocol):
    """Unlike GraphQLClient and rest_get, these return a refusal as an answer, not an error."""

    def fetch_rest(self, path: str) -> RawResponse: ...

    def fetch_graphql(self, query: str, variables: dict[str, Any]) -> RawResponse: ...


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


@dataclass(frozen=True)
class RawResponse:
    """What GitHub answered, whatever it was. `status` is 0 when it could not be reached."""

    status: int
    headers: dict[str, str]
    payload: Any


@dataclass(frozen=True)
class FetchTarget:
    """One private item, addressed by exact ID. Never printed: it names a private repo."""

    kind: str
    owner: str
    repo: str
    number: int | None = None  # pull request or issue
    sha: str | None = None  # commit
    path: str | None = None  # file
    ref: str | None = None  # file; None is the default branch

    def rest_path(self) -> str:
        base = f"/repos/{self.owner}/{self.repo}"
        if self.kind == "pull request":
            return f"{base}/pulls/{self.number}"
        if self.kind == "issue":
            return f"{base}/issues/{self.number}"
        if self.kind == "commit":
            return f"{base}/commits/{self.sha}"
        suffix = f"?ref={quote(self.ref, safe='')}" if self.ref else ""
        return f"{base}/contents/{quote(self.path or '', safe='/')}{suffix}"

    def graphql(self) -> tuple[str, dict[str, Any], tuple[str, ...]]:
        """(query, variables, path to the node that would hold the item)."""
        who: dict[str, Any] = {"owner": self.owner, "name": self.repo}
        if self.kind == "pull request":
            return FETCH_PULL_REQUEST_QUERY, {**who, "number": self.number}, ("repository", "pullRequest")
        if self.kind == "issue":
            return FETCH_ISSUE_QUERY, {**who, "number": self.number}, ("repository", "issue")
        if self.kind == "commit":
            return FETCH_COMMIT_QUERY, {**who, "oid": self.sha}, ("repository", "object")
        expression = f"{self.ref or 'HEAD'}:{self.path}"
        return FETCH_FILE_QUERY, {**who, "expression": expression}, ("repository", "object")


def parse_target(kind: str, text: str) -> FetchTarget:
    """Parse one ID. Strict on purpose: the pieces go into API paths. The text is never
    echoed in an error, because it names a private repository."""
    patterns = {"pull request": _NUMBERED_ID, "issue": _NUMBERED_ID, "commit": _COMMIT_ID, "file": _FILE_ID}
    match = patterns[kind].match(text.strip())
    if match is None or match.group(2) in (".", ".."):
        raise ProbeError(f"not in the form {FETCH_FORMS[kind]}")
    owner, repo, last = match.group(1), match.group(2), match.group(3)
    if kind in ("pull request", "issue"):
        return FetchTarget(kind, owner, repo, number=int(last))
    if kind == "commit":
        return FetchTarget(kind, owner, repo, sha=last.lower())
    if ".." in last.split("/"):
        raise ProbeError(f"not in the form {FETCH_FORMS[kind]}")
    return FetchTarget(kind, owner, repo, path=last, ref=match.group(4))


def rate_limited(headers: dict[str, str]) -> bool:
    """GitHub answers a rate limit with 403 as well as 429."""
    return headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers


def rest_verdict(response: RawResponse) -> str:
    if response.status == 200:
        return EXPOSED
    if response.status == 404:
        return REFUSED
    if response.status == 403 and not rate_limited(response.headers):
        return REFUSED
    return INCONCLUSIVE


def graphql_verdict(response: RawResponse, path: tuple[str, ...]) -> str:
    """EXPOSED if the node came back, REFUSED if GitHub said no or returned nothing,
    INCONCLUSIVE for anything that is not an answer about access."""
    if response.status != 200 or not isinstance(response.payload, dict):
        return INCONCLUSIVE
    data = response.payload.get("data")
    node = data
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, dict):
        return EXPOSED
    errors = [e for e in response.payload.get("errors") or [] if isinstance(e, dict)]
    types = {str(e.get("type", "")) for e in errors}
    if types - GRAPHQL_REFUSALS:
        return INCONCLUSIVE
    if types or isinstance(data, dict):
        return REFUSED
    return INCONCLUSIVE


def combine_verdicts(verdicts: list[str]) -> str:
    """Exposure on any route wins; then doubt; a pass needs every route to refuse."""
    if EXPOSED in verdicts:
        return EXPOSED
    if INCONCLUSIVE in verdicts:
        return INCONCLUSIVE
    return REFUSED


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

    def _send(self, request: Request) -> RawResponse:
        try:
            with urlopen(request, timeout=30) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                try:
                    payload = json.loads(response.read().decode("utf-8"))
                except ValueError:
                    payload = None
                return RawResponse(response.status, headers, payload)
        except HTTPError as error:
            return RawResponse(error.code, {k.lower(): v for k, v in error.headers.items()}, None)
        except URLError:
            return RawResponse(0, {}, None)

    def fetch_rest(self, path: str) -> RawResponse:
        return self._send(
            Request(
                REST_URL + path,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "personal-observability-github-probe",
                },
                method="GET",
            )
        )

    def fetch_graphql(self, query: str, variables: dict[str, Any]) -> RawResponse:
        return self._send(
            Request(
                GRAPHQL_URL,
                data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                    "User-Agent": "personal-observability-github-probe",
                },
                method="POST",
            )
        )


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


def check_target(client: FetchClient, target: FetchTarget) -> tuple[str, int, str]:
    """Request one item over REST and GraphQL: (REST verdict, REST status, GraphQL verdict)."""
    rest = client.fetch_rest(target.rest_path())
    query, variables, path = target.graphql()
    return rest_verdict(rest), rest.status, graphql_verdict(client.fetch_graphql(query, variables), path)


def direct_fetch_audit(
    client: FetchClient, values: Mapping[str, str], control: FetchClient | None = None
) -> tuple[list[str], int, int]:
    """Is each known private item refused when requested by exact ID?

    Returns (report lines, items exposed, items that could not be judged). The IDs are read
    from `values` and never printed. Every item is isolated, and a configured control
    client (a token that CAN read them) is what separates a refusal from a mistyped ID.
    """
    lines = ["-- direct-fetch audit: is a known private item refused by exact ID? (IDs never shown) --"]
    exposed = inconclusive = 0
    for kind in FETCH_KINDS:
        env = FETCH_ENV[kind]
        text = values.get(env, "").strip()
        if not text:
            lines.append(f"{kind}: not configured (set {env})")
            inconclusive += 1
            continue
        try:
            target = parse_target(kind, text)
        except ProbeError as error:
            lines.append(f"{kind}: not usable ({error})")
            inconclusive += 1
            continue
        try:
            rest, status, graphql = check_target(client, target)
            verdict = combine_verdicts([rest, graphql])
            note = "existence not confirmed"
            if control is not None:
                c_rest, _, c_graphql = check_target(control, target)
                if EXPOSED in (c_rest, c_graphql):
                    note = "control token can read it"
                else:
                    note = "control token could not read it, so the ID may be wrong"
                    if verdict == REFUSED:
                        verdict = INCONCLUSIVE
        except Exception as error:  # an item must never take the whole audit down
            lines.append(f"{kind}: not available (unexpected response shape: {type(error).__name__})")
            inconclusive += 1
            continue
        lines.append(f"{kind}: {verdict.upper()} (REST HTTP {status}, GraphQL {graphql}; {note})")
        exposed += verdict == EXPOSED
        inconclusive += verdict == INCONCLUSIVE

    if exposed:
        lines.append(f"RESULT: EXPOSED - {exposed} private item(s) could be read by exact ID with this token")
    elif inconclusive:
        lines.append(f"RESULT: inconclusive - {inconclusive} item(s) could not be judged; this is not a pass")
    elif control is not None:
        lines.append("RESULT: every item was refused, and the control token confirmed each one exists")
    else:
        lines.append(
            "RESULT: every item was refused (no control token, so a mistyped ID would look the "
            "same: confirm each item exists)"
        )
    return lines, exposed, inconclusive


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
    parser.add_argument(
        "--audit-direct-fetch",
        action="store_true",
        help="request known private items of the counts-only account by exact ID and report "
        "refused / exposed / inconclusive (IDs come from GITHUB_PROBE_* and are never shown)",
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
    if args.audit_direct_fetch and not any(s.detail == "counts_only" for s in specs):
        print(
            "--audit-direct-fetch tests the counts-only account: set GITHUB_TOKEN_B / "
            f"GITHUB_LOGIN_B in {args.env_file}.",
            file=sys.stderr,
        )
        return 2

    now = datetime.now(timezone.utc)
    print(f"GitHub probe, {iso_z(now)}. Counts and booleans only.")
    print(f"B 'Private contributions' profile setting (as reported by you): {args.b_private_setting}")
    all_ok = True
    exposed_total = inconclusive_total = 0
    control_token = values.get(CONTROL_ENV, "").strip()
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
        if args.audit_direct_fetch and ok and spec.detail == "counts_only":
            control = GitHubClient(control_token) if control_token else None
            fetch_lines, exposed, inconclusive = direct_fetch_audit(client, values, control)
            exposed_total += exposed
            inconclusive_total += inconclusive
            print()
            print("\n".join(scrub(line, [spec.token, control_token]) for line in fetch_lines))
    if not all_ok or exposed_total:
        return 1
    return 3 if inconclusive_total else 0


if __name__ == "__main__":
    sys.exit(main())
