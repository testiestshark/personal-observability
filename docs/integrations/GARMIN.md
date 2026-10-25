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

The current slice ingests steps, active calories, total calories, consumed calories,
the MyFitnessPal calorie goal, sleep start/end, total sleep, resting heart rate, VO2
max, Garmin's source-sync time, and recorded fitness activities. Active calories are movement energy; total
calories also include resting metabolism. Consumed calories are food intake that
MyFitnessPal sends to Garmin Connect, and are null for days before the accounts were
linked on 2026-09-28 ([MYFITNESSPAL.md](MYFITNESSPAL.md)). The calorie goal is the
daily target set in MyFitnessPal, stored per day as Garmin reports it for that day
(not yet checked across a goal change: the seven-day re-fetch rewrites recent days if
Garmin backdates a new goal). On its own it does not keep a day's row. Garmin activities retain useful summary
fields but deliberately omit route coordinates. Runs and walks also keep their
per-lap splits ([below](#run-splits)). Detailed gym exercises and sets
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

## Run splits

`public.fitness_activity_laps` holds one row per lap of a run or walk, shown as the
**Splits** table on the activity detail page (`/activities/$id`): each lap's time, pace,
average heart rate and net elevation, with a bar per pace so a fade or a fast finish is
visible at a glance. It is a child of `fitness_activities`, following the
`fitness_exercises` precedent (own RLS with four policies, `anon` revoked, deleted with
its activity).

- **Laps are Garmin's own.** The worker stores `lapDTOs` from the per-activity splits
  endpoint in recorded order, so with the watch's auto-lap at 1 km they are per-km splits.
  Garmin's response does not say whether a lap was automatic or manual, so the table does
  not claim to: a lap shorter than the longest shows its distance, which is how the last
  partial km (or a manual lap) reads.
- **Fields:** time, distance, average heart rate, elevation gain and loss. Pace is worked
  out in the app from time and distance. Cadence is left out: the activity already shows
  it, and per-km it mostly repeats that.
- **No coordinates.** Garmin returns start and end positions for every lap; the worker
  copies fields by name and never carries them (route maps are a non-goal in
  [NON_GOALS.md](../NON_GOALS.md)).
- **Foot activities only** (running, walking, hiking type keys), and only when there are at
  least two laps; a single lap would repeat the headline.

**Cost.** Splits are one extra Garmin request per activity, not per run. Each sync asks
only for foot activities in its seven-day window that have **no laps stored yet**, so a new
run costs one request once. A lookup that fails, or an activity with no laps, is a warning
and is retried on the next run while the activity is still in the window; it never fails
the sync. Requests are spaced one second apart, and five failures in a row stop the run:
that is a rate limit or an outage, and more requests would only make it worse.

**Backfill (one-off).** Runs from before this shipped have no laps. After the migration is
applied, fetch them once, newest first:

```powershell
bun run garmin:backfill-splits              # local Supabase
bun run garmin:backfill-splits:live         # hosted Supabase
bun run garmin:backfill-splits --limit 20   # store at most 20, to try it or to stay under a rate limit
```

It is safe to repeat: activities that already have laps are skipped, so a run cut short is
finished by running it again. `--limit` counts activities that got laps, so activities Garmin
reports no laps for do not use it up; those are asked about again on each run.

**Verification.** The table and its replace function follow the roles and ownership policy
([ARCHITECTURE.md](../ARCHITECTURE.md#roles-and-ownership-policy)). Run
`scripts/verify-fitness-activity-laps-rls.sql` after the migration, locally and again
against hosted; it uses two accounts and rolls everything back.

## Run weather

Each outdoor run, walk or hike gets the weather for the hour it started in, stored in
`weather.run_weather` (one row per activity, deleted with it). Design and reasoning:
[ADR 0001](../adr/0001-run-weather-from-a-discarded-start-point.md).

- **Source:** Open-Meteo's historical archive, so it is what the weather actually was, never a
  forecast. Five values for the UTC start hour: temperature, apparent temperature, relative
  humidity, wind speed (mph) and precipitation. Fetch time and source are on the row. It is an
  area reading, not a measurement at the runner's position.
- **The start point is used and discarded.** The activity summary the sync has already fetched
  carries `startLatitude`/`startLongitude`, so weather costs no Garmin request. The worker rounds
  them to one decimal place (about 11 km), sends that to Open-Meteo, and drops it. It is not
  stored, not logged, and not in any error message (failures print the HTTP status only).
  `RunStart` in `garmin_sync.py` hides it from `repr`, and tests check the rows and the output.
- **Indoor activities get none.** A treadmill summary has no start coordinate keys at all (checked
  against a live session on 2026-10-25, #134), so a missing or zero coordinate is what excludes
  it; the type key (`treadmill`, `indoor`, `virtual`) is a second guard. `is_foot_activity` alone
  is not enough, because `treadmill_running` contains "running".
- **Fetched once.** A run that already has a row is not asked about again. If the archive has no
  complete value for the hour yet, no row is written and the next sync tries again, for as long as
  the run is in the sync window (seven days by default). Three failures in a row stop the step for
  that sync. A failure is a warning and never fails the sync.
- **Backfill (one-off).** Runs older than the sync window get weather from a separate command:

  ```powershell
  bun run garmin:backfill-weather              # local Supabase
  bun run garmin:backfill-weather:live         # hosted Supabase
  bun run garmin:backfill-weather --limit 50   # look up at most 50 runs, newest first
  ```

  Start points are not stored, so it reads Garmin's activity list again, 30 days per request and
  one second apart, and looks up only runs that have no weather row; treadmill and other indoor
  activities are skipped. It is safe to repeat: runs with weather are not asked about again, a
  failed lookup or a run the archive does not cover yet is a warning and is retried next time,
  and three failures in a row stop the run. The coordinate follows the same rule as the sync.

**Exposing the schema.** The API serves only the schemas it is told about. Locally
`supabase/config.toml` lists `weather`; **on hosted it is a manual step**: Dashboard > Settings >
API > Exposed schemas, add `weather`. Until then the worker's weather step warns and the rest of
the sync is unaffected. The worker reads and writes with the `Accept-Profile` and `Content-Profile`
headers set to `weather`.

**Verification.** Run `scripts/verify-run-weather-rls.sql` after the migration, locally and again
against hosted (see [ARCHITECTURE.md](../ARCHITECTURE.md#roles-and-ownership-policy)). It checks
that `anon` has no grant on the table or the schema, that a second account cannot read, insert as,
update or delete the first account's rows, and that the table has no location column. It rolls
everything back.

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
