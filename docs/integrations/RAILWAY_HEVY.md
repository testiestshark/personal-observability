# Railway-hosted Hevy sync

**Status: Prepared (2026-10-06), awaiting the owner's go-live steps ([#41][issue])**

Railway runs the Hevy worker as a private hourly cron job, the same shape as the
[Garmin worker](RAILWAY.md):

```text
Hevy app -> Hevy public API -> Railway cron worker -> hosted Supabase -> published app
```

The worker signs in as the app user, replaces every workout updated in the last
seven days (with its exercises and sets), applies deletions, records its time in
`sync_runs`, and exits. It exposes no web server or domain. Design and worker
behaviour are in [HEVY.md](HEVY.md).

Secrets (the app password and the Hevy API key) are entered only in Railway's
Variables editor, never in chat, files or logs.

## 1. Push the migrations to hosted

The dry run on 2026-10-06 reported exactly these pending migrations:

```text
20261006190000_create_fitness_exercises_and_sets.sql
20261006200000_create_sync_runs.sql
```

Check `bunx supabase projects list` shows `ivdhucdiycnbgvdetagw` as linked, review
the dry run, then push:

```powershell
bunx supabase db push --dry-run
bunx supabase db push
```

Then verify, as required for any privilege or RLS change. The two SQL scripts
(`scripts/verify-fitness-workout-rls.sql`, `scripts/verify-sync-runs-rls.sql`) roll
back, but they need two auth users and the hosted project has only the owner's
(signup is closed), so the cross-account half needs a temporary second test account
created and deleted by the owner. The schema half (no `anon` grants, four policies
per table, function privileges) can be checked read-only with
`bunx supabase db query --linked "<sql>"`.

Also confirm that a request with the publishable key and no sign-in gets
`42501 permission denied` for `fitness_exercises`, `fitness_sets` and `sync_runs`,
not `200 []`. Record the results on #41.

## 2. One-time Railway setup

1. In the Railway project add a service named `hevy-sync` from the GitHub
   repository's `main` branch.
2. Paste the keys from `scripts/hevy/railway.env.example` into the service's
   Variables. `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are the public hosted
   values from `.env.production` (the `VITE_` ones). Enter
   `PERSONAL_OBSERVABILITY_APP_PASSWORD` and `HEVY_API_KEY` directly in the editor.
   `RAILWAY_DOCKERFILE_PATH=/scripts/hevy/Dockerfile` makes Railway build the Hevy
   image rather than the Garmin one.
3. Attach a persistent volume named `hevy-data` at `/data`. The worker refuses to
   run on Railway without one.
4. Set the cron schedule to `17 * * * *` (17 minutes past each hour, UTC). Hevy asks
   clients not to poll exactly on the hour, and Garmin already uses `:05`. Leave the
   start command empty: the image defaults to `sync` and exits when done.
5. Do not generate a Railway domain.

## 3. Create the app session

With the credentials set, every run signs in afresh, so no state needs uploading
(unlike Garmin's token store). To confirm the credentials and volume work, run
`setup` once in the service's environment, for example:

```powershell
railway run --service hevy-sync python hevy_sync.py setup
```

If `railway run` does not mount the volume for you, the first scheduled run is the
check instead.

## 4. Confirm the first scheduled run

Watch Railway's logs after the next `:17`. A successful run exits 0 and, on the
Integrations page, "Hevy workouts" shows a fresh "Last synced" time.

## 5. Backfill the full history

Run once, against hosted, from this machine (the Hevy key in `.env.local`, hosted
Supabase values in place of the local ones, and a hosted app login at the
prompt):

```powershell
docker compose --env-file .env.local -f docker-compose.hevy.yml run --rm hevy-sync backfill
```

It prints Hevy's workout count first. Compare that with
`select count(*) from fitness_activities where source = 'hevy'` on hosted, and with
the published app. Rerunning is harmless.

## 6. End-to-end check

Log or edit a workout in Hevy. Within the hour it should appear on the published
app, and "Last synced" should move.

## What a failed run looks like

A failed run exits non-zero, leaves stored data untouched and does not update
`sync_runs`, so "Last synced" simply goes stale. There is no alerting. Read the
Railway log:

- `InvalidApiKey` / 401: the Hevy key was revoked or Pro lapsed. Generate a new key
  in Hevy's web settings and update `HEVY_API_KEY`.
- App sign-in errors: check the two `PERSONAL_OBSERVABILITY_APP_*` variables.
- "Railway requires a persistent volume": the volume is missing or not at `/data`.
- Any other error names its type only; rerun manually and compare with the local
  `sync` output.

A worker that is down for more than seven days can miss edits and deletions; run
`backfill` to repair.

[issue]: https://github.com/testiestshark/personal-observability/issues/41
