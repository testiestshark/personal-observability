# Seeing your work locally

```powershell
bun run local
```

Run it from any worktree. It ends with a banner showing the address for this computer
and the address (and QR code) for a phone on the same Wi-Fi. On the login page, tap
**Sign in as dev**.

## What it does

1. Copies `.env.local` from the main checkout if this worktree has none, and runs
   `bun install` if `node_modules` is missing.
2. Starts this project's local Supabase if it is not already up.
3. Applies migrations this worktree has that the local database lacks. It never resets
   the database.
4. If the local database has no rows, pulls a copy of the hosted data (see below).
5. Makes sure the dev account exists and has the dev password.
6. Takes over port 8080 from any dev server already running, so the phone address is
   always the same, and starts Vite.

`bun run dev` is unchanged — plain `vite dev`, which is what the Lovable sandbox runs.

## The dev account

|          |                                   |
| -------- | --------------------------------- |
| Email    | `DEV_LOGIN_EMAIL` in `.env.local` |
| Password | `12345678`                        |

The password is committed because it only opens the database on your own machine. The
email is not, because this repository is public. Set `DEV_LOGIN_EMAIL` once in the main
checkout's `.env.local`; new worktrees inherit it. Use the same email as your hosted
account, so the pull can find your data.

The **Sign in as dev** button and the branch badge in the corner appear only when both
are true: the server is talking to a Supabase on this machine, and it was started by
`bun run local`. They are compiled out of the production build, and the Lovable preview
(which runs `vite dev` against hosted Supabase) does not show them. The logic is
`resolveDevLogin` in [`src/lib/auth/dev-login.ts`](../src/lib/auth/dev-login.ts).

## Real data

```powershell
bun run local:pull
```

Replaces **all** local data with a copy of the hosted data. Anything you entered
locally is lost. `bun run local` does this for you when the local database is empty —
on first run, and after a `bunx supabase db reset`.

The local dev account is created with the same user id as the hosted account, so the
copied rows belong to it. The copy runs in one transaction: if it does not fit the
local schema, local data is left as it was.

No database password is needed; the Supabase CLI signs in with your account. If the
pull reports the wrong account, run `bunx supabase projects list` — see
[ARCHITECTURE.md](ARCHITECTURE.md) on running alongside another Supabase project.

## Phone: one-time firewall step

Windows blocks inbound connections by default, so the phone cannot reach the dev server
until port 8080 is opened. Run this once in an **administrator** PowerShell while
connected to your home Wi-Fi:

```powershell
Set-NetConnectionProfile -InterfaceAlias "WiFi" -NetworkCategory Private
New-NetFirewallRule -DisplayName "Personal Observability dev server" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow
```

The first line marks the current Wi-Fi network as Private; the second opens the port on
Private networks only, so it stays closed on café and hotel Wi-Fi.

## When something is off

- **The badge shows the wrong branch.** Port 8080 serves whichever worktree ran
  `bun run local` most recently. Run it again from the one you want.
- **"The shared database has migrations from another branch".** All worktrees share one
  local database. Harmless unless this branch adds a migration of its own; in that case
  merge `main` into the branch, or `bunx supabase db reset` and run `bun run local`
  again to rebuild from this branch's migrations and re-pull the data.
- **"Port 8080 is held by …".** Something that is not a dev server has the port. The
  command will not kill it; close it yourself.
- **Phone shows nothing.** Check both devices are on the same Wi-Fi and the firewall
  step above was done. Guest networks often block devices from seeing each other.
