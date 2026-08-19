# Backlog

**This is the list of what needs doing.** When there is no specific instruction about
what to work on, the next item here is the answer.

Last reviewed: 2026-08-15.

## How this file works

- **[ROADMAP.md](ROADMAP.md) is the coarse view** — milestones, and which data domains
  exist at all. This file is the concrete one: things small enough to actually pick up
  and finish.
- **Priority means "what breaks if this waits".** High is correctness, security or
  something actively misleading. Medium is real work with no bleeding. Low is tidying.
- **Items are removed when done**, not ticked off — git history is the record of what was
  completed, and a file of struck-through lines stops being readable.
- **Add the reasoning, not just the task.** An item nobody understands in three months
  gets skipped forever. Where a finding came from a specific commit or file, link it.
- **Deliberate non-goals live at the bottom**, so a decision already made does not get
  re-litigated as though it were an oversight.

---

## High

### Point the weight import script at the shared CSV parser

[`src/lib/weight/csv.ts`](../src/lib/weight/csv.ts) was extracted in c6ea05f as the
shared parser, but [`scripts/import-weights.ts`](../scripts/import-weights.ts) still
carries its own copy of `splitCsvLine`, `DATE_PATTERN`, `parseDayCell`,
`parseWeightCell` and `oneRowPerDay`. Two parsers, free to drift — and the tests in
`csv.test.ts` only cover one of them. Delete the duplicates from the script and import
from the module.

---

## Medium

### Build the CSV import UI

`csv.ts` currently has **no callers at all**. It was written to be called from the
browser — pure, no I/O, and it already returns everything a preview needs
(`skipped`, `duplicates`, `roundedCount`, and the `provesDayFirst` flag that exists
specifically to warn when a file is ambiguous between dd/mm and mm/dd). What is missing
is the dialog: pick a file, show the summary, confirm, submit.

Finishing this retires `scripts/import-weights.ts` as a thing that has to be run by
hand, and makes the item above moot.

### Show weight as a trend, not just a list

There is a calendar and a history table, but nothing that shows direction. A sparkline
or chart on Today or Insights is the smallest useful version. This is also the first
piece of the app that would justify a shared chart component.

### De-duplicate the weight range constants

`MIN_KG` / `MAX_KG` are declared twice: exported from
[`units.ts`](../src/lib/weight/units.ts) (where `csv.ts` imports them) and re-declared
locally in [`weight.functions.ts`](../src/lib/weight/weight.functions.ts). Both mirror
the same `CHECK` constraint, so the server validator and the CSV validator can silently
disagree if one is ever changed. Import from `units.ts` in both places.

### Decide what to do about `routeTree.gen.ts` churn

The file is generated, committed, and unstable: `bun run build` appends a
`declare module` block that something else then removes. History shows it flip-flopping
across at least four commits (`90c882d`, `611cdc6`, `d2b5f4e`, `bf7ed9e`), all titled
"Changes". Either gitignore it, or find which tool removes the block and stop it —
right now it produces meaningless diffs and will produce spurious CI churn.

---

## Low

### `WeightWheel`'s keyboard step has no "did it change" guard

In [`weight-picker.tsx`](../src/components/weight-picker.tsx), `step()` clamps its index
at either end of a column and then calls `onChange` regardless — so an arrow key at the
top of the list fires a change with the value that was already set. `handleScroll` in the
same component guards this with `next !== value`. Harmless today (the parent sets
identical state) but inconsistent. Behaviour is pinned by tests in
`weight-picker.test.tsx`, so changing it will require updating those two expectations.

### History has a hard cap with no "load more"

`HISTORY_LIMIT` in `weight.functions.ts` is 2000 rows. Beyond that, entries are simply
invisible in the History list — the calendar still shows them. Fine for years of daily
weigh-ins; worth revisiting only if the list ever gets near it.

### `react-refresh/only-export-components` warnings

Six warnings, all in vendored shadcn files under `src/components/ui/`. They do not fail
the build or CI. Either fix upstream-style by splitting the constant exports out, or
silence the rule for that directory — but not worth doing on its own.

---

## Deliberate non-goals

Recorded so they are not raised again as gaps.

- **Removing the signup code now that signup is closed.** Decided on 2026-08-19.
  Public signup is off in two places — `VITE_ALLOW_SIGNUP` defaults to closed (see
  [`signup-policy.ts`](../src/lib/auth/signup-policy.ts)) and _Allow new users to sign
  up_ is off in the Supabase dashboard, which is the authoritative block. The `signUp`
  server function, the login page's create-account mode and the flag itself are
  deliberately **kept**: the owner may want a second account later, and re-opening
  should be a flag flip plus a dashboard toggle, not a rewrite. They are gated, not
  dead code — do not strip them as unreachable.
  Local Supabase keeps signup enabled; set `VITE_ALLOW_SIGNUP=true` in `.env.local`
  to create test accounts.

- **End-to-end / browser tests.** Considered and deferred on 2026-08-15. Playwright
  against a local Supabase stack would catch auth, routing and RLS regressions that unit
  and component tests cannot — but it needs Docker in CI, runs in minutes rather than
  seconds, and flaky runs on a solo project train you to ignore red builds. The CI
  workflow is deliberately structured so an E2E suite can be added as a _separate_
  workflow later without slowing this one down.
- **Application-level roles** (admin / editor / viewer). Ownership via
  `user_id = auth.uid()` is the only differentiation this product has, by policy. See
  [ARCHITECTURE.md § Roles and ownership policy](ARCHITECTURE.md#roles-and-ownership-policy).
- **Building on `src/integrations/supabase/`.** Those files are Lovable-generated and
  implement a superseded `localStorage`/Bearer approach. They cannot be deleted (Lovable
  regenerates them) and must not be extended. Use `src/lib/auth/`.
