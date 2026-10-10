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

- **Correlating Garmin and Hevy records of the same gym visit.** Decided on 2026-09-29
  (#21). The owner does not record strength training on the watch, so a Garmin
  strength activity never exists alongside a Hevy workout. The "future presentation
  layer may correlate them" notes in [ARCHITECTURE.md](ARCHITECTURE.md) and
  [HEVY.md](integrations/HEVY.md) describe work that will not be built; ingestion
  keeps each source's records separate regardless.

- **Storing or showing Hevy's workout-level note.** Decided on 2026-10-10 (#29). Hevy
  lets you write a free-text note on a whole workout (`description` in the API). The
  owner does not use it, so the sync deliberately drops it and the workout detail view
  does not show it. Per-exercise notes are different: they are stored and shown.
  Reopen only if the owner starts writing workout notes.

- **A tunnel for opening the local app away from home Wi-Fi.** Decided on 2026-10-06
  (#58). `bun run local` serves the phone over the same Wi-Fi only. A tunnel would put
  a build with a one-tap sign-in and a copy of real data on a public address.

- **A separate port per worktree.** Decided on 2026-10-06 (#58). `bun run local` always
  takes port 8080, replacing whichever worktree was being served, so the phone address
  never changes. The on-screen branch badge says which one is showing.

- **Invented seed data for local development.** Decided on 2026-10-06 (#58). Local data
  is a copy of the hosted data (`bun run local:pull`), which is the only source that
  looks like the live app and includes manual entries. There is no `supabase/seed.sql`.

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

- **The GitHub App "Connect GitHub" flow.** Decided on 2026-10-10 (#20). GitHub is read
  with one fine-grained personal access token per account, held in Railway, instead of an
  installation flow. An App only reaches accounts and orgs where it is installed and
  needs refresh-token rotation; for one owner with two accounts that is more machinery
  than the job needs. [GITHUB.md](integrations/GITHUB.md) is superseded for reading data.
  Reopen only if the app ever becomes multi-user or a "Connect" button is wanted.
- **All branches, for GitHub activity.** Decided on 2026-10-10 (#20). Default branch
  only, which matches the numbers GitHub shows and keeps the worker cheap.
- **Repo names, commit headlines, or even a repo count for the second GitHub account.**
  Decided on 2026-10-10 (#20). That account is counts-only (`detail = 'counts_only'`):
  its queries never select names or messages, a contract test enforces it, and nothing
  but per-type daily counts is stored. Do not add specifics "for completeness".
- **PR, review and issue titles in the first GitHub version.** Decided on 2026-10-10
  (#20). Only the commit list (first account) is itemised; everything else is a count.
- **Bucketing GitHub activity by the commit's own offset when travelling.** Decided on
  2026-10-10 (#20). Superseded in practice by the next entry.
- **Re-bucketing GitHub counts into `Europe/London` days.** Decided on 2026-10-10 (#74,
  #20). GitHub does not honour sub-day `from`/`to` windows and buckets by UTC calendar
  date, so a London-day query spans two dates and double-counts. All GitHub counts use
  GitHub's own UTC date (the **GitHub day**) and the page says so. Account A's commit
  list may still show times in London.
- **A classic `repo` token, or a fine-grained token for account B.** Decided on
  2026-10-10 (#74). `repo` is write access to everything. A fine-grained token cannot
  carry `read:user`, so account B's private work would come back as one unsplit lump.
  Account A uses a fine-grained read-only token; B uses a classic token with `read:user`
  and nothing else, which can read no code and no repo, PR, issue or organisation name.
