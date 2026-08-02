# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## Project

Personal Observability — a private, single-user web app for tracking personal data (GitHub activity, Strava, steps, weight, computer activity, screen time, mood/energy/focus, journal entries, weekly reviews). See [docs/PRODUCT.md](docs/PRODUCT.md) for scope and [docs/ROADMAP.md](docs/ROADMAP.md) for what's built vs planned.

## Stack

TanStack Start (React 19) + Vite, Tailwind v4, Supabase (Postgres/Auth/Storage). Package manager is **Bun** — use `bun`/`bunx`, not `npm`/`npx`.

## Commands

```
bun install       # install dependencies
bun run dev       # start dev server (restart after changing env vars)
bun run build     # production build
bun run lint      # eslint
bun run format    # prettier --write
bunx supabase start / status / stop   # local Supabase stack (requires Docker running)
```

## Authentication

Cookie-based Supabase Auth (email + password) lives in `src/lib/auth/`. All auth runs through server functions; there is no Supabase client in the browser. Route protection is the `beforeLoad` in `src/routes/__root.tsx`.

The generated files in `src/integrations/supabase/` (`client.ts`, `auth-middleware.ts`, `auth-attacher.ts`) implement an older `localStorage`/Bearer-token approach — don't build on them.

**Never register `attachSupabaseAuth` as `functionMiddleware` in `src/start.ts`.** It runs in the browser and throws when `VITE_SUPABASE_*` are absent, which is true of hosted builds but not local ones — so it breaks production while passing locally. Verify auth changes with `bun run build` and check the built client bundle, not just `bun run dev`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#authentication) for design and [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for the verification runbook.

## Environment & Supabase

- Copy `.env.example` to `.env.local` and fill in real values — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the local-vs-hosted Supabase model and secrets policy.
- Local dev points the frontend at local Supabase (`bunx supabase start`); the hosted Lovable deployment continues to use hosted Supabase.
- Never put real credentials in `.env` or `.env.example` — only `.env.local` (gitignored).
- `SUPABASE_SERVICE_ROLE_KEY` / `client.server.ts` bypass RLS — server-side only, never reference it with a `VITE_` prefix.

## Working in this repo

- This repo is synced with [Lovable](https://lovable.dev) — see `AGENTS.md`. Avoid rewriting published git history (force-push, rebase/amend/squash on pushed commits).
- Database schema changes go through Supabase migrations in `supabase/migrations/` — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the migration policy. Don't hand-edit the hosted schema outside of migrations.
- Don't add unnecessary dependencies or scaffold empty feature folders — keep the tree matching what's actually in use.

## Operating rules (must follow)

**Before starting any work:**

```powershell
git switch main
git pull --ff-only origin main
git status
```

Confirm the working tree is clean before making changes.

**For an ordinary feature:** work on a feature branch (`git switch -c feature/short-description`), develop and test with `bun run dev`, then `git add`/`commit`/`push -u origin feature/short-description` and merge to `main` via GitHub when ready. Never push straight to `main` for feature work.

**For a database change:**

```powershell
bunx supabase migration new describe_change   # write SQL under supabase/migrations/
bunx supabase db reset                        # recreate + test the local database
bunx supabase db push --dry-run               # inspect what would deploy
bunx supabase db push                         # apply to hosted, only after review
```

All permanent database changes must exist as version-controlled SQL migrations under `supabase/migrations/`. Local Studio is for inspection/experimentation only — it is never the source of truth.

**Avoid two simultaneous editors.** Lovable and Claude Code must not edit the same files at the same time. Rhythm: pull latest → choose one editor → finish the change → test locally → commit and push → wait for sync → pull again before switching tools. If Lovable creates a reviewed database migration, pull that commit before continuing local database work.
