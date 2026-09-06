# Roadmap

The coarse view: milestones and data domains. **Concrete, pick-up-able tasks live in
[backlog.md](backlog.md)** — that is the file to read when deciding what to do next.

## Done

- Application shell: navigation (Today, Timeline, Insights, Integrations, Journal, Settings), mobile-first layout, mock placeholders.
- Local development environment: local Supabase stack, `.env.example`/`.env.local` split, repository-control docs (this set of files).
- Authentication implementation (local only): cookie-based Supabase Auth (email + password), `/login` route, route protection, sign out. The local flow is verified; Lovable-hosted login still does not work. Design in [ARCHITECTURE.md](ARCHITECTURE.md#authentication), local verification runbook in [AUTHENTICATION.md](AUTHENTICATION.md).
- Roles and ownership policy: user-owned-table RLS pattern documented and enforced ([supabase/README.md](../supabase/README.md), [ARCHITECTURE.md](ARCHITECTURE.md#roles-and-ownership-policy)).
- **Weight tracking — the first data domain wired end-to-end.** Schema and RLS via migration, kilogram scroll-wheel entry, month calendar, full weigh-in history, and a trend chart (raw readings under a 7-day moving average). Historic entries were backfilled once from CSV; that code has since been removed (see [backlog.md](backlog.md) non-goals).
- Testing and CI: Vitest + Testing Library, GitHub Actions running lint, format check, typecheck, test and build. See [TESTING.md](TESTING.md).

## Parked

- **Lovable-hosted login:** still not working as of 2026-09-06. Further debugging is
  deliberately parked to move on; local auth success must not be treated as hosted
  readiness.
- GitHub integration milestone 1 — "Connect GitHub". Its hosted-auth dependency is
  not available, so this is parked too. The spec is
  [docs/integrations/GITHUB.md](integrations/GITHUB.md) — design only, no code or
  migrations yet.

## Later (unordered, one per data domain in [PRODUCT.md](PRODUCT.md))

- GitHub activity (two accounts)
- Strava fitness activities
- Computer activity tracking
- Manually recorded iPhone Screen Time
- Mood / energy / focus / stress / meaning tracking
- Weekly personal reviews
- Insights/analysis across domains

This roadmap is intentionally coarse — update it as milestones complete or priorities shift, rather than maintaining detailed task breakdowns here.
