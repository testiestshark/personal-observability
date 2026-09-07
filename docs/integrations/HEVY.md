# Direct Hevy strength-workout integration

**Status: Planned / API access purchased / Not Implemented**

Hevy is the source of truth for detailed strength training. Personal
Observability will use Hevy's documented public API directly; no intermediary
activity platform is part of the architecture.

```text
Hevy app -> Hevy public API -> Railway worker -> Supabase -> Personal Observability
```

The first implementation should ingest completed workouts, exercises, individual
sets, weights, repetitions, set types, RPE, notes, and stable Hevy identifiers.
Incremental synchronization should poll `/v1/workouts/events` for updates and
deletions, then fetch and idempotently upsert the affected workout details.

The Hevy API key is a secret. Store it only in Railway/local secret configuration,
never in source control, browser code, logs, or chat. The integration must write
through the authenticated app user's Supabase session so existing ownership RLS
continues to apply.

Garmin may also contain a summary of a strength activity recorded on the watch.
That Garmin record and the Hevy workout are distinct source records. A future UI
may correlate them using start time and duration, but ingestion must not guess that
two records are identical or discard either provider's data.
