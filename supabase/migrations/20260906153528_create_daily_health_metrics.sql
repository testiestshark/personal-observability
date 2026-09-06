-- Normalized daily health data. The first provider is Garmin Connect and the
-- first metric is steps; keeping source/provider metadata here lets the Garmin
-- adapter be replaced without changing the product-facing schema.

create table public.daily_health_metrics (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  steps integer,
  source text not null,
  provider text not null,
  external_id text,
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),

  constraint daily_health_metrics_steps_non_negative
    check (steps is null or steps >= 0),
  constraint daily_health_metrics_source_known
    check (source in ('garmin')),
  constraint daily_health_metrics_provider_known
    check (provider in ('garmin_connect_unofficial')),
  constraint daily_health_metrics_user_day_source_unique
    unique (user_id, day, source)
);

create index daily_health_metrics_user_day_idx
  on public.daily_health_metrics (user_id, day desc);

alter table public.daily_health_metrics enable row level security;

-- Anonymous visitors cannot touch health data. The scheduled worker signs in
-- as the app user and therefore goes through the same RLS policies as the UI.
revoke all on public.daily_health_metrics from anon;
grant select, insert, update, delete on public.daily_health_metrics to authenticated;

create policy "Users can read their own daily health metrics"
  on public.daily_health_metrics for select
  to authenticated
  using (user_id = auth.uid());

create policy "Users can insert their own daily health metrics"
  on public.daily_health_metrics for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can update their own daily health metrics"
  on public.daily_health_metrics for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "Users can delete their own daily health metrics"
  on public.daily_health_metrics for delete
  to authenticated
  using (user_id = auth.uid());
