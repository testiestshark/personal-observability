# GitHub integration — Milestone 1: Connect GitHub

Status: design only and parked. No code, migrations, or GitHub configuration exist
yet.

## 1. Milestone definition

**Will do:**

- Add a "Connect GitHub" affordance (Integrations page, possibly mirrored in Settings).
- Let the user install a private GitHub App on a GitHub account (personal or org) they choose during GitHub's own installation UI.
- Handle the return trip from GitHub, verify it, and durably persist that a GitHub App installation is associated with the current Personal Observability (PO) user.
- Show "Connected as [GitHub account login]" — persisted, i.e. still shown after a full page refresh, browser restart, etc.

**Will not do (this milestone):**

- Fetch, store, or display any commits, repositories, pull requests, issues, or other GitHub activity.
- Handle GitHub webhooks (push, installation events, etc.).
- Generate or persist installation access tokens (short-lived, data-fetching tokens) — only the durable `installation_id` is captured now.
- Build a "disconnect" flow, org-specific handling beyond what naturally falls out of the design, or any UI for repository selection (GitHub hosts that itself).
- Implement Personal Observability's own login system, if it doesn't already exist (see §14 — this is a dependency, not part of this milestone, but it blocks it).

**Acceptance criteria:**

1. An authenticated PO user with no existing GitHub connection sees "Connect GitHub" in Integrations.
2. Clicking it takes them to GitHub's installation UI for the PO GitHub App.
3. After installing (any repo selection), GitHub redirects back to PO.
4. PO verifies the redirect, looks up the installation's account login via the GitHub App's own API credentials (not a per-user token), and persists `(user, installation_id, github_account_login, ...)`.
5. The user lands back on Integrations/Settings seeing "Connected as `<login>`".
6. Refreshing the page (or returning in a new session) still shows "Connected as `<login>`" — this is a database-backed fact, not client-only state.
7. No commit, repo, or activity data has been fetched or stored anywhere.

## 2. User journey

```
Settings/Integrations
  └─ "Connect GitHub" button (only shown if not already connected)
       └─ browser navigates to a PO server route: GET /integrations/github/connect
            └─ server generates a signed, short-lived `state` bound to the current PO session
            └─ redirects browser to:
               https://github.com/apps/<app-slug>/installations/new?state=<state>
                    └─ GitHub shows its own installation UI (choose account, choose repos)
                    └─ user installs (or cancels)
                    └─ GitHub redirects browser to the App's configured Setup URL:
                       GET /integrations/github/callback?installation_id=...&setup_action=install&state=...
                            └─ PO server verifies `state` (see §9)
                            └─ PO server calls GitHub API (App JWT) to fetch installation → account login
                            └─ PO server upserts a row scoped to the PO user
                            └─ redirects browser to a fixed internal path: /integrations
  └─ Integrations page (server-rendered / loader) reads the row for the current user
       └─ shows "Connected as <login>" (persists across refresh, since it's a DB read, not client state)
```

What the user sees at each stage: a normal button → GitHub's own hosted installation screens (PO never renders GitHub's UI) → a brief redirect through PO's own domain (no visible PO page in between, ideally sub-second) → landing back on Integrations already showing the connected state.

## 3. System flow

Responsibilities:

- **Browser frontend** — renders "Connect GitHub" as a plain link/anchor to the connect route (not a `fetch`/RPC call, since GitHub must ultimately navigate the top-level browser). Never touches installation IDs, tokens, or secrets directly. Reads connection status only via server-rendered data (loader), never by calling GitHub directly.
- **TanStack Start server layer** — owns both new routes (`connect`, `callback`) as server-side route handlers, in the same runtime as `client.server.ts`/`auth-middleware.ts` today. Signs/verifies `state`, holds the GitHub App private key and calls the GitHub API, performs the DB upsert via the service-role client.
- **Supabase Auth** — establishes _who the PO user is_ (see §4). The connect route must run behind `requireSupabaseAuth`-equivalent session validation so the state can be bound to a real user.
- **Server-side callback handler** — see recommendation below.
- **PostgreSQL** — stores exactly one durable fact per connection: which PO user, which GitHub installation, which account login. RLS-protected (see §7).
- **GitHub App** — hosts the installation UI, issues the `installation_id`, and (via the app-level JWT) answers "what account is installation X for."
- **GitHub installation callback** — GitHub's redirect back to PO's Setup URL; this is a browser navigation with query params, not a webhook POST.

**Text sequence diagram:**

```
Browser          PO server (TanStack Start)         GitHub                 Postgres
  |  click Connect        |                            |                       |
  |----------------------->|                            |                       |
  |                        | verify PO session           |                       |
  |                        | generate signed state        |                       |
  |<-----------------------| 302 -> github.com/apps/.../installations/new?state |
  |------------------------------------------------------->|                       |
  |                        |                            | install UI (GitHub-hosted)
  |                        |                            | user installs         |
  |<-------------------------------------------------------| 302 -> /integrations/github/callback?installation_id&setup_action&state
  |----------------------->|                            |                       |
  |                        | verify state (sig+expiry+user match)                |
  |                        | sign App JWT                |                       |
  |                        |--------------------------->| GET /app/installations/{id}
  |                        |<---------------------------| { account: { login, id, type } }
  |                        | upsert (user_id, installation_id, account...)       |
  |                        |----------------------------------------------------->|
  |                        |<-----------------------------------------------------|
  |<-----------------------| 302 -> /integrations       |                       |
  |  GET /integrations     |                            |                       |
  |----------------------->|                            |                       |
  |                        | loader: select row for user_id                      |
  |                        |----------------------------------------------------->|
  |                        |<-----------------------------------------------------|
  |<-----------------------| "Connected as <login>"     |                       |
```

**Callback handler recommendation:** a **TanStack Start server route** (not a Supabase Edge Function).

Reasoning:

- The repo already has a working, proven pattern for server-only secrets in this exact runtime (`client.server.ts`, `auth-middleware.ts`) — reusing it means no new deployment target, no new secret-management surface, no new local-dev story.
- `vite.config.ts` already targets a single Nitro/Cloudflare deploy; splitting the callback into a separate Supabase Edge Function means maintaining two runtimes, two sets of environment variables (Supabase secrets vs. hosting-platform env vars), and two places to reason about "does the browser ever see this."
- Edge Functions would earn their keep if this needed to run somewhere Postgres-adjacent for latency, or needed Supabase's built-in `supabase secrets set` management independent of the frontend's deploy — neither applies here; this is a low-frequency, human-driven redirect, not a hot path.

Trade-off to note: if webhooks are added later (deferred, see §13), an Edge Function becomes more attractive (Supabase-managed secret storage, isolated from the frontend build, easy to point a GitHub webhook at a stable Supabase URL independent of where the frontend is hosted). That's a decision to revisit specifically when webhook work starts, not now.

## 4. Authentication distinction

Two separate concerns:

- **Signing into Personal Observability** — proving "you are the one PO user," via Supabase Auth (email/password, magic link, etc.). This produces the session/JWT that `requireSupabaseAuth` validates.
- **Authorising PO to access GitHub** — the GitHub App installation flow described above. This produces an `installation_id`, scoped to whatever GitHub account/org the user chooses during installation, and is not an identity assertion about the PO user at all.

**Recommendation: GitHub is an integration provider only, not a PO login provider**, for this milestone and for the foreseeable roadmap. Reasons:

- The product intends to connect **two GitHub accounts** to a single PO user (per `docs/PRODUCT.md`). "Login with GitHub" assumes a 1:1 mapping between a GitHub identity and an app identity — that assumption breaks immediately here.
- This is explicitly a single-user product; the login question is "is this the owner," not "which of several people is this," so GitHub's identity guarantees add nothing PO doesn't already need to solve for its own login regardless of GitHub.
- Keeping the concerns separate means the GitHub connection table never has to double as the user-identity table, which keeps §6/§7 simpler.

## 5. GitHub App design

- **Private App** (not listed publicly) — single-user tool, no reason for public discovery.
- **Homepage URL:** `https://<PLACEHOLDER_HOSTED_DOMAIN>/`
- **Setup URL:** `https://<PLACEHOLDER_HOSTED_DOMAIN>/integrations/github/callback` (also used as the redirect target after install; "Redirect on update" should be enabled so re-configuring repo access also round-trips through this route).
- **Callback/setup flow:** pure App-installation flow (`.../installations/new`), not GitHub's separate "user-to-server OAuth" flow — no `client_id`/`client_secret` needed for this milestone (see §8).
- **Repository selection:** entirely GitHub-hosted UI ("All repositories" or "Only select repositories") — PO builds nothing for this.
- **Minimum permissions:** GitHub requires at least `Metadata: Read-only` on every App; that alone is sufficient for this milestone (we only need the installation's account info, not repo contents). **Open decision:** whether to also request `Contents: Read-only` now, so the later commit-import milestone doesn't force every existing installation through a re-consent ("permissions changed") flow. Trade-off is least-privilege-now vs. avoiding a future forced re-approval — flagged in §14, not decided here.
- **Events/webhooks required now:** none. **This milestone does not need a webhook endpoint.**
- **Events deliberately deferred:** `push` (future commit sync), `installation` (created/deleted — would give live uninstall detection), `installation_repositories` (added/removed — would give live repo-access-change detection).

## 6. Proposed database model

**Evaluation:** a generic `integration_connections` table (provider-agnostic, `provider` discriminator + JSONB payload) vs. a GitHub-specific `github_installations` table vs. both.

**Recommendation: a single GitHub-specific `github_installations` table, not a generic table yet.** Only one provider exists today; a generic table would mean designing a provider-agnostic shape from a sample size of one, and this repo's stated conventions favor not building abstractions before a second concrete case exists. The columns below are still deliberately narrow and additive, so introducing a generic `integration_connections` table later (once Hevy etc. exist) is a normal follow-up migration, not a rewrite.

`github_installations`:

| Column                 | Type                                                                           | Nullable                  | Unique                      | Provider-specific | Sensitive                                                         |
| ---------------------- | ------------------------------------------------------------------------------ | ------------------------- | --------------------------- | ----------------- | ----------------------------------------------------------------- |
| `id`                   | `uuid` (default `gen_random_uuid()`)                                           | no                        | PK                          | no                | no                                                                |
| `user_id`              | `uuid` (FK → `auth.users(id)`)                                                 | no                        | no (see composite below)    | no                | no — but is the ownership key                                     |
| `installation_id`      | `bigint`                                                                       | no                        | yes (globally, GitHub-wide) | yes               | no — durable handle, not itself a credential                      |
| `github_account_id`    | `bigint`                                                                       | no                        | no (see composite)          | yes               | no — public numeric GitHub ID                                     |
| `github_account_login` | `text`                                                                         | no                        | no                          | yes               | no — public GitHub username, but personal data (display purposes) |
| `github_account_type`  | `text` check in (`'User'`,`'Organization'`)                                    | no                        | no                          | yes               | no                                                                |
| `github_app_id`        | `bigint`                                                                       | no                        | no                          | yes               | no                                                                |
| `status`               | `text` check in (`'connected'`,`'action_required'`,`'disconnected'`,`'error'`) | no, default `'connected'` | no                          | no                | no                                                                |
| `connected_at`         | `timestamptz` default `now()`                                                  | no                        | no                          | no                | no                                                                |
| `updated_at`           | `timestamptz` default `now()`                                                  | no                        | no                          | no                | no                                                                |
| `disconnected_at`      | `timestamptz`                                                                  | yes                       | no                          | no                | no                                                                |

**Deliberately absent:** any access token, private key material, or webhook secret — none of that is durable per-connection state; tokens are minted on demand later (per the milestone's own framing) and never persisted here.

**Constraints/indexes:**

- `UNIQUE (installation_id)` — a GitHub installation cannot belong to two PO users.
- `UNIQUE (user_id, github_account_id)` — prevents the same GitHub account being connected twice for the same PO user (handles the "already connected" retry case as an upsert target).
- Index on `user_id` — the only real read pattern ("my connections").

## 7. Ownership and Row Level Security

- Ownership: `user_id = auth.uid()`, enforced the same way the rest of the schema will (per `docs/ARCHITECTURE.md`, RLS is the intended model for user-owned records).
- **Authenticated browser may:** `SELECT` its own row(s) only — enough to render "Connected as `<login>`" and status.
- **Must be server-only:** `INSERT`/`UPDATE`/`DELETE`. The only legitimate writer is the verified callback handler, running under the service-role client (`client.server.ts`), which bypasses RLS entirely by design.
- **The browser must never** directly insert or update an `installation_id` — doing so would let a user claim an installation that isn't theirs, or attach an arbitrary ID with no corresponding verified GitHub install.
- **Likely initial RLS policies** (not implemented yet):
  - `ALTER TABLE github_installations ENABLE ROW LEVEL SECURITY;`
  - `CREATE POLICY select_own ON github_installations FOR SELECT USING (user_id = auth.uid());`
  - No `INSERT`/`UPDATE`/`DELETE` policy for `anon`/`authenticated` at all — absence of a policy denies by default, which is exactly the intended effect (only `service_role`, which bypasses RLS, can write).

## 8. Secret handling

| Value                        | Secret?                                             | Local                                               | Hosted                                                                                            | In `.env.example`?                                     | Browser access?                                     |
| ---------------------------- | --------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------- |
| GitHub App ID                | No (public numeric ID)                              | `.env.local`                                        | hosted server env                                                                                 | Yes (name only, empty value)                           | No — no reason to, keep server-only for consistency |
| GitHub App private key (PEM) | **Yes**                                             | `.env.local` (or a local-only PEM file, gitignored) | Hosted server-side secret store (Supabase server secret / hosting platform secret, not committed) | Yes (name only, empty value)                           | **Never**                                           |
| GitHub App client ID         | Not needed this milestone (no user-to-server OAuth) | —                                                   | —                                                                                                 | Not yet — add only if §4's recommendation is revisited | —                                                   |
| GitHub App client secret     | Not needed this milestone                           | —                                                   | —                                                                                                 | Not yet                                                | —                                                   |
| Webhook secret               | Not needed this milestone (no webhook endpoint, §5) | —                                                   | —                                                                                                 | Not yet                                                | —                                                   |
| State-signing secret (§9)    | **Yes**                                             | `.env.local`                                        | hosted server-side secret                                                                         | Yes (name only, empty value)                           | Never                                               |

Consistent with this repo's existing rule: `.env.example` may contain empty variable names only, real values only ever live in gitignored local files or the hosting platform's own secret storage — never committed.

## 9. Callback security and state validation

- **Preventing wrong-account attachment:** `state` is generated server-side at the _start_ of the connect flow, only while a valid PO session exists, and encodes that session's `user_id`. The callback re-derives `user_id` from the verified `state`, not from whatever session (if any) happens to be active when the callback fires — this also covers the case where the browser's session expired mid-flow.
- **Forged requests:** `state` is an HMAC-signed token (`{user_id, nonce, issued_at}` signed with a server-only secret). A forged `state` fails signature verification and is rejected before any DB write.
- **Replayed requests:** short expiry (e.g. 10 minutes) on the signed token, checked on callback. A repeated callback with an already-processed `state` should be treated as idempotent (see §11), not as a fresh connection attempt.
- **Trusting arbitrary installation IDs from the browser:** the callback route reads `installation_id` only from its own incoming request's query string (the direct GitHub redirect), never from a value posted by client-side JS or any other client-supplied channel.
- **Open redirects:** after processing, the callback always redirects to a single fixed internal path (`/integrations`) — never to a path derived from `state`, query params, or any other request-controlled value.

**Design for `state`:** a signed, stateless token — `base64url(payload) + "." + HMAC-SHA256(payload, STATE_SIGNING_SECRET)`, where `payload = { user_id, nonce, exp }`. Stateless avoids adding a table purely for a short-lived value (consistent with not creating unnecessary tables). Trade-off: without a server-side store, true single-use enforcement (hard replay prevention) isn't free — the short expiry window is the primary mitigation, and this residual risk (replay within the expiry window) is a deliberate, documented trade-off rather than an oversight. If airtight single-use is required later, the fallback is a small `github_connect_attempts` table keyed by nonce.

## 10. Connection states

| State                    | Persisted?                       | Notes                                                                                                                                            |
| ------------------------ | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `not_connected`          | No — implied by absence of a row | UI-only                                                                                                                                          |
| `pending` (mid-redirect) | No                               | Sub-second round trip; not worth persisting                                                                                                      |
| `connected`              | **Yes**                          | Normal steady state                                                                                                                              |
| `action_required`        | **Yes** (enum reserved)          | Detection mechanism deferred — no webhook yet to learn "permissions changed"                                                                     |
| `disconnected`           | **Yes**                          | Set if a future revalidation or webhook detects uninstall                                                                                        |
| `error`                  | **Yes** (enum reserved)          | See §11 — currently: don't persist a row at all if the callback fails before a confirmed installation; reserved for future partial-failure cases |

## 11. Failure handling

- **User cancels installation:** GitHub never redirects to the callback (or redirects without `installation_id`) — no row is written, UI still shows "Connect GitHub."
- **GitHub returns without an installation ID:** treat as a failed attempt; show a generic retry message; no row written.
- **Installation already connected:** upsert on `(user_id, github_account_id)` updates the existing row (refreshes `installation_id`/`status`/`updated_at`) rather than erroring or duplicating.
- **GitHub account changed** (user connects a second, different GitHub account): expected and supported — produces a second row, matching the product's two-GitHub-accounts intent, not an error.
- **Repository access changes:** no live detection this milestone (no webhook); accepted limitation, to be resolved when webhooks or a revalidation check are added.
- **App is uninstalled:** without a webhook, the row stays stale as `connected` until something re-checks. **Recommended (optional) mitigation still within this milestone's scope:** revalidate via a single App-JWT `GET /app/installations/{id}` call when the Integrations page loads, marking the row `disconnected` on a 404. This is a status check, not data import, so it doesn't violate the milestone's "no GitHub data" boundary — flagged as a recommendation, not a requirement (see §14).
- **Database persistence fails after a successful GitHub install:** GitHub-side installation still exists; user sees an error and can retry — retrying is safe because GitHub's own install flow recognizes an existing installation for that account and redirects straight back (`setup_action=update`) rather than creating a duplicate.
- **Callback is repeated:** must be idempotent — a `state` that's already been consumed (or an installation that already matches an existing row) should resolve to "already connected," not a hard error or duplicate row.

## 12. Implementation sequence

**Stage 1 — GitHub App registration (no code)**

- Goal: create the private GitHub App in GitHub's UI with the config from §5.
- Files: none (external configuration only).
- DB impact: none.
- Verification: App exists, install URL loads GitHub's own installation UI.
- Complete when: App ID and private key exist and are stored locally (not committed).

**Stage 2 — Schema**

- Goal: add `github_installations` migration + RLS policies from §6/§7.
- Files: new file under `supabase/migrations/`.
- DB impact: first table in the project.
- Verification: `bunx supabase db reset` succeeds; manually insert a row via the service-role client and confirm the anon/authenticated role can only read its own row (RLS test), never write.
- Complete when: migration applies cleanly locally and RLS behaves as specified.

**Stage 3 — Connect route**

- Goal: server route that verifies the PO session, generates the signed `state`, redirects to GitHub's installation URL.
- Files: new server route (exact TanStack Start API-route convention to be confirmed against the installed version — no prior example exists in this repo yet).
- DB impact: none.
- Verification: hitting the route while logged in redirects to a well-formed `.../installations/new?state=...` URL; hitting it while logged out is rejected.
- Complete when: redirect + state generation work, independent of GitHub actually being installed.

**Stage 4 — Callback route**

- Goal: verify `state`, call GitHub's installation-lookup API with an App JWT, upsert the row, redirect to `/integrations`.
- Files: new server route alongside Stage 3's.
- DB impact: writes to `github_installations` for the first time.
- Verification: full manual run against a real (test) GitHub App and local Supabase — install, get redirected back, confirm row exists with correct `user_id`/`account_login`.
- Complete when: an end-to-end install produces a correct, persisted row.

**Stage 5 — Frontend wiring**

- Goal: Integrations (and/or Settings) page reads the connection row server-side and renders "Connect GitHub" or "Connected as `<login>`" accordingly; wire the button to Stage 3's route.
- Files: `src/routes/integrations.tsx` (and/or `settings.tsx`).
- DB impact: read-only.
- Verification: full click-through from a clean state, refresh the page, confirm the connected state survives — this is the milestone's actual acceptance test.
- Complete when: all seven acceptance criteria in §1 pass.

## 13. Deferred work

- Commit import, historical backfill, scheduled sync.
- Webhooks for push activity (or any webhook at all).
- Pull requests, issues, timeline observations.
- Multi-user production hardening beyond what correct per-user ownership already requires (this is still a single-user product).
- Organisation installations beyond whatever GitHub's own installation UI naturally allows (no PO-side org-specific logic is being built).
- Live detection of permission changes / uninstalls beyond the optional lightweight revalidation check noted in §11.

## 14. Open decisions

- Whether to request `Contents: Read-only` now (avoids a future forced re-consent) vs. `Metadata: Read-only` only (strict least-privilege) — §5.
- Whether the optional installation-revalidation-on-page-load check (§11) is in scope for this milestone or pushed to a later one.
- Exact TanStack Start server-route file convention/location for Stages 3–4 — no existing example in this repo to follow; needs confirming against the installed `@tanstack/react-start` version at implementation time.
- Where the GitHub App private key is actually stored once hosted (which secret mechanism the hosting platform/Supabase setup ultimately uses) — noted as "the appropriate Supabase server-side secret mechanism" in principle, not yet chosen concretely.
