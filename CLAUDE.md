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

## Environment & Supabase

- Copy `.env.example` to `.env.local` and fill in real values — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the local-vs-hosted Supabase model and secrets policy.
- Local dev points the frontend at local Supabase (`bunx supabase start`); the hosted Lovable deployment continues to use hosted Supabase.
- Never put real credentials in `.env` or `.env.example` — only `.env.local` (gitignored).
- `SUPABASE_SERVICE_ROLE_KEY` / `client.server.ts` bypass RLS — server-side only, never reference it with a `VITE_` prefix.

## Working in this repo

- This repo is synced with [Lovable](https://lovable.dev) — see `AGENTS.md`. Avoid rewriting published git history (force-push, rebase/amend/squash on pushed commits).
- Database schema changes go through Supabase migrations in `supabase/migrations/` — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the migration policy. Don't hand-edit the hosted schema outside of migrations.
- Don't add unnecessary dependencies or scaffold empty feature folders — keep the tree matching what's actually in use.
