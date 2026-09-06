# Product

Personal Observability is a private, mobile-first web application for one person to collect and analyse their own life data.

## Purpose

A single-user dashboard that brings together data that's normally scattered across separate apps, so patterns across health, work, and mood become visible in one place. It is not a multi-user product, and has no public-facing or social component.

## Data domains

- GitHub activity, across two accounts
- Strava fitness activities
- Daily steps and calorie burn (Garmin sync implemented for local and hosted data)
- Weight (implemented locally)
- Computer activity
- Manually recorded iPhone Screen Time
- Mood, energy, focus, stress, and meaning
- Journal entries and daily reflections
- Weekly personal reviews

## Current stage

The application shell and authentication are implemented. Weight is wired
end-to-end, and Garmin daily health sync is operational against the hosted data;
cloud scheduling is ready for Railway account setup. See [ROADMAP.md](ROADMAP.md)
for the exact status.

## Explicit non-goals (for now)

- No OAuth integrations
- No AI features
- No payments
- No public profiles or social features
- No unnecessary dependencies

These are current-stage constraints, not permanent restrictions — revisit them as the roadmap progresses.
