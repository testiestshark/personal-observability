# Architecture

## Stack

TanStack Start (React 19 + Vite, SSR via Nitro) on the frontend, Supabase (Postgres, Auth, Storage) as the backend. Package manager/runtime: Bun.

## Environments and sync model

Two independent Supabase projects exist:

- **Hosted** — used by the Lovable-deployed app. Lovable commits changes straight to this repo's `main` branch; pushes to `main` sync back into the Lovable editor. The hosted Supabase project is the one referenced by the (removed-from-git) original `.env` values and `supabase/config.toml`'s linked `project_id`.
- **Local** — used only for local development, run via `bunx supabase start` (Docker). Local Postgres/Auth/API are ephemeral per machine and start empty (no seed data assumed yet).

Local frontend always talks to local Supabase; local development never talks to the hosted project. The relationship is:

```
Local frontend → local Supabase API (127.0.0.1:54321) → local Postgres (127.0.0.1:54322)
```

The hosted Lovable app has the equivalent relationship against the hosted project, independently.

**The hosted build gets its public config from the committed `.env.production`**, because Vite inlines `VITE_*` at build time and a gitignored `.env` on a developer machine can never reach Lovable's builder. Server-side runtime variables (and any actual secret) are configured in Lovable's own panel instead.

When rotating these, take the values from the *hosted* project's dashboard (Project Settings → API on `ivdhucdiycnbgvdetagw`) — never from `.env.local`, which points at the local stack, and never from `.env`, which historically held a **different, now-defunct project** (`sepdqkfqgysnuriynhid`) and is a live trap for exactly this mistake. Verify after any change by building and grepping the bundle:

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
- `.env.production` — **committed on purpose**, holds the hosted project's public config only. Vite inlines `VITE_*` at *build* time, so a gitignored file on a developer machine can never supply them to Lovable's build; this file is how the hosted bundle gets the right project. Loaded only for production builds, so local `bun run dev` is unaffected and still uses local Supabase. Secrets must never go here.
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

**Don't try to delete Lovable's scaffolding — satisfy it instead.** `attachSupabaseAuth` is registered as `functionMiddleware` in `src/start.ts`. It is a `.client()` middleware, so it runs in the *browser* on every server-function call and eagerly constructs the generated Supabase client, which throws if `VITE_SUPABASE_*` are absent from the client bundle. That is a production-only failure mode: local `.env.local` defines those variables, so it stays silent locally and breaks only once deployed.

This broke hosted sign-in on 2026-08-02. It was first "fixed" by removing the middleware from `src/start.ts` (PR #2) — and Lovable silently restored it two commits later during unrelated favicon work, re-breaking the live site. **Removing Lovable-owned code is not a durable fix.** The working fix is `.env.production`, which guarantees the variables exist at build time so the generated client constructs successfully and the middleware becomes a harmless no-op (it finds no `localStorage` session, so attaches no header).

Consequence: the generated Supabase client *is* present in the browser bundle. The httpOnly-cookie design above still holds — auth still runs entirely through server functions and no session token is exposed to client JavaScript — but the earlier claim of "no Supabase client in the browser at all" is not achievable on a Lovable-managed repo and has been dropped.

**Signup lockdown.** This is a single-user product, so public signup should be disabled on the hosted project once the owner account exists — do it in the Supabase dashboard (Authentication → Sign In / Providers), *not* via `supabase config push`. That command pushes the entire local `config.toml`, which contains only `project_id`, so every unspecified auth setting would reset to CLI defaults — including `site_url`, which defaults to `http://127.0.0.1:3000` and would break hosted redirect/confirmation links. There is no `config pull` to recover current values first and no `--dry-run`. Local Supabase intentionally keeps signup enabled so test accounts can still be created.

For a step-by-step, repeatable procedure to verify this actually works (signup, session persistence across refresh, route protection, sign-out), see [AUTHENTICATION.md](AUTHENTICATION.md).

## Database migration policy

All permanent database changes must exist as version-controlled SQL migrations under `supabase/migrations/` — never hand-edited directly against either database. Workflow for a database change:

```powershell
bunx supabase migration new describe_change   # write SQL under supabase/migrations/
bunx supabase db reset                        # recreate + test the local database
bunx supabase db push --dry-run               # inspect what would deploy
bunx supabase db push                         # apply to hosted, only after review
```

Local Studio may be used to inspect and experiment, but the repository migration files are the permanent database history. This keeps local and hosted schemas reproducible from the same source of truth. When Lovable creates a reviewed database migration, pull the resulting GitHub commit before continuing local database work. No migrations exist yet — the current milestone has no database tables (see [PRODUCT.md](PRODUCT.md)).

## Git workflow

- Before starting work: `git switch main` → `git pull --ff-only origin main` → `git status` (confirm a clean tree) before asking Lovable or Claude Code to make changes.
- Ordinary features: work on a `feature/short-description` branch, test locally with `bun run dev`, then commit/push and merge to `main` via GitHub. Lovable edits one active branch at a time — keep it on the branch you deliberately want it to edit.
- Avoid two simultaneous editors: don't have Lovable and Claude Code editing the same files at the same time. Rhythm: pull latest → choose one editor → finish the change → test locally → commit and push → wait for sync → pull again before switching tools.
