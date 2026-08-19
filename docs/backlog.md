# Backlog

**This is the list of what needs doing.** When there is no specific instruction about
what to work on, the next item here is the answer.

Last reviewed: 2026-08-19.

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

_Nothing outstanding._

---

## Medium

### Show weight as a trend, not just a list

There is a calendar and a history table, but nothing that shows direction. A sparkline
or chart on Today or Insights is the smallest useful version. This is also the first
piece of the app that would justify a shared chart component.

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

- **Weigh-in CSV import, in any form.** Dropped on 2026-08-19. The import existed to
  load historic entries once; that is done, this is a single-user app, and weigh-ins now
  come from the PWA daily. `src/lib/weight/csv.ts`, its test and
  `scripts/import-weights.ts` were deleted rather than left as ~856 lines with no
  callers. Recoverable from git history if a bulk import is ever needed again.
- **Splitting the non-component exports out of `src/components/ui/`.** Decided on
  2026-08-19. That directory is vendored shadcn code; its CLI would undo the split on
  the next regeneration. `react-refresh/only-export-components` is switched off for
  that path in `eslint.config.js` instead, and remains on everywhere else.

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
