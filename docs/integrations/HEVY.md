# Direct Hevy strength-workout integration

**Status: Designed (2026-09-29) / Sync tracer built (2026-09-30), local only / Deletions built (#38), local only / Exercises and sets stored (#37), local only / Backfill built (#39), local only / Railway deployment not yet built**

Hevy is the source of truth for detailed strength training. Personal
Observability will use Hevy's documented public API directly; no intermediary
activity platform is part of the architecture.

```text
Hevy app -> Hevy public API -> Railway cron worker -> Supabase -> Personal Observability
```

The Hevy API key is a secret. Store it only in Railway/local secret configuration,
never in source control, browser code, logs, or chat.

## Design

Agreed on 2026-09-29 in [#21][issue], after probing the real API (results in the
[issue comment][probe-results]). Terms follow [CONTEXT.md](../../CONTEXT.md).

- **Storage.** Each workout is one `fitness_activities` row (`source = 'hevy'`,
  `provider = 'hevy_public_api'`, `external_id` = workout `id`,
  `activity_type = 'strength_training'`). Its exercises and sets go in two child
  tables, each following the ownership pattern in
  [supabase/README.md](../../supabase/README.md). An exercise keeps its
  `exercise_template_id` and its title at the time of logging; the exercise-template
  catalogue is not synced.
- **Totals on the fitness activity.** `total_sets` counts every set, `active_sets`
  the non-warmup sets; `total_reps` and `total_volume_kg` (weight × reps) count
  non-warmup sets only; `duration_seconds` is `end_time − start_time`. Calories and
  heart rate stay null.
- **Local day.** `start_time` converted to `Europe/London`. Never `created_at`: 477
  of 493 workouts share a `created_at` from a bulk import.
- **Runtime.** A Python Railway cron service under `scripts/hevy/`, hourly at a
  non-zero minute, signing in as the app user exactly as the
  [Garmin worker](RAILWAY.md) does, so every write goes through RLS.
- **Sync.** Stateless: each run reads `events?since=<now − 7 days>` and applies the
  events oldest first. `updated` upserts the fitness activity in place and replaces
  its exercises and sets in one transaction; `deleted` hard-deletes it. This is safe
  without a stored watermark because the endpoint holds one event per workout (its
  latest state) and an edit moves a workout back into the window. A run only misses
  changes if the worker is down for more than 7 days.
- **Backfill.** A `backfill` command reads `events?since=1970-01-01T00:00:00Z`, run
  once locally against hosted Supabase. Rerunning it is harmless.
- **Failures.** A `401 InvalidApiKey` (revoked key or lapsed Pro) or any other error
  fails the run and leaves stored data untouched. The Integrations page's "Last
  synced" line going stale is the signal; there is no alerting.
- **Last synced.** Each successful run records its time in `sync_runs` (one row per
  owner and source, `last_succeeded_at`), written only after every operation
  succeeds. The Integrations page reads it through `getHevySyncStatus`. It does not use the newest workout row, as
  Garmin does with daily health rows: a week without training would then look the
  same as a broken sync.
- **UI in scope.** Only that "Last synced" line. Workouts already appear on the day
  view through `fitness_activities`. A workout detail view and per-exercise progress
  charts are follow-up issues.
- **Not built.** Correlating Garmin and Hevy records (see
  [NON_GOALS.md](../NON_GOALS.md)) and the webhook, which cannot replace polling.

## Running the worker locally

The worker ([#36][tracer], [#37][sets]) is `scripts/hevy/hevy_sync.py`, standard
library only. `sync` reads the last 7 days of `updated` events and writes each
workout through the `replace_fitness_workout(payload jsonb)` function: in one
transaction it upserts the fitness activity (keeping its id), deletes its exercises
(their sets cascade) and inserts the new ones, so the database always holds a
snapshot of what Hevy holds and a payload that fails partway changes nothing. The
function is `security invoker` and executable by `authenticated` only; the owner is
always `auth.uid()`. A bad workout is reported and the rest are still written, but
the run exits non-zero. `deleted` events hard-delete the fitness activity (a missing
row is not an error), and operations run oldest first, so the newest event for a
workout wins. With local Supabase
running and `HEVY_API_KEY` in `.env.local`:

```powershell
docker compose --env-file .env.local -f docker-compose.hevy.yml run --rm hevy-sync setup
docker compose --env-file .env.local -f docker-compose.hevy.yml run --rm hevy-sync sync
docker compose --env-file .env.local -f docker-compose.hevy.yml run --rm hevy-sync backfill
docker compose --env-file .env.local -f docker-compose.hevy.yml run --rm hevy-sync test
```

After a migration or policy change, run
`scripts/verify-fitness-workout-rls.sql` (it needs two local accounts and rolls
back; the header says how). It checks the `anon` grants, the four policies per
table, the function's privileges, atomicity and that a second account can touch
nothing of the first account's. `scripts/verify-sync-runs-rls.sql` does the same for
`sync_runs`:

```powershell
Get-Content scripts/verify-sync-runs-rls.sql | docker exec -i supabase_db_personal_observability psql -U postgres -v ON_ERROR_STOP=1
```

`backfill` reads `events?since=1970-01-01T00:00:00Z` across every page and applies
the events with the same planner and writes as `sync`, so rerunning it (or running
`sync` afterwards) leaves the data unchanged. It prints Hevy's `/v1/workouts/count`
first, then page and write progress as counts only; compare that count with
`select count(*) from fitness_activities where source = 'hevy'`.

`setup` signs in to the app once and keeps the session in `.hevy-sync/`
(gitignored), separate from the Garmin worker's. Railway variables are listed in
`scripts/hevy/railway.env.example`.

The reference below is the research the design was built on. Where it and this
section disagree (the stored-watermark algorithm, re-fetching workouts after
events), this section wins.

## Hevy public API reference

Researched 2026-09-23 against Hevy's own sources only. The API spec is at version
`0.0.1` and Hevy states it may change or be abandoned ([spec][spec]), so re-check the
spec before implementing. Claims marked **unverified** could not be confirmed from a
primary source; **inferred** means reasoned from primary material but not stated.

Where the facts come from:

- **[spec]**: the OpenAPI 3.0.0 document embedded in the Swagger UI at
  [api.hevyapp.com/docs][docs]. Hevy does not publish it as a standalone JSON file.
  The raw document is inline in [`swagger-ui-init.js`][spec].
- **[web app]**: the Developer section of Hevy's settings page at
  [hevy.com/settings?developer][settings], read from the page's JavaScript
  (`pages/settings-*.js` and the shared app chunk). The page itself needs a login.
- **[probe]**: unauthenticated requests made on 2026-09-23. No API key was used.

### Differences from the plan above

1. **Events already contain the full workout.** An `updated` event embeds a complete
   `Workout` object, so the "then fetch … workout details" step is not needed for
   updates ([spec][spec], schema `UpdatedWorkout`). Fetching again is harmless, just
   redundant.
2. **A webhook exists, but Hevy's settings UI documents it, not the spec.** It fires
   only for **newly created** workouts and delivers only an ID
   ([web app][settings]). Polling `/v1/workouts/events` is still needed for edits and
   deletions. See [Webhooks](#webhooks).
3. **Exercises and sets have no IDs.** The only stable Hevy identifier inside a
   workout is the workout `id`. Exercises and sets are positional (`index`). See
   [Identifiers](#identifiers-and-idempotency).

Otherwise the plan is consistent with the sources: the events endpoint does report
updates and deletions, the API is Pro-only, and there is one secret key per account.

### Access and authentication

| Question           | Answer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Source                            |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| Pro only?          | Yes. "Currently, this API is only available to Hevy Pro users." In the web app, the "Generate API Key" button opens a paywall (`no-api-access`) for non-Pro accounts.                                                                                                                                                                                                                                                                                                                         | [spec][spec], [web app][settings] |
| Where to get a key | Hevy **web** app → Settings → **Developer**: [https://hevy.com/settings?developer][settings]. Click "Generate API Key", then copy it.                                                                                                                                                                                                                                                                                                                                                         | [spec][spec], [web app][settings] |
| How it is sent     | HTTP header `api-key: <key>`. The key is a UUID (`format: uuid`). It is not a Bearer token.                                                                                                                                                                                                                                                                                                                                                                                                   | [spec][spec]                      |
| Rotate / revoke    | The Developer page has a "Revoke API Key" button, with the confirmation "Are you sure you want to delete this API Key? It'll be gone forever." A new key can then be generated. The page shows one key per account. **Inferred:** rotating means revoke and then generate; there is no overlap window.                                                                                                                                                                                        | [web app][settings]               |
| Pro lapses         | **Unverified.** No source says what happens to an existing key when Pro ends.                                                                                                                                                                                                                                                                                                                                                                                                                 | —                                 |
| Terms of use       | The API is "use at your own risk"; Hevy makes "no guarantees that we won't completely change the structure or abandon the project entirely". The current [Terms][terms-current] do not mention the API. The [Terms effective 2026-10-30][terms-new] give a "personal, non-exclusive, non-transferable … right to use the Services for personal purposes" and forbid commercial use without written authorisation. **Inferred:** a private, single-user sync of your own data is personal use. | [spec][spec], [terms][terms-new]  |
| Support contact    | `pavel@hevyapp.com` (named in the spec).                                                                                                                                                                                                                                                                                                                                                                                                                                                      | [spec][spec]                      |

### Base URL and versioning

- Base URL: `https://api.hevyapp.com`. The spec declares no `servers`, so Swagger UI
  uses the docs host's origin. Every path starts with `/v1` ([spec][spec]).
- Version: the path prefix `/v1`; the spec's `info.version` is `0.0.1`. There is no
  changelog or deprecation policy ([spec][spec]).
- Hevy asks: "if … you update data from Hevy hourly or daily, please don't send your
  requests exactly at xx:00. Put some random minute instead." ([spec][spec]).

### Endpoints

Every request needs the `api-key` header. Paginated responses look like
`{ page, page_count, <items>[] }`, with `page` ≥ 1 ([spec][spec]).

| Method | Path                                          | Purpose                                                            | Params / limits                                                                                  | Documented responses                                   |
| ------ | --------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| GET    | `/v1/workouts`                                | Paginated workouts (`workouts[]`)                                  | `page` (default 1), `pageSize` (default 5, **max 10**)                                           | 200, 400 invalid page size                             |
| POST   | `/v1/workouts`                                | Create a workout                                                   | body `{ workout: {...} }`                                                                        | 201 `Workout`, 400                                     |
| GET    | `/v1/workouts/count`                          | `{ workout_count }`                                                | —                                                                                                | 200                                                    |
| GET    | `/v1/workouts/events`                         | Paged update/delete events since a date, **newest first**          | `page`, `pageSize` (max 10), `since` (string, default `1970-01-01T00:00:00Z`)                    | 200 `PaginatedWorkoutEvents`, 500                      |
| GET    | `/v1/workouts/{workoutId}`                    | One complete workout                                               | path `workoutId`                                                                                 | 200 `Workout`, 404                                     |
| PUT    | `/v1/workouts/{workoutId}`                    | Replace a workout                                                  | body as for POST                                                                                 | 200 `Workout`, 400                                     |
| GET    | `/v1/user/info`                               | `{ data: { id, name, url } }`                                      | —                                                                                                | 200, 404                                               |
| GET    | `/v1/routines`                                | Paginated routines                                                 | `page`, `pageSize` (max 10)                                                                      | 200, 400                                               |
| POST   | `/v1/routines`                                | Create a routine                                                   | body                                                                                             | 201, 400, 403 limit exceeded                           |
| GET    | `/v1/routines/{routineId}`                    | One routine, wrapped as `{ routine }`                              | —                                                                                                | 200, 400                                               |
| PUT    | `/v1/routines/{routineId}`                    | Update a routine                                                   | body                                                                                             | 200, 400, 404                                          |
| GET    | `/v1/exercise_templates`                      | Built-in and custom exercise templates                             | `page`, `pageSize` (**max 100**)                                                                 | 200, 400                                               |
| POST   | `/v1/exercise_templates`                      | Create a custom exercise                                           | body `{ exercise: { title, exercise_type, equipment_category, muscle_group, other_muscles[] } }` | 200 `{ id }`, 400, 403 `exceeds-custom-exercise-limit` |
| GET    | `/v1/exercise_templates/{exerciseTemplateId}` | One template                                                       | —                                                                                                | 200, 404                                               |
| GET    | `/v1/routine_folders`                         | Paginated routine folders                                          | `page`, `pageSize` (max 10)                                                                      | 200, 400                                               |
| POST   | `/v1/routine_folders`                         | Create a folder (inserted at index 0)                              | body                                                                                             | 201, 400                                               |
| GET    | `/v1/routine_folders/{folderId}`              | One folder                                                         | —                                                                                                | 200, 404                                               |
| GET    | `/v1/exercise_history/{exerciseTemplateId}`   | Every logged set of one exercise, flattened (`exercise_history[]`) | optional `start_date`, `end_date` (ISO 8601 date-time). **Not paginated.**                       | 200, 400                                               |
| GET    | `/v1/body_measurements`                       | Paginated body measurements                                        | `page`, `pageSize` (default 10, max 10)                                                          | 200, 400, 404 page not found                           |
| POST   | `/v1/body_measurements`                       | Create an entry for a date                                         | body `BodyMeasurement`                                                                           | 200, 400, 409 date exists                              |
| GET    | `/v1/body_measurements/{date}`                | One entry by `YYYY-MM-DD`                                          | —                                                                                                | 200, 404                                               |
| PUT    | `/v1/body_measurements/{date}`                | Overwrite an entry. **Omitted fields become null.**                | body                                                                                             | 200, 400, 404                                          |

Write capabilities: the API can create and update workouts, routines and body
measurements, and can create routine folders and custom exercise templates. **No
endpoint deletes anything** ([spec][spec]). Personal Observability only needs the GET
endpoints. Never call `PUT /v1/workouts/{id}`: it replaces the whole workout in the
user's real training log.

### Workout data model

From the `Workout`, `Exercise` and `Set` schemas ([spec][spec]). The spec marks no
response fields as required, so treat every field as possibly missing. Fields
documented as nullable are marked "null?".

**Workout**

| Field         | Type             | Notes                                                                             |
| ------------- | ---------------- | --------------------------------------------------------------------------------- |
| `id`          | string (UUID)    | The stable workout identifier.                                                    |
| `title`       | string           | Can contain emoji.                                                                |
| `routine_id`  | string           | "The ID of the routine that this workout belongs to." Nullability is not stated.  |
| `description` | string           | The workout-level note.                                                           |
| `start_time`  | string, ISO 8601 | "when the workout was recorded to have started". Examples use a `Z` (UTC) suffix. |
| `end_time`    | string, ISO 8601 | Duration = `end_time − start_time`. There is no separate duration field.          |
| `updated_at`  | string, ISO 8601 | Last update.                                                                      |
| `created_at`  | string, ISO 8601 | Creation.                                                                         |
| `exercises`   | array            | See Exercise.                                                                     |

**Exercise** (inside a workout)

| Field                  | Type          | Notes                                                                              |
| ---------------------- | ------------- | ---------------------------------------------------------------------------------- |
| `index`                | number        | Order in the workout. There is no exercise ID.                                     |
| `title`                | string        | Display name at the time of logging, e.g. "Bench Press (Barbell)".                 |
| `notes`                | string        | The exercise note.                                                                 |
| `exercise_template_id` | string        | Key into `/v1/exercise_templates`. The example is `"05293BCA"` (8 hex characters). |
| `superset_id`          | number, null? | Exercises that share a value form one superset. `null` means not in a superset.    |
| `sets`                 | array         | See Set.                                                                           |

**Set**

| Field              | Type          | Unit / values                                                                                                   |
| ------------------ | ------------- | --------------------------------------------------------------------------------------------------------------- |
| `index`            | number        | "order of the set in the workout". **Unverified** whether this counts per exercise or across the whole workout. |
| `type`             | string        | `normal`, `warmup`, `dropset`, `failure`                                                                        |
| `weight_kg`        | number, null? | **Kilograms**, whatever the user's display unit.                                                                |
| `reps`             | number, null? | Count                                                                                                           |
| `distance_meters`  | number, null? | **Metres**                                                                                                      |
| `duration_seconds` | number, null? | **Seconds**                                                                                                     |
| `rpe`              | number, null? | RPE. The write schema limits it to `6, 7, 7.5, 8, 8.5, 9, 9.5, 10`; the app's scale is 6–10 ([help][help-rpe]). |
| `custom_metric`    | number, null? | "Currently only used to log floors or steps for stair machine exercises"                                        |

Which of the nullable set fields are filled in depends on the template's `type`
(`CustomExerciseType`): `weight_reps`, `reps_only`, `bodyweight_reps`,
`bodyweight_assisted_reps`, `duration`, `weight_duration`, `distance_duration`,
`short_distance_weight`. **Unverified:** whether `weight_kg` for
`bodyweight_assisted_reps` means assistance or load.

**ExerciseTemplate** fields: `id` (string), `title`, `type`, `primary_muscle_group`,
`secondary_muscle_groups[]`, `equipment` (`none`, `barbell`, `dumbbell`,
`kettlebell`, `machine`, `plate`, `resistance_band`, `suspension`, `other`) and
`is_custom` (boolean). Muscle groups: `abdominals`, `shoulders`, `biceps`, `triceps`,
`forearms`, `quadriceps`, `hamstrings`, `calves`, `glutes`, `abductors`, `adductors`,
`lats`, `upper_back`, `traps`, `lower_back`, `chest`, `cardio`, `neck`, `full_body`,
`other` ([spec][spec]).

The ID type is inconsistent. `ExerciseTemplate.id` is a string, with a UUID in one
example and `"05293BCA"` in another, but `POST /v1/exercise_templates` returns
`{ id: integer }`. Store template IDs as text ([spec][spec]).

**BodyMeasurement**: `date` (`YYYY-MM-DD`, required), `weight_kg`, `lean_mass_kg`,
`fat_percent`, `neck_cm`, `shoulder_cm`, `chest_cm`, `left_bicep_cm`,
`right_bicep_cm`, `left_forearm_cm`, `right_forearm_cm`, `abdomen`, `waist`, `hips`,
`left_thigh`, `right_thigh`, `left_calf`, `right_calf`, all nullable numbers. The
last eight have no unit suffix. **Inferred:** they are centimetres, like the
`*_cm` fields ([spec][spec]). There is one entry per calendar date (POST returns 409
if one already exists).

#### Timestamps and time zones

All workout timestamps are ISO 8601 strings, and every example ends in `Z`
([spec][spec]). **No field gives the user's time zone or UTC offset.** A workout's
local calendar date cannot be derived from the API alone. Personal Observability has
to apply its own time-zone rule when bucketing workouts by day, which is the kind of
date/time-zone logic [CLAUDE.md](../../CLAUDE.md) says to test. **Unverified:**
whether the API ever returns non-UTC offsets. Parse with a real ISO 8601 parser
rather than assuming a `Z` suffix.

Body measurements are keyed by a plain calendar `date` with no time zone.

### Incremental sync: `/v1/workouts/events`

What the spec says ([spec][spec]):

- Purpose: "allow clients to keep their local cache of workouts up to date without
  having to fetch the entire list of workouts."
- `GET /v1/workouts/events?since=<ISO 8601>&page=<n>&pageSize=<≤10>`. `since` is a
  string defaulting to `1970-01-01T00:00:00Z`.
- Events are "ordered from newest to oldest".
- Response: `{ page, page_count, events[] }`. Each event is one of these:
  - `{ type: "updated", workout: Workout }`: the full current workout.
  - `{ type: "deleted", id: string, deleted_at?: string }`. Only `type` and `id` are
    required; `deleted_at` is optional.

Not stated in the spec, but **observed** with the real key on 2026-09-29
([probe results][probe-results]):

- A newly created workout appears as an `updated` event.
- There is **one event per workout**, carrying its latest state (495 events, 495
  distinct ids), not a history of changes.
- `since` is compared against `updated_at` (and `deleted_at` for deletions),
  **inclusively** (`≥`).
- `since=1970-01-01T00:00:00Z` returns every workout, so the events endpoint alone
  can backfill.
- Deletion events were still present after about 5 weeks. The upper bound is
  **unverified**.

Research-time sync algorithm (**superseded** by the stateless 7-day window in
[Design](#design); kept for the reasoning):

1. **Backfill once**: page through `GET /v1/workouts?pageSize=10` until
   `page > page_count` and upsert every workout. Check the total against
   `/v1/workouts/count`.
2. **Save a watermark** `T0` equal to the time the backfill _started_, not ended.
3. **Each poll**, at a random minute: record `now` and request `events?since=<watermark − overlap>`,
   with an overlap of a few minutes to cover clock skew and the unclear `>`/`≥`
   comparison. Read every page from 1 to `page_count`. Collect all events, then
   apply them **oldest first** (reverse the order) so a delete that follows an update
   wins.
   - `updated`: upsert the workout by `(user_id, hevy workout id)`. Replace its
     exercises and sets as one unit (delete the existing child rows and insert the
     new ones in one transaction). Exercises and sets have no IDs, so they cannot be
     upserted one by one. Skip the write if the stored `updated_at` is not older.
   - `deleted`: delete the workout by ID, or soft-delete it (keep provenance). A
     missing row is not an error.
4. Only after every page has been applied successfully, set the watermark to the
   `now` recorded in step 3. If anything fails, keep the old watermark; the next run
   replays the same window, which is safe because steps 3a and 3b are idempotent.
5. Offset paging over a newest-first list can repeat an item across pages if events
   arrive mid-read (**inferred**). Idempotent application makes a repeat harmless.

The `workoutId` delivered by the webhook (below) could trigger an earlier poll, or a
`GET /v1/workouts/{id}`, but it cannot replace step 3.

### Identifiers and idempotency

- Workout: `id` (UUID string) is the only stable key. Use `(user_id, source =
'hevy', external_id = workout.id)` as the natural key.
- Exercise within a workout: `(workout.id, exercise.index)`. It is positional, so
  reordering in the app changes it.
- Set: `(workout.id, exercise.index, set.index)`. Also positional. **Observed:**
  `set.index` restarts at 0 for each exercise (2,650 of 2,650 exercises).
- Exercise template: `exercise_template_id` (text). Titles can change, and custom
  templates belong to the user (`is_custom`).
- Hevy user: `/v1/user/info` returns `data.id` (UUID). It could detect a key that
  belongs to a different Hevy account; the design does not check it (single user,
  one key).

### Webhooks

Hevy's settings page offers a webhook, but the OpenAPI spec does not document it
([web app][settings]):

- The UI text says: "Subscribe to our webhook and get notified when you save a new
  workout. When a new workout is created, we will send a POST request to your provided
  URL with the following JSON payload, and we expect your application to respond with
  a 200 OK status code within 5 seconds."
- The example payload in the page is `{ "workoutId": "<uuid>" }`.
- The user enters a URL and an "authorization header, that we'll send along with the
  provided url" (placeholder `Bearer myauthtoken`). This is a shared secret the
  receiver should check. There is no signature or HMAC.
- There is one subscription per account; the page loads and saves a single
  `{ url, auth_token }`.
- **Unverified:** retries after a failure or timeout, delivery guarantees, events for
  edits or deletions (the text says only "new workout"), and whether a subscription
  can be removed. The web app calls an internal `webhook-subscription` route. On the
  public API, `GET /v1/webhook-subscription` returned `401 InvalidApiKey` rather than
  404 ([probe]), which suggests an undocumented public route. With a valid key it
  returns `404 Webhook subscription not found` when none is set (2026-09-29), which
  confirms the route exists. Community clients
  describe get/create/delete operations on it: unverified (secondary:
  [chrisdoc/hevy-mcp][hevy-mcp]).

### Rate limits and errors

- **Rate limits: none documented.** The spec has no 429 response, and an
  unauthenticated probe showed no rate-limit headers ([probe]). With a real key, 30
  sequential requests all returned `200` in about 95 ms with no rate-limit headers
  (2026-09-29). The only guidance is to avoid requests exactly on the hour
  ([spec][spec]). Poll modestly; a 429 or 5xx fails the run.
- **Auth failure**: a missing or invalid key returns `401` with the plain-text body
  `InvalidApiKey`, not JSON ([probe]). 401 is not in the spec.
- **Documented codes** ([spec][spec]): `400` (invalid page size or body; bodies
  `{ error: string }`), `403` (routine or custom-exercise limit), `404` (not found),
  `409` (body measurement already exists for the date), `500` (listed for the events
  endpoint).

### Documented gaps

None of the following appear in the spec ([spec][spec]):

- **Time zone** of a workout (see above).
- **Heart rate, calories, workout volume, and personal records**: these are
  computed in the app but have no API fields.
- **Per-set rest time or completion time.** Routines have `rest_seconds`; workouts do not.
- **Body weight on a workout.** Use `/v1/body_measurements` (`weight_kg` by date)
  instead.
- **Workout privacy/visibility** in responses. `is_private` exists only on the write
  body.
- **DELETE endpoints**, **OAuth** (the key is per account), and **webhooks** in the
  spec itself.
- Cardio exists only as set-level `distance_meters` / `duration_seconds` on
  distance/duration exercise types. There are no GPS, pace or elevation fields.

Hevy's in-app CSV export (Profile → Settings → Export & Import Data → Export Data)
covers workouts and measurements and could be a manual backfill source
([help][help-export]). Its columns are not documented.

### Observations relevant to the design (not decisions)

- **A long-running worker is not required by the API.** Sync is short, paged HTTP GETs
  on a schedule, plus an optional small webhook receiver. A scheduled Supabase Edge
  Function, a scheduled server function, or a Railway cron job would each work. The
  webhook needs a public HTTPS endpoint that answers within 5 s
  ([web app][settings]).
- **Webhook-only sync is not enough.** It covers only new workouts, so edits and
  deletions still need the events poll.
- **Writing through RLS from a headless job** needs a stored user session; it cannot
  use `service_role`, per [CLAUDE.md](../../CLAUDE.md). Resolved: the Garmin Railway
  worker already does this with a refresh token on a volume, and Hevy copies it.
- **The key is powerful.** One Hevy key can also overwrite workouts (`PUT`), routines
  and body measurements. Hevy offers no read-only or scoped keys. That is another
  reason to keep it server-side only.
- **Strava overlap.** Workouts from Hevy may also reach Strava
  ([help][help-strava]). Keep the source records separate.
- **Timestamp formats differ.** `start_time` and `end_time` end in `+00:00`;
  `created_at` and `updated_at` end in `Z` with milliseconds (observed 2026-09-29).

### Open questions

Answered on 2026-09-29 (see above): new workouts as `updated` events, what `since`
compares against, `set.index` scope, and observed rate limits. Still open, and none
blocks the design:

- What happens to the key if Pro lapses, and how long deletion events are kept
  beyond about 5 weeks (ask `pavel@hevyapp.com`). A lapse fails the run; a 7-day
  window only needs deletions kept for 7 days.
- Webhook retry behaviour, and whether edits or deletes ever fire it. Not needed:
  the design does not use the webhook.

### Sources

Accessed 2026-09-23.

- [Hevy Public API Docs (Swagger UI)][docs] and the embedded OpenAPI 3.0.0 document in
  [`swagger-ui-init.js`][spec]: primary.
- [Hevy web app, Settings → Developer][settings] (UI strings and view model in
  `hevy.com/_next/static/chunks/pages/settings-*.js`): primary.
- [Hevy Terms and Conditions (current)][terms-current] and
  [Terms effective 2026-10-30][terms-new]: primary.
- Hevy Help Centre: [Exporting Your Data from Hevy][help-export],
  [RPE vs RIR][help-rpe], [Using Hevy with Strava][help-strava]: primary. No
  help-centre article covers the public API.
- Unauthenticated `curl` probes of `api.hevyapp.com` (no API key): first-hand
  observation.
- [chrisdoc/hevy-mcp][hevy-mcp]: secondary, used only as a lead for the webhook
  route.
- Hevy's GitHub org [github.com/hevyapp](https://github.com/hevyapp) has no API spec or
  SDK repository (3 repos: `.github`, `heroku-buildpack`, `hevy-gpt`).

[docs]: https://api.hevyapp.com/docs/
[spec]: https://api.hevyapp.com/docs/swagger-ui-init.js
[settings]: https://hevy.com/settings?developer
[terms-current]: https://www.hevyapp.com/legal/terms-and-conditions/
[terms-new]: https://www.hevyapp.com/terms/
[help-export]: https://help.hevyapp.com/hc/en-us/articles/43708290987415-Exporting-Your-Data-from-Hevy
[help-rpe]: https://help.hevyapp.com/hc/en-us/articles/34490600233111-RPE-vs-RIR-What-They-Mean-and-How-to-Use-Them-in-Hevy
[help-strava]: https://help.hevyapp.com/hc/en-us/articles/38279744541591-Using-Hevy-with-Strava-Setup-Syncing-and-Editing-Workouts
[hevy-mcp]: https://github.com/chrisdoc/hevy-mcp
[issue]: https://github.com/testiestshark/personal-observability/issues/21
[probe-results]: https://github.com/testiestshark/personal-observability/issues/21#issuecomment-5896520860
[tracer]: https://github.com/testiestshark/personal-observability/issues/36
[sets]: https://github.com/testiestshark/personal-observability/issues/37
