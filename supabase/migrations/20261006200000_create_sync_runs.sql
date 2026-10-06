-- One row per owner and integration source, holding when that source's sync
-- last ran successfully. The Integrations page reads it for "Last synced".
-- It is a heartbeat, deliberately separate from the data rows: a week without
-- training must still look fresh, while a revoked key must look stale.

create table public.sync_runs (
  user_id uuid not null references auth.users (id) on delete cascade,
  source text not null,
  last_succeeded_at timestamptz not null,

  primary key (user_id, source),
  constraint sync_runs_source_known
    check (source in ('hevy'))
);

-- No separate user_id index: the primary key (user_id, source) already leads with it.

alter table public.sync_runs enable row level security;

-- Anonymous visitors cannot touch sync state. The worker signs in as the app
-- user and therefore goes through the same RLS policies as the UI.
revoke all on public.sync_runs from anon;
grant select, insert, update, delete on public.sync_runs to authenticated;

create policy "Users can read their own sync runs"
  on public.sync_runs for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own sync runs"
  on public.sync_runs for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can update their own sync runs"
  on public.sync_runs for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "Users can delete their own sync runs"
  on public.sync_runs for delete
  to authenticated
  using (user_id = auth.uid());
