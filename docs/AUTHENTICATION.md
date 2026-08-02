# Authentication — verification runbook

This is a repeatable, local-only procedure for proving the auth system works, using nothing but what's currently committed on `feature/auth-foundation` plus Docker. For the design/architecture (why cookies, why no browser Supabase client, why the generated files are unused), see [ARCHITECTURE.md § Authentication](ARCHITECTURE.md#authentication).

Last confirmed working: 2026-08-02, by manual browser walkthrough (steps below) — account created, session persisted across refresh, matching local Supabase's `auth.users`.

## Prerequisites

- Docker Desktop running
- `bun install` has been run (pulls in `@supabase/ssr`, added in this branch)
- `.env.local` present (see [ARCHITECTURE.md § Secrets policy](ARCHITECTURE.md#secrets-policy))

## Start from a known state

```powershell
bunx supabase status   # if not running: bunx supabase start
bun run dev
```

`supabase status` should report `API_URL` as `http://127.0.0.1:54321`. `bun run dev` prints a `Local:` URL — these steps assume `http://localhost:8080`; use whatever port it actually printed if 8080 was in use.

If you want a *truly* clean slate (no leftover test users from a previous run):

```powershell
bunx supabase db reset
```

This wipes local `auth.users` along with everything else, so any account created below will need recreating.

## Manual browser walkthrough

1. **Open `http://localhost:8080/`.**
   Expected: immediate redirect to `/login`, no flash of the app shell first. This is `beforeLoad` in [`src/routes/__root.tsx`](../src/routes/__root.tsx) refusing an unauthenticated request server-side.

2. **On the login page, click "Create one," enter an email and an 8+ character password, submit.**
   Expected: redirected straight to `/` (Today), app shell now visible (sidebar nav, bottom nav on mobile widths).
   If instead you see "Check your email to confirm the account" — email confirmations are on for this local project. Get the link from Mailpit at `http://127.0.0.1:54324`, follow it, then sign in normally from `/login`.

3. **Go to Settings.**
   Expected: "Signed in as `<the email you used>`" under Account. This value is rendered server-side ([`src/routes/settings.tsx`](../src/routes/settings.tsx) reading `Route.useRouteContext().user`), not read from browser state.

4. **Hard-refresh the page (Ctrl+Shift+R).**
   Expected: still signed in, same email still shown. This is the actual property the system exists for — the session is a cookie the server reads on every request, not something held only in a JS variable that a refresh would wipe.

5. **While signed in, manually navigate to `http://localhost:8080/login`.**
   Expected: immediately redirected back to `/` — `beforeLoad`'s `PUBLIC_PATHS` check refusing to show the login form to an already-authenticated session.

6. **Click "Sign out" in Settings.**
   Expected: redirected to `/login`. Then navigating to `http://localhost:8080/` should redirect straight back to `/login` — confirms sign-out actually cleared the server-side session, not just client state.

## Confirm against the database directly

Open Supabase Studio at `http://127.0.0.1:54323` → Authentication → Users. The account created in step 2 should be listed there, with the same email shown in Settings — this is the cross-check that "connected as X" reflects a real row, not a client-side illusion.

## What each step is actually proving

| Step | Proves |
|---|---|
| 1 | Server-side route protection works before any React renders |
| 2 | Sign-up writes a real Supabase Auth user, session cookie is set |
| 3 | SSR can read the session (no `localStorage` involved) |
| 4 | Session survives a full page reload — cookie-based, not memory-based |
| 5 | Protection is bidirectional (signed-in users can't see `/login`) |
| 6 | Sign-out clears the server-recognized session, not just UI state |

Step 3+4 together are the property the GitHub integration milestone specifically depends on (see [integrations/GITHUB.md § 3](integrations/GITHUB.md)) — a callback from an external provider is a top-level browser navigation carrying cookies, not a `fetch` carrying an `Authorization` header, so this had to work via cookies or that milestone couldn't proceed at all.

## Troubleshooting

- **Redirect loop or 500 on `/`:** check `.env.local` has `SUPABASE_URL`/`SUPABASE_PUBLISHABLE_KEY` set to the *local* values from `bunx supabase status`, not hosted ones (see [ARCHITECTURE.md § Environments and sync model](ARCHITECTURE.md#environments-and-sync-model)).
- **Sign-up silently does nothing / no error shown:** open the browser console — a thrown error in the server function surfaces there; also check the `bun run dev` terminal output for a stack trace.
- **Want to re-run from scratch without wiping the whole DB:** just delete the user via Studio (Authentication → Users → delete), or sign up with a new email — signup does not enforce anything beyond Supabase's own email-uniqueness rule.
