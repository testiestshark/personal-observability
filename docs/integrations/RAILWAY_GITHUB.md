# Railway-hosted GitHub sync

**Status: ready to deploy, not yet deployed ([#77][issue]).** The worker, image,
variable template and this runbook are in the repository. The Railway service, the
two tokens and the first run are owner steps, and this status stays until they are
done and observed.

Railway runs the GitHub worker as a private hourly cron job, the same shape as the
[Garmin](RAILWAY.md) and [Hevy](RAILWAY_HEVY.md) workers:

```text
GitHub GraphQL API -> Railway cron worker -> hosted Supabase -> published app
```

The worker signs in as the app user, reads each configured account's contribution
counts for the trailing 14 UTC dates (and, for a `full` account, its commit
headlines), writes through Row Level Security, stamps `last_synced_at`, and exits. It
exposes no web server or domain. Design, privacy contract and worker behaviour are
in [GITHUB_MULTI_ACCOUNT.md](GITHUB_MULTI_ACCOUNT.md#the-worker-76).

Secrets (the two GitHub tokens and the app password) are entered only in Railway's
Variables editor, never in chat, files or logs.

## 0. Before any token exists: two-factor

A token is only as safe as the account that can mint it. The bar is the one
[#94][hardening] sets for every account that reaches the data: a passkey or
authenticator app (not SMS or emailed codes), recovery codes kept offline, and a
recovery email that meets the same bar. Confirm each on the account's own security
page, and tick it there too:

- [ ] GitHub account A (github.com/settings/security)
- [ ] GitHub account B
- [ ] Railway, and the email address that can reset it

#94 recorded both GitHub accounts as done on 2026-10-10; Railway was still open.
Recheck rather than trust that, because a token minted behind a weak account is the
whole risk this section exists to close.

## 1. Create the tokens

Create each token while signed in as the account it belongs to (a private window
avoids picking the wrong one). GitHub shows a token exactly once, so paste it
straight into Railway (step 2) and do not save it anywhere else.

**Account A: fine-grained, read-only.**

1. github.com/settings/personal-access-tokens -> Generate new token.
2. Name `po-github-sync-A`, expiration **90 days**, resource owner A.
3. Repository access: the repositories whose commit headlines should be kept.
   Repositories left out are invisible to the commit list.
4. Permissions: **Metadata: read** and nothing else. Anything else is more than the
   worker uses.

**Account B: classic, `read:user` only.** Deliberately classic: `read:user` is the one
scope that makes GitHub split private-repository work by type, and fine-grained tokens
have no equivalent ([the probe findings][probe]).

1. github.com/settings/tokens -> Generate new token (classic).
2. Note `po-github-sync-B`, expiration **90 days**.
3. Scopes: tick `read:user` and **nothing else**. No `repo`, no `user`, no
   `user:email`.

**Check B's scopes** before relying on it. Either read them off github.com/settings/tokens,
or ask the API (the token is typed at a hidden prompt, so it does not reach your
shell history):

```powershell
$secret = Read-Host "Account B token" -AsSecureString
$token = [Net.NetworkCredential]::new('', $secret).Password
(Invoke-WebRequest https://api.github.com/user -UseBasicParsing -Headers @{ Authorization = "Bearer $token" }).Headers['X-OAuth-Scopes']
Remove-Variable token, secret
```

The answer must be exactly `read:user`. (Fine-grained tokens send no such header, so
this check is for B only.) If B ever loses the scope, the worker notices by itself: it
stops B's run with "lost the read:user scope" rather than store an undifferentiated
lump over real counts.

## 2. One-time Railway setup

1. In the Railway project add a service named `github-sync` from the GitHub
   repository's `main` branch.
2. Paste the keys from `scripts/github/railway.env.example` into the service's
   Variables.
   - `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are the public hosted values from
     `.env.production` (the `VITE_` ones).
   - `RAILWAY_DOCKERFILE_PATH=/scripts/github/Dockerfile` makes Railway build this
     image rather than the Garmin or Hevy one.
   - `GITHUB_LOGIN_A` / `GITHUB_LOGIN_B` are the logins the tokens must belong to. A
     mismatch refuses the run before anything is written.
   - `GITHUB_DETAIL_A=full` and `GITHUB_DETAIL_B=counts_only`. The default is
     `counts_only`, so a forgotten setting can only ever store less.
3. **App login: reuse the Garmin service's** rather than keeping a third copy. In the
   `github-sync` Variables editor set

   ```text
   PERSONAL_OBSERVABILITY_APP_EMAIL=${{garmin-sync.PERSONAL_OBSERVABILITY_APP_EMAIL}}
   PERSONAL_OBSERVABILITY_APP_PASSWORD=${{garmin-sync.PERSONAL_OBSERVABILITY_APP_PASSWORD}}
   ```

   Railway's documentation does not say whether a sealed variable can be referenced
   this way. If the Garmin password is sealed and the reference comes up empty, type
   the value in directly instead. Both must be set, or neither: the worker refuses a
   half-configured login.

4. **Tokens: `GITHUB_TOKEN_A` and `GITHUB_TOKEN_B` as sealed variables.** Railway does
   support this (verified against its Variables documentation, 2026-10-11). Paste each
   token, then use the variable's three-dot menu -> Seal. What sealing means:
   - The value reaches builds and deployments and is never shown in the UI or
     returned by the API.
   - It is not provided to `railway run` or `railway variables`.
   - It cannot be un-sealed, and cannot be edited through the Raw Editor (use the
     three-dot menu).
   - It is not copied when a service or environment is duplicated, so a duplicate
     starts without the tokens.

   Because a sealed value cannot be read back, **check a token is right before
   sealing it**: a typo means re-entering it, not fixing it. Rotation (below) is
   always a replacement, which sealing does not get in the way of.

5. Attach a persistent volume named `github-data` at `/data`. The worker refuses to
   run on Railway without one, so that a cached app session cannot vanish with the
   container.
6. Set the cron schedule to `15 * * * *` (15 minutes past each hour, UTC). Garmin
   runs at `:05` and Hevy at `:17`. Leave the start command empty: the image defaults
   to `sync` and exits when done. Railway skips a scheduled run while the previous
   one is still running, so a stuck run silently blocks later ones.
7. Do not generate a Railway domain. This is a private outbound-only job.

If Railway's GitHub app has not been granted repository access, deploy the
checked-out commit directly, as for Garmin:

```powershell
railway deployment up --service github-sync --environment production --detach --yes
```

## 3. Confirm the first scheduled run

Watch Railway's logs after the next `:15`. A successful run exits 0 and its log is
counts and timings only, one line per account, for example:

```text
Account A (full): wrote 14 day(s) and 37 commit(s) in 5.2s.
Account B (counts_only): wrote 14 day(s) and 0 commit(s) in 2.9s.
```

No login, label, repository name, commit headline or token appears in it. If you see
one, treat it as a bug and revoke the token (see below).

Then check what was stored. These read hosted with `bunx supabase db query --linked`
(confirm `bunx supabase projects list` shows the project as linked first):

```sql
select label, detail, last_synced_at, token_expires_at
from github_accounts order by display_order;

-- B has no commits stored, by construction
select a.label, count(c.*) as commits
from github_accounts a
left join github_commits c on c.account_id = a.id
group by a.label;
```

`last_synced_at` should be within the hour for both accounts, and
`token_expires_at` should be about 90 days out.

## 4. Backfill the history

The scheduled run only refetches the trailing 14 UTC dates. Load everything since
2026-01-01 once, from this machine, against hosted. The tokens are not on this
machine and cannot be read back from sealed variables, so paste them here at hidden
prompts into the **current PowerShell session only**, not into `.env.local`:

```powershell
function Read-Secret($prompt) { [Net.NetworkCredential]::new('', (Read-Host $prompt -AsSecureString)).Password }

$env:SUPABASE_URL = "<VITE_SUPABASE_URL from .env.production>"
$env:SUPABASE_PUBLISHABLE_KEY = "<VITE_SUPABASE_PUBLISHABLE_KEY from .env.production>"
$env:GITHUB_LOGIN_A = "<account A login>"; $env:GITHUB_DETAIL_A = "full"
$env:GITHUB_LOGIN_B = "<account B login>"; $env:GITHUB_DETAIL_B = "counts_only"
$env:GITHUB_TOKEN_A = Read-Secret "Account A token"
$env:GITHUB_TOKEN_B = Read-Secret "Account B token"

docker compose -f docker-compose.github.yml run --rm github-sync setup      # hosted app login, prompted
docker compose -f docker-compose.github.yml run --rm github-sync backfill

Remove-Item Env:GITHUB_TOKEN_A, Env:GITHUB_TOKEN_B
Remove-Item -Recurse -Force .github-sync   # the cached hosted session
```

Do not pass `--env-file .env.local`: its Supabase values point at the local stack.
Compose reads the variables above from the session, which is also why nothing is
written to disk.

Backfill is idempotent and resumable. It skips dates already stored except the
trailing 14, and GitHub's rate limit stops it with what was written kept: rerun after
the limit resets and it carries on. Afterwards, `github_daily_contributions` should
hold five rows (one per kind) for every UTC date since 2026-01-01 for each account:

```sql
select a.label, count(distinct d.local_day) as days,
       min(d.local_day) as first_day, max(d.local_day) as last_day
from github_accounts a
join github_daily_contributions d on d.account_id = a.id
group by a.label;
```

## 5. What to record on #77

Tick the issue's boxes only for what was observed: the service and schedule, the
sealed variables, the first run's log (counts only) and the backfill. The two-factor
checks in step 0 belong on #94 as well.

## Rotating a token at 90 days

Tokens expire after 90 days. There is **no alert yet**: the app's expiry warning is
part of [#78](https://github.com/testiestshark/personal-observability/issues/78), so
until it lands, put a reminder in your calendar for about 75 days after creating
each token, and check by query:

```sql
select label, token_expires_at,
       (token_expires_at::date - current_date) as days_left
from github_accounts order by token_expires_at;
```

To rotate (A and B are independent; do one at a time):

1. Create the replacement token as in step 1, with the same scopes. Check B's
   scopes again.
2. In Railway, open `github-sync` -> Variables -> `GITHUB_TOKEN_<slot>` -> three-dot
   menu -> Edit, and paste the new value. It stays sealed.
3. Redeploy the service so the next run reads it. Railway does not apply a variable
   change to a running deployment without one.
4. Wait for the next `:15` and check `last_synced_at` and `token_expires_at` moved
   (about 90 days from now).
5. Delete the old token on GitHub. Do this last, so a mistake in step 2 leaves the
   old token working instead of a gap in the data.

An expired token is not data loss: the trailing 14 dates are refetched, so a gap of
up to about two weeks heals on the first good run. Past that, run the backfill in
step 4 again.

## If a token leaks

A token is read-only. Account A's can read repository metadata; account B's can read
the profile's private contribution _counts_ and nothing named (the exposure audit in
[the probe findings][probe] found no repository, organisation or email readable).
It still gets revoked at once:

1. **Revoke first**, before working out how it leaked. GitHub: A at
   github.com/settings/personal-access-tokens, B at github.com/settings/tokens ->
   Delete. This is immediate and the worker simply fails until step 3.
2. Look for use you did not make: the account's security log at
   github.com/settings/security-log.
3. Create a replacement and put it in Railway, as in the rotation steps above.
4. Find where it was exposed (a log, a message, a file) and remove it there too. A
   token that reached this public repository, an issue or a PR is an incident for the
   repository's security process, not for a public issue: see
   [CLAUDE.md](../../CLAUDE.md#public-repository).
5. If the Railway account itself may be compromised rather than one token, rotate the
   app password and the Hevy API key as well, and re-authenticate Garmin.

## What a failed run looks like

A failed run exits non-zero, leaves stored data as it was for the account that
failed, and does not stamp that account's `last_synced_at`, so its data just goes
stale. One account failing does not stop the other, but the run still exits non-zero.
There is no alerting. Read the Railway log; each failure names the account by slot
letter:

- `GitHub request failed (HTTP 401)`: the token expired or was revoked. Rotate it.
- `belongs to a different GitHub login than GITHUB_LOGIN_x`: the token was pasted into
  the wrong slot, or belongs to the wrong account. Nothing was written.
- `lost the read:user scope` (account B): remake B's token with `read:user` ticked.
- `rate limit`: GitHub's limit was nearly spent. Whatever was written is kept and the
  next hourly run resumes.
- `Railway requires a persistent volume`: the volume is missing or not at `/data`.
- App sign-in errors: check the two `PERSONAL_OBSERVABILITY_APP_*` variables, and the
  reference to the Garmin service if you used one.
- `No GitHub accounts are configured`: the token and login variables are missing from
  this service (a duplicated service does not copy sealed ones).
- Anything else names an exception type only; rerun `sync` by hand (the compose
  command above, with `sync`) and compare.

[issue]: https://github.com/testiestshark/personal-observability/issues/77
[hardening]: https://github.com/testiestshark/personal-observability/issues/94
[probe]: GITHUB_MULTI_ACCOUNT.md#decisions-2026-10-10-20
