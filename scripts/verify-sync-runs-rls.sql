\set ON_ERROR_STOP on

begin;

do $$
begin
  if has_table_privilege('anon', 'public.sync_runs', 'select')
     or has_table_privilege('anon', 'public.sync_runs', 'insert') then
    raise exception 'anon has a sync_runs table grant';
  end if;

  if (select count(*) from pg_policies where schemaname = 'public' and tablename = 'sync_runs') <> 4 then
    raise exception 'sync_runs does not have all four RLS policies';
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

  insert into public.sync_runs (user_id, source, last_succeeded_at)
  values (owner_id, 'hevy', '1900-01-01T00:00:00Z');

  if (select count(*) from public.sync_runs where source = 'hevy') <> 1 then
    raise exception 'owner cannot read their own row';
  end if;

  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from public.sync_runs where user_id = owner_id) <> 0 then
    raise exception 'second user can read the owner row';
  end if;

  update public.sync_runs set last_succeeded_at = now() where user_id = owner_id;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner row';
  end if;

  delete from public.sync_runs where user_id = owner_id;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner row';
  end if;

  begin
    insert into public.sync_runs (user_id, source, last_succeeded_at)
    values (owner_id, 'hevy', now());
    raise exception 'second user can insert a row owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
end
$$;

rollback;

select 'sync_runs RLS verification passed' as result;
