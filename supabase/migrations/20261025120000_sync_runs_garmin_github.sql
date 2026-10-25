-- Widen the heartbeat table so the Garmin and GitHub workers can record a
-- Worker run too, not only Hevy. Grants and RLS are unchanged.

alter table public.sync_runs
  drop constraint sync_runs_source_known;

alter table public.sync_runs
  add constraint sync_runs_source_known
    check (source in ('hevy', 'garmin', 'github'));
