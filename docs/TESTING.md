# Testing

## Commands

```powershell
bun run test           # run everything once (what CI runs)
bun run test:watch     # re-run on change while developing
bun run test:coverage  # coverage report, text + HTML in coverage/
bun run verify         # lint, typecheck, test, build — the full CI gate locally
```

Run `bun run verify` before pushing. It is the same sequence as
[the CI workflow](../.github/workflows/ci.yml), so a green run locally means a green run
on GitHub.

## Layout

Tests sit next to the code they cover, as `*.test.ts` / `*.test.tsx`:

```
src/lib/weight/units.ts        src/lib/weight/units.test.ts
src/lib/weight/csv.ts          src/lib/weight/csv.test.ts
src/components/weight-picker.tsx   src/components/weight-picker.test.tsx
```

Shared setup is in [`src/test/setup.ts`](../src/test/setup.ts); configuration is
[`vitest.config.ts`](../vitest.config.ts), which is deliberately separate from
`vite.config.ts` (that one is built on Lovable's bundled TanStack/nitro config, which a
unit test run has no use for).

## What is worth testing here

This codebase's bugs have been **logic bugs in pure functions**, not UI bugs. Two
timezone defects shipped and had to be fixed later: entries recorded late in the evening
during BST were filed under the wrong day, and every history row displayed a "13:00" that
was an artefact of storage rather than anything recorded. Both are now pinned by tests in
`units.test.ts`.

So, in rough order of value:

1. **Pure logic** — date/timezone handling, CSV parsing, unit conversion, calendar
   arithmetic. Cheap, fast, and where the real defects live.
2. **Component behaviour** — that a control reports the right value, that a destructive
   action asks first and reports failure. Not styling, and not layout.
3. **Everything else** — currently not covered. Server functions in
   `weight.functions.ts` are untested because they need a Supabase client; see the
   end-to-end note in [backlog.md](backlog.md#deliberate-non-goals).

## Conventions

**Assert behaviour, not implementation.** Query by role and accessible name
(`getByRole("button", { name: "Delete" })`) rather than by test id or class. It keeps
tests alive across a restyle, and a component that is hard to query this way usually has
a real accessibility problem.

**Don't assert exact `Intl` output.** Formatted dates and month names vary between ICU
versions, so a CI runner on a different Node build would fail on a string that is
perfectly correct. Assert the parts (`expect(label).toContain("Aug")`), or compare
against another call of the same helper. Day _keys_ (`YYYY-MM-DD`) are stable and may be
asserted exactly.

**Freeze time when testing "now".** `currentLondonDay` and `currentLondonMonth` read the
clock, so tests use `vi.useFakeTimers()` / `vi.setSystemTime()` and restore real timers
afterwards. A test that passes only in summer is worse than no test.

**Say why in the test name.** `"treats a late-evening BST instant as the next London
day"` explains the case; `"works correctly"` does not. Where a test pins a bug that
actually shipped, reference the commit — that is the strongest argument against someone
later "simplifying" the guard away.

## jsdom's limits

jsdom has no layout engine and no pointer capture, so a few DOM methods the real
components call do not exist there. `src/test/setup.ts` stubs them as no-ops —
`scrollTo`, `scrollIntoView`, the pointer-capture trio, `ResizeObserver`, `matchMedia`.

Those stubs are there to stop irrelevant crashes, **not** to be asserted against. The
consequence worth knowing: `WeightWheel` is driven by scroll position in a real browser,
and that path cannot be tested here. Its tests exercise clicking a row and the arrow
keys, which reach the same `onChange`. Genuine scroll-snapping behaviour needs a real
browser and is out of scope by the decision recorded in the backlog.
