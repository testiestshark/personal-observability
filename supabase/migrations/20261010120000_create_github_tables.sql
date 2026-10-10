-- GitHub activity across two accounts (#75, part of #20). The github-sync worker
-- writes these as the app user (the Garmin pattern), so all four policies exist.
--
--   github_accounts             one row per connected GitHub account. No credentials
--                               of any kind: tokens live in Railway variables.
--   github_daily_contributions  GitHub's own per-type daily counts. The core table.
--   github_commits              itemised commits, for accounts with detail = 'full'.
--
-- local_day is the UTC calendar date: GitHub buckets contribution counts by UTC
-- date and ignores sub-day windows (#74), so "day" here is GitHub's day, not
-- Europe/London.

create table public.github_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  github_user_id bigint not null,
  github_node_id text not null,
  login text not null,
  label text not null,
  display_order integer not null default 0,
  -- 'counts_only' stores totals and nothing that names a repository or a commit.
  detail text not null default 'counts_only',
  token_expires_at timestamptz,
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),

  constraint github_accounts_user_github_user_unique
    unique (user_id, github_user_id),
  constraint github_accounts_detail_known
    check (detail in ('full', 'counts_only'))
);

-- No separate user_id index on any of the three tables: each has a unique
-- constraint or index that already leads with user_id.

create table public.github_daily_contributions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  account_id uuid not null references public.github_accounts (id) on delete cascade,
  local_day date not null,
  kind text not null,
  count integer not null,
  synced_at timestamptz not null default now(),

  constraint github_daily_contributions_day_kind_unique
    unique (user_id, account_id, local_day, kind),
  constraint github_daily_contributions_kind_known
    check (kind in ('commit', 'pull_request', 'review', 'issue', 'unsplit')),
  constraint github_daily_contributions_count_non_negative
    check (count >= 0)
);

-- Headline only, never the commit body.
create table public.github_commits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  account_id uuid not null references public.github_accounts (id) on delete cascade,
  repo_node_id text not null,
  repo_name_with_owner text not null,
  repo_is_private boolean not null,
  oid text not null,
  message_headline text not null,
  authored_at timestamptz not null,
  author_date_raw text,
  local_day date not null,
  synced_at timestamptz not null default now(),

  constraint github_commits_account_repo_oid_unique
    unique (user_id, account_id, repo_node_id, oid)
);

create index github_commits_user_day_idx
  on public.github_commits (user_id, local_day desc);

alter table public.github_accounts enable row level security;
alter table public.github_daily_contributions enable row level security;
alter table public.github_commits enable row level security;

-- Anonymous visitors cannot touch any of it.
revoke all on public.github_accounts from anon;
revoke all on public.github_daily_contributions from anon;
revoke all on public.github_commits from anon;
grant select, insert, update, delete on public.github_accounts to authenticated;
grant select, insert, update, delete on public.github_daily_contributions to authenticated;
grant select, insert, update, delete on public.github_commits to authenticated;

create policy "Users can read their own github accounts"
  on public.github_accounts for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own github accounts"
  on public.github_accounts for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can update their own github accounts"
  on public.github_accounts for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "Users can delete their own github accounts"
  on public.github_accounts for delete
  to authenticated
  using (user_id = auth.uid());

-- A foreign key check bypasses RLS, so ownership of the row alone would let a
-- caller attach their own rows to someone else's account. The write policies
-- therefore also require the parent account to be visible to the caller, which
-- RLS limits to their own.
create policy "Users can read their own github daily contributions"
  on public.github_daily_contributions for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own github daily contributions"
  on public.github_daily_contributions for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.github_accounts account
      where account.id = account_id
    )
  );

create policy "Users can update their own github daily contributions"
  on public.github_daily_contributions for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.github_accounts account
      where account.id = account_id
    )
  );

create policy "Users can delete their own github daily contributions"
  on public.github_daily_contributions for delete
  to authenticated
  using (user_id = auth.uid());

-- Commits are stored for 'full' accounts only. The policy makes that structural:
-- a counts_only account cannot have a repository name or a commit headline
-- written against it, whatever the worker does. Flipping an account back to
-- counts_only does not remove commits already stored; that is the worker's job.
create policy "Users can read their own github commits"
  on public.github_commits for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own github commits"
  on public.github_commits for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.github_accounts account
      where account.id = account_id
        and account.detail = 'full'
    )
  );

create policy "Users can update their own github commits"
  on public.github_commits for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.github_accounts account
      where account.id = account_id
        and account.detail = 'full'
    )
  );

create policy "Users can delete their own github commits"
  on public.github_commits for delete
  to authenticated
  using (user_id = auth.uid());
