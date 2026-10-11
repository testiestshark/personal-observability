\set ON_ERROR_STOP on

-- Verifies fitness_activity_laps and replace_fitness_activity_laps() (#95).
-- Run against a Supabase database that has two auth users, local or hosted:
--   psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -f scripts/verify-fitness-activity-laps-rls.sql
-- Everything is rolled back, so it leaves no rows behind.

begin;

do $$
begin
  if has_table_privilege('anon', 'public.fitness_activity_laps', 'select')
     or has_table_privilege('anon', 'public.fitness_activity_laps', 'insert')
     or has_table_privilege('anon', 'public.fitness_activity_laps', 'update')
     or has_table_privilege('anon', 'public.fitness_activity_laps', 'delete') then
    raise exception 'anon has a fitness_activity_laps table grant';
  end if;

  if not (select relrowsecurity from pg_class where oid = 'public.fitness_activity_laps'::regclass) then
    raise exception 'fitness_activity_laps does not have row level security enabled';
  end if;
  if (select count(*) from pg_policies
        where schemaname = 'public' and tablename = 'fitness_activity_laps') <> 4 then
    raise exception 'fitness_activity_laps does not have all four RLS policies';
  end if;

  if has_function_privilege('anon', 'public.replace_fitness_activity_laps(text, text, jsonb)', 'execute') then
    raise exception 'anon can execute replace_fitness_activity_laps';
  end if;
  if not has_function_privilege('authenticated', 'public.replace_fitness_activity_laps(text, text, jsonb)', 'execute') then
    raise exception 'authenticated cannot execute replace_fitness_activity_laps';
  end if;
  if (select prosecdef from pg_proc
        where oid = 'public.replace_fitness_activity_laps(text, text, jsonb)'::regprocedure) then
    raise exception 'replace_fitness_activity_laps is security definer, not invoker';
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
    raise exception 'two auth users are required for the RLS verification';
  end if;
end
$$;

set local role authenticated;

do $$
declare
  owner_id uuid := current_setting('test.owner_id')::uuid;
  other_id uuid := current_setting('test.other_id')::uuid;
  owner_activity uuid;
  stored integer;
  three_laps jsonb := jsonb_build_array(
    jsonb_build_object('position', 0, 'distance_meters', 1000, 'duration_seconds', 330.5,
      'average_heart_rate_bpm', 148, 'elevation_gain_meters', 6, 'elevation_loss_meters', 3),
    jsonb_build_object('position', 1, 'distance_meters', 1000, 'duration_seconds', 325,
      'average_heart_rate_bpm', 153),
    jsonb_build_object('position', 2, 'distance_meters', 340, 'duration_seconds', 120)
  );
  affected integer;
begin
  -- The owner has a Garmin activity and stores its laps through the function.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );

  insert into public.fitness_activities (
    user_id, source, provider, external_id, activity_type, local_day, started_at
  )
  values (
    owner_id, 'garmin', 'garmin_connect_unofficial', 'rls-laps-test', 'running',
    '1900-01-01', '1900-01-01T10:00:00+00:00'
  )
  returning id into owner_activity;

  stored := public.replace_fitness_activity_laps('garmin', 'rls-laps-test', three_laps);
  if stored <> 3 then
    raise exception 'the function reported % laps stored, not 3', stored;
  end if;
  if (select count(*) from public.fitness_activity_laps where fitness_activity_id = owner_activity) <> 3 then
    raise exception 'owner laps were not stored';
  end if;
  if exists (
    select 1 from public.fitness_activity_laps
    where fitness_activity_id = owner_activity and user_id <> owner_id
  ) then
    raise exception 'a lap was stored under a user other than the caller';
  end if;
  if (select average_heart_rate_bpm from public.fitness_activity_laps
        where fitness_activity_id = owner_activity and position = 2) is not null then
    raise exception 'a missing heart rate was not kept as null';
  end if;

  -- Replacing swaps the laps rather than adding to them.
  if public.replace_fitness_activity_laps('garmin', 'rls-laps-test', jsonb_build_array(three_laps -> 0)) <> 1 then
    raise exception 'replacing did not report one lap';
  end if;
  if (select count(*) from public.fitness_activity_laps where fitness_activity_id = owner_activity) <> 1 then
    raise exception 'replacing the laps kept the old ones';
  end if;
  perform public.replace_fitness_activity_laps('garmin', 'rls-laps-test', three_laps);

  -- Atomicity: a payload that fails partway (a negative duration in the second
  -- lap) leaves the previous laps intact.
  begin
    perform public.replace_fitness_activity_laps(
      'garmin', 'rls-laps-test',
      jsonb_set(three_laps, '{1,duration_seconds}', '-5')
    );
    raise exception 'a negative duration was accepted';
  exception
    when check_violation then null;
  end;
  if (select count(*) from public.fitness_activity_laps where fitness_activity_id = owner_activity) <> 3 then
    raise exception 'a failed replace did not leave the previous laps intact';
  end if;

  -- An activity that is not there is an error, not a silent no-op.
  begin
    perform public.replace_fitness_activity_laps('garmin', 'no-such-activity', three_laps);
    raise exception 'laps were stored for an activity that does not exist';
  exception
    when no_data_found then null;
  end;

  -- The second user sees none of it.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from public.fitness_activity_laps) <> 0 then
    raise exception 'second user can read the owner laps';
  end if;

  update public.fitness_activity_laps set duration_seconds = 1;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner laps';
  end if;
  delete from public.fitness_activity_laps;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner laps';
  end if;

  -- Inserting as the owner, or under the owner's activity, is refused.
  begin
    insert into public.fitness_activity_laps (user_id, fitness_activity_id, position, duration_seconds)
    values (owner_id, owner_activity, 9, 60);
    raise exception 'second user can insert a lap owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.fitness_activity_laps (user_id, fitness_activity_id, position, duration_seconds)
    values (other_id, owner_activity, 9, 60);
    raise exception 'second user can attach a lap to the first user activity';
  exception
    when insufficient_privilege then null;
  end;

  -- The function looks the activity up among the caller's own, so the owner's
  -- external id finds nothing for the second user.
  begin
    perform public.replace_fitness_activity_laps('garmin', 'rls-laps-test', '[]'::jsonb);
    raise exception 'second user replaced the first user laps through the function';
  exception
    when no_data_found then null;
  end;

  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );
  if (select count(*) from public.fitness_activity_laps where fitness_activity_id = owner_activity) <> 3 then
    raise exception 'second user changed the first user laps';
  end if;

  -- Deleting the activity takes its laps with it.
  delete from public.fitness_activities where id = owner_activity;
  if exists (select 1 from public.fitness_activity_laps where fitness_activity_id = owner_activity) then
    raise exception 'deleting an activity left its laps behind';
  end if;
end
$$;

-- An anonymous request is refused outright, not shown an empty table.
set local role anon;

do $$
begin
  begin
    perform count(*) from public.fitness_activity_laps;
    raise exception 'anon can read fitness_activity_laps';
  exception
    when insufficient_privilege then null;
  end;
  begin
    perform public.replace_fitness_activity_laps('garmin', 'rls-laps-test', '[]'::jsonb);
    raise exception 'anon can call replace_fitness_activity_laps';
  exception
    when insufficient_privilege then null;
  end;
end
$$;

rollback;

select 'fitness_activity_laps and replace_fitness_activity_laps verification passed' as result;
