-- Sleep score is intentionally outside the product's Garmin health snapshot.
-- Remove it from storage; ingestion and presentation are removed in application code.
alter table public.daily_health_metrics
  drop constraint if exists daily_health_metrics_sleep_score_valid,
  drop column if exists sleep_score;
