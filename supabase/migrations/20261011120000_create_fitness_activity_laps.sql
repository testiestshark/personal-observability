-- Garmin run splits (#95). One row per lap of a fitness activity, in recorded
-- order: with the watch's auto-lap at 1 km these are the per-km splits.
--
-- Deliberately no start or end coordinates: Garmin returns them with every lap,
-- but the route map is a recorded non-goal (docs/NON_GOALS.md, #72).
-- A lap's pace is derived in the app from its time and distance, not stored.

create table public.fitness_activity_laps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  fitness_activity_id uuid not null references public.fitness_activities (id) on delete cascade,
  position integer not null,
  distance_meters double precision,
  duration_seconds double precision not null,
  average_heart_rate_bpm integer,
  elevation_gain_meters double precision,
  elevation_loss_meters double precision,
  created_at timestamptz not null default now(),

  constraint fitness_activity_laps_activity_position_unique
    unique (fitness_activity_id, position),
  constraint fitness_activity_laps_position_non_negative check (position >= 0),
  constraint fitness_activity_laps_measurements_non_negative
    check (
      (distance_meters is null or distance_meters >= 0)
      and duration_seconds >= 0
      and (average_heart_rate_bpm is null or average_heart_rate_bpm >= 0)
      and (elevation_gain_meters is null or elevation_gain_meters >= 0)
      and (elevation_loss_meters is null or elevation_loss_meters >= 0)
    )
);

create index fitness_activity_laps_user_idx on public.fitness_activity_laps (user_id);

alter table public.fitness_activity_laps enable row level security;

revoke all on public.fitness_activity_laps from anon;
grant select, insert, update, delete on public.fitness_activity_laps to authenticated;

-- A foreign key check bypasses RLS, so ownership of the row alone would let a
-- caller attach their own lap to someone else's activity. The write policies
-- therefore also require the parent to be visible to the caller, which RLS
-- limits to their own.
create policy "Users can read their own fitness activity laps"
  on public.fitness_activity_laps for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own fitness activity laps"
  on public.fitness_activity_laps for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can update their own fitness activity laps"
  on public.fitness_activity_laps for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can delete their own fitness activity laps"
  on public.fitness_activity_laps for delete
  to authenticated
  using (user_id = auth.uid());

-- Replaces one activity's laps as a unit, found by its provider id so the
-- worker does not need the activity's uuid. A function body is one transaction,
-- so a payload that fails partway leaves the previous laps intact. Runs as the
-- caller (security invoker): RLS applies, the activity is looked up among the
-- caller's own, and the owner of every lap is auth.uid(). Returns how many laps
-- were stored.
create function public.replace_fitness_activity_laps(
  p_source text,
  p_external_id text,
  p_laps jsonb
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  activity_id uuid;
  stored integer;
begin
  select id into activity_id
  from public.fitness_activities
  where user_id = auth.uid()
    and source = p_source
    and external_id = p_external_id;

  if activity_id is null then
    raise exception 'no fitness activity for source % and external id %', p_source, p_external_id
      using errcode = 'no_data_found';
  end if;

  delete from public.fitness_activity_laps where fitness_activity_id = activity_id;

  insert into public.fitness_activity_laps (
    fitness_activity_id, position, distance_meters, duration_seconds,
    average_heart_rate_bpm, elevation_gain_meters, elevation_loss_meters
  )
  select
    activity_id,
    (item ->> 'position')::integer,
    (item ->> 'distance_meters')::double precision,
    (item ->> 'duration_seconds')::double precision,
    (item ->> 'average_heart_rate_bpm')::integer,
    (item ->> 'elevation_gain_meters')::double precision,
    (item ->> 'elevation_loss_meters')::double precision
  from jsonb_array_elements(coalesce(p_laps, '[]'::jsonb)) as item;

  get diagnostics stored = row_count;
  return stored;
end;
$$;

-- Functions are executable by PUBLIC by default, and Supabase also grants
-- anon explicitly; close both and open only authenticated.
revoke all on function public.replace_fitness_activity_laps(text, text, jsonb) from public;
revoke all on function public.replace_fitness_activity_laps(text, text, jsonb) from anon;
grant execute on function public.replace_fitness_activity_laps(text, text, jsonb) to authenticated;
