# Architecture

## Stack

TanStack Start (React 19 + Vite, SSR via Nitro) on the frontend, Supabase (Postgres, Auth, Storage) as the backend. Package manager/runtime: Bun.

## Planned integration architecture

**Status: Planned / Not Implemented**

Personal Observability will aggregate records from provider-specific integration
boundaries into its own database:

```text
                     Personal Observability
                            Database
                               ^
             +-----------------+-----------------+
             |                 |                 |
           Terra             Strava            GitHub
             ^                 ^                 ^
           Garmin         Hevy / Garmin        GitHub
             |
        health/wellness
```

The intended responsibilities are:

- **Terra / Garmin:** daily health and wellness data.
- **Strava:** discrete fitness and activity data.
- **Hevy:** strength-training logging, synced into Strava.
- **GitHub:** development and productivity activity.
- **Personal Observability database:** canonical aggregation layer and long-term
  source of truth.

External services are data providers; Personal Observability owns its canonical
history. Records from different domains can be combined by time and date, but
must retain provenance concepts such as their original source, ingestion
provider, external identifier, and ingestion time.

Provider boundaries should translate external payloads into internal records so
one provider can be replaced without changing unrelated product code. In
particular, Terra may later be replaced by a direct Garmin integration or a
different health provider.

Garmin workouts may reach Strava while Garmin wellness data reaches Terra. The
system must not blindly create two copies of the same activity: Terra is
initially responsible for health/wellness records and Strava for activities.
Future activity deduplication should prefer external IDs and provenance, with
timestamps, activity type, and duration as additional signals.

Detailed planned designs:

- [Hevy to Strava activity integration](integrations/HEVY_STRAVA.md)
- [Garmin to Terra health and wellness integration](integrations/GARMIN_TERRA.md)
- [GitHub integration](integrations/GITHUB.md)

## Environments and sync model

Two independent Supabase projects exist:

- **Hosted** — used by the Lovable-deployed app. Lovable commits changes straight to this repo's `main` branch; pushes to `main` sync back into the Lovable editor. The hosted Supabase project is the one referenced by the (removed-from-git) original `.env` values and `supabase/config.toml`'s linked `project_id`.
- **Local** — used only for local development, run via `bunx supabase start` (Docker). Local Postgres/Auth/API are ephemeral per machine and start empty (no seed data assumed yet).

Local frontend always talks to local Supabase; local development never talks to the hosted project. The relationship is:

```
Local frontend → local Supabase API (127.0.0.1:54321) → local Postgres (127.0.0.1:54322)
```

The hosted Lovable app has the equivalent relationship against the hosted project, independently.

**The hosted build gets its public config from the committed `.env.production`**, because Vite inlines `VITE_*` at build time and a gitignored `.env` on a developer machine can never reach Lovable's builder. The request-scoped server client prefers the unprefixed `SUPABASE_*` runtime variables and falls back to those same build-time `VITE_SUPABASE_*` public values. That fallback is required for Lovable editor previews, whose server runtime does not expose the unprefixed names. It is safe only for the public project URL and publishable key; any actual secret must remain a server-side runtime variable configured in the hosting panel.

When rotating these, take the values from the _hosted_ project's dashboard (Project Settings → API on `ivdhucdiycnbgvdetagw`) — never from `.env.local`, which points at the local stack, and never from `.env`, which historically held a **different, now-defunct project** (`sepdqkfqgysnuriynhid`) and is a live trap for exactly this mistake. Verify after any change by building and grepping the bundle:

```powershell
bun run build
Select-String -Path .output/public/assets/*.js -Pattern "ivdhucdiycnbgvdetagw" -List
```

## Secrets policy

Two categories, treated differently:

- **Public config** — the Supabase project URL and publishable/anon key (`sb_publishable_*`). These are inlined into the client bundle and served to every visitor by design; RLS is what protects the data, not their secrecy. They may be committed.
- **Secrets** — the service-role key (`sb_secret_*`), database passwords, any provider client secret. Never committed under any circumstance.

Files:

- `.env.example` — committed, placeholder values only, documents every variable the app reads. Never put a real credential in this file.
- `.env.production` — **committed on purpose**, holds the hosted project's public config only. Vite inlines `VITE_*` at _build_ time, so a gitignored file on a developer machine can never supply them to Lovable's build; this file is how the hosted bundle gets the right project. Loaded only for production builds, so local `bun run dev` is unaffected and still uses local Supabase. Secrets must never go here.
- `.env.local` — gitignored (matched by the `*.local` rule in `.gitignore`), holds real local-Supabase values. Never commit this file.
- `.env` — gitignored. Historically this repo committed a `.env` with real hosted credentials; it has since been untracked (`git rm --cached`) and `.env` added to `.gitignore`. Don't recreate a committed `.env`.
- `SUPABASE_SERVICE_ROLE_KEY` (read by `src/integrations/supabase/client.server.ts`) bypasses Row Level Security. It must only ever be read via `process.env`, never `import.meta.env`/a `VITE_`-prefixed name — Vite only inlines `VITE_*` variables into the client bundle, so this convention is what keeps the service-role key out of frontend code. Never import `client.server.ts` from a route file or anything shipped to the browser.
- Restart `bun run dev` after changing any environment variable — Vite only reads `.env*` files at startup.

## Authentication

Supabase Auth with email + password. The session lives in **cookies**, not `localStorage`, and all auth operations run through TanStack Start server functions.

- `src/lib/auth/supabase-request.server.ts` — builds a request-scoped Supabase client whose cookie access is wired to TanStack Start's `getCookies`/`setCookie`. Must be constructed per request, never cached in a module-level variable, or one visitor's session would leak into another's render.
- `src/lib/auth/auth.functions.ts` — `getCurrentUser`, `signIn`, `signUp`, `signOut` as server functions. Follows the repo convention that `*.functions.ts` ships RPC stubs to the client, so it imports the `.server.ts` module dynamically inside each handler.
- `src/routes/__root.tsx` — `beforeLoad` resolves the user and puts it in router context, redirecting to `/login` when signed out (and away from `/login` when signed in). `PUBLIC_PATHS` is the allowlist.
- `src/routes/login.tsx` — sign in / sign up form, rendered without the app shell.

**Why cookies rather than `localStorage`:** the server can read cookies. This is what lets SSR loaders know who the user is on first paint, and it is a hard requirement for provider callbacks (see [integrations/GITHUB.md](integrations/GITHUB.md)) — a top-level browser navigation back from GitHub carries cookies but no `Authorization` header.

**No auth token reaches client-side JavaScript.** Every auth call goes through a server function, so session cookies stay httpOnly. A Supabase client does exist in the browser bundle (Lovable's generated one, see below), but nothing ever signs in through it, so it holds no session.

**Generated scaffolding.** `src/integrations/supabase/client.ts`, `auth-middleware.ts` and `auth-attacher.ts` are Lovable-generated (`// This file is automatically generated`) and implement a different, `localStorage` + `Authorization: Bearer` approach. Don't build on them; use `src/lib/auth/` instead. Don't edit or delete them either — Lovable regenerates them (see below).

**Don't try to delete Lovable's scaffolding — satisfy it instead.** `attachSupabaseAuth` is registered as `functionMiddleware` in `src/start.ts`. It is a `.client()` middleware, so it runs in the _browser_ on every server-function call and eagerly constructs the generated Supabase client, which throws if `VITE_SUPABASE_*` are absent from the client bundle. That is a production-only failure mode: local `.env.local` defines those variables, so it stays silent locally and breaks only once deployed.

This broke hosted sign-in on 2026-08-02. It was first "fixed" by removing the middleware from `src/start.ts` (PR #2) — and Lovable silently restored it two commits later during unrelated favicon work, re-breaking the live site. **Removing Lovable-owned code is not a durable fix.** The working fix is `.env.production`, which guarantees the variables exist at build time so the generated client constructs successfully and the middleware becomes a harmless no-op (it finds no `localStorage` session, so attaches no header).

Consequence: the generated Supabase client _is_ present in the browser bundle. The httpOnly-cookie design above still holds — auth still runs entirely through server functions and no session token is exposed to client JavaScript — but the earlier claim of "no Supabase client in the browser at all" is not achievable on a Lovable-managed repo and has been dropped.

**Signup lockdown.** This is a single-user product, so public signup should be disabled on the hosted project once the owner account exists — do it in the Supabase dashboard (Authentication → Sign In / Providers), _not_ via `supabase config push`. That command pushes the entire local `config.toml`, which contains only `project_id`, so every unspecified auth setting would reset to CLI defaults — including `site_url`, which defaults to `http://127.0.0.1:3000` and would break hosted redirect/confirmation links. There is no `config pull` to recover current values first and no `--dry-run`. Local Supabase intentionally keeps signup enabled so test accounts can still be created.

For a step-by-step, repeatable procedure to verify this actually works (signup, session persistence across refresh, route protection, sign-out), see [AUTHENTICATION.md](AUTHENTICATION.md).

## Roles and ownership policy

Decided 2026-08-04. For the concrete table pattern and the two-gates mechanics (`GRANT`/`REVOKE` vs. RLS policies) these rules assume, see [supabase/README.md](../supabase/README.md). This section is the policy; that one is the how.

**No application-level roles.** Everyone who authenticates is just "the user" — there is no admin/editor/viewer distinction, no `role`/`is_admin` column anywhere. The only differentiation in the entire schema is row ownership: `user_id = auth.uid()`. This is deliberate, not an oversight — see `supabase/README.md` for why it's a complete model for a single-user app, and the specific triggers (a second user with different powers, sharing, background writes, file storage) that would make it insufficient. None of those apply yet. Don't add a permissions column "just in case" — an unenforced flag is worse than no flag, since it looks like a security boundary without being one.

If a genuine second tier is ever needed, it is **data** (a column checked inside RLS policies), not a custom Postgres role. Supabase's API layer only ever connects as one of `anon` / `authenticated` / `service_role` — there is no per-user Postgres role in this architecture, and building one means wiring a custom-claims hook, exposing the new role to PostgREST, and redoing every table's `GRANT`/`REVOKE` a second time. A column is scoped entirely to this schema and needs none of that.

**`service_role` is never used in application code.** Nothing under `src/` — no route, no server function, no middleware — may import `supabaseAdmin` from `src/integrations/supabase/client.server.ts`. It stays wired up and dormant. The only legitimate use is a one-off script run by hand from a terminal for genuine admin work (backfills, manual fixes) — something a developer watches happen, not deployed code that runs unattended. Reason: `service_role` bypasses Row Level Security entirely (`BYPASSRLS`), so any query it runs skips ownership checking completely; using it inside a normal request path would silently delete the entire ownership model for that query, with nothing in the database to catch the mistake. Revisit only when a feature genuinely has no user session to scope by (e.g. a scheduled sync job with nobody signed in) — not before. Note that even the future GitHub-callback design runs inside the user's own browser session via cookies, so it does not need this either.

**Mandatory verification after every migration that touches table privileges or RLS.** This is required, not best-effort — it already caught a real bug once (`weight_entries` shipped with `anon` holding table-level `SELECT`/`INSERT` on hosted that no migration asked for; typechecking and the build were both clean, only direct testing found it). After any `db push` that creates or changes a table:

1. Confirm `anon` has no grant on the table — either query `information_schema.role_table_grants`, or `curl` the table with the anon/publishable key and confirm `42501 permission denied for table`, not `200 []`. A `200` with an empty array means the table is reachable and only RLS is filtering — that's one gate, not two.
2. Confirm ownership isolation with a real second account — sign up a second test user, and confirm it cannot `select`, `insert` (as the first user), `update`, or `delete` the first user's rows. Anonymous (no session) must also see nothing.

Do this locally before pushing, and again against hosted after pushing — the two environments' default privileges are not guaranteed to match (this is exactly how the `weight_entries` gap happened: `db push` runs as `postgres`, and Supabase's default privileges auto-grant more to `anon` on hosted than local ever showed).

## Database migration policy

All permanent database changes must exist as version-controlled SQL migrations under `supabase/migrations/` — never hand-edited directly against either database. Workflow for a database change:

```powershell
bunx supabase migration new describe_change   # write SQL under supabase/migrations/
bunx supabase db reset                        # recreate + test the local database
bunx supabase db push --dry-run               # inspect what would deploy
bunx supabase db push                         # apply to hosted, only after review
```

Local Studio may be used to inspect and experiment, but the repository migration files are the permanent database history. This keeps local and hosted schemas reproducible from the same source of truth. When Lovable creates a reviewed database migration, pull the resulting GitHub commit before continuing local database work.

### Running alongside another Supabase project on the same machine

This machine also runs a work stack (`cmg_data_platform`). Both can run at once; three things keep them separate.

**1. Container names.** `project_id` in `supabase/config.toml` is the Docker container prefix for the _local_ stack — `supabase_db_personal_observability`, and so on. It is deliberately a readable name rather than the hosted project ref. It does **not** control which hosted project is linked: that lives in `supabase/.temp/project-ref` (gitignored) and still points at `ivdhucdiycnbgvdetagw`.

Changing `project_id` orphans the existing Docker volume, so the local database comes back empty — run `bunx supabase db reset` afterwards. Always `bunx supabase stop` _before_ changing it, since `stop` locates containers by the current value.

**2. Ports.** The two stacks are on different ports, so neither blocks the other:

|          | Personal (this repo) | Work (`cmg_data_platform`) |
| -------- | -------------------- | -------------------------- |
| API      | 54321                | 55321                      |
| Postgres | 54322                | 55322                      |
| Studio   | 54323                | 55323                      |

**3. CLI account.** The Supabase CLI is signed into one account at a time globally, which is what causes the 403s described below. To pin _this repo_ to the right account regardless of global login state, add a personal access token to `.env.local` (gitignored):

```
SUPABASE_ACCESS_TOKEN=sbp_...
```

Bun loads `.env.local` for `bunx`, so every `bunx supabase …` run from this directory then uses that account automatically — no manual switching when moving between repos. Generate the token from the Supabase dashboard (Account → Access Tokens) while signed in as the personal account. It is a **secret**: `.env.local` only, never `.env.production` or `.env.example`.

### Troubleshooting: `403 ... does not have the necessary privileges`

Symptom — any command touching the _linked_ project (`db push`, `db push --dry-run`, `migration list`, `projects api-keys`) fails with:

```
unexpected login role status 403: {"message":"Your account does not have the necessary privileges..."}
```

**Cause: the Supabase CLI is signed in to the wrong account**, not a real permissions problem with this project. Multiple Supabase accounts are in play on this machine. Confirm with:

```powershell
bunx supabase projects list
```

If the output lists `cmg_database` / `Loadfinder` / `UK Route Planner` — and **not** `personal-observability` — the CLI is in the wrong account context and every call against `ivdhucdiycnbgvdetagw` will 403. Sometimes simply re-running the command flips the session back; when it doesn't, re-authenticate with `bunx supabase login`.

**Workaround that avoids the account problem entirely:** connect straight to Postgres, bypassing the management API, using the hosted connection string from Dashboard → Project Settings → Database:

```powershell
bunx supabase db push --db-url "postgresql://postgres:<PASSWORD>@db.ivdhucdiycnbgvdetagw.supabase.co:5432/postgres"
```

The password is a **secret** — pass it transiently, never commit it and never add it to `.env.production`. This has now cost debugging time on two separate occasions; check the account context _first_.

## Git workflow

- Before starting work: `git switch main` → `git pull --ff-only origin main` → `git status` (confirm a clean tree) before asking Lovable or Claude Code to make changes.
- Ordinary features: work on a `feature/short-description` branch, test locally with `bun run dev`, then commit/push and merge to `main` via GitHub. Lovable edits one active branch at a time — keep it on the branch you deliberately want it to edit.
- Avoid two simultaneous editors: don't have Lovable and Claude Code editing the same files at the same time. Rhythm: pull latest → choose one editor → finish the change → test locally → commit and push → wait for sync → pull again before switching tools.
