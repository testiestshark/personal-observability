\set ON_ERROR_STOP on

-- Verifies weather.run_weather (#135).
-- Run against a Supabase database that has two auth users, local or hosted:
--   psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -f scripts/verify-run-weather-rls.sql
-- Everything is rolled back, so it leaves no rows behind.

begin;

do $$
begin
  if has_table_privilege('anon', 'weather.run_weather', 'select')
     or has_table_privilege('anon', 'weather.run_weather', 'insert')
     or has_table_privilege('anon', 'weather.run_weather', 'update')
     or has_table_privilege('anon', 'weather.run_weather', 'delete') then
    raise exception 'anon has a run_weather table grant';
  end if;
  if has_schema_privilege('anon', 'weather', 'usage') then
    raise exception 'anon can use the weather schema';
  end if;
  if not has_schema_privilege('authenticated', 'weather', 'usage') then
    raise exception 'authenticated cannot use the weather schema';
  end if;

  if not (select relrowsecurity from pg_class where oid = 'weather.run_weather'::regclass) then
    raise exception 'run_weather does not have row level security enabled';
  end if;
  if (select count(*) from pg_policies
        where schemaname = 'weather' and tablename = 'run_weather') <> 4 then
    raise exception 'run_weather does not have all four RLS policies';
  end if;

  -- The place the weather was looked up for is never stored (ADR 0001).
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'weather' and table_name = 'run_weather'
      and column_name ~* '(^|_)(lat|latitude|lon|lng|longitude|coord|coords|coordinates|location|geo|point)(_|$)'
  ) then
    raise exception 'run_weather has a location column';
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
  affected integer;
begin
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );

  insert into public.fitness_activities (
    user_id, source, provider, external_id, activity_type, local_day, started_at
  )
  values (
    owner_id, 'garmin', 'garmin_connect_unofficial', 'rls-weather-test', 'running',
    '1900-01-01', '1900-01-01T10:00:00+00:00'
  )
  returning id into owner_activity;

  -- The owner stores weather; the owner column is filled from the caller.
  insert into weather.run_weather (
    fitness_activity_id, hour_start, temperature_c, apparent_temperature_c,
    relative_humidity_percent, wind_speed_mph, precipitation_mm, source
  )
  values (owner_activity, '1900-01-01T10:00:00+00:00', 11.2, 9.1, 78, 8.4, 0, 'open-meteo-archive');

  if (select count(*) from weather.run_weather where fitness_activity_id = owner_activity and user_id = owner_id) <> 1 then
    raise exception 'owner weather was not stored under the owner';
  end if;

  -- One row per run.
  begin
    insert into weather.run_weather (
      fitness_activity_id, hour_start, temperature_c, apparent_temperature_c,
      relative_humidity_percent, wind_speed_mph, precipitation_mm, source
    )
    values (owner_activity, '1900-01-01T10:00:00+00:00', 1, 1, 50, 1, 0, 'open-meteo-archive');
    raise exception 'a second weather row was accepted for one run';
  exception
    when unique_violation then null;
  end;

  -- Values outside their range are refused.
  begin
    update weather.run_weather set relative_humidity_percent = 140;
    raise exception 'a humidity over 100 was accepted';
  exception
    when check_violation then null;
  end;

  -- The second user sees none of it.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from weather.run_weather) <> 0 then
    raise exception 'second user can read the owner weather';
  end if;

  update weather.run_weather set temperature_c = -50;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner weather';
  end if;
  delete from weather.run_weather;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner weather';
  end if;

  -- Inserting as the owner, or under the owner's activity, is refused.
  begin
    insert into weather.run_weather (
      user_id, fitness_activity_id, hour_start, temperature_c, apparent_temperature_c,
      relative_humidity_percent, wind_speed_mph, precipitation_mm, source
    )
    values (owner_id, owner_activity, '1900-01-01T11:00:00+00:00', 1, 1, 50, 1, 0, 'x');
    raise exception 'second user can insert weather owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into weather.run_weather (
      user_id, fitness_activity_id, hour_start, temperature_c, apparent_temperature_c,
      relative_humidity_percent, wind_speed_mph, precipitation_mm, source
    )
    values (other_id, owner_activity, '1900-01-01T11:00:00+00:00', 1, 1, 50, 1, 0, 'x');
    raise exception 'second user can attach weather to the first user activity';
  exception
    when insufficient_privilege or unique_violation then null;
  end;

  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );
  if (select temperature_c from weather.run_weather where fitness_activity_id = owner_activity) <> 11.2 then
    raise exception 'second user changed the first user weather';
  end if;

  -- Deleting the activity takes its weather with it.
  delete from public.fitness_activities where id = owner_activity;
  if exists (select 1 from weather.run_weather where fitness_activity_id = owner_activity) then
    raise exception 'deleting an activity left its weather behind';
  end if;
end
$$;

-- An anonymous request is refused outright, not shown an empty table.
set local role anon;

do $$
begin
  begin
    perform count(*) from weather.run_weather;
    raise exception 'anon can read run_weather';
  exception
    when insufficient_privilege then null;
  end;
end
$$;

rollback;

select 'weather.run_weather verification passed' as result;
