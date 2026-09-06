-- Garmin's daily summary distinguishes movement calories from total energy.
-- Keep both so the UI never presents resting metabolism as exercise burn.

alter table public.daily_health_metrics
  add column active_calories_kcal integer,
  add column total_calories_kcal integer,
  add constraint daily_health_metrics_active_calories_non_negative
    check (active_calories_kcal is null or active_calories_kcal >= 0),
  add constraint daily_health_metrics_total_calories_non_negative
    check (total_calories_kcal is null or total_calories_kcal >= 0),
  add constraint daily_health_metrics_calorie_order
    check (
      active_calories_kcal is null
      or total_calories_kcal is null
      or active_calories_kcal <= total_calories_kcal
    );
