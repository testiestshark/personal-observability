\set ON_ERROR_STOP on

-- Verifies fitness_exercises, fitness_sets and replace_fitness_workout().
-- Run against local Supabase after `supabase db reset`, with two auth users:
--   psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -f scripts/verify-fitness-workout-rls.sql
-- Everything is rolled back.

begin;

do $$
declare
  tbl text;
begin
  foreach tbl in array array['fitness_exercises', 'fitness_sets'] loop
    if has_table_privilege('anon', 'public.' || tbl, 'select')
       or has_table_privilege('anon', 'public.' || tbl, 'insert')
       or has_table_privilege('anon', 'public.' || tbl, 'update')
       or has_table_privilege('anon', 'public.' || tbl, 'delete') then
      raise exception 'anon has a % table grant', tbl;
    end if;

    if (select count(*) from pg_policies where schemaname = 'public' and tablename = tbl) <> 4 then
      raise exception '% does not have all four RLS policies', tbl;
    end if;
  end loop;

  if has_function_privilege('anon', 'public.replace_fitness_workout(jsonb)', 'execute') then
    raise exception 'anon can execute replace_fitness_workout';
  end if;
  if not has_function_privilege('authenticated', 'public.replace_fitness_workout(jsonb)', 'execute') then
    raise exception 'authenticated cannot execute replace_fitness_workout';
  end if;
  if (select prosecdef from pg_proc where oid = 'public.replace_fitness_workout(jsonb)'::regprocedure) then
    raise exception 'replace_fitness_workout is security definer, not invoker';
  end if;
end
$$;

select set_config(
  'test.owner_id',
  (select id::text from auth.users order by created_at, id limit 1),
  true
);
select set_config(
  'test.other_id',
  (select id::text from auth.users order by created_at, id offset 1 limit 1),
  true
);

do $$
begin
  if current_setting('test.owner_id', true) = ''
     or current_setting('test.other_id', true) = '' then
    raise exception 'two local auth users are required for the RLS verification';
  end if;
end
$$;

set local role authenticated;

do $$
declare
  owner_id uuid := current_setting('test.owner_id')::uuid;
  other_id uuid := current_setting('test.other_id')::uuid;
  owner_activity uuid;
  other_activity uuid;
  owner_exercise uuid;
  affected integer;
  workout jsonb := jsonb_build_object(
    'source', 'hevy',
    'provider', 'hevy_public_api',
    'external_id', 'rls-test',
    'activity_name', 'RLS test',
    'activity_type', 'strength_training',
    'local_day', '1900-01-01',
    'started_at', '1900-01-01T10:00:00+00:00',
    'exercises', jsonb_build_array(
      jsonb_build_object('position', 0, 'title', 'Squat', 'superset_id', 0, 'sets', jsonb_build_array(
        jsonb_build_object('position', 0, 'type', 'warmup', 'weight_kg', 40, 'reps', 10),
        jsonb_build_object('position', 1, 'type', 'normal', 'weight_kg', 100, 'reps', 5)
      )),
      jsonb_build_object('position', 1, 'title', 'Plank', 'sets', jsonb_build_array(
        jsonb_build_object('position', 0, 'type', 'normal', 'duration_seconds', 60)
      ))
    )
  );
begin
  -- The owner stores a workout through the function.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );

  owner_activity := public.replace_fitness_workout(workout);

  if (select count(*) from public.fitness_exercises where fitness_activity_id = owner_activity) <> 2 then
    raise exception 'owner workout did not store its exercises';
  end if;
  if (select count(*) from public.fitness_sets s
        join public.fitness_exercises e on e.id = s.fitness_exercise_id
       where e.fitness_activity_id = owner_activity) <> 3 then
    raise exception 'owner workout did not store its sets';
  end if;

  -- Replacing keeps the activity id and swaps the children.
  if public.replace_fitness_workout(
       jsonb_set(workout, '{exercises}', jsonb_build_array(workout -> 'exercises' -> 1))
     ) <> owner_activity then
    raise exception 'replacing a workout changed its fitness activity id';
  end if;
  if (select count(*) from public.fitness_exercises where fitness_activity_id = owner_activity) <> 1 then
    raise exception 'replacing a workout kept its old exercises';
  end if;
  if (select count(*) from public.fitness_sets where user_id = owner_id) <> 1 then
    raise exception 'replacing a workout kept its old sets';
  end if;

  perform public.replace_fitness_workout(workout);
  select id into owner_exercise
    from public.fitness_exercises where fitness_activity_id = owner_activity and position = 0;

  -- Atomicity: a payload that fails partway (an invalid set type in the second
  -- exercise) leaves the previous exercises and sets intact.
  begin
    perform public.replace_fitness_workout(
      jsonb_set(
        jsonb_set(workout, '{activity_name}', '"Should not stick"'),
        '{exercises,1,sets,0,type}', '"amrap"'
      )
    );
    raise exception 'an invalid set type was accepted';
  exception
    when check_violation then null;
  end;

  if (select count(*) from public.fitness_exercises where fitness_activity_id = owner_activity) <> 2
     or (select count(*) from public.fitness_sets where user_id = owner_id) <> 3 then
    raise exception 'a failed replace did not leave the previous exercises and sets intact';
  end if;
  if (select activity_name from public.fitness_activities where id = owner_activity) <> 'RLS test' then
    raise exception 'a failed replace changed the fitness activity';
  end if;

  -- The second user sees none of it.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from public.fitness_exercises) <> 0
     or (select count(*) from public.fitness_sets) <> 0 then
    raise exception 'second user can read the owner exercises or sets';
  end if;

  update public.fitness_exercises set title = 'hijacked';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner exercises';
  end if;
  update public.fitness_sets set reps = 999;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner sets';
  end if;

  delete from public.fitness_sets;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner sets';
  end if;
  delete from public.fitness_exercises;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner exercises';
  end if;

  -- Inserting as the owner, or under the owner's parent, is refused.
  begin
    insert into public.fitness_exercises (user_id, fitness_activity_id, position)
    values (owner_id, owner_activity, 9);
    raise exception 'second user can insert an exercise owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.fitness_exercises (user_id, fitness_activity_id, position)
    values (other_id, owner_activity, 9);
    raise exception 'second user can attach an exercise to the first user workout';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.fitness_sets (user_id, fitness_exercise_id, position, type)
    values (owner_id, owner_exercise, 9, 'normal');
    raise exception 'second user can insert a set owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.fitness_sets (user_id, fitness_exercise_id, position, type)
    values (other_id, owner_exercise, 9, 'normal');
    raise exception 'second user can attach a set to the first user exercise';
  exception
    when insufficient_privilege then null;
  end;

  -- Calling the function with the owner's workout id writes the second user's
  -- own workout and leaves the owner's untouched.
  other_activity := public.replace_fitness_workout(
    jsonb_set(workout, '{exercises}', '[]'::jsonb)
  );
  if other_activity = owner_activity then
    raise exception 'second user replaced the first user workout';
  end if;

  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );
  if (select count(*) from public.fitness_exercises where fitness_activity_id = owner_activity) <> 2
     or (select count(*) from public.fitness_sets where user_id = owner_id) <> 3 then
    raise exception 'second user calling the function changed the first user exercises or sets';
  end if;
end
$$;

rollback;

select 'fitness exercises, sets and replace_fitness_workout verification passed' as result;
