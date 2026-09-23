# MyFitnessPal nutrition integration options

**Status: Research only / Not Implemented. Researched on 2026-09-23**

The goal is to get daily calories, carbohydrates, protein and fat from the owner's
**free** MyFitnessPal (MFP) account into Supabase automatically. The owner logs food
every day and already runs a Garmin Connect sync to Supabase from a scheduled Python
worker on Railway ([GARMIN.md](GARMIN.md), [RAILWAY.md](RAILWAY.md)).

## Summary and recommendation

- **There is no official route for an individual.** MFP's API is private, and its
  developer site says "We are not accepting requests for API access at this time"
  ([myfitnesspalapi.com](https://myfitnesspalapi.com/), reached by redirect from
  [myfitnesspal.com/api](https://www.myfitnesspal.com/api)).
- **The free tier has no data export.** File export is Premium or Premium+ only. Free
  accounts get a printable web report and diary sharing
  ([MFP Help: export or share](https://support.myfitnesspal.com/hc/en-us/articles/360032623371-Export-your-data-or-share-your-diary-with-a-Trainer-Doctor-or-Nutritionist)).
- **Garmin carries calories but not macros.** MFP sends "Calories Consumed" to Garmin
  Connect ([MFP Help: Garmin](https://support.myfitnesspal.com/hc/en-us/articles/360040110912-Garmin-Connect-FAQ-and-Troubleshooting)).
  Garmin files it under **Calories** only
  ([Garmin Support](https://support.garmin.com/en-US/?faq=Re90uqqOnh30BtqHQYkoa8)).
- **MFP officially pushes macros to phone health platforms.** It writes meal summaries
  with nutrients to Apple Health, Android Health Connect and Google Health (Fitbit), on
  free accounts too. Linking to partner apps is a free-tier feature
  ([MFP Help: plans](https://support.myfitnesspal.com/hc/en-us/articles/34889191368077-The-difference-between-Free-Premium-and-Premium)).

**Recommended route: do this in two steps.**

1. **Calories now, through the existing Garmin sync.** The worker already calls
   `garmin.get_stats(day)` for every day
   ([`scripts/garmin/garmin_sync.py`](../../scripts/garmin/garmin_sync.py), `sync()`).
   That payload is reported to contain `consumedKilocalories` from MFP
   ([python-garminconnect #189](https://github.com/cyberjunky/python-garminconnect/issues/189)).
   `normalize_daily_health()` currently drops it. Storing it needs one nullable column and
   one line of normalization. It needs no new credentials, no new service and no new ToS
   exposure. First check the field against a real day's payload, because the only source
   for its name is a 2024 user comment.
2. **Macros, through a phone health platform.** MFP writes meal summaries with
   nutrients to Health Connect (Android) or Apple Health (iOS). A small phone app then
   POSTs those records to an endpoint that writes them to Supabase. This is the only
   automatic route for macros that uses MFP's own supported data sharing and does not
   break MFP's Terms of Service. The cost is a phone app plus a new ingestion endpoint.

Scraping MFP with a browser cookie (python-myfitnesspal and newer forks) is the only way
to read MFP directly. It breaks MFP's Terms of Service §5, and it has broken repeatedly
behind Cloudflare since mid-2025. Use it only as a deliberate, personally accepted
fallback.

## 1. Official MFP API

MFP's `/api` URL redirects to [myfitnesspalapi.com](https://myfitnesspalapi.com/). That
page says the API exists and offers RESTful interfaces. It also says: "We are not
accepting requests for API access at this time." The page does not say who holds access
today or when requests might reopen. Existing partners are listed in MFP's help centre
under categories such as "Data Sharing Partners" (Personify Health, ABC Trainerize)
([MFP Help: products and apps](https://support.myfitnesspal.com/hc/en-us/articles/360032274232-What-kind-of-products-and-apps-work-with-MyFitnessPal)).
All of them are businesses.

- **Free-account viability:** Not applicable. No individual access is offered.
- **Reliability / ToS risk:** Not applicable.
- **Effort:** Not available.

Could not verify: when the public API closed. Secondary sources say 2019, but no MFP
primary source for that date was found.

## 2. MFP's own export options

### 2a. In-app / web file export (Premium only)

The export is started from the app (Nutrition or Progress, then Export) or from the web
(Reports, then Export). MFP emails a zip of three CSV files: _Nutrition_, _Progress_ and
_Exercise_. The nutrition file contains "Calories, macronutrients, micronutrients, and
timestamps for your logged foods, **summarized by meal**, plus any food notes"
([MFP Help: Data Export](https://support.myfitnesspal.com/hc/en-us/articles/360032273352-Data-Export-FAQs),
edited 2026-08-06). The granularity is per meal per day, so daily totals are a sum.
Every export includes all three files, and the user chooses the date range.

The same article states: "Data Export is available to Premium and Premium+ subscribers."
The plan comparison table also marks Data Export as Premium-only
([MFP Help: plans](https://support.myfitnesspal.com/hc/en-us/articles/34889191368077-The-difference-between-Free-Premium-and-Premium)).

- **Free-account viability:** No.
- **Automation:** Poor even with Premium. Each export is requested by hand and delivered
  as an email link. Automating it would mean scripting the UI and parsing email. No
  documented API triggers it.
- **Use:** A good one-off backfill of history if the owner ever pays for a month of
  Premium.

### 2b. Free-account alternatives: printable report and diary sharing

Free users can open the web **Food** tab, choose **View Full Report (Printable)**, pick a
date range, and print or save the report as PDF. The report is website-only. Free users
can also share the diary with another MFP account
([MFP Help: export or share](https://support.myfitnesspal.com/hc/en-us/articles/360032623371-Export-your-data-or-share-your-diary-with-a-Trainer-Doctor-or-Nutritionist)).
Both are for people to read. Reading either one automatically is scraping, covered in §3.

### 2c. Privacy (GDPR / UK GDPR) data request

MFP offers a "Right to Access and Data Portability" to get "a copy of your personal
information in a portable and, to the extent technically feasible, readily usable
format". Requests go through the MyFitnessPal Privacy Request Center, by phone, or to
`privacy@myfitnesspal.com`
([MFP Help: Privacy Rights](https://support.myfitnesspal.com/hc/en-us/articles/34887801585549-What-are-my-Privacy-Rights)).
This right does not depend on Premium.

- **Free-account viability:** Yes.
- **Automation:** No. It is a manual, one-off legal request.
- **Could not verify:** the file format, the granularity (per food, per meal or per day)
  and the turnaround time. MFP does not publish them. The request would have to be made
  to find out.

## 3. Unofficial access: scraping with browser cookies

### python-myfitnesspal (coddingtonbear)

[coddingtonbear/python-myfitnesspal](https://github.com/coddingtonbear/python-myfitnesspal)
reads the MFP website as the logged-in user. `get_date()` parses `/food/diary/`
per day, and `get_report()` calls `api/services/reports/results/`
([`client.py`](https://github.com/coddingtonbear/python-myfitnesspal/blob/master/myfitnesspal/client.py)).
Current state:

- **No password login since 2022.** "Starting on August 25th, 2022, MyFitnessPal added a
  hidden captcha to their login flow." Version 2.x instead reads browser cookies through
  `browser_cookie3`, or takes a `cookiejar`
  ([getting_started.rst](https://github.com/coddingtonbear/python-myfitnesspal/blob/master/docs/source/getting_started.rst),
  [#144](https://github.com/coddingtonbear/python-myfitnesspal/issues/144)).
- **The last release is stale.** PyPI `myfitnesspal` 2.1.2 was released 2025-03-09
  ([PyPI](https://pypi.org/project/myfitnesspal/)). A fix for "403 Forbidden on
  authentication" ([PR #197](https://github.com/coddingtonbear/python-myfitnesspal/pull/197),
  which removes `cloudscraper`) was merged into `master` on 2025-09-28 and has not been
  released. That merge is also the last push to the repo.
- **It is breaking behind Cloudflare.**
  [#196](https://github.com/coddingtonbear/python-myfitnesspal/issues/196) (2025-06-24)
  reports a 403 on `/user/auth_token`, traced to Cloudflare and NextAuth session cookies.
  [#203](https://github.com/coddingtonbear/python-myfitnesspal/issues/203) (2025-12-14)
  reports: "Myfitnesspal.com has a new design today and the program is failing with …
  status code: 403."
  [#205](https://github.com/coddingtonbear/python-myfitnesspal/issues/205) (2026-02)
  has one user saying it "works great", using cookies from a browser on a server they VNC
  into. Another user gets 403 from a headless container even with fresh exported cookies,
  and suspects WAF fingerprinting. None of these are resolved.
- **Maintenance is minimal.** There are 25 open issues. Open PRs fix saved meals,
  measurements and dependencies, and none has been merged since 2025.

### Newer cookie-based clients

[Mason-Levyy/myfitnesspal-mcp](https://github.com/Mason-Levyy/myfitnesspal-mcp) (PyPI
`mfp-mcp`, created 2026-07, active in 2026-09) says it exists because MFP "moved behind
Cloudflare + NextAuth". It authenticates with the `__Secure-next-auth.session-token`
cookie over a real Chrome TLS fingerprint using `curl_cffi`. It says sessions last
"around 30 days", and it can refresh them with a headless Playwright profile. Its tools
include `fitness_get_day` (nutrition totals) and `fitness_bulk_export`. The session
length and refresh behaviour are the author's claims, not tested here. The worker
already pins `curl-cffi` ([`scripts/garmin/requirements.txt`](../../scripts/garmin/requirements.txt)).

- **Free-account viability:** Yes in principle. These clients read the free food diary
  and do not need the Premium export. Whether `get_report()` works for free accounts was
  not verified.
- **Data:** Per-food and per-meal diary entries with daily totals. This is the richest
  source.
- **Reliability:** Low. The route depends on MFP's front end and Cloudflare's bot
  checks, and both have changed at least twice since mid-2025. A headless Railway
  container is the environment reported to fail (#205). Someone would also have to
  re-seed a browser session about once a month.
- **ToS risk:** High. MFP's Terms (effective 2025-03-18) §5 forbid retrieving "data or
  content from the Services … using automated means, including … scrapers … or any
  other automated tools or processes", and forbid bypassing CAPTCHA or authentication
  measures ([MFP Terms](https://www.myfitnesspal.com/terms-of-service)). The worst
  outcome is losing the account that holds the owner's food history.
- **Effort:** Medium to build and ongoing to maintain.

## 4. Phone health-platform bridges (MFP-supported sharing)

MFP writes nutrition to the phone's health platform itself. A second app then forwards
it to an HTTPS endpoint. None of this reads MFP directly.

```text
MFP app -> Health Connect / Apple Health -> forwarding app on phone -> HTTPS endpoint -> Supabase
```

What MFP writes, per platform:

| Platform       | What MFP sends                                                                                                                                                        | Source                                                                                                                              |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Health Connect | "Calories eaten" as a **meal summary (not individual foods)**. Only Breakfast, Lunch, Dinner and Snack keep their names; custom meals arrive as "Other". Android 10+. | [MFP Help](https://support.myfitnesspal.com/hc/en-us/articles/10553948248973-Health-Connect-FAQ-and-Troubleshooting)                |
| Apple Health   | Food: "Meal summaries and most nutrients sync. Caffeine and Vitamin A do not sync. **Timestamps do not sync.**"                                                       | [MFP Help](https://support.myfitnesspal.com/hc/en-us/articles/360032271092-Apple-Health-connection-and-syncing) (edited 2026-08-25) |
| Google Health  | Meal summaries. Individual food names only for Premium (since 2026-05-26).                                                                                            | [MFP Help](https://support.myfitnesspal.com/hc/en-us/articles/47285002432013-What-syncs-to-and-from-Google-Health-Fitbit)           |
| Samsung Health | "Calories added to MyFitnessPal will transfer to Samsung Health." Macros are not mentioned.                                                                           | [MFP Help](https://support.myfitnesspal.com/hc/en-us/articles/360040108452-Samsung-Health-FAQ-and-Troubleshooting)                  |

On every platform, only data logged after linking syncs. MFP does not backfill history.

Getting the data from the phone to Supabase:

- **Android: HC Webhook**
  ([mcnaveen/health-connect-webhook](https://github.com/mcnaveen/health-connect-webhook),
  AGPL-3.0, release v1.9.21 on 2026-09-16, on Google Play). It reads Health Connect on an
  interval or a schedule and POSTs JSON to your webhook URLs. Its `nutrition` records
  carry `start_time`, `end_time`, `calories`, `protein_grams`, `carbs_grams` and
  `fat_grams` ([docs/webhook.md](https://github.com/mcnaveen/health-connect-webhook/blob/main/docs/webhook.md)).
  The project also links an iOS build, "Health Webhook". Its Apple Health coverage and
  store pricing were not verified.
  [kas-cor/healthconnect-export](https://github.com/kas-cor/healthconnect-export) is a
  smaller alternative with nutrition data and a webhook every 2 hours.
- **iOS: Health Auto Export.** Exports Dietary Energy, Carbohydrates, Protein and Total
  Fat ([supported data](https://help.healthyapps.dev/en/health-auto-export/getting-started/supported-data/))
  to a REST API ([REST automation](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/)).
  Automations need Premium: $0.99/month, $5.99/year or $24.99 lifetime. It "can only
  read Apple Health when your phone is unlocked" and cannot sync at fixed times
  ([FAQ](https://help.healthyapps.dev/en/health-auto-export/faq/)).
- **Google Health API.** MFP also syncs to Google Health (Fitbit), and the Google Health
  API has a readable `nutrition-log` type with energy, carbohydrate, fat and protein
  ([Google](https://developers.google.com/health/data-types/nutrition)). The legacy
  Fitbit Web API is being turned down in September 2026
  ([Google](https://developers.google.com/health/about)). All Google Health scopes are
  **Restricted**, so a published app needs verification and a CASA security assessment
  ($500–$4,500) ([Google](https://developers.google.com/health/app-verification)). An
  unverified "Testing" OAuth app gets refresh tokens that expire in 7 days
  ([Google OAuth](https://developers.google.com/identity/protocols/oauth2)), so a
  server-side personal sync would need re-consent every week. The owner would also need
  a Google Health account. This route is not a good fit.

Assessment:

- **Free-account viability:** Yes. Linking partner apps is on the free tier.
- **Reliability:** Medium. The MFP-to-platform leg is supported by MFP. The phone leg
  depends on OS background limits (iOS: only while unlocked). Data arrives as meal
  summaries, so the worker must sum them per day and treat each day as mutable. Apple
  Health gets no timestamps, so day assignment has to be checked, especially around
  midnight and BST. The 7-day re-fetch pattern from [GARMIN.md](GARMIN.md) applies.
- **ToS risk:** Low. This is MFP's documented sharing.
- **Effort:** Medium. It needs an ingestion endpoint that accepts the phone's POSTs and
  writes rows that the owner's `user_id` owns under RLS, with no service-role key in
  application code (see `CLAUDE.md`, "Roles and ownership"). It also needs a new
  migration and table following [supabase/README.md](../../supabase/README.md). The
  endpoint's auth design is still open.

Could not verify: which phone OS the owner uses, which decides between these two paths.

## 5. The existing Garmin sync

### What MFP and Garmin exchange

MFP says: "MyFitnessPal will sync Calories Consumed and Individual Exercise Workouts
logged directly in MyFitnessPal with Garmin. Garmin will sync Weight (to and from
MyFitnessPal), Individual Workouts logged in Garmin Connect, Step Count, and its related
calorie burn with MyFitnessPal"
([MFP Help: Garmin](https://support.myfitnesspal.com/hc/en-us/articles/360040110912-Garmin-Connect-FAQ-and-Troubleshooting)).
Garmin says: "Caloric intake that is input into MyFitnessPal will sync over to nutrition
under **Calories** in the Calories & Macros section"
([Garmin Support](https://support.garmin.com/en-US/?faq=Re90uqqOnh30BtqHQYkoa8)). Only
future data syncs after linking. MFP's known-issues page currently lists "Error message
when trying to link MyFitnessPal to Garmin Connect on iOS devices"
([MFP Help: known issues](https://support.myfitnesspal.com/hc/en-us/articles/360032625231-Known-Issues-Integration-Partners),
2026-09-19).

**Direction and content:** MFP to Garmin carries **one calories-in number** (plus
MFP-logged workouts). Macros are not included. A Garmin forum thread reports that after
linking, only calories appear and the macro fields stay blank
([Garmin Forums](https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-mobile-ios/428894/how-do-i-get-the-macros-carbs-protein-and-fat-to-show-in-the-connect-app-from-myfitnesspal)).
No Garmin staff answered in that thread.

**The Garmin Connect+ Nutrition conflict:** Garmin launched its own food logging on
2026-01-05, and it is exclusive to Connect+
([Garmin press release](https://www.garmin.com/en-US/newsroom/press-release/sports-fitness/stay-on-top-of-nutrition-goals-in-garmin-connect/)).
Garmin's FAQ says it cannot run alongside MFP. "You must choose one source. To use
Garmin Nutrition, you must disconnect MFP", and "no new data will sync once the Garmin
Nutrition feature is active"
([Garmin Support: Connect+ Nutrition](https://support.garmin.com/en-US/?faq=yve3hAUsxU1IEzbzo91Gt6)).
If the owner turns on Connect+ Nutrition, the calories-in route below stops.

### What this repo fetches today

- [`scripts/garmin/requirements.txt`](../../scripts/garmin/requirements.txt) pins
  `garminconnect==0.3.11`.
- `sync()` in [`garmin_sync.py`](../../scripts/garmin/garmin_sync.py) calls
  `get_stats(day)`, `get_sleep_data(day)`, `get_max_metrics(day)` and
  `get_activities_by_date(...)`. In 0.3.11, `get_stats` calls `get_user_summary`, which
  hits `/usersummary-service/usersummary/daily`
  ([0.3.11 source](https://github.com/cyberjunky/python-garminconnect/blob/0.3.11/garminconnect/__init__.py)).
- `normalize_daily_health()` keeps only `totalSteps`, `activeKilocalories`,
  `totalKilocalories`, `restingHeartRate` and `lastSyncTimestampGMT`, plus sleep and
  VO2 max. Nothing about intake is kept.
- The schema has `active_calories_kcal` and `total_calories_kcal` (burn only)
  ([`20260906180500_add_garmin_calories.sql`](../../supabase/migrations/20260906180500_add_garmin_calories.sql))
  and sleep, heart-rate and VO2-max columns
  ([`20260907090000_expand_garmin_health_and_activities.sql`](../../supabase/migrations/20260907090000_expand_garmin_health_and_activities.sql)).
  There is no intake or macro column.

### What garminconnect exposes

- **The daily summary** (already fetched). A user reports that `get_stats()` returns
  `consumedKilocalories` ("For me, this comes from MyFitnessPal"), along with
  `remainingKilocalories` and `netCalorieGoal`
  ([issue #189](https://github.com/cyberjunky/python-garminconnect/issues/189), 2024).
  The library passes the payload through, so the field depends on Garmin's server and
  not on the library version.
- **Nutrition-service endpoints.** `get_nutrition_daily_food_log(cdate)`,
  `get_nutrition_daily_meals(cdate)` and `get_nutrition_daily_settings(cdate)` call
  `/nutrition-service/food/logs/{date}`, `/nutrition-service/meals/{date}` and
  `/nutrition-service/settings/{date}`. They were added in
  [PR #323](https://github.com/cyberjunky/python-garminconnect/pull/323) (merged
  2026-03-16) and **are present in the pinned 0.3.11**. They back Garmin's own
  Connect+ Nutrition log. Given Garmin's statement that MFP intake lands under Calories
  only, and that Garmin Nutrition and MFP are mutually exclusive, they probably do not
  return MFP macros. That was not tested.

**Conclusion:** The existing Garmin sync can carry **daily calories consumed** from MFP
at almost no cost. It cannot carry carbs, protein or fat. Before building on it, run a
one-off probe with the cached Garmin session:

1. Print `get_stats(day)["consumedKilocalories"]` for a day with MFP logging, and compare
   it with MFP's diary total.
2. Print `get_nutrition_daily_food_log(day)` to confirm it holds no MFP macros.

- **Free-account viability:** Yes. The Garmin link is a free-tier partner integration.
- **Reliability:** The same as the existing Garmin worker (unofficial Garmin endpoints).
  MFP-to-Garmin sync timing is not documented. The 7-day re-fetch absorbs late syncs.
- **ToS risk:** No new risk beyond the existing Garmin route.
- **Effort:** Low. One nullable `consumed_calories_kcal` column, one normalizer line and
  a test.

## 6. Aggregators and automation platforms

- **Terra API.** Lists MyFitnessPal as a Web API integration that is "Periodically
  fetched" ([Terra docs](https://docs.tryterra.co/reference/health-and-fitness-api/supported-integrations.md)).
  Terra polls every 5–10 minutes and delivers "meal logs, calorie counts, macronutrient
  breakdowns" ([Terra MFP page](https://tryterra.co/integrations/myfitnesspal)). Pricing
  starts at $499/month, or $399/month billed annually, with no free tier
  ([Terra pricing](https://tryterra.co/pricing)). Terra does not say whether a free MFP
  account works, or how it reaches MFP despite MFP's closed API. It was already rejected
  on cost in [GARMIN_TERRA.md](GARMIN_TERRA.md). **Not viable.**
- **Cronometer.** Has no MyFitnessPal import. A Cronometer moderator wrote in November
  2018: "we do not support a bulk import from myfitnesspal at this time"
  ([Cronometer forum](https://forums.cronometer.com/discussion/958/bulk-import-from-myfitnesspal)).
  No newer Cronometer statement was found. It is not a bridge in any case. **Not viable.**
- **Zapier / IFTTT.** Neither has an MFP integration. `zapier.com/apps/myfitnesspal` and
  `ifttt.com/myfitnesspal` both returned HTTP 404 on 2026-09-23. Search results that
  describe "Zapier + MyFitnessPal" workflows are AI-generated pages without a real
  connector. **Not viable.**
- **Fitbit / Google Health, Samsung Health.** See §4.

## Comparison

| Route                                | Calories | Macros  | Free MFP account | Automatic                 | Cost                    | ToS risk | Effort          |
| ------------------------------------ | -------- | ------- | ---------------- | ------------------------- | ----------------------- | -------- | --------------- |
| Official MFP API                     | —        | —       | No access        | —                         | —                       | —        | Not available   |
| MFP file export                      | Yes      | Yes     | **No** (Premium) | No (emailed zip)          | Premium subscription    | None     | Low (manual)    |
| Printable report / diary sharing     | Yes      | Yes     | Yes              | Only by scraping          | Free                    | High     | —               |
| GDPR access request                  | Unknown  | Unknown | Yes              | No                        | Free                    | None     | Manual          |
| python-myfitnesspal / cookie clients | Yes      | Yes     | Yes              | Yes, fragile              | Free                    | **High** | Medium, ongoing |
| Health Connect + HC Webhook          | Yes      | Yes     | Yes              | Yes (per meal)            | Free                    | Low      | Medium          |
| Apple Health + Health Auto Export    | Yes      | Yes     | Yes              | Yes, only while unlocked  | $5.99/yr or $24.99 once | Low      | Medium          |
| Google Health API                    | Yes      | Yes     | Yes              | 7-day tokens unverified   | Free / CASA to publish  | Low      | High            |
| **Existing Garmin sync**             | **Yes**  | **No**  | Yes              | **Yes (already running)** | Free                    | None new | **Low**         |
| Terra                                | Yes      | Yes     | Unverified       | Yes                       | $399–$499/month         | Low      | Medium          |
| Cronometer / Zapier / IFTTT          | —        | —       | —                | —                         | —                       | —        | Not available   |

## Unverified points

- The `consumedKilocalories` field name and its presence in the 2026 daily-summary
  payload. The source is a 2024 user comment, and the probe above would confirm it.
- Whether Garmin's `/nutrition-service` endpoints return anything for MFP-linked
  accounts.
- The format, granularity and turnaround of an MFP privacy access request.
- Whether python-myfitnesspal's `get_report()` works on a free account.
- Whether python-myfitnesspal or `mfp-mcp` works from a headless Railway container
  today. Issue #205 suggests it does not reliably.
- When MFP's public API closed.
- How Terra reaches MFP, and whether it supports free accounts.

## Sources

MyFitnessPal:

- [MFP developer site (API closed to requests)](https://myfitnesspalapi.com/)
- [MFP Help: Export your nutrition, progress, and exercise data](https://support.myfitnesspal.com/hc/en-us/articles/360032273352-Data-Export-FAQs)
- [MFP Help: Export your data or share your diary (free accounts)](https://support.myfitnesspal.com/hc/en-us/articles/360032623371-Export-your-data-or-share-your-diary-with-a-Trainer-Doctor-or-Nutritionist)
- [MFP Help: The difference between Free, Premium, and Premium+](https://support.myfitnesspal.com/hc/en-us/articles/34889191368077-The-difference-between-Free-Premium-and-Premium)
- [MFP Help: Garmin Connect FAQ and Troubleshooting](https://support.myfitnesspal.com/hc/en-us/articles/360040110912-Garmin-Connect-FAQ-and-Troubleshooting)
- [MFP Help: Apple Health connection and syncing](https://support.myfitnesspal.com/hc/en-us/articles/360032271092-Apple-Health-connection-and-syncing)
- [MFP Help: Health Connect FAQ and Troubleshooting](https://support.myfitnesspal.com/hc/en-us/articles/10553948248973-Health-Connect-FAQ-and-Troubleshooting)
- [MFP Help: What syncs to and from Google Health (Fitbit)](https://support.myfitnesspal.com/hc/en-us/articles/47285002432013-What-syncs-to-and-from-Google-Health-Fitbit)
- [MFP Help: Samsung Health FAQ and Troubleshooting](https://support.myfitnesspal.com/hc/en-us/articles/360040108452-Samsung-Health-FAQ-and-Troubleshooting)
- [MFP Help: What kind of products and apps work with MyFitnessPal?](https://support.myfitnesspal.com/hc/en-us/articles/360032274232-What-kind-of-products-and-apps-work-with-MyFitnessPal)
- [MFP Help: Known Issues: Integration Partners](https://support.myfitnesspal.com/hc/en-us/articles/360032625231-Known-Issues-Integration-Partners)
- [MFP Help: What are my Privacy Rights?](https://support.myfitnesspal.com/hc/en-us/articles/34887801585549-What-are-my-Privacy-Rights)
- [MFP Terms of Service (effective 2025-03-18)](https://www.myfitnesspal.com/terms-of-service)

Garmin:

- [Garmin Support: Steps to Link Your Garmin Connect Account with MyFitnessPal](https://support.garmin.com/en-US/?faq=Re90uqqOnh30BtqHQYkoa8)
- [Garmin Support: Garmin Connect+ Nutrition](https://support.garmin.com/en-US/?faq=yve3hAUsxU1IEzbzo91Gt6)
- [Garmin press release: nutrition tracking in Garmin Connect (2026-01-05)](https://www.garmin.com/en-US/newsroom/press-release/sports-fitness/stay-on-top-of-nutrition-goals-in-garmin-connect/)
- [Garmin Forums: MFP macros not showing in Connect](https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-mobile-ios/428894/how-do-i-get-the-macros-carbs-protein-and-fat-to-show-in-the-connect-app-from-myfitnesspal)
- [cyberjunky/python-garminconnect 0.3.11 source](https://github.com/cyberjunky/python-garminconnect/blob/0.3.11/garminconnect/__init__.py)
- [python-garminconnect PR #323: nutrition endpoints](https://github.com/cyberjunky/python-garminconnect/pull/323)
- [python-garminconnect issue #189: Daily calories](https://github.com/cyberjunky/python-garminconnect/issues/189)

Unofficial MFP clients:

- [coddingtonbear/python-myfitnesspal](https://github.com/coddingtonbear/python-myfitnesspal)
  and issues [#144](https://github.com/coddingtonbear/python-myfitnesspal/issues/144),
  [#196](https://github.com/coddingtonbear/python-myfitnesspal/issues/196),
  [#203](https://github.com/coddingtonbear/python-myfitnesspal/issues/203),
  [#205](https://github.com/coddingtonbear/python-myfitnesspal/issues/205),
  [PR #197](https://github.com/coddingtonbear/python-myfitnesspal/pull/197)
- [PyPI: myfitnesspal](https://pypi.org/project/myfitnesspal/)
- [Mason-Levyy/myfitnesspal-mcp](https://github.com/Mason-Levyy/myfitnesspal-mcp)

Health-platform bridges and aggregators:

- [mcnaveen/health-connect-webhook](https://github.com/mcnaveen/health-connect-webhook)
- [kas-cor/healthconnect-export](https://github.com/kas-cor/healthconnect-export)
- [Health Auto Export: supported data](https://help.healthyapps.dev/en/health-auto-export/getting-started/supported-data/),
  [REST API automation](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/),
  [FAQ](https://help.healthyapps.dev/en/health-auto-export/faq/)
- [Google Health API: nutrition](https://developers.google.com/health/data-types/nutrition),
  [about](https://developers.google.com/health/about),
  [app verification](https://developers.google.com/health/app-verification)
- [Google OAuth 2.0: refresh token expiration](https://developers.google.com/identity/protocols/oauth2)
- [Terra supported integrations](https://docs.tryterra.co/reference/health-and-fitness-api/supported-integrations.md),
  [Terra MyFitnessPal](https://tryterra.co/integrations/myfitnesspal),
  [Terra pricing](https://tryterra.co/pricing)
- [Cronometer forum: bulk import from MyFitnessPal](https://forums.cronometer.com/discussion/958/bulk-import-from-myfitnesspal)
