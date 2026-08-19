# Roadmap

The coarse view: milestones and data domains. **Concrete, pick-up-able tasks live in
[backlog.md](backlog.md)** — that is the file to read when deciding what to do next.

## Done

- Application shell: navigation (Today, Timeline, Insights, Integrations, Journal, Settings), mobile-first layout, mock placeholders.
- Local development environment: local Supabase stack, `.env.example`/`.env.local` split, repository-control docs (this set of files).
- Authentication: cookie-based Supabase Auth (email + password), `/login` route, route protection, sign out. Design in [ARCHITECTURE.md](ARCHITECTURE.md#authentication), manual verification runbook in [AUTHENTICATION.md](AUTHENTICATION.md).
- Roles and ownership policy: user-owned-table RLS pattern documented and enforced ([supabase/README.md](../supabase/README.md), [ARCHITECTURE.md](ARCHITECTURE.md#roles-and-ownership-policy)).
- **Weight tracking — the first data domain wired end-to-end.** Schema and RLS via migration, kilogram scroll-wheel entry, month calendar, and full weigh-in history. Historic entries were backfilled once from CSV; that code has since been removed (see [backlog.md](backlog.md) non-goals).
- Testing and CI: Vitest + Testing Library, GitHub Actions running lint, format check, typecheck, test and build. See [TESTING.md](TESTING.md).

## Next

- GitHub integration milestone 1 — "Connect GitHub"; auth, its blocking dependency, is in place. The spec is [docs/integrations/GITHUB.md](integrations/GITHUB.md) — design only, no code or migrations yet.
- Close public signup now the owner account exists — dashboard only, see [backlog.md](backlog.md).
- Finish the weight domain: a trend view rather than only a list.

## Later (unordered, one per data domain in [PRODUCT.md](PRODUCT.md))

- GitHub activity (two accounts)
- Strava fitness activities
- Computer activity tracking
- Manually recorded iPhone Screen Time
- Mood / energy / focus / stress / meaning tracking
- Weekly personal reviews
- Insights/analysis across domains

This roadmap is intentionally coarse — update it as milestones complete or priorities shift, rather than maintaining detailed task breakdowns here.
