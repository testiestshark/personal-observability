# Garmin health and wellness integration

**Status: Implemented and verified locally on 2026-09-06**

Personal Observability reads daily health totals automatically from the owner's Garmin
Connect account and writes normalized records to local Supabase:

```text
Garmin Watch -> Garmin Connect -> local Docker worker -> local Supabase -> app
```

Terra is deliberately not used. Its current entry pricing is disproportionate
for a private single-user project, while recurring exports fail the requirement
that ingestion be automatic.

## Scope

The current slice ingests steps, active calories, total calories, sleep start/end,
total sleep, resting heart rate, VO2 max, Garmin's source-sync time,
and recorded fitness activities. Active calories are movement energy; total
calories also include resting metabolism. Garmin activities retain useful summary
fields but deliberately omit route coordinates. Detailed gym exercises and sets
belong to the separate Hevy integration.

The worker fetches the latest seven days on every run. This intentionally
revisits recent dates so a late watch sync or Garmin correction overwrites the
same `(user_id, day, source)` row instead of creating duplicates. Missing or
malformed measurements are not converted to zero.

## Why this route

Garmin's official Health API requires an approved commercial integration. This
worker instead uses the open-source `garminconnect` client against Garmin
Connect's undocumented personal endpoints. That makes it free and fully
automatic after setup, but not officially supported: Garmin can change its auth
flow, endpoints, rate limits, or bot protection. All Garmin-specific code is
kept inside `scripts/garmin/` so it can be replaced without changing the app's
health model.

## Security model

Setup authenticates two accounts in the local terminal:

1. The existing Personal Observability login. Its refresh token lets the worker
   write as that user through normal Row Level Security.
2. Garmin Connect. The password and optional MFA code are sent to Garmin once,
   then discarded; Garmin access and refresh tokens are cached.

No service-role key is used by the worker. Both sessions are bearer credentials
and are stored below `.garmin-sync/`, which is gitignored. Do not copy, commit,
log, or paste that directory into chat. Deleting it disconnects the worker and
requires setup again.

## Setup and verification

Keep Docker Desktop and local Supabase running, and ensure `.env.local` contains
the local `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Apply the migration,
then run:

```powershell
bun run garmin:build
bun run garmin:test
bun run garmin:setup
bun run garmin:status
bun run garmin:sync
```

Setup is interactive and must be run in a real terminal. Never put Garmin or app
passwords in `.env.local`, source code, a task definition, or chat.

After the first successful sync, install the hourly task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/garmin/install-schedule.ps1
```

The task calls `scripts/garmin/run-sync.ps1` every hour. It is safe to retry:
the database write is an idempotent upsert. Sync only runs while the computer,
Docker Desktop, and local Supabase are available; a missed run is recovered by
the next seven-day fetch.

## Canonical record

`public.daily_health_metrics` owns normalized daily history, while
`public.fitness_activities` owns discrete Garmin and future Hevy activity records.
A Garmin daily row
retains:

- the owning `user_id` and Garmin calendar `day`;
- canonical steps, calories, sleep, resting-heart-rate, and VO2-max values;
- `source = garmin`;
- `provider = garmin_connect_unofficial`;
- a deterministic external identifier and the latest sync timestamp.

Authenticated users can only read and modify their own rows. Anonymous table
access is revoked, and all four authenticated operations are protected by RLS.

## Live architecture

The published app can use the same automatic integration without running Docker
inside Lovable:

```text
Garmin Watch -> Garmin Connect -> local Docker worker -> hosted Supabase -> published app
```

The production worker runs as a private Railway cron service with its Garmin bearer
session on a persistent volume. It signs in to Supabase afresh from private Railway
variables each run. A local Windows worker remains available for development and
recovery. Both use the app user, so existing RLS ownership checks remain in force.
The published frontend never receives Garmin credentials or tokens.

This design avoids both a paid health-data intermediary and a public server holding
the Garmin session. It does mean the computer and Docker Desktop must run periodically.
Because every sync revisits seven days, ordinary downtime is recovered on the next run.

Before enabling live sync:

1. Push the `daily_health_metrics` migration to the linked hosted Supabase project.
2. Store a separate hosted Supabase user session while reusing the existing Garmin
   token cache; do not perform another Garmin password login.
3. Run one live sync and verify the row is visible only to its owning user.
4. Install the scheduled task against the live profile.

The live Compose override maps the public hosted values from `.env.production` into
the worker's unprefixed variables and stores its app session separately at
`.garmin-sync/supabase-session-live.json`. Both profiles share only the existing
`.garmin-sync/garmin/` token cache. The local commands continue to use `.env.local`
and `.garmin-sync/supabase-session.json`, so local and hosted data cannot be confused.

## Live setup and verification

Preview and apply the pending migration to the linked hosted project:

```powershell
bunx supabase db push --dry-run
bunx supabase db push
```

Authenticate the hosted app account. This command deliberately does not ask for the
Garmin password:

```powershell
bun run garmin:setup:live
bun run garmin:status:live
bun run garmin:sync:live
```

Sign in to the published app and confirm that today's steps match Garmin. Then install
the separate live schedule:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/garmin/install-live-schedule.ps1
```

The task runs hourly and catches up the latest seven days after ordinary downtime.
Do not install it until the one-off live sync succeeds. Local and live schedules have
different task names and may coexist, although only the live schedule is needed when
the published app is the primary interface.

To run independently of the owner's computer, use the private Railway cron
deployment documented in `docs/integrations/RAILWAY.md`. Keep the Windows live
task enabled until a scheduled Railway run has been verified.
