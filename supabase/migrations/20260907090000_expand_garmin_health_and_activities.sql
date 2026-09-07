-- Extend the Garmin boundary with the deliberately small recovery snapshot and
-- discrete recorded activities. Detailed strength exercises and sets belong to
-- the separate Hevy integration, not this Garmin activity summary.

alter table public.daily_health_metrics
  add column sleep_start_at timestamptz,
  add column sleep_end_at timestamptz,
  add column total_sleep_seconds integer,
  add column sleep_score smallint,
  add column resting_heart_rate_bpm smallint,
  add column vo2_max double precision,
  add column source_synced_at timestamptz,
  add constraint daily_health_metrics_sleep_duration_valid
    check (total_sleep_seconds is null or total_sleep_seconds between 0 and 86400),
  add constraint daily_health_metrics_sleep_window_valid
    check (
      sleep_start_at is null
      or sleep_end_at is null
      or sleep_start_at <= sleep_end_at
    ),
  add constraint daily_health_metrics_sleep_score_valid
    check (sleep_score is null or sleep_score between 0 and 100),
  add constraint daily_health_metrics_resting_hr_valid
    check (resting_heart_rate_bpm is null or resting_heart_rate_bpm between 1 and 300),
  add constraint daily_health_metrics_vo2_max_valid
    check (vo2_max is null or vo2_max > 0);

create table public.fitness_activities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  source text not null,
  provider text not null,
  external_id text not null,
  activity_name text,
  activity_type text not null,
  local_day date not null,
  started_at timestamptz not null,
  duration_seconds double precision,
  moving_duration_seconds double precision,
  elapsed_duration_seconds double precision,
  distance_meters double precision,
  calories_kcal integer,
  average_heart_rate_bpm integer,
  maximum_heart_rate_bpm integer,
  elevation_gain_meters double precision,
  elevation_loss_meters double precision,
  average_speed_mps double precision,
  maximum_speed_mps double precision,
  average_cadence_spm double precision,
  maximum_cadence_spm double precision,
  average_power_watts double precision,
  maximum_power_watts double precision,
  normalized_power_watts double precision,
  aerobic_training_effect double precision,
  anaerobic_training_effect double precision,
  training_load double precision,
  training_effect_label text,
  total_sets integer,
  active_sets integer,
  total_reps integer,
  total_volume_kg double precision,
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),

  constraint fitness_activities_source_known check (source in ('garmin', 'hevy')),
  constraint fitness_activities_provider_known
    check (provider in ('garmin_connect_unofficial', 'hevy_public_api')),
  constraint fitness_activities_user_source_external_unique
    unique (user_id, source, external_id),
  constraint fitness_activities_duration_non_negative
    check (
      (duration_seconds is null or duration_seconds >= 0)
      and (moving_duration_seconds is null or moving_duration_seconds >= 0)
      and (elapsed_duration_seconds is null or elapsed_duration_seconds >= 0)
    ),
  constraint fitness_activities_measurements_non_negative
    check (
      (distance_meters is null or distance_meters >= 0)
      and (calories_kcal is null or calories_kcal >= 0)
      and (elevation_gain_meters is null or elevation_gain_meters >= 0)
      and (elevation_loss_meters is null or elevation_loss_meters >= 0)
      and (total_sets is null or total_sets >= 0)
      and (active_sets is null or active_sets >= 0)
      and (total_reps is null or total_reps >= 0)
      and (total_volume_kg is null or total_volume_kg >= 0)
    )
);

create index fitness_activities_user_started_idx
  on public.fitness_activities (user_id, started_at desc);

alter table public.fitness_activities enable row level security;

revoke all on public.fitness_activities from anon;
grant select, insert, update, delete on public.fitness_activities to authenticated;

create policy "Users can read their own fitness activities"
  on public.fitness_activities for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own fitness activities"
  on public.fitness_activities for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can update their own fitness activities"
  on public.fitness_activities for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "Users can delete their own fitness activities"
  on public.fitness_activities for delete
  to authenticated
  using (user_id = auth.uid());
