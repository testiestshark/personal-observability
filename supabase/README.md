# Standard pattern: a new user-owned table

Every table that stores this user's data (weight, steps, journal entries, etc.) should follow this shape. Copy it into a fresh migration (`bunx supabase migration new create_<thing>`) and fill in the blanks.

```sql
create table public.<thing> (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  ...
);
create index <thing>_user_idx on public.<thing> (user_id);

alter table public.<thing> enable row level security;
revoke all on public.<thing> from anon;                    -- close Gate 1 for anon
grant select, insert, update, delete on public.<thing> to authenticated;

-- Gate 2, all four verbs. WITH CHECK on write stops forging rows owned by others.
create policy "read own"   on public.<thing> for select to authenticated using (user_id = auth.uid());
create policy "insert own" on public.<thing> for insert to authenticated with check (user_id = auth.uid());
create policy "update own" on public.<thing> for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "delete own" on public.<thing> for delete to authenticated using (user_id = auth.uid());
```

## Why each part matters

- **`on delete cascade`** — deleting the user cleans up their data automatically. No orphaned rows to hunt down later.
- **Index on `user_id`** — every real query is "this user's rows," so this is the only index that earns its keep at this stage.
- **`enable row level security`** — without this, RLS policies exist but are never consulted; Postgres just runs the query as if they weren't there.
- **`revoke all ... from anon`** — closes **Gate 1** (table-level access) explicitly. Supabase's default privileges otherwise auto-grant broad access to `anon`/`authenticated` on any table created as `postgres` (which `db push` does), so without this, `anon` gets more than intended. Belt-and-braces: **Gate 2** (the policies, via `auth.uid()` returning `NULL` for anonymous requests) already blocks anonymous reads of real rows even without the revoke — this is defense in depth, not the only thing standing between anon and your data.
- **`grant ... to authenticated`** — opens Gate 1 for the one role that should have it. Skipping this is the single most common way to break a brand-new table: RLS policies can be perfect and every query still fails with `permission denied for table`, because the role was never allowed to touch it in the first place.
- **Four separate policies, not one** — `select`/`insert`/`update`/`delete` are checked independently. A table with only a `select` policy denies every write by default (which is often what you want, but must be a deliberate choice, not an oversight).
- **`with check` on insert/update** — `using` alone only filters what you can _see_; `with check` is what stops a request from _writing_ a row it shouldn't own. Insert has no existing row to filter on, so `using` wouldn't apply there at all — `with check` is the only gate available for insert.

## Two gates, not one

| Gate | Question                              | Mechanism          | What happens if skipped                                                                      |
| ---- | ------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------- |
| 1    | May this role touch the table at all? | `GRANT` / `REVOKE` | Every query fails with `permission denied for table`                                         |
| 2    | Which _rows_ may it see?              | RLS policy         | The role can touch the table, but sees/changes nothing (or everything, if RLS itself is off) |

Both gates apply independently. A table can pass Gate 1 and still be correctly locked down by Gate 2 (this is what actually protects `anon` on rows it has table-level access to but no matching `user_id`) — but relying on Gate 2 alone leaves the table's privileges wider than they need to be, which is worth closing explicitly rather than leaving to Supabase's defaults.

## Is this enough for a single-user app?

Yes, for the case this project is actually in right now: one person, their own data, no sharing, no admin/service accounts touching user tables directly. `user_id = auth.uid()` plus the two gates above is a complete, correct isolation model for that case — proven by direct testing against `weight_entries` (a second user genuinely cannot read, insert-as, update, or delete another user's rows; anonymous sees nothing).

This pattern stops being sufficient the moment any of these becomes true — not before:

- **A second person gets an account with different powers** (viewer vs. editor) — needs actual application roles, not just ownership.
- **A background job or integration writes on the user's behalf** without them present in the request (e.g. a scheduled sync) — needs a `service_role`-backed path with its own scoping, since `service_role` bypasses RLS entirely by design and must not become the accidental default for ordinary requests.
- **Anything gets shared** between users, even partially — ownership by a single `user_id` can't express "mine, but visible to one other person" without an explicit sharing table and its own policies.
- **File storage is added** (e.g. photos, exports) — Supabase Storage buckets have their own RLS model, separate from table RLS, and need the same ownership thinking applied there independently.

None of those apply yet. Don't build for them now — add the mechanism when one of them actually happens.

This is the _how_. For the actual decided policy — no application roles, `service_role` banned from application code, and the mandatory verification step after any privilege/RLS change — see [docs/ARCHITECTURE.md § Roles and ownership policy](../docs/ARCHITECTURE.md#roles-and-ownership-policy).
