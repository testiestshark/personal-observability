\set ON_ERROR_STOP on

begin;

do $$
begin
  if has_table_privilege('anon', 'public.daily_health_metrics', 'select')
     or has_table_privilege('anon', 'public.daily_health_metrics', 'insert') then
    raise exception 'anon has a daily_health_metrics table grant';
  end if;

  if (select count(*) from pg_policies where schemaname = 'public' and tablename = 'daily_health_metrics') <> 4 then
    raise exception 'daily_health_metrics does not have all four RLS policies';
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
  affected integer;
begin
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );

  insert into public.daily_health_metrics
    (user_id, day, steps, source, provider, external_id)
  values
    (owner_id, '1900-01-01', 1234, 'garmin', 'garmin_connect_unofficial', 'rls-test');

  if (select count(*) from public.daily_health_metrics where external_id = 'rls-test') <> 1 then
    raise exception 'owner cannot read their own row';
  end if;

  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from public.daily_health_metrics where external_id = 'rls-test') <> 0 then
    raise exception 'second user can read the owner row';
  end if;

  update public.daily_health_metrics set steps = 9999 where external_id = 'rls-test';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner row';
  end if;

  delete from public.daily_health_metrics where external_id = 'rls-test';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner row';
  end if;

  begin
    insert into public.daily_health_metrics
      (user_id, day, steps, source, provider, external_id)
    values
      (owner_id, '1900-01-02', 4321, 'garmin', 'garmin_connect_unofficial', 'rls-forge');
    raise exception 'second user can insert a row owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
end
$$;

rollback;

select 'daily_health_metrics RLS verification passed' as result;
