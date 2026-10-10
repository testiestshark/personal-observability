"""GitHub contribution sync for Personal Observability (#76, part of #20).

Like the Hevy and Garmin workers, this authenticates to Supabase as the app user, so
every write passes through the same Row Level Security policies as a browser request;
it never receives the service-role key. It only ever reads from GitHub, and only through
GraphQL queries defined in this file.

Privacy: a `counts_only` account runs queries that select counts and nothing else, and
the schema's insert policy on `github_commits` refuses rows for it regardless. See
docs/integrations/GITHUB_MULTI_ACCOUNT.md.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import sys
import unittest
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from time import time as unix_time
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

# #20: counts are GitHub's own UTC date buckets, and the history starts here.
BACKFILL_START = date(2026, 1, 1)
# Each run refetches this many UTC dates, today included, to pick up late-landing work.
TRAILING_DAYS = 14

DETAIL_FULL = "full"
DETAIL_COUNTS_ONLY = "counts_only"

# GraphQL field -> github_daily_contributions.kind, in the order rows are written.
COUNT_KINDS = (
    ("totalCommitContributions", "commit"),
    ("totalPullRequestContributions", "pull_request"),
    ("totalPullRequestReviewContributions", "review"),
    ("totalIssueContributions", "issue"),
    ("restrictedContributionsCount", "unsplit"),
)


class SyncError(RuntimeError):
    """An actionable sync failure safe to print without leaking secrets."""


class RateLimited(SyncError):
    """GitHub's rate limit is nearly spent. Whatever was written is kept; rerun to resume."""


# ── GraphQL documents ─────────────────────────────────────────────────────────
# Every query the worker may send is a constant here, so the privacy contract test can
# see all of them. The two below are all a counts_only account ever runs: they select
# counts and the account's own identity, and no repository, message, URL or author.

IDENTITY_QUERY = "query { viewer { id login databaseId } }"

COUNTS_QUERY = """
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

# Full-detail accounts only: default-branch commits by this author, headline only.
COMMITS_QUERY = """
query($id: ID!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String) {
  viewer {
    repositories(first: 25, after: $after, orderBy: {field: PUSHED_AT, direction: DESC}, ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        nameWithOwner
        isPrivate
        pushedAt
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100, author: {id: $id}, since: $since, until: $until) {
                pageInfo { hasNextPage endCursor }
                nodes { oid messageHeadline authoredDate author { date } }
              }
            }
          }
        }
      }
    }
  }
}
"""

# The rest of one repository's history, when a repository has more than a page of it.
COMMIT_HISTORY_QUERY = """
query($repo: ID!, $id: ID!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String!) {
  node(id: $repo) {
    ... on Repository {
      defaultBranchRef {
        target {
          ... on Commit {
            history(first: 100, after: $after, author: {id: $id}, since: $since, until: $until) {
              pageInfo { hasNextPage endCursor }
              nodes { oid messageHeadline authoredDate author { date } }
            }
          }
        }
      }
    }
  }
}
"""


def queries_for(detail: str) -> tuple[str, ...]:
    """The GraphQL documents an account at this detail level is allowed to send."""
    if detail == DETAIL_COUNTS_ONLY:
        return (IDENTITY_QUERY, COUNTS_QUERY)
    if detail == DETAIL_FULL:
        return (IDENTITY_QUERY, COUNTS_QUERY, COMMITS_QUERY, COMMIT_HISTORY_QUERY)
    raise SyncError(f"Unknown detail level {detail!r}; expected 'full' or 'counts_only'.")


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def utc_day_window(day: date) -> tuple[str, str]:
    """The `from` and `to` of one UTC date, both inclusive: 00:00:00Z to 23:59:59Z.

    GitHub buckets contribution counts by UTC date and ignores sub-day windows (probe,
    2026-10-10), so a window is always exactly one date. A London-day window spans two
    UTC dates and GitHub would sum both, double-counting.
    """
    stamp = day.isoformat()
    return f"{stamp}T00:00:00Z", f"{stamp}T23:59:59Z"


def trailing_days(today: date) -> list[date]:
    """The last TRAILING_DAYS UTC dates up to and including `today`, oldest first."""
    return [today - timedelta(days=offset) for offset in range(TRAILING_DAYS - 1, -1, -1)]


def backfill_days(today: date) -> list[date]:
    """Every UTC date from BACKFILL_START to `today` inclusive, oldest first."""
    count = (today - BACKFILL_START).days + 1
    return [BACKFILL_START + timedelta(days=offset) for offset in range(max(count, 0))]


def plan_daily_rows(
    user_id: str, account_id: str, day: date, response: Any, synced_at: str
) -> list[dict[str, Any]]:
    """One github_daily_contributions row per kind for one UTC date.

    All five kinds are written even when zero, so a quiet day is distinguishable from a
    day that was never synced. A response that is not the expected shape is an error,
    never a day of zeros.
    """
    viewer = response.get("viewer") if isinstance(response, dict) else None
    collection = viewer.get("contributionsCollection") if isinstance(viewer, dict) else None
    if not isinstance(collection, dict):
        raise SyncError("GitHub returned an unexpected contributions response.")

    rows: list[dict[str, Any]] = []
    for field, kind in COUNT_KINDS:
        count = _count(collection.get(field))
        if count is None:
            raise SyncError("GitHub returned an unexpected contributions count.")
        rows.append({
            "user_id": user_id,
            "account_id": account_id,
            "local_day": day.isoformat(),
            "kind": kind,
            "count": count,
            "synced_at": synced_at,
        })
    return rows


def _instant(value: Any) -> datetime | None:
    """Parse a GitHub ISO 8601 timestamp as an aware UTC instant."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _headline(value: Any) -> str | None:
    """The first line only: the schema rejects a headline with a newline in it."""
    if not isinstance(value, str):
        return None
    return value.splitlines()[0].strip() if value.strip() else ""


def _history_block(repository: dict[str, Any]) -> dict[str, Any] | None:
    """The default branch's `history` connection of a repository node, if it has one."""
    ref = repository.get("defaultBranchRef")
    target = ref.get("target") if isinstance(ref, dict) else None
    history = target.get("history") if isinstance(target, dict) else None
    return history if isinstance(history, dict) else None


def _history_nodes(repository: dict[str, Any]) -> list[Any]:
    history = _history_block(repository)
    nodes = history.get("nodes") if history else None
    return nodes if isinstance(nodes, list) else []


def plan_commit_rows(
    user_id: str,
    account_id: str,
    repositories: list[Any],
    synced_at: str,
    first_day: date,
    last_day: date,
) -> list[dict[str, Any]]:
    """github_commits rows for the default-branch commits in `repositories`.

    `local_day` is the UTC date of `authoredDate`, GitHub's own bucket, so a row always
    agrees with the daily count for the same date: a commit at 23:30Z and one at 00:30Z
    fall on different dates, and a BST commit just after London midnight stays on the UTC
    date before. Only the headline is kept. Commits whose date is outside
    [first_day, last_day] are dropped, because the API's since/until filter is on the
    committer date, not the author date.
    """
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        repo_id = repository.get("id")
        repo_name = repository.get("nameWithOwner")
        if not isinstance(repo_id, str) or not isinstance(repo_name, str):
            continue
        is_private = repository.get("isPrivate") is True
        for node in _history_nodes(repository):
            if not isinstance(node, dict):
                continue
            oid = node.get("oid")
            authored = _instant(node.get("authoredDate"))
            headline = _headline(node.get("messageHeadline"))
            if not isinstance(oid, str) or not oid or authored is None or headline is None:
                continue
            day = authored.date()
            if not first_day <= day <= last_day:
                continue
            author = node.get("author")
            raw = author.get("date") if isinstance(author, dict) else None
            rows[(repo_id, oid)] = {
                "user_id": user_id,
                "account_id": account_id,
                "repo_node_id": repo_id,
                "repo_name_with_owner": repo_name,
                "repo_is_private": is_private,
                "oid": oid,
                "message_headline": headline,
                "authored_at": authored.isoformat(),
                "author_date_raw": raw if isinstance(raw, str) else None,
                "local_day": day.isoformat(),
                "synced_at": synced_at,
            }
    return list(rows.values())


def _page_cursor(block: Any) -> str | None:
    """The `after` cursor for the next page of a connection, or None on the last page."""
    info = block.get("pageInfo") if isinstance(block, dict) else None
    if isinstance(info, dict) and info.get("hasNextPage") is True:
        cursor = info.get("endCursor")
        if isinstance(cursor, str) and cursor:
            return cursor
        raise SyncError("GitHub reported another page without a cursor for it.")
    return None


def _complete_history(
    github: GitHubApi, author_id: str, repository: dict[str, Any], since: str, until: str
) -> None:
    """Read a repository's remaining history pages, appending them to its first page."""
    history = _history_block(repository)
    if history is None or not isinstance(history.get("nodes"), list):
        return
    cursor = _page_cursor(history)
    while cursor:
        data, _ = github.query(
            COMMIT_HISTORY_QUERY,
            {"repo": repository["id"], "id": author_id, "since": since, "until": until, "after": cursor},
        )
        node = data.get("node") if isinstance(data, dict) else None
        page = _history_block(node) if isinstance(node, dict) else None
        if page is None or not isinstance(page.get("nodes"), list):
            raise SyncError("GitHub returned an unexpected commit history page.")
        history["nodes"].extend(page["nodes"])
        cursor = _page_cursor(page)


def fetch_repositories(
    github: GitHubApi, author_id: str, first_day: date, last_day: date
) -> list[dict[str, Any]]:
    """Repositories (most recently pushed first) with the author's default-branch commits.

    Stops paging at the first repository last pushed before `first_day`: nothing in it
    can hold a commit from the window, and everything after it is older still.
    """
    since, _ = utc_day_window(first_day)
    _, until = utc_day_window(last_day)
    oldest = datetime.combine(first_day, time.min, tzinfo=timezone.utc)
    repositories: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        data, _ = github.query(
            COMMITS_QUERY, {"id": author_id, "since": since, "until": until, "after": after}
        )
        viewer = data.get("viewer") if isinstance(data, dict) else None
        block = viewer.get("repositories") if isinstance(viewer, dict) else None
        nodes = block.get("nodes") if isinstance(block, dict) else None
        if not isinstance(nodes, list):
            raise SyncError("GitHub returned an unexpected repositories response.")
        for node in nodes:
            if not isinstance(node, dict):
                continue
            pushed = _instant(node.get("pushedAt"))
            if pushed is not None and pushed < oldest:
                return repositories
            _complete_history(github, author_id, node, since, until)
            repositories.append(node)
        after = _page_cursor(block)
        if after is None:
            return repositories

# ── accounts and one account's sync ───────────────────────────────────────────

EXPIRY_HEADER = "github-authentication-token-expiration"
GRAPHQL_URL = "https://api.github.com/graphql"
REMAINING_HEADER = "x-ratelimit-remaining"
# GraphQL points left at which the worker stops rather than risk the hour's budget.
RATE_LIMIT_RESERVE = 25
ACCOUNT_SLOTS = ("A", "B")
CONNECTION_ATTEMPTS = 4
CONNECTION_BACKOFF_SECONDS = 1
# Rows per request when upserting commits, to keep each request comfortably small.
COMMIT_BATCH = 200
# PostgREST default row cap. stored_days reads one row per date, so a year fits.
STORED_DAYS_LIMIT = 1000
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


@dataclass(frozen=True)
class AccountConfig:
    """One GitHub account the worker syncs, from configuration.

    The token, login and label are kept out of `repr`, which turns up in assertion
    diffs and tracebacks; only the slot letter and detail level are safe to print.
    """

    slot: str  # "A" or "B": the suffix of its GITHUB_TOKEN_<slot> variable
    token: str = field(repr=False)
    login: str = field(repr=False)  # the login this token must belong to
    label: str = field(repr=False)
    detail: str
    display_order: int


@dataclass
class AccountResult:
    days_written: int = 0
    commits_written: int = 0
    unsplit_days: int = 0


class GitHubApi(Protocol):
    def query(
        self, document: str, variables: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]: ...


class RestrictedGitHub:
    """A GitHub client that sends only the documents it was given.

    This is what makes the privacy contract a property of the running code rather than
    of a test: a counts_only account is wrapped with queries_for("counts_only"), so a
    commit or repository query cannot reach GitHub for it whatever the caller does.
    """

    def __init__(self, github: GitHubApi, allowed: tuple[str, ...]) -> None:
        self._github = github
        self._allowed = frozenset(allowed)

    def query(
        self, document: str, variables: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if document not in self._allowed:
            raise SyncError("Refused to send a GraphQL document this account may not run.")
        return self._github.query(document, variables)


def user_id_of(session: dict[str, Any]) -> str:
    user = session.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise SyncError("The cached app session has no user id. Run setup again.")
    return user_id


def parse_token_expiry(value: str | None) -> str | None:
    """The token-expiry header as an ISO timestamp, or None if absent or unrecognised."""
    if not value or not value.strip():
        return None
    text = value.strip()
    if text.endswith(" UTC"):
        text = text[: -len(" UTC")] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _viewer(data: Any) -> dict[str, Any]:
    viewer = data.get("viewer") if isinstance(data, dict) else None
    if (
        not isinstance(viewer, dict)
        or not isinstance(viewer.get("login"), str)
        or not isinstance(viewer.get("id"), str)
        or isinstance(viewer.get("databaseId"), bool)
        or not isinstance(viewer.get("databaseId"), int)
    ):
        raise SyncError("GitHub returned an unexpected identity response.")
    return viewer


def resolve_account(
    supabase: Any, session: dict[str, Any], config: AccountConfig, viewer: dict[str, Any]
) -> dict[str, Any]:
    """The github_accounts row this token belongs to, created on the first run.

    Refuses, before anything is written, when the token is not for the login it is
    configured for, or when the stored row for that login is a different GitHub user.
    A row found by the token's own user id under an older login is the same account
    renamed on GitHub, and takes the new login.
    """
    if viewer["login"].lower() != config.login.lower():
        raise SyncError(
            f"The token for account {config.slot} belongs to a different GitHub login "
            f"than GITHUB_LOGIN_{config.slot}. Nothing was written."
        )
    row = supabase.find_account(config.login, session)
    if row is None:
        row = supabase.find_account_by_github_user_id(viewer["databaseId"], session)
        if row is not None:
            supabase.update_account(row["id"], {"login": viewer["login"]}, session)
            row = {**row, "login": viewer["login"]}
    if row is None:
        return supabase.create_account(
            {
                "user_id": user_id_of(session),
                "github_user_id": viewer["databaseId"],
                "github_node_id": viewer["id"],
                "login": viewer["login"],
                "label": config.label,
                "detail": config.detail,
                "display_order": config.display_order,
            },
            session,
        )
    if row.get("github_user_id") != viewer["databaseId"]:
        raise SyncError(
            f"The stored row for account {config.slot} is a different GitHub user than "
            "this token. Nothing was written."
        )
    wanted = {"label": config.label, "detail": config.detail, "display_order": config.display_order}
    changed = {key: value for key, value in wanted.items() if row.get(key) != value}
    if changed:
        supabase.update_account(row["id"], changed, session)
        row = {**row, **changed}
    return row


def _sync_commits(
    supabase: Any,
    github: GitHubApi,
    session: dict[str, Any],
    user_id: str,
    account_id: str,
    author_id: str,
    window: tuple[date, date],
    synced_at: str,
) -> int:
    """Upsert the author's default-branch commits for the window; returns how many.

    Only adds and updates. A commit GitHub stops reporting (a force-push) stays until
    removed by hand: deleting on a read that might be incomplete would lose data that a
    shorter later window could not bring back. The daily counts still follow GitHub.
    """
    first_day, last_day = window
    repositories = fetch_repositories(github, author_id, first_day, last_day)
    rows = plan_commit_rows(user_id, account_id, repositories, synced_at, first_day, last_day)
    if rows:
        supabase.upsert_commit_rows(rows, session)
    return len(rows)


def sync_account(
    supabase: Any,
    github: GitHubApi,
    session: dict[str, Any],
    config: AccountConfig,
    days: list[date],
    commit_window: tuple[date, date],
    now: datetime,
    resume: bool = False,
) -> AccountResult:
    """Sync one account's counts (and, for a full account, commits) for `days`.

    With `resume`, dates that are already stored are skipped, except the trailing dates,
    which are always refetched. Each date is written as it is read, so a run stopped by a
    rate limit or an error leaves everything before the stop in place.
    """
    # An unknown detail level stops here, before any request. Everything this account
    # sends goes through the allow-list for its level.
    allowed = queries_for(config.detail)
    github = RestrictedGitHub(github, allowed)
    synced_at = now.isoformat()
    identity, headers = github.query(IDENTITY_QUERY)
    viewer = _viewer(identity)
    account = resolve_account(supabase, session, config, viewer)
    user_id = user_id_of(session)

    result = AccountResult()
    reads_commits = COMMITS_QUERY in allowed
    if not reads_commits:
        # The insert policy stops new commit rows for this account; only the worker can
        # remove any stored while it was `full`.
        supabase.delete_commits(account["id"], session)

    if resume and days:
        stored = supabase.stored_days(account["id"], days[0], days[-1], session)
        always = set(trailing_days(now.astimezone(timezone.utc).date()))
        days = [day for day in days if day not in stored or day in always]

    for day in days:
        window_from, window_to = utc_day_window(day)
        data, _ = github.query(COUNTS_QUERY, {"from": window_from, "to": window_to})
        rows = plan_daily_rows(user_id, account["id"], day, data, synced_at)
        counts = {row["kind"]: row["count"] for row in rows}
        if counts["unsplit"] > 0:
            if not reads_commits:
                # B's read:user token splits private work by type, so an unsplit lump
                # means that scope is gone. Storing it would overwrite real typed counts.
                raise SyncError(
                    f"Account {config.slot} reports contributions it cannot split by type, "
                    "which means its token lost the read:user scope. Nothing was written "
                    f"for {day.isoformat()} or later; remake the token."
                )
            result.unsplit_days += 1
        supabase.upsert_daily_rows(rows, session)
        result.days_written += 1

    if reads_commits:
        result.commits_written = _sync_commits(
            supabase, github, session, user_id, account["id"], viewer["id"], commit_window, synced_at
        )

    stamp: dict[str, Any] = {"last_synced_at": synced_at}
    expiry = parse_token_expiry(headers.get(EXPIRY_HEADER))
    if expiry:
        stamp["token_expires_at"] = expiry
    supabase.update_account(account["id"], stamp, session)
    return result


def run_sync(
    supabase: Any,
    github_for: Callable[[AccountConfig], GitHubApi],
    session: dict[str, Any],
    accounts: list[AccountConfig],
    now: datetime,
    backfill: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, AccountResult]:
    """Sync every configured account; one failing does not stop the others.

    The trailing dates by default, or every date since BACKFILL_START with `backfill`
    (idempotent and resumable). Raises SyncError afterwards if any account failed, so
    the process exits non-zero. The log carries counts and timings only.
    """
    today = now.astimezone(timezone.utc).date()
    days = backfill_days(today) if backfill else trailing_days(today)
    window = (BACKFILL_START if backfill else days[0], today)

    results: dict[str, AccountResult] = {}
    failed: list[str] = []
    for account in accounts:
        started = monotonic()
        try:
            result = sync_account(
                supabase, github_for(account), session, account, days, window, now, resume=backfill
            )
        except SyncError as error:
            failed.append(account.slot)
            log(f"Account {account.slot}: failed: {error}")
            continue
        except Exception as error:
            # Name the failure without its message, which could quote a request.
            failed.append(account.slot)
            log(f"Account {account.slot}: failed unexpectedly: {type(error).__name__}")
            continue
        results[account.slot] = result
        line = (
            f"Account {account.slot} ({account.detail}): wrote {result.days_written} day(s) "
            f"and {result.commits_written} commit(s) in {monotonic() - started:.1f}s."
        )
        if result.unsplit_days:
            line += (
                f" {result.unsplit_days} day(s) include contributions this token cannot "
                "see into (unsplit)."
            )
        log(line)

    if failed:
        raise SyncError(f"GitHub sync failed for account(s): {', '.join(failed)}.")
    return results


# ── GitHub over HTTP ──────────────────────────────────────────────────────────


def _lowercase_headers(headers: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()} if headers else {}


class GitHubClient:
    """A GraphQL-only client for one account's token.

    It sends nothing but documents defined in this file, so it can only read. The token
    is scrubbed from any text it raises, and response bodies are never echoed: a GraphQL
    error is reported by its type alone.
    """

    def __init__(
        self,
        token: str,
        open_url: Callable[..., Any] = urlopen,
        reserve: int = RATE_LIMIT_RESERVE,
    ) -> None:
        self._token = token
        self._open_url = open_url
        self._reserve = reserve
        self._exhausted = False

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "[token]") if self._token else text

    def query(
        self, document: str, variables: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if self._exhausted:
            raise RateLimited("GitHub rate limit nearly spent; rerun after it resets to resume.")
        request = Request(
            GRAPHQL_URL,
            data=json.dumps({"query": document, "variables": variables or {}}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "personal-observability-github-sync",
            },
            method="POST",
        )
        try:
            with self._open_url(request, timeout=30) as response:
                headers = _lowercase_headers(response.headers)
                raw = response.read()
        except HTTPError as error:
            sent = _lowercase_headers(error.headers)
            limited = "retry-after" in sent or sent.get(REMAINING_HEADER) == "0"
            if error.code == 429 or (error.code == 403 and limited):
                raise RateLimited("GitHub rate limit reached; rerun after it resets to resume.") from None
            raise SyncError(
                f"GitHub request failed (HTTP {error.code}); if this is 401 the token is "
                "expired or revoked."
            ) from None
        except URLError as error:
            raise SyncError(f"Could not reach GitHub: {self._scrub(str(error.reason))}") from None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise SyncError("GitHub returned a response that is not JSON.") from None
        if not isinstance(payload, dict):
            raise SyncError("GitHub returned an unexpected response.")
        if payload.get("errors"):
            errors = payload["errors"] if isinstance(payload["errors"], list) else []
            kinds = sorted({str(e.get("type", "UNKNOWN")) for e in errors if isinstance(e, dict)})
            raise SyncError("GitHub returned GraphQL error type(s): " + (", ".join(kinds) or "UNKNOWN"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SyncError("GitHub returned a response without data.")
        remaining = headers.get(REMAINING_HEADER)
        if remaining is not None and remaining.isdigit() and int(remaining) < self._reserve:
            self._exhausted = True
        return data, headers


# ── configuration ─────────────────────────────────────────────────────────────


def accounts_from_env(values: Mapping[str, str]) -> list[AccountConfig]:
    """The accounts to sync, from GITHUB_{TOKEN,LOGIN,LABEL,DETAIL}_{A,B}.

    Detail defaults to counts_only, so an unset or forgotten setting can never cause
    repository names or commit headlines to be stored. A token needs the login it is
    expected to belong to, and the other way round: a half-configured account is an
    error, not a silent skip, because a skipped account just stops syncing.
    """

    def get(name: str) -> str:
        return str(values.get(name, "")).strip()

    accounts: list[AccountConfig] = []
    for order, slot in enumerate(ACCOUNT_SLOTS):
        token, login = get(f"GITHUB_TOKEN_{slot}"), get(f"GITHUB_LOGIN_{slot}")
        if not token and not login:
            continue
        if not token:
            raise SyncError(f"GITHUB_LOGIN_{slot} is set but GITHUB_TOKEN_{slot} is empty.")
        if not login:
            raise SyncError(
                f"GITHUB_LOGIN_{slot} is required: the login the GITHUB_TOKEN_{slot} must belong to."
            )
        if not LOGIN_PATTERN.match(login):
            raise SyncError(f"GITHUB_LOGIN_{slot} is not a valid GitHub login.")
        detail = get(f"GITHUB_DETAIL_{slot}") or DETAIL_COUNTS_ONLY
        if detail not in (DETAIL_FULL, DETAIL_COUNTS_ONLY):
            raise SyncError(f"GITHUB_DETAIL_{slot} must be 'full' or 'counts_only'.")
        accounts.append(
            AccountConfig(slot, token, login, get(f"GITHUB_LABEL_{slot}") or f"Account {slot}", detail, order)
        )
    if not accounts:
        raise SyncError(
            "No GitHub accounts are configured: set GITHUB_TOKEN_A and GITHUB_LOGIN_A "
            "(and the B pair) in .env.local or the Railway variables."
        )
    return accounts


# ── Supabase, as the app user ─────────────────────────────────────────────────


def docker_host_url(value: str, in_docker: bool) -> str:
    """Make a host-local Supabase URL reachable from the worker container."""
    if not in_docker:
        return value.rstrip("/")

    parsed = urlsplit(value)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return value.rstrip("/")

    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(
        (parsed.scheme, f"host.docker.internal{port}", parsed.path, parsed.query, parsed.fragment)
    ).rstrip("/")


def validate_railway_volume(session_path: Path) -> None:
    """Refuse a Railway run that would lose the app session after the container exits."""
    if not os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return

    raw_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if not raw_mount:
        raise SyncError("Railway requires a persistent volume mounted at /data.")

    mount = Path(raw_mount).resolve()
    try:
        session_path.resolve().relative_to(mount)
    except ValueError as error:
        message = f"SUPABASE_SESSION_FILE must be stored below the Railway volume at {mount}."
        raise SyncError(message) from error


def _error_message(error: HTTPError) -> str:
    """The `message` of a Supabase error body, and nothing else from it.

    PostgREST puts the offending row in `details`. For these tables that is a repository
    name or a commit headline, and this text reaches the run log, so a body without a
    message is reported as such rather than echoed.
    """
    try:
        parsed = json.loads(error.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return "no message in the response"
    if isinstance(parsed, dict):
        for key in ("message", "msg", "error_description"):
            if isinstance(parsed.get(key), str) and parsed[key]:
                return parsed[key]
    return "no message in the response"


class SupabaseSession:
    """The app user session and the github_* writes made with it.

    Every call goes out with the user access token and the publishable key, so Row
    Level Security applies to it exactly as it does in the browser.
    """

    def __init__(self, base_url: str, publishable_key: str, session_file: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.publishable_key = publishable_key
        self.session_file = session_file

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        access_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"apikey": self.publishable_key, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if extra_headers:
            headers.update(extra_headers)

        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        # Connection-level failures are retried: the Docker Desktop host gateway drops
        # the odd connection, and a backfill makes hundreds of requests. Every call here
        # is idempotent, and an HTTP error response is a real answer, never retried.
        for attempt in range(CONNECTION_ATTEMPTS):
            try:
                with urlopen(request, timeout=30) as response:
                    raw = response.read()
                break
            except HTTPError as error:
                raise SyncError(
                    f"Supabase request failed ({error.code}): {_error_message(error)}"
                ) from error
            except URLError as error:
                if attempt == CONNECTION_ATTEMPTS - 1:
                    raise SyncError(f"Could not reach Supabase at {self.base_url}: {error.reason}") from error
                sleep(CONNECTION_BACKOFF_SECONDS * (attempt + 1))

        return json.loads(raw) if raw else None

    def _save(self, session: dict[str, Any]) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.session_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(session), encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(self.session_file)

    def login(self, email: str, password: str) -> dict[str, Any]:
        session = self._request(
            "POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password}
        )
        if not isinstance(session, dict) or not session.get("refresh_token"):
            raise SyncError("Supabase login succeeded without returning a reusable session.")
        self._save(session)
        return session

    def load(self) -> dict[str, Any]:
        if not self.session_file.exists():
            raise SyncError("App session is missing. Run the GitHub setup command first.")
        try:
            session = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SyncError("The cached app session is unreadable. Run setup again.") from error
        if not isinstance(session, dict):
            raise SyncError("The cached app session is invalid. Run setup again.")
        return session

    def active(self) -> dict[str, Any]:
        session = self.load()
        expires_at = session.get("expires_at", 0)
        if isinstance(expires_at, (int, float)) and expires_at > unix_time() + 60:
            return session

        refresh_token = session.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise SyncError("The app refresh token is missing. Run setup again.")
        refreshed = self._request(
            "POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": refresh_token}
        )
        if not isinstance(refreshed, dict):
            raise SyncError("Supabase did not return a valid refreshed session.")
        self._save(refreshed)
        return refreshed

    @staticmethod
    def _token(session: dict[str, Any]) -> str:
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SyncError("The cached app access token is missing. Run setup again.")
        return access_token

    def _rest(
        self,
        method: str,
        table: str,
        session: dict[str, Any],
        query: list[tuple[str, str]],
        payload: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        path = f"/rest/v1/{table}"
        if query:
            path += "?" + urlencode(query, safe=",:.")
        return self._request(
            method,
            path,
            payload,
            access_token=self._token(session),
            extra_headers={"Prefer": prefer} if prefer else None,
        )

    def find_account(self, login: str, session: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._rest(
            "GET",
            "github_accounts",
            session,
            [
                ("select", "*"),
                ("user_id", f"eq.{user_id_of(session)}"),
                ("login", f"ilike.{login}"),
                ("limit", "1"),
            ],
        )
        return rows[0] if isinstance(rows, list) and rows else None

    def find_account_by_github_user_id(
        self, github_user_id: int, session: dict[str, Any]
    ) -> dict[str, Any] | None:
        rows = self._rest(
            "GET",
            "github_accounts",
            session,
            [
                ("select", "*"),
                ("user_id", f"eq.{user_id_of(session)}"),
                ("github_user_id", f"eq.{github_user_id}"),
                ("limit", "1"),
            ],
        )
        return rows[0] if isinstance(rows, list) and rows else None

    def create_account(self, row: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        created = self._rest("POST", "github_accounts", session, [], row, prefer="return=representation")
        created = created[0] if isinstance(created, list) and created else created
        if not isinstance(created, dict) or not created.get("id"):
            raise SyncError("Supabase did not return the new GitHub account row.")
        return created

    def update_account(self, account_id: str, fields: dict[str, Any], session: dict[str, Any]) -> None:
        self._rest(
            "PATCH", "github_accounts", session, [("id", f"eq.{account_id}")], fields, prefer="return=minimal"
        )

    def stored_days(
        self, account_id: str, first: date, last: date, session: dict[str, Any]
    ) -> set[date]:
        """Dates that already have counts. One kind per date is enough: all five kinds
        of a date go in together, in one request."""
        rows = self._rest(
            "GET",
            "github_daily_contributions",
            session,
            [
                ("select", "local_day"),
                ("account_id", f"eq.{account_id}"),
                ("kind", "eq.commit"),
                ("local_day", f"gte.{first.isoformat()}"),
                ("local_day", f"lte.{last.isoformat()}"),
                ("limit", str(STORED_DAYS_LIMIT)),
            ],
        )
        days: set[date] = set()
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get("local_day"), str):
                days.add(date.fromisoformat(row["local_day"]))
        return days

    def upsert_daily_rows(self, rows: list[dict[str, Any]], session: dict[str, Any]) -> None:
        self._rest(
            "POST",
            "github_daily_contributions",
            session,
            [("on_conflict", "user_id,account_id,local_day,kind")],
            rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def upsert_commit_rows(self, rows: list[dict[str, Any]], session: dict[str, Any]) -> None:
        for start in range(0, len(rows), COMMIT_BATCH):
            self._rest(
                "POST",
                "github_commits",
                session,
                [("on_conflict", "user_id,account_id,repo_node_id,oid")],
                rows[start : start + COMMIT_BATCH],
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def delete_commits(self, account_id: str, session: dict[str, Any]) -> None:
        self._rest(
            "DELETE", "github_commits", session, [("account_id", f"eq.{account_id}")], prefer="return=minimal"
        )


def configuration() -> SupabaseSession:
    raw_url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not raw_url or not key:
        raise SyncError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required in .env.local.")

    in_docker = os.getenv("GITHUB_SYNC_IN_DOCKER", "").lower() == "true"
    base_url = docker_host_url(raw_url, in_docker)
    session_path = Path(os.getenv("SUPABASE_SESSION_FILE", "/data/supabase-session.json"))
    validate_railway_volume(session_path)
    return SupabaseSession(base_url, key, session_path)


def session_for_sync(supabase: Any) -> dict[str, Any]:
    """Use dedicated runtime credentials when configured, otherwise reuse the cache."""
    app_email = os.getenv("PERSONAL_OBSERVABILITY_APP_EMAIL", "").strip()
    app_password = os.getenv("PERSONAL_OBSERVABILITY_APP_PASSWORD", "")
    if bool(app_email) != bool(app_password):
        raise SyncError(
            "PERSONAL_OBSERVABILITY_APP_EMAIL and "
            "PERSONAL_OBSERVABILITY_APP_PASSWORD must be configured together."
        )
    if app_email and app_password:
        return supabase.login(app_email, app_password)
    return supabase.active()


# ── commands ──────────────────────────────────────────────────────────────────


def setup() -> None:
    supabase = configuration()
    print("Sign in to the Personal Observability app account.")
    app_email = input("App email: ").strip()
    app_password = getpass.getpass("App password: ")
    try:
        session = supabase.login(app_email, app_password)
    finally:
        del app_password

    user = session.get("user")
    identity = user.get("email") if isinstance(user, dict) else app_email
    print(f"Setup complete for {identity}.")
    for slot in ACCOUNT_SLOTS:
        state = "configured" if os.getenv(f"GITHUB_TOKEN_{slot}", "").strip() else "missing"
        print(f"GitHub token {slot}: {state}.")


def run_from_environment(backfill: bool) -> None:
    """Sync every account configured in the environment, as the cached or configured app user."""
    supabase = configuration()
    accounts = accounts_from_env(os.environ)
    session = session_for_sync(supabase)
    run_sync(
        supabase,
        lambda account: GitHubClient(account.token),
        session,
        accounts,
        datetime.now(timezone.utc),
        backfill=backfill,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync GitHub contribution counts into Personal Observability."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup", help="Sign in once to the app and store its session.")
    subcommands.add_parser("sync", help="Refetch the trailing 14 UTC dates for every account.")
    subcommands.add_parser(
        "backfill", help=f"Load every UTC date since {BACKFILL_START.isoformat()}. Safe to rerun."
    )
    subcommands.add_parser("test", help="Run the worker unit tests.")
    args = parser.parse_args(argv)

    try:
        if args.command == "setup":
            setup()
        elif args.command == "sync":
            run_from_environment(backfill=False)
        elif args.command == "backfill":
            run_from_environment(backfill=True)
        else:
            suite = unittest.defaultTestLoader.discover(
                str(Path(__file__).parent), pattern="test_github_sync.py"
            )
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    except (SyncError, KeyboardInterrupt) as error:
        message = "Cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except Exception as error:
        # Name the failure without its message, which could quote a request.
        print(f"GitHub sync failed unexpectedly: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
