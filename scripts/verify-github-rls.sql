\set ON_ERROR_STOP on

-- Verifies github_accounts, github_daily_contributions and github_commits.
-- Run against local Supabase after `supabase db reset`, with two auth users:
--   Get-Content scripts/verify-github-rls.sql | docker exec -i supabase_db_personal_observability psql -U postgres -v ON_ERROR_STOP=1
-- Everything is rolled back.

begin;

do $$
declare
  tbl text;
begin
  foreach tbl in array array['github_accounts', 'github_daily_contributions', 'github_commits'] loop
    if has_table_privilege('anon', 'public.' || tbl, 'select')
       or has_table_privilege('anon', 'public.' || tbl, 'insert')
       or has_table_privilege('anon', 'public.' || tbl, 'update')
       or has_table_privilege('anon', 'public.' || tbl, 'delete') then
      raise exception 'anon has a % table grant', tbl;
    end if;

    if (select count(*) from pg_policies where schemaname = 'public' and tablename = tbl) <> 4 then
      raise exception '% does not have all four RLS policies', tbl;
    end if;

    if not (select relrowsecurity from pg_class where oid = ('public.' || tbl)::regclass) then
      raise exception '% does not have row level security enabled', tbl;
    end if;
  end loop;
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
  full_account uuid;
  counts_account uuid;
  affected integer;
begin
  -- The owner sets up a full account and a counts-only one, and stores rows.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', owner_id, 'role', 'authenticated')::text,
    true
  );

  insert into public.github_accounts (user_id, github_user_id, github_node_id, login, label, detail)
  values (owner_id, -1, 'U_rls_full', 'rls-full', 'Full', 'full')
  returning id into full_account;

  -- detail defaults to counts_only.
  insert into public.github_accounts (user_id, github_user_id, github_node_id, login, label)
  values (owner_id, -2, 'U_rls_counts', 'rls-counts', 'Counts')
  returning id into counts_account;

  if (select detail from public.github_accounts where id = counts_account) <> 'counts_only' then
    raise exception 'detail does not default to counts_only';
  end if;

  insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
  values (owner_id, full_account, '1900-01-01', 'commit', 3),
         (owner_id, counts_account, '1900-01-01', 'unsplit', 2);

  insert into public.github_commits (
    user_id, account_id, repo_node_id, repo_name_with_owner, repo_is_private,
    oid, message_headline, authored_at, local_day
  )
  values (owner_id, full_account, 'R_rls', 'rls/repo', true, 'abc123',
          'headline', '1900-01-01T10:00:00Z', '1900-01-01');

  if (select count(*) from public.github_accounts where user_id = owner_id and github_user_id < 0) <> 2
     or (select count(*) from public.github_daily_contributions where user_id = owner_id) <> 2
     or (select count(*) from public.github_commits where user_id = owner_id) <> 1 then
    raise exception 'owner cannot read their own rows';
  end if;

  -- Table constraints.
  begin
    insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
    values (owner_id, full_account, '1900-01-01', 'commit', 4);
    raise exception 'a duplicate (account, day, kind) was accepted';
  exception
    when unique_violation then null;
  end;
  begin
    insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
    values (owner_id, full_account, '1900-01-02', 'push', 1);
    raise exception 'an unknown kind was accepted';
  exception
    when check_violation then null;
  end;
  begin
    insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
    values (owner_id, full_account, '1900-01-02', 'commit', -1);
    raise exception 'a negative count was accepted';
  exception
    when check_violation then null;
  end;
  begin
    insert into public.github_accounts (user_id, github_user_id, github_node_id, login, label, detail)
    values (owner_id, -3, 'U_rls_bad', 'rls-bad', 'Bad', 'everything');
    raise exception 'an unknown detail level was accepted';
  exception
    when check_violation then null;
  end;

  -- A counts_only account cannot have commits written against it.
  begin
    insert into public.github_commits (
      user_id, account_id, repo_node_id, repo_name_with_owner, repo_is_private,
      oid, message_headline, authored_at, local_day
    )
    values (owner_id, counts_account, 'R_rls', 'rls/repo', true, 'def456',
            'headline', '1900-01-01T10:00:00Z', '1900-01-01');
    raise exception 'a commit was stored against a counts_only account';
  exception
    when insufficient_privilege then null;
  end;

  -- The second user sees none of it.
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', other_id, 'role', 'authenticated')::text,
    true
  );

  if (select count(*) from public.github_accounts where github_user_id < 0) <> 0
     or (select count(*) from public.github_daily_contributions) <> 0
     or (select count(*) from public.github_commits) <> 0 then
    raise exception 'second user can read the owner rows';
  end if;

  update public.github_accounts set label = 'hijacked' where github_user_id < 0;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner accounts';
  end if;
  update public.github_daily_contributions set count = 999;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner daily contributions';
  end if;
  update public.github_commits set message_headline = 'hijacked';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can update the owner commits';
  end if;

  delete from public.github_commits;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner commits';
  end if;
  delete from public.github_daily_contributions;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner daily contributions';
  end if;
  delete from public.github_accounts where github_user_id < 0;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'second user can delete the owner accounts';
  end if;

  -- Inserting as the owner, or under the owner's account, is refused.
  begin
    insert into public.github_accounts (user_id, github_user_id, github_node_id, login, label)
    values (owner_id, -4, 'U_rls_forged', 'rls-forged', 'Forged');
    raise exception 'second user can insert an account owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
    values (owner_id, full_account, '1900-01-03', 'commit', 1);
    raise exception 'second user can insert a daily contribution owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.github_daily_contributions (user_id, account_id, local_day, kind, count)
    values (other_id, full_account, '1900-01-03', 'commit', 1);
    raise exception 'second user can attach a daily contribution to the first user account';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.github_commits (
      user_id, account_id, repo_node_id, repo_name_with_owner, repo_is_private,
      oid, message_headline, authored_at, local_day
    )
    values (owner_id, full_account, 'R_rls', 'rls/repo', true, 'forged1',
            'headline', '1900-01-01T10:00:00Z', '1900-01-01');
    raise exception 'second user can insert a commit owned by the first user';
  exception
    when insufficient_privilege then null;
  end;
  begin
    insert into public.github_commits (
      user_id, account_id, repo_node_id, repo_name_with_owner, repo_is_private,
      oid, message_headline, authored_at, local_day
    )
    values (other_id, full_account, 'R_rls', 'rls/repo', true, 'forged2',
            'headline', '1900-01-01T10:00:00Z', '1900-01-01');
    raise exception 'second user can attach a commit to the first user account';
  exception
    when insufficient_privilege then null;
  end;

  -- The second user can still write their own rows, including the same GitHub
  -- user id as the owner (uniqueness is per owner).
  insert into public.github_accounts (user_id, github_user_id, github_node_id, login, label, detail)
  values (other_id, -1, 'U_rls_other', 'rls-other', 'Other', 'full');

  -- A request with no user sees nothing.
  perform set_config('request.jwt.claims', '', true);
  if (select count(*) from public.github_accounts) <> 0
     or (select count(*) from public.github_daily_contributions) <> 0
     or (select count(*) from public.github_commits) <> 0 then
    raise exception 'a request with no user can read rows';
  end if;
end
$$;

rollback;

select 'github accounts, daily contributions and commits RLS verification passed' as result;
