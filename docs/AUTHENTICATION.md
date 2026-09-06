# Authentication — local verification runbook

This is a repeatable, local-only procedure for proving the auth system works against
local Supabase, using the current checkout plus Docker. For the design/architecture
(why cookies and why the generated files are unused), see
[ARCHITECTURE.md § Authentication](ARCHITECTURE.md#authentication).

Local flow last confirmed working: 2026-09-06 — account created, login reached the app,
the session persisted across a hard refresh, and the disposable user was removed.

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

If you want a _truly_ clean slate (no leftover test users from a previous run):

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

## Production-build sanity check

The dev server reads `.env.local`, while hosted builds read the committed public values
from `.env.production`. The request-scoped client can use the build-time
`VITE_SUPABASE_*` public values when unprefixed runtime variables are unavailable.
These commands catch packaging regressions:

```powershell
bun run build
```

Then assert on the output:

```powershell
# Must print nothing — the generated Supabase client must never reach the browser
Select-String -Path .output/public/assets/*.js -Pattern "Connect Supabase in Lovable Cloud"

# Must list a chunk — auth server code must be present server-side
Get-ChildItem .output/server/_ssr/ | Where-Object { $_.Name -like "supabase-request.server*" }
```

If the first command prints a match, the browser bundle contains the generated Supabase
client instead of the app's cookie-based auth path — see
[ARCHITECTURE.md § Authentication](ARCHITECTURE.md#authentication).

Note that `bunx vite preview` does **not** work for this project: Nitro builds a Cloudflare Worker to `.output/server/`, while `vite preview` expects `dist/server/server.js`. A 500 from it is a tooling mismatch, not an app failure.

## Confirm against the database directly

Open Supabase Studio at `http://127.0.0.1:54323` → Authentication → Users. The account created in step 2 should be listed there, with the same email shown in Settings — this is the cross-check that "connected as X" reflects a real row, not a client-side illusion.

## What each step is actually proving

| Step | Proves                                                               |
| ---- | -------------------------------------------------------------------- |
| 1    | Server-side route protection works before any React renders          |
| 2    | Sign-up writes a real Supabase Auth user, session cookie is set      |
| 3    | SSR can read the session (no `localStorage` involved)                |
| 4    | Session survives a full page reload — cookie-based, not memory-based |
| 5    | Protection is bidirectional (signed-in users can't see `/login`)     |
| 6    | Sign-out clears the server-recognized session, not just UI state     |

Step 3+4 together are the property the GitHub integration milestone depends on (see
[integrations/GITHUB.md § 3](integrations/GITHUB.md)).

## Troubleshooting

- **Redirect loop or 500 on `/`:** check `.env.local` has `SUPABASE_URL`/`SUPABASE_PUBLISHABLE_KEY` set to the _local_ values from `bunx supabase status`, not hosted ones (see [ARCHITECTURE.md § Environments and sync model](ARCHITECTURE.md#environments-and-sync-model)).
- **Sign-up silently does nothing / no error shown:** open the browser console — a thrown error in the server function surfaces there; also check the `bun run dev` terminal output for a stack trace.
- **Want to re-run from scratch without wiping the whole DB:** just delete the user via Studio (Authentication → Users → delete), or sign up with a new email — signup does not enforce anything beyond Supabase's own email-uniqueness rule.
