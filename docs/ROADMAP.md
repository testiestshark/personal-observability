# Roadmap

## Done

- Application shell: navigation (Today, Timeline, Insights, Integrations, Journal, Settings), mobile-first layout, mock placeholders.
- Local development environment: local Supabase stack, `.env.example`/`.env.local` split, repository-control docs (this set of files).

## Next

- First real data domain wired end-to-end (schema → migration → ingestion → UI), likely starting with the simplest of: daily steps, weight, or journal entries.
- Supabase schema/migrations for whichever domain is picked first.
- Auth (single-user login) if not already covered by the app shell.

## Later (unordered, one per data domain in [PRODUCT.md](PRODUCT.md))

- GitHub activity (two accounts)
- Strava fitness activities
- Computer activity tracking
- Manually recorded iPhone Screen Time
- Mood / energy / focus / stress / meaning tracking
- Weekly personal reviews
- Insights/analysis across domains

This roadmap is intentionally coarse — update it as milestones complete or priorities shift, rather than maintaining detailed task breakdowns here.
