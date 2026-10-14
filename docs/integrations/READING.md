# Reading integration: Kindle, Audible, Spotify audiobooks

**Status: Researched on 2026-10-14 from primary sources only (documentation and
source code). Nothing was run against any account, and no private API was called.
Not designed and not built. Replaces the first pass in #112, which was written from
secondary summaries.**

The goal is the owner's reading and listening history as a data domain next to
Garmin and Hevy. Audible is the first target; Kindle second; Spotify audiobooks are
explicitly not first. Every claim below names the source that owns it. Anything not
confirmed from a primary source is marked **unverified**.

## Summary

- **No source has an official API for this data.** Audible's API is private;
  Amazon's Kindle data comes only from the manual data request; Spotify's public API
  has no audiobook listening history.
- **Audible gives totals, not sessions, through the API.** The only listening-time
  endpoint returns monthly (up to 12 months) and daily (up to 30 days) aggregates.
  The per-session "Listen Log" exists in the Audible app but its help page says it
  cannot be downloaded or exported.
- **Kindle sessions exist in the Amazon data export**, but only second-hand sources
  describe the file. Amazon's own pages do not list the categories (the request
  form is behind sign-in).
- **Spotify is a poor fit.** `recently-played` is documented for tracks only, a
  development-mode app needs the owner to hold Premium, and audiobook progress is
  only a per-chapter resume point.
- **Audible and Amazon terms exclude "data mining, robots, or similar data gathering
  and extraction tools".** The Audible licence text is quoted in full below.

## 1. Audible

### What the library is

`audible` ([mkb79/Audible](https://github.com/mkb79/Audible), Python, v0.13.0
released 2026-10-12) is a "Python low-level interface" to Audible's non-public API.
Its own docs say "There is currently no publicly available documentation about the
Audible API" and that the API is "partially self-documenting"
([external_api.rst](https://github.com/mkb79/Audible/blob/master/docs/source/misc/external_api.rst)).
`audible-cli` ([mkb79/audible-cli](https://github.com/mkb79/audible-cli)) is a CLI
on top of it. Neither is affiliated with Audible. The parameter lists below are the
maintainer's, not Audible's.

### Endpoints

All paths are on `api.audible.<tld>`. Parameters are from
[external_api.rst](https://github.com/mkb79/Audible/blob/master/docs/source/misc/external_api.rst)
(Stats section) unless stated.

**`GET /1.0/stats/aggregates`**

| Parameter                               | Documented values                                               |
| --------------------------------------- | --------------------------------------------------------------- |
| `daily_listening_interval_duration`     | 0 to 30 inclusive                                               |
| `daily_listening_interval_start_date`   | `YYYY-MM-DD`                                                    |
| `monthly_listening_interval_duration`   | 0 to 12 inclusive                                               |
| `monthly_listening_interval_start_date` | `YYYY-MM`                                                       |
| `response_groups`                       | `total_listening_stats`                                         |
| `store`                                 | `AudibleForInstitutions`, `Audible`, `AmazonEnglish`, `Rodizio` |
| `locale`                                | e.g. `en_US`                                                    |

Response, from real use in
[`examples/listening_stats.py`](https://github.com/mkb79/Audible/blob/master/examples/listening_stats.py)
and
[`plugin_cmds/cmd_listening-stats.py`](https://github.com/mkb79/audible-cli/blob/master/plugin_cmds/cmd_listening-stats.py):

- Top-level key `aggregated_monthly_listening_stats`, a list.
- Each entry has `interval_identifier` (the month) and `aggregated_sum`, which both
  scripts convert as **milliseconds**.
- The daily key name, the shape of `total_listening_stats`, and whether a month with
  no listening is present or omitted are **unverified**: no source shows a daily
  response body.
- Both scripts convert milliseconds with `hours % 24`, so a month over 24 hours would
  be misreported if copied. Store milliseconds or seconds and format at display time.
- The maintainer's own account of the endpoint family (issue
  [#495](https://github.com/mkb79/Audible/issues/495), 2024-08-29) lists
  `stats/status/finished`, `stats/aggregates` and `stats/continuelistening`, and says
  `stats/events` "only [has] PUT requests". A user who tried the aggregates endpoint
  replied the responses were "mostly gibberish and without anything besides plain
  listening time".

**`GET /1.0/library`**

- `response_groups` accepts, among others, `is_finished`, `listening_status` and
  `percent_complete`; `num_results` max 1000; `purchased_after` takes RFC 3339.
  Same docs file.
- Field types from a third-party client's DTOs
  ([AudibleApi `LibraryDtoV10.generated.cs`](https://github.com/rmcrackan/AudibleApi/blob/master/AudibleApi.Common/LibraryDtoV10.generated.cs)):
  `is_finished` is a boolean and `percent_complete` a double.
- `audible-cli` lists `is_finished` and `percent_complete` as exported library
  fields ([`cmd_library.py`](https://github.com/mkb79/audible-cli/blob/master/src/audible_cli/cmds/cmd_library.py)).
- The shape of `listening_status` is **unverified**: it appears as a response group
  in both projects but in no response model or test found.
- The unit of `percent_complete` (0 to 1 or 0 to 100) is **unverified**.
- There is no finished date on the item in anything read. `GET /1.0/stats/status/finished`
  (`asin`, `start_date` query parameters) is the endpoint that might carry one; its
  response is **unverified**.

**`GET /1.0/annotations/lastpositions?asins=<comma list>`**

A response shown by the maintainer in audible-cli issue
[#242](https://github.com/mkb79/audible-cli/issues/242) (quoted from a capture of the
iOS app calling `...&response_groups=always-returned`):

```json
{
  "asin_last_position_heard_annots": [
    {
      "asin": "...",
      "last_position_heard": {
        "last_updated": "2025-06-16 20:23:18.818",
        "position_ms": 4542015,
        "status": "Exists"
      }
    }
  ],
  "response_groups": ["always-returned"]
}
```

This is a position per book with a last-updated time, not a history.

### Granularity

The API-reachable data is: monthly and daily totals, per-book finished flag and
percent, and the last position per book. No source read shows per-session or
per-day-per-book listening through the API.

Audible's help centre says otherwise about the app. The Listen Log "shows you
everything from when you first started a title to when you finished listening to
it", with start time, pause time and session length per session, "is available only
on the Audible app", and "Listen Log data cannot be downloaded or exported"
([Audible Help: view listening log](https://help.audible.com/s/article/view-listening-log?language=en_US),
accessed 2026-10-14; also states "Listening History data cannot be downloaded or
exported"). "View Your Listening Stats" says stats are "updated in real-time" and
that "certain insights" such as top genres "are updated monthly"; it does not say
whether offline listening is counted
([Audible Help: listening stats](https://help.audible.com/s/article/view-your-listening-stats?language=en_US),
accessed 2026-10-14).

So per-session history exists inside Audible but, as far as these sources show, is
not reachable by the API. Whether `stats/events` holds it is unknown, since only
`PUT` is documented.

### Authentication

From [authorization.rst](https://github.com/mkb79/Audible/blob/master/docs/source/auth/authorization.rst),
[authentication.rst](https://github.com/mkb79/Audible/blob/master/docs/source/auth/authentication.rst),
[register.rst](https://github.com/mkb79/Audible/blob/master/docs/source/auth/register.rst)
and [`auth.py`](https://github.com/mkb79/Audible/blob/master/src/audible/auth.py):

- **Login** is an Amazon sign-in that registers a "virtual" Audible device
  (`Authenticator.from_login` or `from_login_external`). The external flow has the
  owner sign in in a normal browser and paste back the final URL, so the library
  never sees the password.
- **Challenges the docs list:** CAPTCHA ("in some cases"), 2FA OTP, a CVF verify
  code when Amazon "detects some security risks", and an approval alert with an
  email from Amazon.
- **Registration shows on the Amazon devices list.** "Every device registration will
  be shown on the Amazon devices list. So only register once and save your
  credentials."
- **Lifetime.** "Authentication data obtained by a device registration are valid
  until deregister." The access token expires after 60 minutes and is renewed with
  the refresh token (`refresh_access_token`).
- **Token file contents**, from the test fixture
  ([`auth_fixture.json`](https://github.com/mkb79/Audible/blob/master/tests/fixtures/auth_fixture.json),
  fake values): website cookies, `adp_token`, `access_token`, `refresh_token`, an RSA
  `device_private_key`, `device_info`, `customer_info` (user id, name, home region),
  `expires`, `locale_code`, and `activation_bytes`. It holds no password but is
  full account access for Audible, so it needs the same care as the Garmin session
  volume ([RAILWAY.md](RAILWAY.md)). The file can be encrypted with a password.
- **Request signing** uses the device key (`x-adp-signature`); the bearer method
  "has some restrictions".
- **Marketplaces** ([marketplaces.rst](https://github.com/mkb79/Audible/blob/master/docs/source/marketplaces/marketplaces.rst)):
  11 codes: `us`, `ca`, `uk`, `au`, `fr`, `de`, `jp`, `it`, `in`, `es`, `br`. Device
  registration data "are valid for all marketplaces", website cookies are not.
  `stats/aggregates` takes a `store` parameter, and the library is per marketplace.

### Breakage and account problems in the project's issues

- [Audible #832](https://github.com/mkb79/Audible/issues/832) (2025-11-24, closed):
  report that the app now sends `x-amz-access-token` instead of `Authorization:
Bearer` and that `/auth/token` returns `actor_access_token`/`actor_refresh_token`.
  On 2026-10-14 `auth.py` on `master` still reads `resp_dict["access_token"]`; whether
  that endpoint's behaviour changed for the signing method is **unverified**.
- [Audible #732](https://github.com/mkb79/Audible/issues/732) (2025-06, closed
  stale): Amazon moved login to an AWS WAF CAPTCHA that the library's own flow could
  not complete, while the browser-based URL worked.
- [Audible #796](https://github.com/mkb79/Audible/issues/796) and
  [audible-cli #113](https://github.com/mkb79/audible-cli/issues/113): login
  failures for old Audible accounts not linked to Amazon.
- [audible-cli #317](https://github.com/mkb79/audible-cli/issues/317) (2026-09-03,
  open): "audible changed something in the last day or 2" causing licence denials
  and throttling, for downloads (not stats).
- No issue read reports an account suspended or banned for using the API. The
  absence of reports is not evidence of safety.
- Releases are frequent (v0.13.0 on 2026-10-12), so the project is maintained, but
  a private API can change without notice.

## 2. Kindle and the Amazon data export

### First-party reading features

- Amazon's help says Kindle books "automatically display as Read when you turn the
  last page" ([Identify Which Kindle Books Have Been Read](https://www.amazon.com/gp/help/customer/display.html?nodeId=GH7S4XVK46YEMQPH),
  accessed 2026-10-14).
- Reading Challenges count books read, streaks and achievements for books "read on
  your Kindle device, app, or Kindle for Web"; tracking needs "mobile data enabled"
  ([Learn About Kindle Reading Challenges](https://www.amazon.com/gp/help/customer/display.html?nodeId=TdP7Fpp3mrAY4gibL9),
  accessed 2026-10-14).
- No first-party Kindle reading-insights export or API was found. The "Reading
  Insights" feature turned up only in third-party write-ups, not on an Amazon help
  page, so its contents are **unverified**.

### The data request

[Request your personal information](https://www.amazon.com/gp/help/customer/display.html?nodeId=GXPU3YPMBZQRWZK2)
(accessed 2026-10-14) gives the steps: go to Request your data, sign in, "Select the
information that you want to receive", submit, "Select the validation link in the
confirmation email", then "Download your data using the secure link sent to your
email address when ready." It says the request is for "personal data that isn't
available in Your Account, such as your search history."

Not stated on any Amazon page reachable without signing in, so **unverified from a
primary source**: the category list, whether Kindle or Audible is a category, file
formats, turnaround, and how long the link is valid. The request form itself is
behind sign-in, and the owner would see the real category list there.

Second-hand, from one journalist's own export
([Xataka](https://www.xataka.com/privacidad/he-descargado-todo-que-amazon-sabe-mi-esto-que-me-he-encontrado-1/amp),
revised March 2023): a file named `Kindle.Devices.ReadingSession.csv` with start and
end time, book ASIN, reading time in milliseconds and pages turned per session;
"data ready" email after 22 days; about 130 ZIP files with no bulk download; small
CSVs. Individual users' transcripts describe the same file name. Treat the file and
column names as indicative until the owner has an export. The export is a snapshot
that must be requested again, so it gives batch history, not a live feed.

Audible listening data in the export: **unverified**. No source read mentions it.

## 3. Spotify

All from [developer.spotify.com](https://developer.spotify.com), accessed 2026-10-14.

- **Recently played** ([reference](https://developer.spotify.com/documentation/web-api/reference/get-recently-played)):
  "Get tracks from the current user's recently played tracks." Note: "Currently
  doesn't support podcast episodes." It says nothing about audiobooks. Scope
  `user-read-recently-played`; `limit` max 50; `after`/`before` Unix ms cursors;
  items are `{track, played_at, context}`. Whether an audiobook chapter play appears
  here is **unverified**; the page documents tracks only.
- **Currently playing** ([reference](https://developer.spotify.com/documentation/web-api/reference/get-the-users-currently-playing-track)):
  `currently_playing_type` is `track`, `episode`, `ad` or `unknown`; no audiobook
  value is listed. Scope `user-read-currently-playing`.
- **Saved audiobooks** ([reference](https://developer.spotify.com/documentation/web-api/reference/get-users-saved-audiobooks)):
  `user-library-read`; returns audiobook metadata (title, authors, narrators,
  `total_chapters`), no listening data.
- **Progress** ([Get an Audiobook](https://developer.spotify.com/documentation/web-api/reference/get-an-audiobook)):
  each chapter can carry `resume_point` (`fully_played`, `resume_position_ms`), "set
  if ... the scope 'user-read-playback-position'". The audiobook endpoint is limited
  to the US, UK, Canada, Ireland, New Zealand and Australia. This is state, not
  history, with no timestamps.
- **OAuth** ([authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization)):
  Authorization code (server-side secret, refresh supported), Authorization code
  with PKCE, and Client credentials (no user data). Implicit grant is deprecated.
  A single-user worker would use Authorization code with a stored refresh token.
- **Development mode** ([quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes),
  [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)):
  up to 5 allowlisted users; "The app owner must have a Spotify Premium account";
  new development-mode apps got new restrictions on 2026-02-11 and existing ones were
  migrated on 2026-03-09; if the Premium subscription lapses "the app stops
  working". Extended quota is closed to individuals ("as of May 15th 2025, Spotify
  only accepts applications from organizations"). A personal single-user app
  therefore has to live in development mode.

## 4. Terms of use

Quoted, not interpreted.

**Audible Licence** ([audible.com/legal/license-agreement](https://www.audible.com/legal/license-agreement),
"Last Updated: February 18, 2025", accessed 2026-10-14):

> This License does not include any resale or commercial use of purchased content;
> any collection and use of any product listings, descriptions, or prices; any
> derivative use; any downloading, copying, or other use of account information for
> the benefit of any third party; or any use of data mining, robots, or similar data
> gathering and extraction tools.

**Audible Service Conditions of Use** ([audible.com/legal/conditions-of-use](https://www.audible.com/legal/conditions-of-use),
"Last updated: September 10, 2025", accessed 2026-10-14), "Service Restrictions":

> We reserve the right to accept or refuse membership or to restrict use of the
> Service in our discretion. ... We may take actions we deem reasonably necessary to
> prevent fraud and abuse, including placing restrictions on the amount of content
> or other services that can be accessed from the Service at any one time.

"Termination by Us":

> ... we reserve the right to cancel the Service and any membership plan in whole or
> in part, and to terminate your membership and use of the Service at our discretion
> without notice.

The same document states that the Audible Service "is an Amazon Service for the
purposes of the Amazon.com Conditions of Use" and that the Audible terms "take
precedence over any conflicting provisions".

**Amazon Conditions of Use** ([amazon.com Conditions of Use](https://www.amazon.com/gp/help/customer/display.html?nodeId=GLSBYFE9MGKKQXXM),
"Last updated: August 14, 2026", accessed 2026-10-14), "License and Access":

> This license does not include any resale or commercial use of any Amazon Service,
> or its contents; any collection and use of any product listings, descriptions, or
> prices; any derivative use of any Amazon Service or its contents; any downloading,
> copying, or other use of account information for the benefit of any third party;
> or any use of data mining, robots, or similar data gathering and extraction tools.

The Audible and Amazon pages quoted here were read in the US-English edition.
Other regional editions may differ and were not read.

## What this means for the design

- **Treat Audible as monthly and daily totals.** One row per owner, source and
  month (and per day for the last 30 days) in milliseconds, plus a per-book finished
  flag. Do not design for sessions or per-book-per-day time: the API does not show
  them.
- **Daily data decays.** The daily window is at most 30 days, so a worker has to
  poll at least that often or days are lost for good. This matches the Hevy
  pattern of a short stateless window plus a one-off backfill. The monthly window
  covers a backfill of up to 12 months per call, and the example scripts page back
  by year.
- **Probe before schema**, as #112 proposed. The unverified fields above
  (`listening_status`, the daily response key, `percent_complete` units, the
  `status/finished` body) are exactly what a one-off call from the owner's machine
  would settle. That call is the owner's to make.
- **Credential handling follows Garmin.** A token file in a Railway volume or
  secret, one registered device, expiry showing as a stale "Last synced" line. A
  registration appears on the owner's Amazon devices list.
- **Kindle is a batch import.** If the export holds a reading-session file, a
  one-off or occasional importer fits; nothing live is available. Manual entry is
  the fallback and is independent of Amazon.
- **Spotify adds little.** It needs Premium on the owner's account, is capped at 5
  users, and gives no audiobook history. Revisit only if the owner moves most
  listening there.
- **Terms.** The clauses above are for the owner to weigh; nothing here is legal
  advice. The unofficial Audible route is the only automated one and it is the one
  those clauses name.

## Decisions for the owner

1. **Is the unofficial Audible route acceptable, given the quoted clauses?** If not,
   Audible has no automated path and the options reduce to manual entry.
2. **What counts as a reading day?** Minutes, pages, books finished or a streak.
   Audible totals give minutes only; Kindle sessions (if exported) give minutes and
   pages.
3. **Request the Amazon data export now.** It is free and the slow step (22 days in
   one report). Tick whichever Kindle or Audible categories the form offers, then
   share the file names and column headers (not the contents) so this note can be
   corrected.
4. **Run the Audible probe?** One call each to `stats/aggregates` and `library`
   from the owner's machine, with the output reduced to field names, to settle the
   unverified fields. Needs a one-time sign-in the owner performs.
5. **Audible marketplace** of the account (decides `locale`, `store` and the
   library).
6. **One "reading" domain or two** (Kindle and Audible).
7. **Spotify:** confirm it stays out of scope.

## Sources

All accessed 2026-10-14.

- [mkb79/Audible](https://github.com/mkb79/Audible): `docs/source/misc/external_api.rst`,
  `docs/source/misc/examples.rst`, `docs/source/auth/*.rst`,
  `docs/source/marketplaces/marketplaces.rst`, `examples/listening_stats.py`,
  `src/audible/auth.py`, `tests/fixtures/auth_fixture.json`, issues #495, #732,
  #796, #832
- [mkb79/audible-cli](https://github.com/mkb79/audible-cli):
  `plugin_cmds/cmd_listening-stats.py`, `src/audible_cli/cmds/cmd_library.py`,
  issues #113, #242, #317
- [rmcrackan/AudibleApi](https://github.com/rmcrackan/AudibleApi):
  `AudibleApi.Common/LibraryDtoV10.generated.cs` (third-party client)
- Audible Help: [view listening log](https://help.audible.com/s/article/view-listening-log?language=en_US),
  [view your listening stats](https://help.audible.com/s/article/view-your-listening-stats?language=en_US)
- Audible: [License](https://www.audible.com/legal/license-agreement),
  [Conditions of Use](https://www.audible.com/legal/conditions-of-use)
- Amazon: [Conditions of Use](https://www.amazon.com/gp/help/customer/display.html?nodeId=GLSBYFE9MGKKQXXM),
  [Request your personal information](https://www.amazon.com/gp/help/customer/display.html?nodeId=GXPU3YPMBZQRWZK2),
  [Identify Which Kindle Books Have Been Read](https://www.amazon.com/gp/help/customer/display.html?nodeId=GH7S4XVK46YEMQPH),
  [Kindle Reading Challenges](https://www.amazon.com/gp/help/customer/display.html?nodeId=TdP7Fpp3mrAY4gibL9)
- Spotify for Developers: recently played, currently playing, saved audiobooks, get
  an audiobook, scopes, authorization, quota modes, February 2026 migration guide
  (URLs above)
- Secondary, used only where marked: [Xataka](https://www.xataka.com/privacidad/he-descargado-todo-que-amazon-sabe-mi-esto-que-me-he-encontrado-1/amp)
