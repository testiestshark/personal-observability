# Deliberate non-goals

Decisions _not_ to do something, recorded with the date and the reason so they are not
raised again as oversights. Outstanding work lives in GitHub issues.

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

- **Pagination or "load more" for the weigh-in History list.** Settled on 2026-08-19.
  `HISTORY_LIMIT` is 10,000 rows — about 27 years of daily weigh-ins. Closed, not a gap.
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
