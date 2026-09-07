# Railway-hosted Garmin sync

**Status: Operational in Railway production since 2026-09-06**

Railway can run the Garmin worker as a private hourly cron job, so syncing no
longer depends on this computer or Docker Desktop being awake:

```text
Garmin Watch -> Garmin Connect -> Railway cron worker -> hosted Supabase -> published app
```

The worker starts, signs in as the existing app user, refreshes the latest seven
days, writes through Row Level Security, and exits. It does not expose a web
server or public domain. Reprocessing seven days makes missed runs and late
watch uploads self-healing.

## One-time Railway setup

1. Create a Railway project and add a service from the GitHub repository's
   `main` branch.
2. In the service variables, paste the keys from
   `scripts/garmin/railway.env.example`, substituting the two public hosted
   Supabase values from `.env.production`. Enter the app email and password
   directly in Railway's private Variables editor; never commit the password.
3. Attach a persistent volume named `garmin-data` at `/data`. The worker refuses
   to run on Railway without one, protecting the sessions from disappearing
   with an ephemeral container.
4. Set the service cron schedule to `5 * * * *` (05 minutes past each hour,
   UTC). Leave the start command empty: the Docker image defaults to `sync` and
   exits after completion.
5. Do not generate a Railway domain. This is a private outbound-only job.

The Garmin bearer session is cached locally and gitignored. Do not paste it into
variables, logs, source control, or chat. Install the Railway CLI, authenticate
it, link this folder to the new project/service, then copy the Garmin session
into the volume:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/garmin/upload-railway-state.ps1 -Volume garmin-data
```

The helper uploads `.garmin-sync/garmin/` to `/data/garmin/`. It never uploads
the Garmin password. The worker signs in to Supabase afresh on every run using
the private Railway app-login variables, avoiding shared refresh-token rotation.

If Railway's GitHub app has not been granted repository access, deploy the
checked-out commit directly instead:

```powershell
railway deployment up --service garmin-sync --environment production --detach --yes
```

Railway respects `.gitignore` for its source archive, and `.dockerignore`
independently excludes `.garmin-sync/` plus all local environment files from the
Docker build context. Granting the Railway GitHub app access later enables
automatic redeployment from `main`; it is not required for scheduled execution.

## Verify and cut over

After a deployment, manually trigger or observe the Railway cron service. A successful log ends with
text like:

```text
Synced 7 Garmin health day(s), 2026-08-31 to 2026-09-06.
```

Check that today's health and recorded activities update in the published app.
The old Windows live task is no longer required; Railway owns the production
schedule. Database writes are idempotent if a manual verification run overlaps.

If Railway reports a missing Garmin session, rerun the upload helper. If Garmin
revokes its tokens, run the existing local interactive setup again and re-upload
the refreshed state; never put the Garmin password in Railway. App-authentication
errors should be resolved by checking the two private app-login variables.

## Why the volume matters

Railway containers are replaceable. The attached `/data` volume persists the
Garmin token store and the latest app session between hourly jobs. Railway sets
`RAILWAY_VOLUME_MOUNT_PATH` automatically; the worker checks that both paths are
underneath it before contacting either provider. The app session is replaceable
because the worker signs in again at the start of every run.

## Future jobs on Railway

The same project can host other small ingestion services later—for example
GitHub contribution ingestion, Hevy workout polling, scheduled aggregation,
data-quality checks, and notification workers. Give each integration its own
service, least-privilege credentials, schedule, and volume only where persistent
state is actually required. The main web app can remain hosted separately.
