# Hevy to Strava activity integration

**Status: Planned / Not Implemented**

This document describes the intended integration boundary and data flow. It does
not describe behavior that exists today, and it does not define a final database
schema.

## Purpose and responsibility

Hevy is the dedicated strength-training application. A completed workout is
expected to sync from Hevy into Strava, after which Personal Observability can
ingest the activity through its Strava integration:

```text
Hevy -> Strava -> Personal Observability backend -> database
```

Strava is an **activity integration layer**, not the source of truth for the
whole Personal Observability platform. It is responsible for discrete fitness
activities. The Personal Observability database is the canonical aggregation
and long-term historical layer.

## Planned data scope

The first implementation should ingest only useful activity data that Strava's
read APIs actually expose, potentially including:

- Workout or activity type.
- Activity date and time.
- Duration.
- Exercise or strength information where exposed by Strava.
- Heart-rate information where available.
- Activity metadata.
- Original source or application where determinable.

The exact amount of Hevy strength detail available through Strava must be
verified during implementation. Strava displaying strength information does not
guarantee that its read APIs expose every exercise, set, repetition, or weight.
The design must not assume that level of detail until it has been observed in
real API responses from a Hevy-originated activity.

## Provenance

Ingestion must preserve both where an activity originated and how Personal
Observability received it. For a Hevy workout received through Strava, the
conceptual provenance is:

```text
source = hevy
ingestion_source = strava
```

Names such as `source`, `provider`, `external_id`, and `ingested_at` describe
concepts the eventual normalized record should retain; they are not a final
schema proposal. If Strava cannot reliably identify Hevy as the original source,
the record must represent that uncertainty rather than inventing provenance.
Raw provider identifiers and enough source metadata to investigate or reprocess
an activity should be retained where practical.

This distinction matters because Garmin activities may also sync into Strava in
the future. Recording only `strava` as the source would lose the activity's
origin and make duplicate detection harder.

## Ingestion boundary and lifecycle

The Strava integration should live behind a provider-specific boundary that is
responsible for:

1. Receiving or discovering an activity through the appropriate Strava webhook
   and API flow.
2. Fetching the permitted activity details from Strava.
3. Mapping Strava's representation into an internal activity representation.
4. Attaching provider identifiers, origin information, and ingestion metadata.
5. Writing an idempotent normalized activity record to the database.

Provider payloads should not leak into unrelated product code. Changes to
Strava's API or a future activity provider should be handled at this boundary.

Authentication, token storage, webhook verification, and the exact normalized
record shape are implementation decisions to be designed when this integration
is scheduled.

## Duplicate prevention

Strava should be the primary path for **activities**, while the local Garmin
bridge should be the primary path for Garmin **health and wellness** data. Its
initial scope should therefore not create a second copy of a workout already
received through Strava.

Activity ingestion must be idempotent. Future duplicate detection should first
use stable provider or external IDs where they are available, and may also need
to compare:

- Original source and ingestion provider.
- Start timestamps, with explicit timezone handling.
- Activity type.
- Duration.

Heuristic matching should be a fallback rather than a replacement for stable
identifiers. If Garmin activity ingestion through the health bridge is ever
added, that change requires an explicit cross-provider identity and
deduplication design.

## Relationship to the wider system

This integration contributes discrete workouts to the shared Personal
Observability timeline. Daily Garmin health and wellness summaries arrive by a
separate Garmin-health boundary, while GitHub contributes development activity. The
database combines those records by time and date while retaining each record's
origin and ingestion path. See [Architecture](../ARCHITECTURE.md#integration-architecture)
and [Garmin health and wellness](GARMIN.md).

## Open Questions / Implementation Validation

- What strength-specific fields does the Strava API expose when an activity
  originates from Hevy?
- Can the original app/source be reliably identified?
- What webhook events should Personal Observability subscribe to?
- How should historical activity backfill work?
- Which stable identifiers are available for idempotency and cross-provider
  duplicate detection?
- What permissions and retention rules apply to heart-rate and other sensitive
  activity data?
