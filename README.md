# My Personal Hub

Create a private, mobile-first web application shell called Personal Observability.

The product will eventually collect and analyse one person’s:

GitHub activity from two accounts

Strava fitness activities

Daily steps

Weight

Computer activity

Manually recorded iPhone Screen Time

Mood, energy, focus, stress and meaning

Journal entries and daily reflections

Weekly personal reviews

For this first change, create only the application shell and visual navigation.

Create these routes:

Today

Timeline

Insights

Integrations

Journal

Settings

Requirements:

Use Lovable’s current default framework and conventions.

Use a calm, restrained and private-feeling design.

Prioritise mobile usability.

Create a simple desktop sidebar and mobile bottom navigation.

Use clearly labelled mock placeholders where data will eventually appear.

Keep the design neutral so the product can be renamed later.

Do not create database tables.

Do not create Edge Functions.

Do not implement OAuth integrations.

Do not implement AI.

Do not implement payments.

Do not implement public profiles or social features.

Do not add unnecessary libraries.

This step is only intended to establish the application shell and repository structure.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/7c53fb77-15d6-43af-b60e-ce45c17fa9be).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

This project uses [Bun](https://bun.sh) as its package manager and runtime, and [Supabase](https://supabase.com) (run locally via Docker) for the database/auth backend.

Prerequisites:

- [Bun](https://bun.sh)
- [Docker](https://www.docker.com/) (running) — needed for the local Supabase stack

Setup:

```sh
git clone <this-repository-url>
cd <repository-name>
bun install

# Start local Supabase (Postgres, Auth, Storage, Studio)
bunx supabase start

# Copy the env template and fill in the local values printed by `bunx supabase status`
cp .env.example .env.local

bun run dev
```

Restart `bun run dev` after changing any environment variable.

Other useful commands:

```sh
bun run build     # production build
bun run lint       # eslint
bun run format     # prettier --write
bunx supabase stop # stop the local Supabase stack
```

## Automatic Garmin steps

Garmin steps can sync directly from Garmin Connect into the local Supabase
database without Terra or manual exports. Build the worker, complete the one-time
interactive login, test a sync, then install the hourly Windows task:

```powershell
bun run garmin:build
bun run garmin:setup
bun run garmin:sync
powershell -ExecutionPolicy Bypass -File scripts/garmin/install-schedule.ps1
```

The setup prompts locally for both account passwords and Garmin MFA when needed;
passwords are never stored. Reusable bearer tokens live under the gitignored
`.garmin-sync/` directory. The local Supabase stack must be running when a sync
fires. See [the Garmin integration runbook](docs/integrations/GARMIN.md).

The hosted app (this repo's `main` branch, synced with Lovable) connects to **hosted** Supabase — only local development uses the local stack. See [CLAUDE.md](CLAUDE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details on the local-vs-hosted split and secrets policy.

For the published app, authenticate only its separate Supabase session and reuse
the existing Garmin token cache:

```powershell
bun run garmin:setup:live
bun run garmin:sync:live
powershell -ExecutionPolicy Bypass -File scripts/garmin/install-live-schedule.ps1
```

The hosted database migration must be deployed before the first live sync. See
[the Garmin integration runbook](docs/integrations/GARMIN.md#live-setup-and-verification).
