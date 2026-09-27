# Crawling a site from another machine

**lifegence_i18n 0.1.0 · 20 September 2026**

How to run the screen route (route 4) from a second machine, when the site you
want to measure cannot run a browser itself — Frappe Cloud, for instance.

---

## 1. When you need this

The screen route starts Playwright inside the site that runs the scan. Frappe
Cloud does not let you add software to the server, so a scan run on a production
site there writes

```
Screen : skipped — Playwright is not installed on this server
```

to its log and the other three routes carry on without it.

When that happens, **install this app with Playwright on a second machine (the
"crawling machine") and open the production site's screens from there.** The
findings land in the crawling machine's ledger. Carrying them back to the
production site is not automated; the import and export sections of the user
manual describe how translations move between the two.

## 2. What the crawling machine needs

| | | How to check |
|---|---|---|
| A Frappe bench | The same line as the target site — version-15 for version-15 | `bench version` |
| The same applications | frappe, erpnext and any site-specific applications, at the versions the target runs. The list of screens to visit, and the distinction between interface text and data, are read from the crawling machine's own site. **Translation files need not match** (section 6) | compare `bench version` with the target |
| This app | `lifegence_i18n` installed with Playwright | `pip install "lifegence_i18n[screen]"` then `playwright install chromium` |
| HTTPS reach | The crawling machine can open the target site's URL | open it in a browser |
| A locale | On the crawling machine's site: the same locale as the target (say `ja-JP`) and the same list of target applications | open the Locale Profile |

## 3. On the target site

1. **Create a crawl user.** Read-only, with **read permission on the DocTypes of
   every target application**. A screen the user may not open is counted as not
   opened, not as measured. Measuring public applications with an
   under-permissioned user left 324 of 400 screens unopened.
2. **Set that user's display language to the locale's language** — `ja` for
   `ja-JP`. If they differ the crawl stops right after login and the scan log
   says `The crawl user … reads the site in en, not ja`.
3. **Exempt the user from two-factor authentication and password expiry.**
   Either one stops the crawl at the login screen.
4. **Use a password used for nothing else.** It is stored in the crawling
   machine's settings, and any System Manager there can read it back.
5. **The host name in the URL must be the target site's own name** — the
   directory name under `sites/`. Frappe resolves the site from the `Host`
   header, so an IP address returns `<address> does not exist` as a 404 and no
   login form is drawn at all. The crawl then waits for a field that will never
   appear and ends with `Page.fill: Timeout 30000ms exceeded`. Writing
   `currentsite.txt` does not make it fall back to a default site.
6. **The target site must serve `/assets/`.** The desk loads its JavaScript
   before it moves to `/app`. Where assets return 404 the login succeeds but the
   move never completes, and `wait_for_url` gives up after 30 seconds with
   `Timeout 30000ms exceeded`. In production nginx serves them, so this does not
   arise. If you stand up your own site to try this locally, **use `bench
   serve`** — a bare gunicorn does not serve assets.

    ```bash
    bench --site <target site> serve --port 8100
    ```

## 4. On the crawling machine

### 4-1. Settings, once

I18n Settings (`/app/i18n-settings`), the "Screen Crawl" section.

| Field | What goes in it |
|---|---|
| Site URL to Crawl (`screen_site_url`) | The target site's URL. **https only**, and the **host name must be the site's own name** (`https://<target site>`). An IP address will not work (section 3, item 5) |
| Crawl User (`screen_user`) | The user from section 3. Administrator when empty |
| Crawl User Password (`screen_password`) | That user's password |
| Max Screens per Scan (`screen_max_screens`) | 300 by default. 0 means every screen |

The names in brackets are the field names, for setting these from a script.
Writing to a different name saves without complaint and has no effect on the
crawl, which then tries the site's own default URL and fails with
`ERR_CONNECTION_REFUSED`.

Add this to the crawling machine's `site_config.json`. Without it, saving a
setting that points at another site is refused:

```json
"i18n_allow_remote_crawl": 1
```

### 4-2. Running it, two ways

**From the screen.** Open the locale (say `ja-JP`), tick "Screens (browser
crawl)" under what to measure, and press Run Scan. The crawl starts after the
other three routes.

**From the command line**, for the screen route alone:

```bash
bench --site <crawling machine's site> execute lifegence_i18n.scanner.screen.run \
  --kwargs '{"locale": "ja-JP"}'
```

Add `"cap": 500` to change the limit for that run only, leaving the setting
alone.

Reckon on about three seconds a screen: roughly 15 minutes for 300 screens, 17
for 400.

### 4-3. While it runs

- **Do not start a second scan of the same locale.** A scan already running
  makes the next one stop with "still running".
- The scan record is touched every 25 screens to say it is alive. After 15
  minutes without an update it is taken as dead, and another scan may start.

## 5. Reading the result

The scan log holds lines like these:

```
Screen: crawling https://<target site> as i18n-crawler@…
Screen: judging by the site's own dictionary, 31842 translations for ja
Screen           :     12 new / 10 not wrapped on screen / 3 not delivered / 1006 confirmed — 398 screens in 982.2s (2 could not be opened)
Not delivered to the site (3): translated in the ledger, not served by the site
  'Zzz Export' on /app/data-export
Screen: could not open 2 of 400 — 2 x not available to the crawl user (no permission, or no such page)
Screens not opened: /app/authorization-control, /app/welcome-workspace
Ledger (screen): 12 new / 0 updated
Screens visited (398):
  /app/selling
  …
```

| Line | What it means | Where to look |
|---|---|---|
| `crawling … as …` | Which site was crawled, as whom | Without this line the crawl never started |
| `judging by the site's own dictionary, N translations for ja` | N translations were read from the target site and used to judge. What follows `for` is the target's display language | If `could not be read from the desk` appears instead, judgement fell back to the crawling machine's own dictionary (section 6) |
| `N new` | Strings the other three routes did not know | Filter the ledger by Found In = Screen |
| `M not wrapped on screen` | The ledger has a translation, **the target site serves it too**, and the screen still shows the source | Filter issues by Not Wrapped and look at the detail beginning `screen:`. Translating will not fix this |
| `L not delivered` | The ledger has a translation and **the target site does not** — not shipped yet, or shipped stale | The `Not delivered to the site` list that follows (up to 40). Ship the CSV |
| `K confirmed` | Ledger gaps seen on a screen | — |
| `could not open` | How many screens could not be opened, and why. `Screens not opened` names them (up to 40) | If it is permission, revisit section 3, item 1 |
| `Screens visited` | Where the crawl went. Record names are cut back to the DocType | — |

**A large `not delivered` means the translation files have not reached the
target site, or reached it stale.** That is not a code defect. Ship the
translations before sending anything to a developer.

## 6. The dictionary that judges is the target's

Whether a string on screen is untranslated, or translated-but-not-rendered, or
translated-but-not-shipped, is decided against **the target site's own**
dictionary. When Frappe draws the desk it hands the browser every translation
for that user's language (`frappe.boot.__messages`, the same on version-15 and
version-16). The crawl reads it once after login and judges by it from then on.
The `judging by the site's own dictionary` line records that it did.

This is why **the crawling machine's translation files need not match the
target's.** Between the crawling machine's ledger (what the translation should
be) and the target's dictionary (what it actually serves), every source string
on screen falls into one of three:

| Target's dictionary | Crawling machine's ledger | Verdict | Meaning |
|---|---|---|---|
| has it, same as the ledger | has it, approved | `not wrapped on screen` | The site holds the translation and the screen does not show it. A fix in the code |
| lacks it, or has a different one | has it, approved | `not delivered` | The translation exists and has not reached the site, or reached it stale. Ship the CSV |
| (either way) | lacks it | `confirmed` | Nobody has translated it. A gap, whatever the site happens to serve |

Rows still in draft, and rows ruled out as not applicable, are not judged.

The target's display language is read at the same moment. If it differs from the
locale's, the crawl stops there and the log says `reads the site in …, not …`
(section 3, item 2).

Only if the desk cannot be read at all — the log says `could not be read from
the desk` — does judgement fall back to the crawling machine's own dictionary.
In that case, as before, `not wrapped` is overstated unless both sides carry the
same translation files.

## 7. What has been verified

In a local Docker environment, a version-15 bench acted as the crawling machine
and a version-16 site in the same container (on another port) as the target.
Login, reading the target's dictionary, reading screens, detecting screens the
user may not open, logout and writing the scan record all worked: 8 of 12
screens read, 4 classed as not opened for want of permission.

Changing the judging dictionary from the crawling machine's to the target's was
measured in that environment. Crawling a version-16 site with no Japanese, 65
strings across 8 screens were counted as "translated but rendered as the source"
before the change; afterwards they separated into 2 not wrapped and 62 not
delivered (14 new, 25 confirmed, 511 translations in the target's dictionary).
The 62 are translations the crawling machine's ledger holds and the version-16
site does not serve, which is what they are. The 2 that remained are strings the
target itself serves while the screen still shows the source — two workspace
names drawn as links, `Acme I18n Fixture` and `Localization`, for which the
target serves Japanese and version-16 drew the source anyway. That verdict is
correct. Crawling a site from itself, the ordinary case (400 screens on
version-15), gives the same result before and after the change: 6 new, 10 not
wrapped, 0 false positives, 0 not delivered, with the same strings in each.

**Acceptance measurement, 27 September 2026.** A bench running frappe 15.121.0
and erpnext 15.121.3 crawled a site served from the same bench by `bench serve`.
Of a 300-screen limit, 205 were read and 95 classed as not opened for want of
permission (accounting, asset and bank DocTypes). It took 2,244 seconds — about
11 seconds a screen, slower than production because `bench serve` is a single
process.

Judgement used the target's own dictionary, 22,701 translations for `ja`. The
result was 4 new, 7 not wrapped, 0 not delivered, 196 confirmed.

The 4 new strings were absent from the 15,543 rows the other three routes had
already written (15,223 from source code, 320 from the database):

| Application | Source string |
|---|---|
| frappe | `Begin typing for results.` |
| frappe | `Compare` |
| clefincode_chat | `Check Status` |
| clefincode_chat | `Set Telegram Webhook` |

The 7 not wrapped include the `Export` button on `/app/data-export`, a
description on `/app/security-settings`, and three literals handed straight to
`throw()`. None of the 4 new strings was a false positive — no customer data, no
brand names, no fragments of code.

Three crawls failed before that measurement, every one of them for a setting or
an environment rather than a defect. Items 5 and 6 of section 3, and the field
names in section 4-1, were established then.

## 8. Known limits

- Findings land in the crawling machine's ledger. Carrying them to the target
  site's ledger is out of scope
- The list of screens to visit, and the distinction between data and interface
  text, come from the crawling machine's own site. Keep its applications the
  same as the target's
- Playwright on Frappe Cloud is out of scope. If Cloud ever allows it, this
  document becomes unnecessary
- A site that only accepts two-factor authentication or single sign-on cannot be
  crawled: the crawl user cannot log in
