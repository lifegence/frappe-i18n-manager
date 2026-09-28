# I18n Manager

Runs a Frappe or ERPNext site in another language, and keeps it that way.

It finds what is untranslated, hands it out as a spreadsheet, takes the filled-in
sheet back, writes the agreed translations to the site and into the files an
application ships, and then checks that they reached the screen. One step of
that loop is not the app's: somebody who knows the language writes the
translations. Everything on either side of that is.

The initial locale set is Japan, Taiwan, Hong Kong and Croatia. It is a starting
set, not a fixed list — a further country needs four values and nothing else.

Workspace: `/app/localization` (listed as **Localization** in the app switcher).

Built jointly by **Lush Japan** and **Lifegence Corporation**, and released as
open source rather than kept private. Copyright is held by Lush, Lush Japan and
Lifegence — see [NOTICE](NOTICE). Lifegence maintains it: it follows the Frappe
and ERPNext release lines and fixes defects.

## The loop

| | Step | What the app does | Where |
|---|---|---|---|
| 1 | **Measure** | Four routes find what is untranslated and write one ledger row per source string | Run Scan |
| 2 | **Hand out** | The gaps leave as a CSV a translator can open in a spreadsheet | Export → Review Sheet |
| 3 | *Translate* | *Outside the app. A person, an agency, a machine — whoever knows the language* | — |
| 4 | **Take back** | Only the proposal column is read, so a half-finished sheet is safe to return | Import File → Review Sheet |
| 5 | **Agree** | A translation somebody typed and one somebody agreed to are different states | Approve Drafts |
| 6 | **Deliver** | Write them to the site, and generate the `translations/<lang>.csv` an application ships — optionally straight into the app's own folder | Apply to Site / Export → App Translation CSV |
| 7 | **Check** | Whether each translation actually reached the screen, and if not, why | Verify Delivery |

Step 6 is what makes the site multilingual. Steps 1 and 7 are what stop it
quietly stopping.

Alongside the loop: a glossary with wordings that must not be used, nine checks
over the ledger, exclusion rules that file a naming series as *not applicable*
with a reason rather than dropping it, and display formats — date, number, first
day of the week — written to the Language record so the site follows the
locale's conventions and not just its words.

| Record | What it holds |
|---|---|
| Locale Profile | Country, language, currency and display formats as one record |
| Translation Entry | Source text, translation, where it was found, its status |
| Glossary Term | Agreed wordings, and renderings that must not be used |
| Translation Scan | One scan: counts, timings, what each route found |
| Translation Issue | Placeholder damage, glossary violations, script residue |
| I18n Settings | Detection settings shared across locales |

## Delivering translations

Two ways out, and they answer different questions.

**Apply to Site** writes the approved translations as `Translation` records in
this site's database. Frappe resolves app CSV, then app MO, then Translation
records — last wins — so this reliably overrides whatever an application ships,
and it takes effect on the next page load. The same button writes the locale's
display formats to the `Language` record, so dates, numbers and the first day of
the week follow the locale too.

**Export → App Translation CSV** generates the file an application ships,
`<app>/translations/<lang>.csv`, in exactly the format Frappe reads. Commit it
and every site running that application gets the translations, not just this
one. On a bench you can reach, it will write straight into the application's own
folder so a developer can commit from there; on Frappe Cloud you get the
download.

A row whose translation equals its source is left out — Frappe resolves to the
source anyway — except where leaving it alone was the decision: a brand name or
an acronym ruled *not applicable* ships as itself, so it stops being reported as
a gap. A row with no context is written with two columns and a row with one with
three, so re-exporting over an existing file does not rewrite every line.

### Did it arrive?

`Verify Delivery` on a Locale Profile compares three dictionaries — the
ledger, the application files read straight from disk, and what the site
resolves right now — and reports each approved string as one of:

| State | Meaning | Fix |
|---|---|---|
| Live | on the screen | — |
| Cache Stale | the file has it, this site is serving an older copy | `bench clear-cache` |
| Not Deployed | no file has it: not exported, merged or deployed — whatever the site shows meanwhile | ship it |
| Overridden | some app's file has it and a later file or a Translation record wins | find the other source |

Reading the files past the cache is what separates the last three, which look
identical from a browser and need completely different fixes.

## Four ways of finding what to translate

Step 1 of the loop. What you never find, you never hand out, so the routes
decide the ceiling on everything after them.

| # | Route | What it covers | In Frappe |
|---|---|---|---|
| 1 | Source code | translatable strings in `.py` / `.js` / `.json` | yes — `bench get-untranslated` |
| 2 | **Database** | onboarding, workspaces (including the headings and shortcut formats kept in their content JSON), report names, notification subjects | **no** |
| 3 | **Code messages** | literals passed straight to `frappe.throw`, never reaching a translation function | **no** |
| 4 | **Screen** | what a browser actually renders for a user of the locale | **no** |

Routes 2 to 4 are invisible to the standard tooling. An environment that
measures 98% on source code alone can be at 4–14% on the database route.

### Route 4: the screen

The first three routes measure what *should* be translated. None of them looks
at the page. Route 4 logs in with a headless browser (Playwright), walks the
screens of the target apps — every public workspace, and for each DocType a
list view, a blank form and one record — and reads the text that is really
there. It reports three things:

- strings no other route knew about (a heading kept inside a workspace's JSON,
  a button whose label never went through `__()`), added to the ledger with
  origin `Screen` and the route as their location;
- strings that have a translation the site resolves and still render in
  English — the rendering code never asked for it. Delivery verification
  reports these as `Live`, so only this route can see them. They are filed as
  `Not Wrapped` issues, like a bare literal in `frappe.throw`, with a detail
  that starts `screen: <route> (<element>)`;
- untranslated ledger rows confirmed on screen.

Whether a string is data or interface text is decided by *where it sits*, not by
what it looks like: form values, list rows, grid rows, tree nodes, chart labels,
the record name in the URL, the names of master records and the signed-in
user's own name are data. Numbers and keyboard hints are not
translation targets. Japanese on screen means translated; a rendered string
equal to some translation means translated; everything else is matched against
the ledger, including templates such as `You haven't created a {0} yet`, and
against the lines of the strings the ledger holds whole: a DocType's
description is markdown and an HTML field is markup, which Frappe translates
as one string each and the browser draws as a heading, a paragraph and a list.
Those pieces are that row's business, not rows of their own.

The route is optional. It runs where Playwright is installed and stays silent
where it is not — Frappe Cloud has no shell, so there the scan simply reports
`Screen: skipped`. To enable it on a server or a developer machine:

```bash
./env/bin/pip install playwright
./env/bin/playwright install --with-deps chromium
```

then fill in `I18n Settings > Screen Crawl` (site URL, the crawl user, its
password, and the maximum number of screens per scan) and tick `Rendered
Screens (browser crawl)` on the Locale Profile. About three seconds per
screen; 300 screens take a quarter of an hour. Pressing `Run Scan` with the
route on and Playwright absent stops with a message saying so.

**A read-only crawl user is recommended.** Administrator is used when the
field is empty. The password is stored encrypted, but Frappe lets any System
Manager read a stored password back, so give the crawl user a password used
for nothing else. It needs read permission on the DocTypes of every target
app and nothing more: a screen it may not open is counted as not opened and
goes unmeasured (324 of 400 with one read-only user during validation). Its
language must be the locale's language, and it must not be subject to
two-factor authentication or a password-expiry policy. Log entries such as
Activity Log, View Log and Route History will carry that user's name, which
is what makes them easy to filter out.

The first version reads each screen as it stands — visible text,
placeholders, tooltips and the options of a Select. Nothing is clicked, so
menus, filters and dialogs are left for a later version.

The screens are visited in a fixed order — workspaces (a site's own, made in
the UI, before any app's), then single settings, then each DocType's list,
blank form and one record, alphabetically — and the
crawl stops at the configured maximum, or walks every screen when the maximum
is 0. A site with 650 DocTypes has about 2,000 screens, at three seconds each.
The background job's timeout follows the maximum (four seconds per screen plus
half an hour, never less than two hours; with no maximum it assumes 2,000
screens).

To crawl a site from another machine — the shape Frappe Cloud needs — run the
screens route alone from a bench that has Playwright, with the site URL and
credentials in its own I18n Settings. The URL must be HTTPS, may not point at a
private address, and is refused until `i18n_allow_remote_crawl` is set in that
bench's `site_config.json`; remove the credentials again when done:

```bash
bench --site <site> execute lifegence_i18n.scanner.screen.run --kwargs '{"locale": "ja-JP"}'
```

Strings the crawl finds go through the same exclusion rules as the other
routes, so a naming series seen on screen is recorded as Not Applicable with
its reason rather than filed as a gap.

Three things to know before running it:

- `playwright install --with-deps chromium` installs system libraries and
  needs root (or `sudo`) once per server; `playwright install chromium` alone
  is enough where they are already present.
- When the site URL is left empty, the crawl logs in to this site by the URL
  Frappe derives from `host_name` in `site_config.json`; without `host_name`
  it falls back to `http://<site name>` plus the bench's `webserver_port`.
  Set `host_name` (or fill in the site URL) on any server where that is not
  reachable.
- The crawl user's language must be the locale's language; on this site the
  scan refuses to run otherwise, on a remote site the crawl stops after login
  when the desk says it serves another language. What is on screen is judged
  by the crawled site's own dictionary, read once from the desk after login
  (`frappe.boot.__messages`), so the two sites need not carry the same
  translation files: a translation the ledger holds and the site does not
  serve is counted as *not delivered*, not as a rendering defect. The names
  used to tell data from interface text (master records, installed apps) do
  come from *this* site's database, so crawl a site that mirrors this one, or
  expect a few more candidates to check by hand.
- Never run the worker with `DEBUG=pw:api`: Playwright would then print what
  it types into the login form.
- Records are opened one per DocType; the ledger and the log record such a
  screen as `/app/<doctype>`, never the record's name. The scan log lists
  every screen visited and every string it normalised before storing it.

## String classes

A role name and an item group are records the customer owns, not interface text.
Folding them into one denominator makes the coverage figure argue with itself, so
each string carries a class and only `UI Text` counts towards the headline
number. Master data and role names are off by default.

Frappe's own extractor emits the role of every DocPerm row, so roles arrive on
the source route looking like interface text. They are only treated as roles when
the database route did not also find the same string stored as a label —
`Customer` and `Leave Approver` are both.

## Running the tests

    bench --site <site> run-tests --app lifegence_i18n                        # version-15
    bench --site <site> run-tests --app lifegence_i18n --test-category all    # version-16

Version-16 sorts tests into unit and integration and runs only the unit ones
by default, so without the flag it reports a green run of the tests that
never touch the database and silently leaves the rest out.

## Exclusions

A string that is not a translation target — a naming series, a lone placeholder,
a bare acronym — is recorded and marked `Not Applicable` with a reason, never
dropped in silence. An exclusion nobody can point at cannot be explained when a
customer asks what the excluded rows were. Rules live in
`I18n Settings > Exclusion Rules`; one with `Auto Apply` off records its reason
as a suggestion and leaves the string counting as untranslated until someone
confirms it; the shipped `Acronym` rule is one of those. A glossary term marked
Do Not Translate, met as a whole string, is filed as a `Brand or Product Name`,
and the app CSV ships it as its own translation so the string is settled.

## Checks

Recorded as `Translation Issue`.

- Untranslated / empty translation
- Placeholders (`{0}`, `%s`) dropped or added
- HTML tags dropped or added
- **Leading and trailing whitespace** — `_()` strips the message before looking it
  up, so an entry keyed `" Save "` can never be reached from Python. Only `__()`
  in the browser matches verbatim. Padded source strings are reported so they can
  be re-keyed.
- Glossary violations and renderings marked as not to be used
- Latin script left in a translation — **skipped automatically for languages
  written in Latin script**
- Messages that never reach a translation function

## Two coverage figures

`Coverage on Screen` counts anything that renders, including a translation
inherited from the parent language. `Own Coverage` counts only what the locale
genuinely has.

They can differ sharply. In the reference environment `zh-TW` and `zh-HK` read
71.7% on screen and 13.9% of their own: the remainder renders as Simplified
Chinese, inherited from `zh`.

## Fallback

Frappe resolves a variant language to its parent, so `zh-HK` falls back to `zh`
— Simplified Chinese, which is wrong for Hong Kong. `zh-TW` is a sibling, not a
parent, so Frappe will never reach it on its own.

A locale's translation is decided as:

1. translations belonging to the exact language code
2. the fallback locale's ledger
3. whatever Frappe resolves today

A locale is always scanned after its fallback source.

## Install

```bash
bench get-app lifegence-i18n <repo>
bench --site <site> install-app lifegence_i18n
```

Seed the initial locales:

```python
from lifegence_i18n.setup.demo import setup_initial_locales

setup_initial_locales()
```

## Adding a country

Create a Locale Profile with a locale code, country, language and currency. On
save the app creates the Language record if it does not exist and enables it,
enables the Currency, derives whether the language uses Latin script, and takes
the time zone from the country.

```python
from lifegence_i18n.localization.doctype.locale_profile.locale_profile import add_locale

add_locale(country="Korea, Republic of", language="ko", currency="KRW", locale_code="ko-KR")
```

## Continuous measurement

`hooks.py` registers a weekly scan of every enabled locale. Coverage is a number
that moves as upstream development continues, not a one-off report.

## This app's own interface

English is the source language; Japanese lives in `translations/ja.csv`. Under
any other display language the app renders in English rather than Japanese.

An app's translation CSV applies to the whole site: translations are merged
in install order and the last app wins. So a row whose value differs from
what another installed app ships for the same key — frappe's own Japanese,
or a distributed translation app's — would rewrite that label everywhere,
and a test refuses such rows (a row repeating the same value is harmless).
Where the app wants a wording of its own, its source string is its own too:
`Finding Summary`, `Occurrence Count`.

## Not included

- **Writing the translations.** Step 3 of the loop is a person, an agency or a
  machine translation service, working on the CSV the app hands out. The app
  does not call one, and does not judge the quality of what comes back
- Print format (APITemplate) localization

Scan logs and issue findings are written in English as diagnostic data; they are
not translated for display.

## Licence

**GNU Affero General Public License v3.0 or later** — see [LICENSE](LICENSE) for the
licence text and [NOTICE](NOTICE) for the copyright notice.

Copyright (C) 2026 Lush Ltd., Lush Japan G.K. and Lifegence Corporation. The
app was built as a joint development between Lush Japan and Lifegence, and is
released under the same terms as the software it measures. If you run a
modified version as a network service, the AGPL asks you to offer its source to
the people who use it.

Lifegence Corporation maintains the app: it follows the Frappe and ERPNext
release lines and fixes defects.

It imports the Frappe Framework (MIT) and the Python standard library, plus
Playwright (Apache-2.0) as an optional extra for the screen route. It does not
import ERPNext (GPLv3) — ERPNext's translatable strings are measured
through Frappe's public interfaces.

## Documentation

| Document | Audience |
|---|---|
| [Four languages on one site](docs/coverage-across-locales.md) | Anyone deciding whether this is worth running |
| [User manual](docs/user-manual.md) | Operators |
| [Crawling a site from another machine](docs/remote-crawl.md) | Operators running the screen route against a site that cannot host a browser |

Everything else you need to run the app is in this file and in
[CONTRIBUTING](CONTRIBUTING.md).

Each of these has a Japanese translation beside it, named `*.ja.md`. **English
is the original**; where a translation and the English disagree, the English is
what the software does.
