# iPhone Screen Time: can it be collected automatically?

**Status: Research only — not implemented (2026-09-23)**

This note answers one question: as of September 2026, is there a reliable, automatic way
to get iPhone Screen Time data into Personal Observability? Today the app only has
_manually recorded_ iPhone Screen Time ([PRODUCT.md](../PRODUCT.md),
[ROADMAP.md](../ROADMAP.md)). There is no table for it yet. The integrations page shows it
as "Manual entry" (`src/routes/integrations.tsx`).

Every claim below links to the source it comes from. Claims marked **(unverified)** come
from developer reports or from code that has not been checked against Apple, and should be
tested before anything relies on them.

## Short answer

**Yes, one route now works, but it needs an iOS app that we build and sideload ourselves,
and that comes with a real cost.** iOS 26.4 added
[`DeviceActivityData.activityData(filteredBy:using:)`][activityData], which Apple documents
as a way "to export family activity data, for use in another app or platform". It returns
the same numbers the Screen Time report shows: total time, time per app, time per category,
pickups and notifications, all readable in the app's normal process, which can make network
requests. Apple limits it to the EU for **customer installations**. The same page also says
"You can develop and test an app that uses this method on devices in any region". A
single-user app that is installed from Xcode as a development build is exactly that case.

What it costs:

- a paid Apple Developer Program membership ([99 USD/year][adp-fee]);
- access to a Mac to build with Xcode;
- only [one app per device can hold the data-access permission][approvedWithDataAccess];
- a developer report that granting it **stops Apple's own Screen Time pane from recording
  new usage** ([forum 844661][forum-844661], **unverified**);
- depending on a development-build allowance that Apple could remove.

Without an iOS app, the only automatic route runs through a **Mac**. The Mac receives
iPhone app-focus events through iCloud Biome sync, and open-source tools read them from
disk. That route is undocumented, needs Full Disk Access and has already broken across
macOS versions. The owner uses Windows, so it would also mean buying and running a Mac.

Everything else is either impossible (HealthKit, Shortcuts, the Screen Time report
extension, the RescueTime API) or not automatic (backups, screenshot OCR).

## Constraints specific to this app

- The owner's machine is **Windows**. Xcode is a macOS app
  ([Mac App Store listing][xcode]), so any iOS-app route needs a Mac for building, either
  owned or rented.
- Ingestion is local-first. The Garmin worker writes to local Supabase through normal RLS
  ([GARMIN.md](GARMIN.md)). An iPhone cannot reach local Supabase on the PC by default.
  **Hosted login is also parked** ([CLAUDE.md](../../CLAUDE.md#authentication)), so "POST
  to the hosted app" is not currently an option either. Any design has to land data on the
  PC some other way (see [the transport section](#transport-from-the-phone-to-the-pc)).
- "Automatic" means what it means for Garmin: after setup, no recurring manual step
  ([GARMIN.md](GARMIN.md)).

## Naming note: iOS 26 vs WWDC 2026

Apple's year-based numbering means iOS 26 shipped in 2025, and WWDC 2026 (June 2026)
announced **iOS 27**. Apple's September 2026 release notes for Screen Time in iOS 27 cover
parental-control features only: Ask to Browse, Time Allowances, a redesigned Screen Time and
child setup ([Apple Newsroom, 2026-09-14][newsroom-2026-09]). None of Apple's developer
documentation pages checked for this note mark any DeviceActivity or FamilyControls symbol as
introduced in 27. The relevant API change is **iOS 26.4**, covered below.

---

## Route 1: Apple's Screen Time API (FamilyControls, DeviceActivity, ManagedSettings)

### What the frameworks are

- **FamilyControls** handles authorization. An app must have the
  `com.apple.developer.family-controls` entitlement before calling `requestAuthorization`,
  and "Before submitting your app to the App Store, you must request permission to use the
  entitlement" ([FamilyControls][fc], [entitlement][fc-ent]). Apple reviews the request and
  grants it as a managed capability ([Requesting the entitlement][fc-request]).
  - **Individual authorization** (iOS 16+) lets an adult authorize an app on their own device
    with Face ID or Touch ID ([`requestAuthorization(for:)`][fc-reqauth]). Apple introduced it
    so that "the Screen Time API can be used to build more than just parental controls apps".
    Unlike child authorization, it "can be used by any number of apps per device"
    ([WWDC22 110336][wwdc22]).
  - **Child authorization** needs a parent or guardian in the same Family Sharing group, and
    blocks the child from deleting the app or signing out of iCloud ([FamilyControls][fc]).
    This is not relevant for a single adult.
  - The **development** Family Controls capability is available to paid Apple Developer
    Program members, not to free accounts ([supported capabilities table][caps]).
    Distribution through TestFlight or the App Store needs the approved distribution
    entitlement ([Configuring Family Controls][fc-config]).
- **ManagedSettings** applies restrictions such as shields and blocking. It does not report
  usage ([ManagedSettings][ms]).
- **DeviceActivity** handles monitoring (schedules and thresholds) and reporting
  ([DeviceActivity][da]).

### 1a. Before iOS 26.4: usage data cannot leave the device

**DeviceActivityReport extension.** The report API renders a SwiftUI view in a separate
extension. Apple: "To protect the user's privacy, your extension runs in a sandbox. This
sandbox prevents your extension from making network requests or moving sensitive content
outside the extension's address space" ([DeviceActivityReport][dar]). The extension can
show per-app, per-category and pickup numbers to the user, but it cannot write them to an
App Group, send them to a server, or hand them back to the host app. **This is by design,
not a bug to work around.**

Apps are also represented by opaque tokens. `Application.bundleIdentifier` "is `nil`" outside
a shield-configuration extension ([bundleIdentifier][bundleid]), and `ApplicationToken`
exists to "restrict and filter device applications without access to personal user data"
([ApplicationToken][apptoken]).

**DeviceActivityMonitor threshold workaround.** The monitor extension receives
`eventDidReachThreshold` callbacks ([DeviceActivityMonitor][dam],
[eventDidReachThreshold][dam-threshold]). One developer reports that a `URLSession` request
started from this extension completes ([forum 846053][forum-846053], **unverified, and no
Apple reply**). In theory you could register events at thresholds of 15, 30, 45 minutes and
so on, and log which ones fire. Apple's documented limits make this coarse:

- at most **20** monitored activities per app ([excessiveActivities][err-excessive]);
- a minimum schedule interval of **15 minutes** ([intervalTooShort][err-short]);
- apps identified only by opaque tokens chosen through the picker.

The result is "crossed N minutes today" buckets, not real per-app totals, with no pickups
or notifications. The same forum thread also reports the extension stops being invoked
after days without the host app launching. This route is fragile and imprecise. **Not
recommended.**

### 1b. iOS 26.4+: an official export path (EU for customers, any region for development)

iOS 26.4 added three things:

- [`AuthorizationStatus.approvedWithDataAccess`][approvedWithDataAccess]: "access to
  non-tokenized family activity data".
- The entitlement [`com.apple.developer.family-controls.app-and-website-usage`][aawu-ent],
  added by "enabling the Family Controls App And Website Usage on your target in Xcode".
- [`DeviceActivityData.activityData(filteredBy:using:)`][activityData], with a
  [`Policy`][policy] of `.cached` or `.live`.

Apple's documentation for `activityData` says:

> Use this method to export family activity data, for use in another app or platform.
> … You can develop and test an app that uses this method on devices in any region.
> Customer installations of your app can only use the method on devices located in the EU
> that are signed in with an Apple Account with an EU country or region. Otherwise, it
> throws an error. ([source][activityData])

[`FamilyActivityData`][fad] maps tokens to real names. `installedApplications` gives each
app's `bundleIdentifier` with its token, `activityCategories` gives each category's
`localizedDisplayName`, and `visitedWebDomains` gives each domain ([installedApplications][fad-apps],
[activityCategories][fad-cats]).

**What data it returns.** The data types are the same as in the report extension, but the
normal app process can read them:

| Level                                      | Fields                                                                                                                            |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| [`DeviceActivityData`][dad]                | `user`, `device` (name, model), `segmentInterval`, `lastUpdatedDate`, `activitySegments`                                          |
| [`ActivitySegment`][seg] (per day or hour) | `dateInterval`, `totalActivityDuration`, `longestActivity`, `firstPickup`, `totalPickupsWithoutApplicationActivity`, `categories` |
| [`CategoryActivity`][cat]                  | `category`, `totalActivityDuration`, `applications`, `webDomains`                                                                 |
| [`ApplicationActivity`][appact]            | `application`, `totalActivityDuration`, `numberOfPickups`, `numberOfNotifications`                                                |

That covers everything asked for: total, per app, per category, pickups, notifications and
first pickup.

**Caveats, all from Apple's documentation unless marked:**

- "Only one app at a time can hold this authorization status on a given device. If a person
  grants data access to a different app, your app's status reverts to `.notDetermined`"
  ([approvedWithDataAccess][approvedWithDataAccess]).
- **Apple's own Screen Time may stop recording.** One developer reports that the consent
  sheet says Screen Time "will lose access to this data as only one app or service can
  access it at a time". On their test devices, the Screen Time pane in Settings showed no new
  usage until the app was switched off ([forum 844661][forum-844661], **unverified, no
  Apple reply**). If this is true, turning the integration on also gives up the built-in
  Screen Time UI. **Test this before committing to the route.**
- The permission is all or nothing. When the capability is present, a user reportedly cannot
  approve Screen Time without also granting data access ([forum 820283][forum-820283],
  **unverified**).
- **Region.** A developer's TestFlight or App Store build returned only `.approved`. An Apple
  DTS engineer replied by quoting the EU-only restriction ([forum 844623][forum-844623]). The
  same developer's _development_ build returned `.approvedWithDataAccess`, which matches the
  "develop and test … in any region" wording. The owner's region is not recorded here. If the
  owner is in the EU with an EU Apple Account, even a distributed build would qualify.
  Otherwise, only a development-signed build will.
- **Background execution** has not been checked. Nothing found says whether `activityData`
  can be called from a background task, an App Intent run by a Shortcuts automation, or the
  monitor extension. This needs a spike.

**How automatic can it be?** A personal automation with a Time of Day trigger can run
"without asking you for confirmation", with "Allow Running When Locked" turned on
([Apple Support: Shortcuts automations][shortcuts-auto]). An App Intent in our app that
calls `activityData`, serializes the last 7 days and saves or sends them could therefore run
daily with no interaction, as long as the background call is allowed (see above).

**Risks.**

- **App Review: not applicable.** The app would not be submitted. Apple's guidelines
  themselves point people who only want an app for themselves to "Consider using Xcode to
  install your app on a device for free or use Ad Hoc distribution"
  ([App Review Guidelines][guidelines]). Note that "free" there does not cover Family
  Controls, which needs a paid membership ([caps]).
- **Policy risk.** Using the "develop and test" allowance for daily personal use goes beyond
  its evident intent, and Apple could narrow it.
- **Maintenance.** Provisioning profiles expire and have to be regenerated and the app
  re-signed ([Apple: regenerate a profile][profiles]). That is a periodic manual step on a
  Mac.

**Cost:** 99 USD/year ([ADP fee][adp-fee]) plus Mac access.

**What it would take to build:**

- a small SwiftUI app with FamilyControls authorization (individual), the App-and-Website-
  Usage capability, one App Intent "Export Screen Time" and a JSON serializer;
- a Shortcuts Time-of-Day automation that runs it;
- a transport to the PC;
- a Windows-side worker, in the same shape as `scripts/garmin/`, that upserts
  `(user_id, day, source)` rows, plus a migration for a new user-owned table that follows
  [supabase/README.md](../../supabase/README.md).

This would be the repo's first Swift code.

### Transport from the phone to the PC

Hosted auth is parked and local Supabase is not reachable from the phone, so the least
fragile option is **file drop through iCloud Drive**. The iOS side writes
`ScreenTime/YYYY-MM-DD.json` to iCloud Drive. iCloud for Windows syncs iCloud Drive to
`C:\Users\<name>\iCloud Drive` ([Apple Support 118443][icloud-win]). A scheduled Windows
worker then reads new files and upserts them, with the same idempotent 7-day overlap as
Garmin. This keeps credentials off the phone. The alternative is a POST over a LAN or VPN to
a small local endpoint. Shortcuts' Get Contents of URL supports POST with a JSON body
([Apple Support: request your first API][shortcuts-api]), but that needs the PC to be
reachable and a token on the phone.

---

## Route 2: HealthKit — not possible

HealthKit has no Screen Time type. Apple's
[`HKQuantityTypeIdentifier`][hk-quantity] list (123 identifiers checked) and
[`HKCategoryTypeIdentifier`][hk-category] list (36 checked) contain nothing about app usage,
device usage or pickups. The nearest types, `timeInDaylight` and `headphoneAudioExposure`,
are unrelated. Health-export apps such as Health Auto Export therefore cannot provide it.

## Route 3: Shortcuts, App Intents, personal automations — no data source

- **Running without interaction works.** Time of Day is among "the following automations
  [that] can be run automatically", and they "will not notify you" when set up that way
  ([Apple Support][shortcuts-auto]). Get Contents of URL can POST JSON ([Apple
  Support][shortcuts-api]).
- **Reading Screen Time does not.** No Apple-documented Shortcuts action reads Screen Time
  usage. This is based on searching Apple's Shortcuts User Guide and finding nothing, which
  is a negative result rather than a confirmed one. Shortcuts can only reach Screen Time
  through a third-party app's App Intent, and that app is back to Route 1's limits. So
  Shortcuts is the **trigger and transport** for Route 1b, not a source on its own.

## Route 4: macOS (iCloud sync to a Mac) — works, fragile, needs a Mac

**The sync is documented.** On a Mac, turning on "Share across devices" lets you "view app
and device usage for all of your devices". The Device menu can select a single device, and
the report covers app usage, notifications and pickups ([Apple Support: Track app and device
usage, macOS Tahoe 26][mac-st]). Apple offers no export; tools read undocumented stores on
disk.

| Store                                                                                                                 | What's there                                                                                                                         | Evidence                                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `~/Library/Biome/streams/restricted/App.InFocus/remote/<device-id>/` (SEGB protobuf) + `~/Library/Biome/sync/sync.db` | Foreground app intervals synced from other devices on the account. Per-app time can be derived; no pickups or notifications.         | [aw-import-screentime README][aw] (updated 2026-07); [iLEAPP `biomeInfocus.py`][ileapp-infocus] (local vs remote, tested to iOS 26.5.2) |
| `~/Library/Application Support/Knowledge/knowledgeC.db`                                                               | `/app/usage` events. Older tools used this for iPhone data too; current tools use it for the Mac only and Biome for iOS.             | [ScreenTime2CSV][st2csv] (last push 2024); [nichtlegacy/screentime][nichtlegacy] (Mac from knowledgeC, iOS from Biome)                  |
| `$DARWIN_USER_DIR/com.apple.ScreenTimeAgent/Store/RMAdminStore-{Local,Cloud}.sqlite`                                  | Screen Time's own hourly aggregates: per-app time, `ZNUMBEROFNOTIFICATIONS`, `ZNUMBEROFPICKUPS`, first pickup, per device, per user. | [APOLLO `screentime_counted_items`][apollo] (validated only up to macOS 10.15/11 and iOS 13/14); [mac_apt `screentime.py`][macapt]      |

**Fragility, documented in the tools' own issue trackers:**

- knowledgeC.db has returned `authorization denied` even with Full Disk Access on some
  macOS 12 and 15 machines, while it was readable on 14.5 ([APOLLO #26][apollo-26]).
- On macOS 26.1 the iPad peer was recorded as `platform = 1` rather than the expected 2, so
  the watcher "silently imported nothing" ([aw-import-screentime #18][aw-18]).
- A sync gap produced one **189.79 h** interval that was "85 % of the imported total"
  ([#19][aw-19]).
- The tools need Full Disk Access for the process reading the files ([aw README][aw]).
- The Biome format changed in 2025 and needed a new parser ([aw #12][aw-12]).

**Data and effort.** Biome gives per-app foreground intervals. RMAdminStore, if still
present on current macOS (unverified for 15/26), would add pickups and notifications.
Automation is full: a launchd job on the Mac. Cost is a Mac left running and signed into the
same Apple Account. The owner is on **Windows**, so this route needs new hardware plus a
Mac-side worker that sends data to the PC. There is no App Review or ToS contract here, but
it reads private, undocumented system stores.

## Route 5: iPhone backups, sysdiagnose, forensic tools — not viable as a pipeline

iLEAPP, the main open-source iOS forensic parser, runs on Windows and accepts encrypted
iTunes/Finder backups (`-t itunes`) ([iLEAPP README][ileapp]). Its Screen Time-relevant
artifacts read `*/mobile/Library/CoreDuet/Knowledge/knowledgeC.db*` and `*/[Bb]iome/...`
([knowledgeC.py][ileapp-kc], [biomeInfocus.py][ileapp-infocus]).

Its validation corpora are full-file-system extractions. Nothing in the repo shows these
stores present in a standard Finder/iTunes backup, and forensic practice generally treats
them as full-file-system-only (**unverified**). A full file system extraction of a current,
non-jailbroken iPhone needs commercial forensic tooling. Backups are also manual: a cable or
Wi-Fi sync to a PC running Apple Devices or iTunes. iLEAPP's own notes show streams going
empty across iOS versions: several knowledgeC streams have "no rows on any iOS 16.1.1-26.5.2
image checked" ([knowledgeC.py][ileapp-kc]). **Not reliable and not automatic.**

## Route 6: third-party apps and services — none export iPhone data

- **RescueTime** states: "On iOS, your phone activity stays on your phone. Apple does not
  allow it to be sent to RescueTime's servers" ([RescueTime help][rescuetime]). Its API's
  `mobile` source type ([API docs][rescuetime-api]) therefore will not contain iPhone data.
- Screen-time and blocker apps such as Opal and One Sec are built on the same FamilyControls
  and DeviceActivity frameworks, so before 26.4 they could not export either. The
  open-source "ScreenTimeExporter" iOS repo referenced in search results
  (`hoovdc/ScreenTimeExporter`) now returns 404 from the GitHub API.
- EU apps may adopt the 26.4 export API. Examples appear in the forum threads above, such as
  App时记 in [forum 844541][forum-844541]. No product was found that re-exposes the data
  through a public API or webhook. Any such app would also take the single data-access slot
  on the phone.
- On the Mac side, [ActivityWatch][aw] and [nichtlegacy/screentime][nichtlegacy] are Route 4
  packaged.

## Route 7: OCR of Screen Time screenshots — semi-automatic fallback

The iPhone Screen Time report shows daily and weekly totals, the most-used apps, pickups and
notifications ([Apple Support: Screen Time on iPhone][iphone-st]). A manual-plus flow would
work like this:

1. The owner takes a screenshot of Settings → Screen Time → the day view.
2. They share it to a shortcut.
3. The shortcut uses the Extract Text from Image action for on-device Live Text OCR. This
   action is observed in the Shortcuts app, but no Apple reference page was found, so it is
   documented only by third parties such as [Cassinelli][cassinelli] (**unverified**).
4. The shortcut saves the text to iCloud Drive for the Windows worker to parse. OCR could
   also be done on the PC instead.

- **Data:** whatever is on screen: total, top apps (usually the first few unless you scroll
  and take more screenshots), pickups, notifications.
- **Automation:** one tap per day. No Apple API makes Shortcuts screenshot the Settings
  pane.
- **Reliability:** OCR parsing of localized "3h 12m" strings and a changing layout. iOS 27
  just redesigned Screen Time ([Newsroom][newsroom-2026-09]).
- **Cost and risk:** free, with no ToS risk.

It is a better version of manual entry, not an integration.

---

## Comparison

| Route                                            | Granularity                                                                                                           | Automatic?                                                    | Reliability                                              | ToS / review risk                                         | Cost                   | Build effort                                      |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------- | ---------------------- | ------------------------------------------------- |
| **1b. Own iOS app, `activityData` (26.4+)**      | Total, per app (bundle ID), per category, web domains, pickups, notifications, first pickup; hourly or daily segments | Yes, via Shortcuts automation (background call needs a spike) | Official API; new (March 2026) with open forum questions | No review (dev build); relies on the dev-region allowance | 99 USD/yr + Mac access | High: first Swift code, Mac toolchain, re-signing |
| 4. Mac + Biome/RMAdminStore                      | Per-app intervals (Biome); + pickups and notifications (RMAdminStore, unverified on current macOS)                    | Yes (launchd)                                                 | Undocumented; broken by several macOS releases already   | None contractual; reads private stores                    | A Mac, always on       | Medium: Python on Mac + PC transport              |
| 7. Screenshot OCR                                | Total, visible top apps, pickups, notifications                                                                       | No: one tap per day                                           | OCR and layout fragility                                 | None                                                      | Free                   | Low to medium                                     |
| 1a. Report extension / monitor thresholds        | Display only; threshold buckets                                                                                       | Partly                                                        | Poor                                                     | Distribution entitlement needed for non-dev               | 99 USD/yr + Mac        | High, for little data                             |
| 5. Backups / forensics                           | Raw events, if present                                                                                                | No                                                            | Poor; stores likely absent from backups                  | None                                                      | Free to very expensive | Medium                                            |
| 2. HealthKit / 3. Shortcuts alone / 6. SaaS APIs | None                                                                                                                  | n/a                                                           | n/a                                                      | n/a                                                       | n/a                    | Not possible                                      |

## Recommendation

1. **Keep manual entry as the baseline.** Do not add a backlog item for automatic
   collection until the spike below passes.
2. **If automatic collection is wanted, spike Route 1b first. Budget one weekend on a Mac.**
   Build a throwaway app with individual authorization and the App-and-Website-Usage
   capability, then answer four questions:
   - (a) Does a development build on the owner's phone reach `.approvedWithDataAccess` in the
     owner's region?
   - (b) Does Apple's own Screen Time pane really stop recording?
   - (c) Can an App Intent call `activityData` from a Time-of-Day automation while the phone
     is locked?
   - (d) Do the per-day totals match the Settings pane?

   Go ahead only if (a), (c) and (d) pass and (b) is acceptable.

3. **If the spike fails, or a Mac is not available, choose between Route 7 (screenshot OCR)
   and staying manual.** Route 4 is only worth it if a Mac is going to be running anyway.

**Ranked shortlist:**

1. Own iOS app using `DeviceActivityData.activityData` (iOS 26.4+), triggered by a
   Shortcuts automation, with results moved to the PC through iCloud Drive.
2. Screenshot to Shortcuts to OCR to iCloud Drive. Semi-automatic, and needs no Mac.
3. A Mac reading the iCloud-synced Biome `App.InFocus` stream (plus RMAdminStore), only if
   a Mac becomes part of the setup.
4. Manual entry (current).

## What is NOT possible (as of 2026-09-23)

- Reading Screen Time from **HealthKit**: no such data type exists.
- A Shortcuts action that reads Screen Time without a helper app: none documented.
- Sending data out of a **DeviceActivityReport extension** by network, shared container or
  pasteboard: Apple's sandbox prevents it ([DeviceActivityReport][dar]).
- Getting real app names or bundle IDs under plain `.approved` authorization: tokens only.
- Using the 26.4 export API in a **distributed (TestFlight or App Store) build outside the
  EU** ([activityData][activityData]).
- Two apps holding data access at the same time, or (reportedly) data access while Apple's
  Screen Time keeps recording.
- Any server-side or cloud API from Apple for Screen Time, or any third-party SaaS API that
  carries iPhone Screen Time (RescueTime says so explicitly).
- Any route from **Windows alone** that is automatic. Every automatic route needs a Mac,
  either to build the iOS app or to read synced data.
- Automated extraction from standard iPhone backups on Windows, in practice.

---

## Sources

Apple developer documentation (fetched 2026-09-23 through Apple's documentation JSON
endpoints):

- [DeviceActivity][da] · [DeviceActivityReport][dar] · [DeviceActivityMonitor][dam] ·
  [eventDidReachThreshold][dam-threshold] · [MonitoringError.excessiveActivities][err-excessive] ·
  [MonitoringError.intervalTooShort][err-short] · [DeviceActivityData][dad] ·
  [ActivitySegment][seg] · [CategoryActivity][cat] · [ApplicationActivity][appact] ·
  [activityData(filteredBy:using:)][activityData] · [DeviceActivityData.Policy][policy]
- [FamilyControls][fc] · [requestAuthorization(for:)][fc-reqauth] ·
  [AuthorizationStatus.approvedWithDataAccess][approvedWithDataAccess] ·
  [FamilyActivityData][fad] · [installedApplications][fad-apps] ·
  [activityCategories][fad-cats] · [family-controls entitlement][fc-ent] ·
  [app-and-website-usage entitlement][aawu-ent] ·
  [Requesting the Family Controls entitlement][fc-request] ·
  [Configuring Family Controls][fc-config]
- [ManagedSettings][ms] · [Application.bundleIdentifier][bundleid] ·
  [ApplicationToken][apptoken]
- [HKQuantityTypeIdentifier][hk-quantity] · [HKCategoryTypeIdentifier][hk-category]
- [WWDC22 "What's new in Screen Time API"][wwdc22]
- [Supported capabilities (iOS)][caps] · [App Review Guidelines][guidelines] ·
  [Program enrollment / fee][adp-fee] · [Regenerate a provisioning profile][profiles] ·
  [Xcode on the Mac App Store][xcode]

Apple Developer Forums (developer reports; Apple replies noted where present):

- [820283][forum-820283] · [844541][forum-844541] ·
  [844623 (DTS reply quoting the EU restriction)][forum-844623] · [844661][forum-844661] ·
  [846053][forum-846053]

Apple Support and Newsroom:

- [Shortcuts personal automations][shortcuts-auto] ·
  [Shortcuts: request your first API][shortcuts-api] · [Screen Time on Mac][mac-st] ·
  [Screen Time on iPhone][iphone-st] · [iCloud Drive on Windows][icloud-win] ·
  [Newsroom 2026-09-14][newsroom-2026-09]

Open-source code (read directly from the repositories):

- [ActivityWatch/aw-import-screentime][aw] and issues [#12][aw-12], [#18][aw-18], [#19][aw-19]
- [nichtlegacy/screentime][nichtlegacy] · [FelixKohlhas/ScreenTime2CSV][st2csv]
- [abrignoni/iLEAPP][ileapp]: [biomeInfocus.py][ileapp-infocus], [knowledgeC.py][ileapp-kc]
- [mac4n6/APOLLO screentime modules][apollo] and [issue #26][apollo-26] ·
  [ydkhatri/mac_apt screentime.py][macapt]

Third-party first-party docs:

- [RescueTime iOS help][rescuetime] · [RescueTime API][rescuetime-api]
- [Matthew Cassinelli: Extract Text from Image][cassinelli] (secondary; no Apple page found)

[da]: https://developer.apple.com/documentation/deviceactivity
[dar]: https://developer.apple.com/documentation/deviceactivity/deviceactivityreport
[dam]: https://developer.apple.com/documentation/deviceactivity/deviceactivitymonitor
[dam-threshold]: https://developer.apple.com/documentation/deviceactivity/deviceactivitymonitor/eventdidreachthreshold(_:activity:)
[err-excessive]: https://developer.apple.com/documentation/deviceactivity/deviceactivitycenter/monitoringerror/excessiveactivities
[err-short]: https://developer.apple.com/documentation/deviceactivity/deviceactivitycenter/monitoringerror/intervaltooshort
[dad]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata
[seg]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata/activitysegment
[cat]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata/categoryactivity
[appact]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata/applicationactivity
[activityData]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata/activitydata(filteredby:using:)
[policy]: https://developer.apple.com/documentation/deviceactivity/deviceactivitydata/policy
[fc]: https://developer.apple.com/documentation/familycontrols
[fc-reqauth]: https://developer.apple.com/documentation/familycontrols/authorizationcenter/requestauthorization(for:)
[approvedWithDataAccess]: https://developer.apple.com/documentation/familycontrols/authorizationstatus/approvedwithdataaccess
[fad]: https://developer.apple.com/documentation/familycontrols/familyactivitydata
[fad-apps]: https://developer.apple.com/documentation/familycontrols/familyactivitydata/installedapplications
[fad-cats]: https://developer.apple.com/documentation/familycontrols/familyactivitydata/activitycategories
[fc-ent]: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.family-controls
[aawu-ent]: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.family-controls.app-and-website-usage
[fc-request]: https://developer.apple.com/documentation/familycontrols/requesting-the-family-controls-entitlement
[fc-config]: https://developer.apple.com/documentation/xcode/configuring-family-controls
[ms]: https://developer.apple.com/documentation/managedsettings
[bundleid]: https://developer.apple.com/documentation/managedsettings/application/bundleidentifier
[apptoken]: https://developer.apple.com/documentation/managedsettings/applicationtoken
[hk-quantity]: https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier
[hk-category]: https://developer.apple.com/documentation/healthkit/hkcategorytypeidentifier
[wwdc22]: https://developer.apple.com/videos/play/wwdc2022/110336/
[caps]: https://developer.apple.com/help/account/reference/supported-capabilities-ios
[guidelines]: https://developer.apple.com/app-store/review/guidelines/
[adp-fee]: https://developer.apple.com/help/account/membership/program-enrollment
[profiles]: https://developer.apple.com/help/account/provisioning-profiles/edit-download-or-delete-profiles
[xcode]: https://apps.apple.com/app/xcode/id497799835
[forum-820283]: https://developer.apple.com/forums/thread/820283
[forum-844541]: https://developer.apple.com/forums/thread/844541
[forum-844623]: https://developer.apple.com/forums/thread/844623
[forum-844661]: https://developer.apple.com/forums/thread/844661
[forum-846053]: https://developer.apple.com/forums/thread/846053
[shortcuts-auto]: https://support.apple.com/guide/shortcuts/create-a-new-personal-automation-apdfbdbd7123/ios
[shortcuts-api]: https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios
[mac-st]: https://support.apple.com/en-gb/guide/mac-help/mchlf2c0c770/mac
[iphone-st]: https://support.apple.com/guide/iphone/get-started-with-screen-time-iphbfa595995/ios
[icloud-win]: https://support.apple.com/en-us/118443
[newsroom-2026-09]: https://www.apple.com/newsroom/2026/09/apples-new-child-safety-features-now-available/
[aw]: https://github.com/ActivityWatch/aw-import-screentime
[aw-12]: https://github.com/ActivityWatch/aw-import-screentime/pull/12
[aw-18]: https://github.com/ActivityWatch/aw-import-screentime/issues/18
[aw-19]: https://github.com/ActivityWatch/aw-import-screentime/pull/19
[nichtlegacy]: https://github.com/nichtlegacy/screentime
[st2csv]: https://github.com/FelixKohlhas/ScreenTime2CSV
[ileapp]: https://github.com/abrignoni/iLEAPP
[ileapp-infocus]: https://github.com/abrignoni/iLEAPP/blob/main/scripts/artifacts/biomeInfocus.py
[ileapp-kc]: https://github.com/abrignoni/iLEAPP/blob/main/scripts/artifacts/knowledgeC.py
[apollo]: https://github.com/mac4n6/APOLLO/tree/master/modules
[apollo-26]: https://github.com/mac4n6/APOLLO/issues/26
[macapt]: https://github.com/ydkhatri/mac_apt/blob/master/plugins/screentime.py
[rescuetime]: https://help.rescuetime.com/article/380-rescuetime-ios-mobile-app
[rescuetime-api]: https://www.rescuetime.com/apidoc
[cassinelli]: https://matthewcassinelli.com/actions/extract-text-from-image/
