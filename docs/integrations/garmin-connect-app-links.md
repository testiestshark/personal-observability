# Garmin Connect app links

**Status: Tested on an iPhone (2026-10-25). Android untested.**

Which link forms might open the Garmin Connect mobile app from a web page in the
phone's browser or from an installed home-screen web app. This feeds
[issue #142](https://github.com/testiestshark/personal-observability/issues/142); the
answer is recorded there after a device test. Garmin publishes no document describing a
link scheme for the app, so what follows is what Garmin's own site files and the
platform documentation support, with everything else marked UNVERIFIED.

## What Garmin publishes

Fetched from `connect.garmin.com` on 2026-10-25.

### iOS: apple-app-site-association

<https://connect.garmin.com/.well-known/apple-app-site-association> (the same file is
also served at `/apple-app-site-association`) declares the production app as
`72ES32VZUA.com.garmin.connect.mobile`, with `applinks` paths including:

- `modern/home`, `app/home`
- `modern/activities`, `app/activities`
- `modern/activity/*`, `app/activity/*`, `activity/*`
- `modern/profile/*`, `app/profile/*`
- `mobile-link/gcm/*`, `ml/gcm/*`

Other entries (challenges, courses, subscription, OAuth confirmation and so on) exist
but are not relevant here. The file lists a separate beta app ID and several other
Garmin apps; the production Connect app is the one that matters.

Caveats on the file itself:

- Some paths have a leading slash and some do not. Whether the unslashed ones match is
  UNVERIFIED, and the home paths are among the unslashed ones. Test both `/app/home`
  and `/modern/home`.
- The file proves the app claims these paths. It does not prove the app still handles
  them well today (UNVERIFIED), nor what it shows for `home`.

### Android: assetlinks.json

<https://connect.garmin.com/.well-known/assetlinks.json> lists
`com.garmin.android.apps.connectmobile` with relation
`delegate_permission/common.handle_all_urls` (and `get_login_creds`) and two signing
certificate fingerprints. So the Android app is verified to handle `https` links on
`connect.garmin.com`. Which paths its intent filters accept is not published
(UNVERIFIED), and the iOS path list cannot be assumed to apply.

### Custom URL scheme

No Garmin documentation or site file names a custom URL scheme for the Connect
mobile app. The only evidence is user reports on Garmin's forums, which are not
primary sources:

- `gcm-ciq://` "opens the Garmin Connect start page", reported by a user, with no
  deeper pages known:
  <https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-mobile-ios/404610/url-scheme>
- `connect://` "opens the Garmin Connect app", reported by a user who tried it, not
  from documentation:
  <https://forums.garmin.com/developer/connect-iq/f/discussion/216653/how-to-launch-gcm-app-from-my-own-ios-app>

Both are UNVERIFIED. `garminconnect://` was not found anywhere and is not a candidate.
`connect://` is generic, so another app could claim it.

### Home page tags

`connect.garmin.com/` returned no smart-banner (`apple-itunes-app`) or `al:` app-link
meta tags to a phone user agent.

## Platform behaviour

### iOS universal links

Source: <https://developer.apple.com/documentation/xcode/allowing-apps-and-websites-to-link-to-your-content>

- When a user taps a universal link, the system opens the app directly instead of the
  browser. If the app is not installed, the URL opens in the default browser.
- When someone browsing a site in Safari taps a universal link in the **same domain**,
  Safari opens it. A link to a different domain opens the app. So the test page must
  not be hosted on `connect.garmin.com`, and typing the URL is not a test of a tap.

Not stated on that page, so UNVERIFIED: how a universal link behaves from a
home-screen web app (standalone mode). The test is the only way to know.

### iOS custom schemes

Source: <https://developer.apple.com/documentation/uikit/uiapplication/canopenurl(_:)>

- An app registers a custom scheme and the system launches an installed handler.
  Declaring the scheme in `LSApplicationQueriesSchemes` is only needed to call
  `canOpenURL`, not to open a URL, so a plain link can try a scheme from a web page.
- What Safari does when no app handles a scheme (an error alert, or nothing) is not in
  the pages consulted (UNVERIFIED).

### Android App Links and intent URLs

Sources:
<https://developer.android.com/training/app-links/verify-android-applinks> and
<https://developer.chrome.com/docs/android/intents>

- With a verified `https` App Link, selecting a link on that domain opens the app
  automatically. Garmin's `assetlinks.json` is the verification file for it.
- Chrome intent URLs have the form
  `intent://HOST/PATH#Intent;scheme=...;package=...;S.browser_fallback_url=ENCODED_URL;end`.
- Chrome will not launch an app for an intent URL started without a user gesture, or
  one redirected from a URL the user typed. So it must be a tap on a link or button.
- If no app can handle the intent, the user can be redirected to the fallback URL.
- How an installed home-screen web app treats links to another origin is not covered
  by these pages (UNVERIFIED).

## Store pages

- App Store: <https://apps.apple.com/app/id583446403> (the Garmin Connect listing
  returned by search; not otherwise fetched).
- Play Store: `https://play.google.com/store/apps/details?id=com.garmin.android.apps.connectmobile`
  (package name taken from Garmin's `assetlinks.json`; the listing was not fetched).

## Candidates to test

Host the test page on a domain other than `connect.garmin.com`. Test each from Safari
or Chrome, and again from the page installed to the home screen, tapping a real link.
Record phone, OS version and result in issue #142.

| Form                              | URL                                                                                                                                                                                  | Why                                                              | Expected result                                                                                                   |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Universal link, app home (iOS)    | `https://connect.garmin.com/app/home`                                                                                                                                                | Listed in Garmin's AASA file                                     | Safari: opens the app if the path matches, else the web page. Home-screen app: UNVERIFIED                         |
| Universal link, legacy home (iOS) | `https://connect.garmin.com/modern/home`                                                                                                                                             | Also listed in the AASA file                                     | Same as above                                                                                                     |
| Universal link, a known activity  | `https://connect.garmin.com/modern/activity/<id>` (use a real activity id)                                                                                                           | `modern/activity/*` is listed; proves a deeper path              | Same as above, lands on that activity if handled                                                                  |
| App Link (Android)                | `https://connect.garmin.com/app/home`                                                                                                                                                | `assetlinks.json` verifies the package for the domain            | Chrome: opens the app if its filters accept the path (UNVERIFIED), else the web page. Home-screen app: UNVERIFIED |
| Intent URL (Android)              | `intent://connect.garmin.com/app/home#Intent;scheme=https;package=com.garmin.android.apps.connectmobile;S.browser_fallback_url=https%3A%2F%2Fconnect.garmin.com%2Fmodern%2Fhome;end` | Forces the package; falls back to the web page if it cannot open | Chrome: app opens on a tap, or the fallback loads. Android only                                                   |
| Custom scheme, forum report       | `gcm-ciq://`                                                                                                                                                                         | Only reported scheme that looks Garmin-specific                  | UNVERIFIED: may open the app's start page; may do nothing or show an error                                        |
| Custom scheme, generic            | `connect://`                                                                                                                                                                         | Forum report                                                     | UNVERIFIED: could open Garmin Connect, another app, or nothing                                                    |
| App Store fallback                | `https://apps.apple.com/app/id583446403`                                                                                                                                             | Confirms the store path if nothing else works                    | Opens the store page, or the listing in the App Store app                                                         |
| Play Store fallback               | `https://play.google.com/store/apps/details?id=com.garmin.android.apps.connectmobile`                                                                                                | Same, for Android                                                | Opens the Play listing                                                                                            |

Also try each universal link two ways, typed into the address bar versus tapped from
the test page, to learn what the owner will actually see.

## Device test result

iPhone 13, iOS 27.0.1, Garmin Connect installed and signed in. Each form was tapped from
a test page on another domain, in a Safari tab and again from the page added to the home
screen. The two gave the same results.

| Form                                              | Result                                |
| ------------------------------------------------- | ------------------------------------- |
| `https://connect.garmin.com/app/home`             | Opened the app                        |
| `https://connect.garmin.com/modern/home`          | Opened the app                        |
| `https://connect.garmin.com/modern/activity/<id>` | Opened the app on that activity       |
| Android intent URL                                | No effect (Android only, as expected) |
| `gcm-ciq://`                                      | Opened the app                        |
| `connect://`                                      | Opened the app                        |
| App Store link                                    | Opened the App Store                  |
| Play Store link                                   | Opened the Play Store page            |

Recommendation: use the universal link. It deep-links to an activity and falls back to
the web page when the app is missing, which a custom scheme does not. The custom schemes
worked but come only from forum reports, so Garmin could change them without notice.
Android and a phone without the app installed were not tested.
