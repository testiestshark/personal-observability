# Roadmap

## Done

- Application shell: navigation (Today, Timeline, Insights, Integrations, Journal, Settings), mobile-first layout, mock placeholders.
- Local development environment: local Supabase stack, `.env.example`/`.env.local` split, repository-control docs (this set of files).
- Authentication: cookie-based Supabase Auth (email + password), `/login` route, route protection, sign out. Design in [ARCHITECTURE.md](ARCHITECTURE.md#authentication), manual verification runbook in [AUTHENTICATION.md](AUTHENTICATION.md).

## Next

- GitHub integration milestone 1 — "Connect GitHub" (see [integrations/GITHUB.md](integrations/GITHUB.md)); auth, its blocking dependency, is now in place.
- Close public signup once the owner account exists (`enable_signup = false`).
- First real data domain wired end-to-end (schema → migration → ingestion → UI).

## Later (unordered, one per data domain in [PRODUCT.md](PRODUCT.md))

- GitHub activity (two accounts)
- Strava fitness activities
- Computer activity tracking
- Manually recorded iPhone Screen Time
- Mood / energy / focus / stress / meaning tracking
- Weekly personal reviews
- Insights/analysis across domains

This roadmap is intentionally coarse — update it as milestones complete or priorities shift, rather than maintaining detailed task breakdowns here.
