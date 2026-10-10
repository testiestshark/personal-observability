# Roadmap

The coarse view: milestones and data domains. **Concrete, pick-up-able tasks live in
GitHub issues** — that is where to look when deciding what to do next.

## Done

- Application shell: navigation (Today, Timeline, Insights, Integrations, Journal, Settings), mobile-first layout, mock placeholders.
- Local development environment: local Supabase stack, `.env.example`/`.env.local` split, repository-control docs (this set of files).
- Authentication: cookie-based Supabase Auth (email + password), `/login` route, route protection, sign out. Design in [ARCHITECTURE.md](ARCHITECTURE.md#authentication), local verification runbook in [AUTHENTICATION.md](AUTHENTICATION.md).
- Roles and ownership policy: user-owned-table RLS pattern documented and enforced ([supabase/README.md](../supabase/README.md), [ARCHITECTURE.md](ARCHITECTURE.md#roles-and-ownership-policy)).
- **Weight tracking — the first data domain wired end-to-end.** Schema and RLS via migration, kilogram scroll-wheel entry, month calendar, full weigh-in history, and a trend chart (raw readings under a 7-day moving average). Historic entries were backfilled once from CSV; that code has since been removed (see [NON_GOALS.md](NON_GOALS.md)).
- Testing and CI: Vitest + Testing Library, GitHub Actions running lint, format check, typecheck, test and build. See [TESTING.md](TESTING.md).
- Garmin health and activities, local and live: normalized schemas, RLS-backed
  dashboard reads, Dockerised worker, steps/calorie/sleep/resting-HR/VO2-max and
  recorded-activity ingestion, account authentication,
  hourly Windows scheduling, and successful end-to-end hosted sync.
- Garmin Railway production: hourly cron worker, persistent Garmin-session volume,
  fresh per-run app authentication, secure token upload helper, and operating runbook.
- Hevy strength workouts, operational on Railway since 2026-10-06: workouts with their
  exercises and sets, deletions, full-history backfill, an hourly cron worker, and a
  "Last synced" time on the Integrations page. Design in
  [integrations/HEVY.md](integrations/HEVY.md), runbook in
  [integrations/RAILWAY_HEVY.md](integrations/RAILWAY_HEVY.md).

## Parked

- Nothing currently parked. The GitHub "Connect GitHub" milestone was superseded on
  2026-10-10; see below.

## Next

- GitHub activity (two accounts): decided and split into issues under #20; the token
  probe is done (#74) and the schema (#75) and worker (#76) are next. Design and probe
  findings in
  [integrations/GITHUB_MULTI_ACCOUNT.md](integrations/GITHUB_MULTI_ACCOUNT.md);
  [integrations/GITHUB.md](integrations/GITHUB.md) is superseded.

## Later (unordered, one per data domain in [PRODUCT.md](PRODUCT.md))

- Computer activity tracking
- Manually recorded iPhone Screen Time
- Mood / energy / focus / stress / meaning tracking
- Weekly personal reviews
- Insights/analysis across domains

This roadmap is intentionally coarse — update it as milestones complete or priorities shift, rather than maintaining detailed task breakdowns here.
