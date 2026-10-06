-- Hevy exercises and sets (#37). A workout's exercises and sets are replaced as
-- one unit by replace_fitness_workout(), so the database always holds a
-- consistent snapshot of what Hevy holds.

create table public.fitness_exercises (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  fitness_activity_id uuid not null references public.fitness_activities (id) on delete cascade,
  position integer not null,
  title text,
  exercise_template_id text,
  notes text,
  superset_id integer,
  created_at timestamptz not null default now(),

  constraint fitness_exercises_activity_position_unique
    unique (fitness_activity_id, position),
  constraint fitness_exercises_position_non_negative check (position >= 0)
);

create index fitness_exercises_user_idx on public.fitness_exercises (user_id);

create table public.fitness_sets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  fitness_exercise_id uuid not null references public.fitness_exercises (id) on delete cascade,
  position integer not null,
  type text not null,
  weight_kg double precision,
  reps integer,
  rpe double precision,
  distance_meters double precision,
  duration_seconds double precision,
  custom_metric double precision,
  created_at timestamptz not null default now(),

  constraint fitness_sets_exercise_position_unique
    unique (fitness_exercise_id, position),
  constraint fitness_sets_position_non_negative check (position >= 0),
  constraint fitness_sets_type_known
    check (type in ('normal', 'warmup', 'dropset', 'failure')),
  constraint fitness_sets_measurements_non_negative
    check (
      (weight_kg is null or weight_kg >= 0)
      and (reps is null or reps >= 0)
      and (rpe is null or rpe >= 0)
      and (distance_meters is null or distance_meters >= 0)
      and (duration_seconds is null or duration_seconds >= 0)
      and (custom_metric is null or custom_metric >= 0)
    )
);

create index fitness_sets_user_idx on public.fitness_sets (user_id);

alter table public.fitness_exercises enable row level security;
alter table public.fitness_sets enable row level security;

revoke all on public.fitness_exercises from anon;
revoke all on public.fitness_sets from anon;
grant select, insert, update, delete on public.fitness_exercises to authenticated;
grant select, insert, update, delete on public.fitness_sets to authenticated;

-- A foreign key check bypasses RLS, so ownership of the row alone would let a
-- caller attach their own exercise to someone else's workout. The write
-- policies therefore also require the parent to be visible to the caller,
-- which RLS limits to their own.
create policy "Users can read their own fitness exercises"
  on public.fitness_exercises for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own fitness exercises"
  on public.fitness_exercises for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can update their own fitness exercises"
  on public.fitness_exercises for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_activities activity
      where activity.id = fitness_activity_id
    )
  );

create policy "Users can delete their own fitness exercises"
  on public.fitness_exercises for delete
  to authenticated
  using (user_id = auth.uid());

create policy "Users can read their own fitness sets"
  on public.fitness_sets for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own fitness sets"
  on public.fitness_sets for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_exercises exercise
      where exercise.id = fitness_exercise_id
    )
  );

create policy "Users can update their own fitness sets"
  on public.fitness_sets for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.fitness_exercises exercise
      where exercise.id = fitness_exercise_id
    )
  );

create policy "Users can delete their own fitness sets"
  on public.fitness_sets for delete
  to authenticated
  using (user_id = auth.uid());

-- Takes one workout's full payload: the fitness activity columns plus an
-- `exercises` array, each with a `sets` array (the shape the Hevy worker plans).
-- A function body is one transaction, so a payload that fails partway leaves the
-- previous exercises and sets intact. Runs as the caller (security invoker), so
-- RLS applies and the owner is always auth.uid(); any user_id in the payload is
-- ignored. Returns the fitness activity id, which an update keeps.
create function public.replace_fitness_workout(payload jsonb)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  activity_id uuid;
  exercise jsonb;
  exercise_id uuid;
begin
  insert into public.fitness_activities (
    user_id, source, provider, external_id, activity_name, activity_type,
    local_day, started_at, duration_seconds, calories_kcal,
    average_heart_rate_bpm, maximum_heart_rate_bpm, total_sets, active_sets,
    total_reps, total_volume_kg, synced_at
  )
  values (
    auth.uid(),
    payload ->> 'source',
    payload ->> 'provider',
    payload ->> 'external_id',
    payload ->> 'activity_name',
    payload ->> 'activity_type',
    (payload ->> 'local_day')::date,
    (payload ->> 'started_at')::timestamptz,
    (payload ->> 'duration_seconds')::double precision,
    (payload ->> 'calories_kcal')::integer,
    (payload ->> 'average_heart_rate_bpm')::integer,
    (payload ->> 'maximum_heart_rate_bpm')::integer,
    (payload ->> 'total_sets')::integer,
    (payload ->> 'active_sets')::integer,
    (payload ->> 'total_reps')::integer,
    (payload ->> 'total_volume_kg')::double precision,
    coalesce((payload ->> 'synced_at')::timestamptz, now())
  )
  on conflict (user_id, source, external_id) do update set
    provider = excluded.provider,
    activity_name = excluded.activity_name,
    activity_type = excluded.activity_type,
    local_day = excluded.local_day,
    started_at = excluded.started_at,
    duration_seconds = excluded.duration_seconds,
    calories_kcal = excluded.calories_kcal,
    average_heart_rate_bpm = excluded.average_heart_rate_bpm,
    maximum_heart_rate_bpm = excluded.maximum_heart_rate_bpm,
    total_sets = excluded.total_sets,
    active_sets = excluded.active_sets,
    total_reps = excluded.total_reps,
    total_volume_kg = excluded.total_volume_kg,
    synced_at = excluded.synced_at
  returning id into activity_id;

  -- The sets go with their exercises (on delete cascade).
  delete from public.fitness_exercises where fitness_activity_id = activity_id;

  for exercise in
    select value from jsonb_array_elements(coalesce(payload -> 'exercises', '[]'::jsonb))
  loop
    insert into public.fitness_exercises (
      fitness_activity_id, position, title, exercise_template_id, notes, superset_id
    )
    values (
      activity_id,
      (exercise ->> 'position')::integer,
      exercise ->> 'title',
      exercise ->> 'exercise_template_id',
      exercise ->> 'notes',
      (exercise ->> 'superset_id')::integer
    )
    returning id into exercise_id;

    insert into public.fitness_sets (
      fitness_exercise_id, position, type, weight_kg, reps, rpe,
      distance_meters, duration_seconds, custom_metric
    )
    select
      exercise_id,
      (item ->> 'position')::integer,
      item ->> 'type',
      (item ->> 'weight_kg')::double precision,
      (item ->> 'reps')::integer,
      (item ->> 'rpe')::double precision,
      (item ->> 'distance_meters')::double precision,
      (item ->> 'duration_seconds')::double precision,
      (item ->> 'custom_metric')::double precision
    from jsonb_array_elements(coalesce(exercise -> 'sets', '[]'::jsonb)) as item;
  end loop;

  return activity_id;
end;
$$;

-- Functions are executable by PUBLIC by default, and Supabase also grants
-- anon explicitly; close both and open only authenticated.
revoke all on function public.replace_fitness_workout(jsonb) from public;
revoke all on function public.replace_fitness_workout(jsonb) from anon;
grant execute on function public.replace_fitness_workout(jsonb) to authenticated;
