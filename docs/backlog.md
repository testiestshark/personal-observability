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

### Close public signup on the hosted project

Anyone can currently create an account on the deployed app. This is a single-user
product, so signup should be off now the owner account exists.

Must be done in the Supabase dashboard (Authentication → Sign In / Providers), **not**
via `supabase config push` — see
[ARCHITECTURE.md § Authentication](ARCHITECTURE.md#authentication) for why that command
would reset `site_url` and break hosted redirect links. Local Supabase intentionally
keeps signup enabled so test accounts can still be created.

---

## Medium

### Show weight as a trend, not just a list

There is a calendar and a history table, but nothing that shows direction. A sparkline
or chart on Today or Insights is the smallest useful version. This is also the first
piece of the app that would justify a shared chart component.

### De-duplicate the weight range constants

`MIN_KG` / `MAX_KG` are declared twice: exported from
[`units.ts`](../src/lib/weight/units.ts) and re-declared locally in
[`weight.functions.ts`](../src/lib/weight/weight.functions.ts). Both mirror the same
`CHECK` constraint, so they can silently disagree if one is ever changed. Since the CSV
parser was deleted the `units.ts` pair has no consumer left at all — keep `units.ts` as
the single home and import from it in `weight.functions.ts`.

### Decide what to do about `routeTree.gen.ts` churn

The file is generated, committed, and unstable: `bun run build` appends a
`declare module` block that something else then removes. History shows it flip-flopping
across at least four commits (`90c882d`, `611cdc6`, `d2b5f4e`, `bf7ed9e`), all titled
"Changes". Either gitignore it, or find which tool removes the block and stop it —
right now it produces meaningless diffs and will produce spurious CI churn.

### Land or retire the GitHub integration spec

[ROADMAP.md](ROADMAP.md) links `docs/integrations/GITHUB.md`, **which does not exist on
`main`.** The 266-line spec lives only on the unmerged `feature/github-integration`
branch. Either merge that branch (it is docs-only, so it is safe) or drop the link.
Right now the roadmap points at nothing.

### Prune merged branches

`feature/github-integration` is the last one left. It exists **only locally** — it was
never pushed, and it is not merged, so `git branch -d` refuses it and `git branch -D`
would destroy the only copy of the 266-line spec described in the item above. Resolve
that item first; deleting the branch is the last step of it, not a separate chore.

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
