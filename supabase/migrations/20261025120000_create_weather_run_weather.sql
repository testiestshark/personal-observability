-- Run weather (#131, #135, ADR 0001): the weather for the hour an outdoor run
-- started in, from Open-Meteo's historical archive, fetched once per run.
--
-- It lives in its own schema, not public. The place the weather was looked up
-- for is deliberately not stored anywhere: the worker rounds the run's start
-- point, uses it for one request and discards it, so this table has no
-- coordinate column (docs/NON_GOALS.md, #72).
--
-- A schema outside public is not exposed to the API by default. Locally,
-- supabase/config.toml exposes it; on hosted it is a manual step in the
-- dashboard's API settings. Merging or pushing this migration does not do it.

create schema if not exists weather;

revoke all on schema weather from public;
revoke all on schema weather from anon;
grant usage on schema weather to authenticated;

create table weather.run_weather (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  fitness_activity_id uuid not null references public.fitness_activities (id) on delete cascade,
  hour_start timestamptz not null,
  temperature_c double precision not null,
  apparent_temperature_c double precision not null,
  relative_humidity_percent double precision not null,
  wind_speed_mph double precision not null,
  precipitation_mm double precision not null,
  source text not null,
  fetched_at timestamptz not null default now(),
  created_at timestamptz not null default now(),

  -- One row per run: weather is fetched once and not revised.
  constraint run_weather_activity_unique unique (fitness_activity_id),
  constraint run_weather_humidity_range
    check (relative_humidity_percent between 0 and 100),
  constraint run_weather_wind_non_negative check (wind_speed_mph >= 0),
  constraint run_weather_precipitation_non_negative check (precipitation_mm >= 0)
);

create index run_weather_user_idx on weather.run_weather (user_id);

alter table weather.run_weather enable row level security;

revoke all on weather.run_weather from anon;
grant select, insert, update, delete on weather.run_weather to authenticated;

-- A foreign key check bypasses RLS, so ownership of the row alone would let a
-- caller attach weather to someone else's activity. The write policies also
-- require the parent to be visible to the caller, which RLS limits to their own.
create policy "Users can read their own run weather"
  on weather.run_weather for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own run weather"
  on weather.run_weather for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can update their own run weather"
  on weather.run_weather for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can delete their own run weather"
  on weather.run_weather for delete
  to authenticated
  using (user_id = auth.uid());
