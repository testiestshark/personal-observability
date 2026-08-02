-- Weight tracking: one row per weigh-in.
--
-- Weight is stored canonically in kilograms so entries stay comparable even when
-- the user switches units between weigh-ins, while `entered_unit` records how the
-- value was typed so it can be displayed back the same way.
--
-- numeric (not float) keeps the decimal exact. timestamptz stores UTC; rendering
-- in UK local time is a presentation concern handled in the app.

create table public.weight_entries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  recorded_at timestamptz not null default now(),
  weight_kg numeric(6, 3) not null,
  entered_unit text not null,
  created_at timestamptz not null default now(),

  -- Sanity bounds only. Catches unit-confusion typos and fat-finger entries
  -- without being fussy about what a plausible human weight is.
  constraint weight_entries_weight_kg_sane check (weight_kg > 0.5 and weight_kg < 1000),
  constraint weight_entries_entered_unit_valid check (entered_unit in ('kg', 'lb', 'st'))
);

-- The only read pattern: this user's entries, newest first.
create index weight_entries_user_recorded_at_idx
  on public.weight_entries (user_id, recorded_at desc);

alter table public.weight_entries enable row level security;

-- RLS filters which rows a role may touch, but it cannot grant access to the
-- table in the first place — without this the policies below never get a chance
-- to run and every query fails with "permission denied for table". `anon` is
-- deliberately excluded: weight data is only ever readable when signed in.
grant select, insert, update, delete on public.weight_entries to authenticated;

-- Users may only ever see or touch their own rows. Reads and writes both go
-- through the cookie-backed request client, so auth.uid() is the signed-in user.
-- The WITH CHECK clauses stop a user writing a row owned by somebody else.
create policy "Users can read their own weight entries"
  on public.weight_entries for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own weight entries"
  on public.weight_entries for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can update their own weight entries"
  on public.weight_entries for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "Users can delete their own weight entries"
  on public.weight_entries for delete
  to authenticated
  using (user_id = auth.uid());
