# Archived Garmin-to-Terra design

**Status: Superseded on 2026-09-06 — do not implement**

Terra was rejected because its entry pricing is disproportionate for this
single-user app. The active automatic integration is the local Garmin Connect
bridge in [GARMIN.md](GARMIN.md). The original design remains below only as a
record of the abandoned approach.

This document describes the intended integration boundary and data flow. It does
not describe behavior that exists today, and it does not define a final database
schema.

## Purpose and responsibility

Terra is intended to provide access to Garmin health and wellness data without
requiring Personal Observability to depend directly on Garmin's developer API in
the first implementation:

```text
Garmin Watch -> Garmin Connect -> Terra -> Personal Observability backend -> database
```

Terra and Garmin are responsible primarily for **daily health and wellness**
data. Discrete fitness activities belong primarily to the Strava integration.
The Personal Observability database remains the canonical aggregation and
long-term historical layer; Terra is an external data provider, not the
platform's source of truth.

## Initial data scope

The first implementation should deliberately ingest a small, useful set of
daily metrics rather than every metric Terra exposes. Candidate metrics are:

- Steps.
- Sleep duration.
- Sleep stages where available.
- Resting heart rate.
- Heart-rate variability (HRV).
- Calories.
- Distance.
- Stress where available.
- Other Garmin daily or wellness metrics only when they have a clear initial
  product use.

The exact set should be finalized after validating Terra's Garmin payloads,
field semantics, units, availability, and update behavior. Unsupported or
missing measurements must remain missing; they should not be inferred as zero.

Activities are intentionally outside the initial Terra scope. This keeps the
provider responsibilities clear and reduces the risk of duplicating Garmin
workouts that also reach Strava.

## Planned integration mechanism

The likely flow is:

```text
Garmin sync -> Terra -> webhook/API -> backend -> normalized database records
```

At a high level, the integration should:

1. Associate the Garmin connection exposed by Terra with the Personal
   Observability user.
2. Receive relevant Terra webhook events and fetch additional data through the
   Terra API where required.
3. Verify webhook authenticity and acknowledge deliveries according to Terra's
   requirements.
4. Map selected Garmin/Terra measurements, dates, units, and provenance into
   internal daily health records.
5. Upsert records idempotently so retries and later corrections update the same
   logical day or measurement rather than creating duplicates.

Authentication, connection setup, webhook verification, secret storage, and the
exact normalized record shape are implementation decisions to be designed when
this integration is scheduled.

## Provider boundary

Terra must sit behind a clear integration boundary. Provider-specific payloads,
field names, authentication, pagination, and retry behavior should be translated
there rather than spread through product or database code.

The rest of Personal Observability should consume normalized health records and
should not need to know whether Garmin data arrived through Terra. This permits a
future change such as:

```text
Terra -> direct Garmin API
```

or a move to another health-data provider without redesigning unrelated parts of
the application. Replacing the provider may require a focused migration or
identifier mapping, but should not require changing the product's health-domain
model.

## Provenance and canonical history

Every normalized record should retain enough information to identify its
original source and ingestion provider. Concepts such as `source`, `provider`,
`external_id`, and `ingested_at` should be represented eventually, without
committing to a final schema here. For this flow, Garmin is the data source and
Terra is the provider through which it was ingested.

Where practical, retain provider identifiers and enough source metadata to make
webhook retries idempotent, apply provider corrections, audit mappings, and
reprocess records. The Personal Observability database owns the canonical
historical view after normalization; external services remain providers.

Daily aggregation needs explicit date, timezone, and unit rules. A Garmin daily
summary can be updated after its first delivery, especially for sleep or late
syncs, so writes should support correction rather than treating the first event
as immutable.

## Avoiding duplicate activities

Garmin may send an activity to Strava while Garmin-derived data also arrives
through Terra. The initial split of responsibility is therefore:

- Terra: daily health and wellness data.
- Strava: discrete fitness activities.

The first Terra version should not blindly ingest workout/activity objects. If
activity ingestion through Terra is considered later, it must first define
cross-provider deduplication using stable external IDs where possible, plus
source, timestamps, activity type, and duration where necessary.

## Relationship to the wider system

Terra contributes daily Garmin health and wellness records to the shared
Personal Observability history. Strava contributes discrete activities,
including strength workouts synced from Hevy, while GitHub contributes
development activity. The database combines these domains by time and date
without discarding provenance. See [Architecture](../ARCHITECTURE.md#planned-integration-architecture)
and [Hevy to Strava](HEVY_STRAVA.md).

## Open Questions / Implementation Validation

- Which exact Terra Garmin fields correspond to the initial daily metrics?
- What Terra account/access requirements apply?
- Which events are pushed via webhook versus fetched?
- How should historical Garmin data be backfilled?
- How should webhook retries and idempotency work?
- How does Terra represent later corrections to daily summaries, sleep, and
  timezone boundaries?
- Which provider identifiers can remain stable if Terra is later replaced?
