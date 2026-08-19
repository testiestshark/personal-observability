# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## Project

Personal Observability — a private, single-user web app for tracking personal data (GitHub activity, Strava, steps, weight, computer activity, screen time, mood/energy/focus, journal entries, weekly reviews). See [docs/PRODUCT.md](docs/PRODUCT.md) for scope and [docs/ROADMAP.md](docs/ROADMAP.md) for what's built vs planned.

## What to work on

**[docs/backlog.md](docs/backlog.md) is the source of truth for outstanding work.** When
you are asked to do something specific, do that. When you are not — "what's next?", "pick
something up", or any open-ended request — read the backlog and take the highest-priority
item, rather than inventing work or guessing from the code.

Keep it current as part of the job, not as a separate chore:

- Finished an item? **Delete it** from the backlog in the same commit as the work. Git
  history is the record of what was done; a file of struck-through lines stops being read.
- Found a problem you are not fixing right now? Add it, with the reasoning and a link to
  the file or commit it came from. A finding that only exists in a chat transcript is lost.
- Decided _not_ to do something? Put it under "Deliberate non-goals" with the date and the
  why, so it is not raised again later as an oversight.

[docs/ROADMAP.md](docs/ROADMAP.md) stays coarse — milestones and data domains. Concrete,
pick-up-able tasks belong in the backlog.

## Stack

TanStack Start (React 19) + Vite, Tailwind v4, Supabase (Postgres/Auth/Storage). Package manager is **Bun** — use `bun`/`bunx`, not `npm`/`npx`.

## Commands

```
bun install       # install dependencies
bun run dev       # start dev server (restart after changing env vars)
bun run build     # production build
bun run lint      # eslint
bun run typecheck # tsc --noEmit
bun run test      # vitest, single run
bun run test:watch    # vitest in watch mode
bun run test:coverage # coverage report
bun run format    # prettier --write
bun run format:check  # prettier --check (what CI runs)
bun run verify    # lint + build + typecheck + test — the full CI gate, locally
bunx supabase start / status / stop   # local Supabase stack (requires Docker running)
```

## Testing and CI

Vitest + Testing Library, with tests beside the code as `*.test.ts` / `*.test.tsx`.
[.github/workflows/ci.yml](.github/workflows/ci.yml) runs lint, format check, typecheck,
test and build on every pull request and every push to `main`.

**Run `bun run verify` before pushing** — it is the same sequence CI runs, so green
locally means green on GitHub.

New behaviour needs a test, and a bug fix needs a test that fails without the fix. Prefer
testing pure logic: this codebase's real defects have been in date/timezone and parsing
code, not in the UI. Conventions, and what jsdom cannot do, are in
[docs/TESTING.md](docs/TESTING.md) — read it before writing tests.

## Authentication

Cookie-based Supabase Auth (email + password) lives in `src/lib/auth/`. All auth runs through server functions; there is no Supabase client in the browser. Route protection is the `beforeLoad` in `src/routes/__root.tsx`.

The generated files in `src/integrations/supabase/` (`client.ts`, `auth-middleware.ts`, `auth-attacher.ts`) implement an older `localStorage`/Bearer-token approach — don't build on them.

**Never register `attachSupabaseAuth` as `functionMiddleware` in `src/start.ts`.** It runs in the browser and throws when `VITE_SUPABASE_*` are absent, which is true of hosted builds but not local ones — so it breaks production while passing locally. Verify auth changes with `bun run build` and check the built client bundle, not just `bun run dev`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#authentication) for design and [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for the verification runbook.

## Environment & Supabase

- Copy `.env.example` to `.env.local` and fill in real values — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the local-vs-hosted Supabase model and secrets policy.
- Local dev points the frontend at local Supabase (`bunx supabase start`); the hosted Lovable deployment continues to use hosted Supabase.
- Never put real credentials in `.env` or `.env.example` — only `.env.local` (gitignored).
- `SUPABASE_SERVICE_ROLE_KEY` / `client.server.ts` bypass RLS — server-side only, never reference it with a `VITE_` prefix.

## Roles and ownership

No application-level roles (admin/editor/viewer) — ownership via `user_id = auth.uid()` is the only differentiation, and that's a deliberate policy, not a gap to fill in. **`supabaseAdmin` / `service_role` must never be imported from application code** (routes, server functions, middleware) — it bypasses RLS entirely, and using it in a request path silently deletes the ownership model for that query with nothing in the database to catch the mistake. Every new user-owned table must follow the pattern in [supabase/README.md](supabase/README.md) (ownership column, RLS, `anon` revoked, four policies), and every migration touching table privileges or RLS must be verified per [docs/ARCHITECTURE.md § Roles and ownership policy](docs/ARCHITECTURE.md#roles-and-ownership-policy) — this is a required step, not best-effort, and has already caught a real bug once.

## Working in this repo

- This repo is synced with [Lovable](https://lovable.dev) — see `AGENTS.md`. Avoid rewriting published git history (force-push, rebase/amend/squash on pushed commits).
- Database schema changes go through Supabase migrations in `supabase/migrations/` — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the migration policy. Don't hand-edit the hosted schema outside of migrations.
- Don't add unnecessary dependencies or scaffold empty feature folders — keep the tree matching what's actually in use.
- `src/routeTree.gen.ts` is generated and **gitignored**. Never edit or commit it. It
  is why `bun run verify` and CI run the build _before_ typecheck — `tsc` fails on
  every route without it. See the comment in `.gitignore` before reordering either.

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

**If the change touches table privileges or RLS, verify — locally and again against hosted, since their default privileges are not guaranteed to match:**

1. `anon` has no grant on the table (`information_schema.role_table_grants`, or a `curl` with the publishable key returns `42501 permission denied for table`, not `200 []`)
2. a second real test account cannot read, insert-as, update, or delete the first account's rows, and an anonymous request sees nothing

This is mandatory, not best-effort — see [docs/ARCHITECTURE.md § Roles and ownership policy](docs/ARCHITECTURE.md#roles-and-ownership-policy) for why.

**Avoid two simultaneous editors.** Lovable and Claude Code must not edit the same files at the same time. Rhythm: pull latest → choose one editor → finish the change → test locally → commit and push → wait for sync → pull again before switching tools. If Lovable creates a reviewed database migration, pull that commit before continuing local database work.
