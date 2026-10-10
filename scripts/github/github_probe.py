"""One-off probe for #74: what do the two GitHub tokens actually return?

Answers the open facts in docs/integrations/GITHUB_MULTI_ACCOUNT.md before any schema
or worker is built:

  1. Do per-type totals include private-repo work at the token's permission level?
  2. Are sub-day from/to windows honoured for commit contributions?
  3. Does the response carry the token-expiry header?
  4. Does the account's profile setting change what B's totals show? (recorded, asked
     by the wizard; the probe only reports what it sees)
  5. Is A's restricted (unsplit) count zero?

Privacy: this script prints counts, booleans and timestamps only. It never selects a
repository name, commit message, URL or author field, and the counts-only account (B)
is never asked about repositories at all. Standard library only, like the Hevy worker.

Run via scripts/github/token-wizard.sh, or directly:
    python scripts/github/github_probe.py --env-file .env.local
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
EXPIRY_HEADER = "github-authentication-token-expiration"
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

        # Check 2, day level: the busiest of the last RECENT_DAYS London days, in halves.
        today = now.astimezone(LONDON).date()
        busiest_day, busiest = today, -1
        for offset in range(RECENT_DAYS):
            day = today - timedelta(days=offset)
            start, end = london_day_window(day)
            count = fetch_totals(client, start, end).commit
            if count > busiest:
                busiest_day, busiest = day, count
        if busiest <= 0:
            lines.append(f"day-level windows: no commits in the last {RECENT_DAYS} days (inconclusive)")
        else:
            start, end = london_day_window(busiest_day)
            midday = start + (end - start) / 2
            first = fetch_totals(client, start, midday).commit
            second = fetch_totals(client, midday, end).commit
            verdict = classify_halves(busiest, first, second)
            lines.append(
                f"day-level windows: day={busiest} first-half={first} second-half={second} -> {verdict}"
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
                day_start, day_end = london_day_window(london_day_of(newest))
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
        lines, ok = probe_account(GitHubClient(spec.token), spec, now)
        print()
        print("\n".join(lines))
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
