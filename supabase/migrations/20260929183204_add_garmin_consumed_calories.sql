-- Food intake that MyFitnessPal sends to Garmin Connect, read back from Garmin's
-- daily summary. Null for days before the accounts were linked.

alter table public.daily_health_metrics
  add column consumed_calories_kcal integer,
  add constraint daily_health_metrics_consumed_calories_non_negative
    check (consumed_calories_kcal is null or consumed_calories_kcal >= 0);
