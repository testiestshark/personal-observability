-- The daily calorie goal the owner sets in MyFitnessPal, read back from Garmin's
-- daily summary (netCalorieGoal). Stored per day, as Garmin reports it for that
-- day; the sync re-fetches the last seven days, so whether a goal change leaves
-- recent days untouched depends on Garmin. Null before the accounts were linked.

alter table public.daily_health_metrics
  add column calorie_goal_kcal integer,
  add constraint daily_health_metrics_calorie_goal_non_negative
    check (calorie_goal_kcal is null or calorie_goal_kcal >= 0);
