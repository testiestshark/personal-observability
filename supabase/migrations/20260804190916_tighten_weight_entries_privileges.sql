-- Close Gate 1 (table-level access) for anon on weight_entries, matching the
-- standard pattern in supabase/README.md.
--
-- The original migration ran as `postgres` (db push always does), and Supabase's
-- default privileges auto-grant broad access to anon/authenticated/service_role
-- on any table created that way. Confirmed on hosted: anon had table-level SELECT
-- and INSERT on weight_entries, wider than the migration explicitly asked for.
--
-- This was never a real exposure -- RLS policies (Gate 2) already stop anon from
-- reading or writing real rows, since auth.uid() is NULL for an unauthenticated
-- request and no row has a NULL user_id. This migration closes the belt-and-braces
-- layer explicitly rather than relying on Supabase's defaults.
revoke all on public.weight_entries from anon;

-- service_role is intentionally left with full privileges -- it bypasses RLS by
-- design for trusted server-side code (see src/integrations/supabase/client.server.ts).
