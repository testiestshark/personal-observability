# GitHub activity across two accounts — research

Status: research only (2026-09-23). No code, migrations or GitHub configuration exist.
Builds on [GITHUB.md](GITHUB.md) (Milestone 1, "Connect GitHub", parked) — read §0
below for where this note agrees and where it departs from that plan.

The owner's question: how to bring GitHub activity — commits, short summaries, a total
for the day — into the app, for **two separate GitHub accounts** (called account A and
account B here), shown in one combined view that still keeps the accounts clearly apart.

Sources are primary (docs.github.com, the published GitHub GraphQL schema, the GitHub
changelog, supabase.com). Numbered references like [S4] point to the list at the end.
Anything not confirmed in a primary source is marked **unverified**.

---

## Summary and recommendation

1. **Read activity with a per-account token from a scheduled Railway worker**, the same
   shape as the Garmin sync ([RAILWAY.md](RAILWAY.md), [GARMIN.md](GARMIN.md)): one
   `github-sync` service, hourly, signs in to Supabase as the app user and writes
   through RLS. No `service_role`, no browser tokens, no dependency on hosted login
   (which is parked).
2. **Use the GraphQL API**, two calls per account per run:
   - find recently pushed repositories (`viewer.repositories(orderBy: PUSHED_AT)`), then
   - for each, read default-branch history filtered to that user
     (`history(author: {id}, since, until)`), which returns `oid`, `messageHeadline`,
     `authoredDate`, `author.date` and more [S4].
     Optionally also store `contributionsCollection.contributionCalendar` per day as
     "GitHub's own count" for a heatmap and cross-check [S4].
3. **Count "today" ourselves from commit author timestamps, bucketed in
   `Europe/London`** — the timezone the rest of the app already uses. Do not treat
   GitHub's contribution calendar as the source of "today": the docs give conflicting
   descriptions of how it buckets days (§4), and it can lag by up to 24 hours [S3].
4. **Auth: one personal access token per account, held only in Railway variables.**
   Fine-grained (read-only) if all that account's work is in repos it owns; classic
   with `repo` if it commits to organisation or collaborator repos, because a
   fine-grained token is limited to a single resource owner and cannot reach repos
   where the user is an outside collaborator [S12]. A GitHub App (GITHUB.md's plan)
   only reaches accounts/orgs where the app is **installed** [S15], which is a poor fit
   for "everything I committed, wherever".
5. **Schema:** `github_accounts` (no tokens) + `github_commits` keyed by account and
   commit, both on the standard ownership/RLS pattern. Combined totals count
   **distinct commit SHAs**, so a commit attributed to both accounts (e.g. a
   co-authored one) is counted once in the headline but shown under each account.
6. **UI:** fill the existing "Making" placeholder on Today with a combined headline,
   a two-colour segmented bar, and a per-account column/list; a stacked 7/30-day bar
   chart for history. Account colour and label are the identity cue everywhere.

---

## 0. Relationship to GITHUB.md (Milestone 1)

| GITHUB.md says                                                               | This note                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GitHub is an integration provider, not a login provider (§4)                 | Agree.                                                                                                                                                                                                                                                                                                                                    |
| Two GitHub accounts → two connection rows (§11)                              | Agree; `github_accounts` below is the same idea.                                                                                                                                                                                                                                                                                          |
| Connect via a private **GitHub App** installation + callback route (§2–§5)   | **Departs for data reading.** Installation access only covers accounts/orgs where the app is installed, and user-to-server tokens have the same limit [S15]. Reading "my commits across repos I don't own" needs the app installed on every org involved. PATs avoid that, and avoid 8-hour token / 6-month refresh-token rotation [S14]. |
| Callback runs in the TanStack Start server; writes via service role (§3, §7) | Not needed for the PAT route: the worker writes as the signed-in app user, like Garmin. (ARCHITECTURE.md already bans `service_role` in application code.)                                                                                                                                                                                |
| Blocked on PO login (§1, §14)                                                | The worker route does not use the hosted browser login flow; the Garmin worker already authenticates to hosted Supabase directly.                                                                                                                                                                                                         |

The GitHub App path is not wrong — it is the better choice if this ever becomes
multi-user, or if the owner wants a "Connect" button in the UI. For one owner with two
accounts, it is more machinery than the job needs. **Owner decision** (see §8).

---

## 1. Ways to get per-day activity, compared

| Option                                                                                          | What you get                                                                                                                                                                                                                                                                               | Limits that matter                                                                                                                                                                                                                                                                                                                                                                                              | Verdict                                                                                            |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **GraphQL `user.contributionsCollection(from, to)`**                                            | `contributionCalendar.weeks[].contributionDays[]` with `date` + `contributionCount`; `totalCommitContributions`; `commitContributionsByRepository(maxRepositories: 25 default)` → per-repo, per-day `commitCount` + `occurredAt`; `restrictedContributionsCount` [S4]. No commit messages. | `from` defaults to a year ago; `to` defaults to now or one year after `from` [S4]. A hard 1-year max span is widely reported but **unverified** in the docs. Only contributions that meet GitHub's rules count: default or `gh-pages` branch, not a fork, linked email, and collaborator/member/forked/opened-PR-or-issue [S1]. Up to 24 h to appear [S3]. The maximum for `maxRepositories` is **unverified**. | Good for a heatmap and GitHub's official daily count. Not for messages or a precise local "today". |
| **GraphQL `Repository.defaultBranchRef…history(author: {id \| emails}, since, until)`**         | Real commits: `oid`, `messageHeadline`, `message`, `authoredDate` (UTC), `committedDate` (UTC), `author { date, email, user }` where `author.date` is a `GitTimestamp` **not converted to UTC**, `authors` (includes `Co-authored-by`), `additions`, `deletions` [S4].                     | Needs a list of repos to ask about. `first`/`last` 1–100 per page [S11]. Whether `since`/`until` filter on author or committer date is **unverified** — overlap the window and filter on `authoredDate` in code.                                                                                                                                                                                                | **Recommended** for commits and summaries.                                                         |
| **GraphQL `viewer.repositories(affiliations, ownerAffiliations, orderBy: {field: PUSHED_AT})`** | The repos the token's user owns, collaborates on, or reaches through org membership, most recently pushed first, each with `pushedAt` [S4].                                                                                                                                                | Only repos the token can see.                                                                                                                                                                                                                                                                                                                                                                                   | **Recommended** for choosing which repos to read `history` from.                                   |
| **REST Events API** (`GET /users/{username}/events`)                                            | Push/PR/issue events; private events if authenticated as that user [S5].                                                                                                                                                                                                                   | Up to 300 events, **30 days** only (cut from 90 days on 2025-01-30) [S5][S6]. Latency 30 s–6 h, "not built to serve real-time use cases" [S5]. Commit summaries and counts were **removed from push events** from 2025-10-07 [S7].                                                                                                                                                                              | Not suitable. (The "90 days" figure you'll see quoted is out of date.)                             |
| **REST Search commits** (`GET /search/commits?q=author:… author-date:…`)                        | Commits across repos in one query.                                                                                                                                                                                                                                                         | 30 requests/minute; up to 1,000 results per search; default branch only [S8]. Private-repo coverage depends on token access [S8].                                                                                                                                                                                                                                                                               | Workable fallback; a less direct fit than GraphQL.                                                 |
| **REST List commits** (`GET /repos/{owner}/{repo}/commits?author=&since=&until=`)               | Commits per repo; `author` accepts a username or email [S9].                                                                                                                                                                                                                               | Per repo; `per_page` max 100 [S9]. The docs describe `since` as "last updated after", not author date [S9].                                                                                                                                                                                                                                                                                                     | Equivalent to GraphQL `history`, but more calls.                                                   |
| **Webhooks** (`push`)                                                                           | Real-time pushes.                                                                                                                                                                                                                                                                          | Needs a public endpoint and an app or hook on every repo/org. GITHUB.md already defers webhooks (§13).                                                                                                                                                                                                                                                                                                          | Not now.                                                                                           |

**Private activity, and what a token sees.** If a token cannot access a private repo,
its contributions are not itemised. They show up only as `restrictedContributionsCount`,
which is "only non-zero when the user has chosen to share their private contribution
counts" [S4] — the profile's _Private contributions_ setting, which shows other people
daily counts without details [S17]. So:

- To get **messages and repo names**, the token must be able to read the repo.
- If a token cannot reach some repos (e.g. an org blocks PATs), turning on "Private
  contributions" for that account still gets **counts** through the calendar.

---

## 2. Authentication, per account

| Mechanism                                   | Reach                                                                                                                                                                                                                                                                                                                                                                                                        | Fit                                                                                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fine-grained PAT**                        | "Each token is limited to access resources owned by a single user or organization"; cannot be used for repos where the user is an outside or repository collaborator [S12]. Org owners may block fine-grained PATs or require approval for each one [S13].                                                                                                                                                   | Best for an account whose commits are all in **its own repos**: read-only (`Contents: read`, `Metadata: read`), expiring, least privilege.                    |
| **Classic PAT** (`repo`, `user:email`)      | `repo` grants access to "all repositories within the organizations that you have access to, as well as all personal repositories" [S12]; `repo` "grants full access to public and private repositories including read and write access to code" and no read-only private-repo scope exists [S20]; `user:email` is needed for `GET /user/emails` [S16]. Orgs can block classic PATs from org resources [S13]. | Needed if the account commits to **org or collaborator repos**. Broader than required — accept it deliberately, or don't.                                     |
| **GitHub App** (installation or user token) | Limited to accounts/orgs where the app is installed, to what the user can access, and to the app's permissions [S15]. User tokens expire after 8 h; refresh tokens after 6 months [S14].                                                                                                                                                                                                                     | GITHUB.md's plan. Right for a multi-user product; heavier here (org installs, and refresh-token rotation needs persistent worker state like Garmin's volume). |
| OAuth App                                   | Classic-style scopes.                                                                                                                                                                                                                                                                                                                                                                                        | No advantage over a PAT for a single owner.                                                                                                                   |

**Recommendation:** one token per account, chosen per account by where that account
commits. It is quite likely account B is a work/organisation account — in that case,
check whether the org allows PATs at all [S13] before building anything. **Unverified
here:** SAML-SSO orgs may also require a token to be SSO-authorised; [S13] does not
cover it.

**Where tokens live.** Railway service variables, and `.env.local` for local runs —
the same policy HEVY.md sets for the Hevy key and RAILWAY.md for Garmin. Never in the
database, browser code, `.env.example` (names only), logs or chat. Supabase Vault stores
secrets encrypted on disk, but anyone who can read `vault.decrypted_secrets` can read
them [S19]. It would only earn its place if a Postgres-side job (pg_cron/Edge Function)
did the fetching, which this repo doesn't do.

**Stop a token being used for the wrong account.** At the start of each run, the
worker should query `viewer { login databaseId }` and refuse to write if it doesn't
match the `github_accounts` row the token is configured for.

---

## 3. Two accounts: attribution and dedup

- **Attribution is by author email.** A commit counts for an account only if its email
  is associated with that account [S1][S3]. Commits from an unlinked email (e.g. a work
  laptop's default) are invisible to the contribution graph and to
  `history(author: {id})`. The fix is on GitHub: add the email to the right account
  [S3]. `GET /user/emails` shows each account's addresses and `verified` flags [S16] —
  worth showing in Settings so a misconfigured machine is easy to spot. It is
  **unverified** in the docs fetched that GitHub stops one email being added to two
  accounts; the design should not rely on it.
- **One commit, two accounts.** This happens when both accounts are authors
  (`Co-authored-by`, which `Commit.authors` lists [S4]; co-authors need an associated
  email to get credit [S18]), and possibly for rebased commits, where both the original
  author and the rebaser get credit [S1]. Whether `history(author: {id})` also matches
  co-authors is **unverified**.
- **Rule:** store one row per `(account, repo, oid)`. For per-account figures, count
  that account's rows. For the combined headline, count
  `DISTINCT oid` across both accounts. The UI can mark shared commits
  ("also on account B").
- **Same commit in two repos** (mirrors, or fork and upstream): contributions in forks
  don't count [S1], and deduping on `oid` handles the rest.
- **Default branch only.** Feature-branch commits don't count until merged [S1][S3].
  Squash merges replace the individual commits with one — **unverified** what author
  and date GitHub gives the squashed commit. Default-branch-only matches GitHub's own
  numbers; reading every branch costs more and needs `oid` dedup. **Owner decision.**

---

## 4. Timezones — how to get "today" right

What the sources say:

- GraphQL `DateTime` is "An ISO-8601 encoded UTC date string"; `GitTimestamp` is "not
  converted in UTC" [S4]. So `Commit.authoredDate` / `committedDate` are UTC instants,
  and `Commit.author.date` keeps the offset the commit was written with.
- The profile docs disagree with each other: "Contributions are timestamped according
  to Coordinated Universal Time (UTC) rather than your local time zone" [S2], but also
  "Commits use the time zone information in the commit timestamp" [S1].
  `ContributionCalendarDay.date` is a plain `Date` [S4]. **How the calendar buckets a
  late-evening BST commit is unverified**, which is why it is not the source of truth for
  "today".
- The profile uses the **author date**; repository views use the commit date [S1].
  Rebasing and amending change the committer date but keep the author date. **Use the
  author date.**

Recommended rule, in line with the app's existing `Europe/London` convention
(`src/lib/weight/units.ts`, `src/lib/health/format.ts`):

```text
local_day = (authoredDate :: timestamptz AT TIME ZONE 'Europe/London')::date
```

- Worked example: a commit at 00:30 BST on 24 Sep is `2026-09-23T23:30:00Z` in UTC. It
  belongs to **24 Sep** locally, while a UTC calendar puts it on 23 Sep.
- Queries for "today" use the UTC window [local midnight, next local midnight). On DST
  change days that window is 23 or 25 hours long. Build it with a tested helper that
  goes through the timezone, never `+24h`.
- Store `local_day` when the worker writes each row (a pure, unit-tested function), or
  compute it in a view. `AT TIME ZONE` is STABLE, not IMMUTABLE, so it cannot go in a
  generated column — the same issue noted in
  `src/lib/weight/weight.functions.ts`.
- Keep the raw `author.date` string (with its original offset) too. Then a later "bucket
  by the commit's own local time when travelling" decision can be applied without
  refetching.
- Test cases worth writing: 23:30 and 00:30 either side of midnight in BST and in GMT;
  both DST transition days; a commit whose `author.date` offset differs from London's.

---

## 5. Rate limits and sync cadence

- GraphQL: 5,000 points/hour per user. A query's cost is roughly (requests needed for
  each connection, at its `first` limit) ÷ 100, minimum 1. `first`/`last` must be 1–100,
  and there is a 500,000-node cap per call. Secondary limits: 100 concurrent requests
  and 2,000 points/minute. Requests over 10 s time out [S11].
- REST: 5,000/hour for PATs; secondary limit 900 points/minute; Search is 30/minute
  [S10][S8].
- Each token has its own user budget [S10][S11], so the two accounts don't share one.

Cadence: **hourly** (e.g. `15 * * * *`, offset from Garmin's `:05`). Each run, per
account:

1. `viewer.repositories(first: 50, orderBy: {field: PUSHED_AT, direction: DESC})`,
   stopping at repos whose `pushedAt` is older than the window.
2. One aliased query batching `history(author: {id}, since: now-14d, first: 100)` for
   each of those repos.
3. Upsert on `(user_id, account_id, repo_id, oid)`.
4. Optionally, `contributionsCollection(from: now-14d)` for the calendar.

That is a handful of points per hour against 5,000. The trailing 14-day window fixes
itself the way Garmin's 7-day refetch does, and covers late pushes and the calendar's
24-hour lag [S3]. **Backfill** once, per account, a year at a time using `contributionYears`
[S4] and per-repo `history`.

---

## 6. Data model sketch (not a migration)

Both tables follow [supabase/README.md](../../supabase/README.md) exactly:
`user_id uuid not null references auth.users on delete cascade`, index on `user_id`,
RLS on, `revoke all … from anon`, grant to `authenticated`, and the four `… own`
policies. The worker writes as the app user (Garmin pattern), so all four are needed.
The mandatory anon/second-account check in ARCHITECTURE.md applies to each.

```sql
-- One row per connected GitHub account. No credentials here.
create table public.github_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  github_user_id bigint not null,      -- User.databaseId
  github_node_id text not null,        -- User.id, used for history(author: {id})
  login text not null,
  label text not null,                 -- owner-chosen, e.g. 'Personal', 'Work'
  display_order smallint not null default 0,
  created_at timestamptz not null default now(),
  unique (user_id, github_user_id)
);

-- One row per (account, repo, commit). Combined views count DISTINCT oid.
create table public.github_commits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  account_id uuid not null references public.github_accounts (id) on delete cascade,
  repo_node_id text not null,
  repo_name_with_owner text not null,
  repo_is_private boolean not null,
  oid text not null,
  message_headline text not null,
  authored_at timestamptz not null,    -- Commit.authoredDate (UTC)
  author_date_raw text,                -- Commit.author.date, original offset kept
  committed_at timestamptz not null,
  local_day date not null,             -- Europe/London, computed by the worker
  additions integer,
  deletions integer,
  synced_at timestamptz not null default now(),
  unique (user_id, account_id, repo_node_id, oid)
);
create index github_commits_user_day_idx on public.github_commits (user_id, local_day desc);

-- Optional: GitHub's own daily count, as GitHub buckets it (see §4).
create table public.github_daily_contributions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  account_id uuid not null references public.github_accounts (id) on delete cascade,
  github_date date not null,           -- ContributionCalendarDay.date, as GitHub gives it
  contribution_count integer not null check (contribution_count >= 0),
  synced_at timestamptz not null default now(),
  unique (user_id, account_id, github_date)
);
```

Notes:

- Store only `messageHeadline`, not the full body: it's enough for a summary and keeps
  less of a possibly-employer repo in a personal database. See §8.
- `github_daily_contributions` counts issues, PRs and reviews too, not just commits.
  Label it "GitHub contributions", never "commits".
- An "account" is a connected GitHub user. GitHub.md's `github_installations` table
  would sit alongside this if the App route is ever built. CONTEXT.md should get the
  terms **GitHub account**, **commit (local day)** and **GitHub contribution** once
  this is decided.

---

## 7. UI: combined, but clearly separate

It fits what's there: the **"Making"** placeholder on Today (`src/routes/index.tsx`,
"Commits across both GitHub accounts") and the two "GitHub — account one/two" rows on
Integrations (`src/routes/integrations.tsx`).

- **Today → "Making" card** (same card style as the Garmin sections):
  - Headline: **combined distinct commits today**, e.g. "7 commits".
  - Directly under it, a **two-segment bar** — account A in one colour, account B in
    another — with the per-account number and label beside each segment ("Personal 5 ·
    Work 2"). A shared commit is counted once in the headline and shown under each
    account.
  - Then **two columns (stacked on mobile), one per account**, each headed by its
    label, login and colour dot. Each lists that day's commits: local time,
    `owner/repo`, message headline. Private repos get a lock icon, and the list can
    collapse to "N commits in M repos".
  - Empty state for each account separately ("No commits on Work today"), so
    "quiet" and "not synced" are never confused. Show each account's last sync time in
    the same chip as Garmin's.
- **History (Timeline/Insights):** a 7- or 30-day **stacked bar** with one series per
  account, on the existing chart component (`src/components/ui/chart.tsx`, as used by
  `weight-trend.tsx`). Optionally a GitHub-style heatmap per account, from
  `github_daily_contributions`, labelled as GitHub's count.
- **Colour:** two fixed series colours set as theme tokens, and the same colour for an
  account everywhere. Always pair colour with a text label (not colour alone).
- **Summaries:** for the first version, "summary" means counts + repos + headlines.
  An LLM-written daily or monthly narrative is already listed in
  [future-possibilities.md](../future-possibilities.md); it can read from
  `github_commits` later.

---

## 8. Open questions for the owner

1. **PAT route vs GitHub App route.** Do you accept per-account tokens in Railway (this
   note), in place of GITHUB.md's GitHub App "Connect" flow for reading data? If yes,
   GITHUB.md Milestone 1 should be re-scoped or marked superseded.
2. **What is account B?** If it commits to an employer's org: does the org allow PATs
   [S13], is it SAML-protected, and are you comfortable copying repo names and commit
   headlines into this app? The alternative is **counts only** for that account (turn on
   Private contributions [S17] and read just the calendar with a no-scope token).
3. **Classic `repo` scope** (read **and write** to everything) — acceptable for either
   account, or fine-grained only, with whatever coverage that gives?
4. **Default branch only** (matches GitHub, cheaper) or **all branches** (counts
   unmerged work)?
5. **"Today" timezone:** always `Europe/London` (recommended, matches the rest of the
   app), or the commit's own offset when travelling?
6. **What counts as activity:** commits only, or also PRs opened, reviews and issues
   (available from `contributionsCollection` [S4])?
7. **Backfill depth:** how many years of history?

---

## Sources

- [S1] GitHub Docs — Profile contributions reference: https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference
- [S2] GitHub Docs — Contributions on your profile: https://docs.github.com/en/account-and-profile/concepts/contributions-on-your-profile
- [S3] GitHub Docs — Troubleshooting missing contributions: https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions
- [S4] GitHub GraphQL public schema (`ContributionsCollection`, `ContributionCalendarDay`, `CreatedCommitContribution`, `CommitContributionsByRepository`, `User.contributionsCollection`, `User.repositories`, `Commit`, `CommitAuthor`, `DateTime`, `GitTimestamp`): https://docs.github.com/public/fpt/schema.docs.graphql — rendered at https://docs.github.com/en/graphql/reference/objects#contributionscollection
- [S5] GitHub Docs — REST API endpoints for events: https://docs.github.com/en/rest/activity/events
- [S6] GitHub Changelog, 2024-11-08 — Events API retention reduced from 90 to 30 days on 2025-01-30: https://github.blog/changelog/2024-11-08-upcoming-changes-to-data-retention-for-events-api-atom-feed-timeline-and-dashboard-feed-features/
- [S7] GitHub Changelog, 2025-08-08 — Events API payload changes (push-event commit summaries/counts removed, effective 2025-10-07): https://github.blog/changelog/2025-08-08-upcoming-changes-to-github-events-api-payloads/
- [S8] GitHub Docs — Search commits: https://docs.github.com/en/rest/search/search#search-commits
- [S9] GitHub Docs — List commits: https://docs.github.com/en/rest/commits/commits#list-commits
- [S10] GitHub Docs — Rate limits for the REST API: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- [S11] GitHub Docs — Rate limits and query limits for the GraphQL API: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
- [S12] GitHub Docs — Managing your personal access tokens: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- [S13] GitHub Docs — Setting a personal access token policy for your organization: https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization
- [S14] GitHub Docs — Generating a user access token for a GitHub App: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
- [S15] GitHub Docs — Authenticating with a GitHub App on behalf of a user: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user
- [S16] GitHub Docs — List email addresses for the authenticated user: https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user
- [S17] GitHub Docs — Manage visibility settings for private contributions: https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/showing-your-private-contributions-and-achievements-on-your-profile
- [S18] GitHub Docs — Creating a commit with multiple authors: https://docs.github.com/en/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/creating-a-commit-with-multiple-authors
- [S19] Supabase Docs — Vault: https://supabase.com/docs/guides/database/vault
- [S20] GitHub Docs — Scopes for OAuth apps (classic PAT scopes): https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
