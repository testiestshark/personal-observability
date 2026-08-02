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

## Secrets policy

- `.env.example` — committed, placeholder values only, documents every variable the app reads. Never put a real credential in this file.
- `.env.local` — gitignored (matched by the `*.local` rule in `.gitignore`), holds real local-Supabase values. Never commit this file.
- `.env` — gitignored. Historically this repo committed a `.env` with real hosted credentials; it has since been untracked (`git rm --cached`) and `.env` added to `.gitignore`. Don't recreate a committed `.env`.
- `SUPABASE_SERVICE_ROLE_KEY` (read by `src/integrations/supabase/client.server.ts`) bypasses Row Level Security. It must only ever be read via `process.env`, never `import.meta.env`/a `VITE_`-prefixed name — Vite only inlines `VITE_*` variables into the client bundle, so this convention is what keeps the service-role key out of frontend code. Never import `client.server.ts` from a route file or anything shipped to the browser.
- Restart `bun run dev` after changing any environment variable — Vite only reads `.env*` files at startup.

## Database migration policy

Schema changes are made via Supabase migrations (`supabase/migrations/`), applied locally with `bunx supabase db reset` / `bunx supabase migration up` and pushed to the hosted project via `bunx supabase db push` (or the Lovable-managed equivalent) rather than hand-edited directly against either database. This keeps local and hosted schemas reproducible from the same source of truth. No migrations exist yet — the current milestone has no database tables (see [PRODUCT.md](PRODUCT.md)).
