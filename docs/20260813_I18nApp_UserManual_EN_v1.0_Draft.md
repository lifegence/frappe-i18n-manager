# Multilingual Management App — User Manual

**lifegence_i18n v0.1.0 / 13 August 2026 / v1.0 / CONFIDENTIAL**

For Frappe v16 / ERPNext v16

Copyright © 2026 Lifegence Corporation. All rights reserved. This document and the software it describes are proprietary and are licensed, not sold, under a separate written agreement.

---

## 1. About this app

### What it does

**It measures the state of multilingual support continuously and finds the gaps, for a Frappe / ERPNext installation running in several countries, languages and currencies.**

It is not a tool for translating. It is a ledger that **finds what has not been translated, checks the quality of what has, and generates the deliverables**.

### Why it is needed

Frappe ships two things: `Translation` (source and target text) and `Language`. It does not have:

- a ledger of what is to be translated, and the state of each string
- a glossary, or any check against one
- a coverage figure
- detection of damaged placeholders such as `{0}`

In particular, `bench get-untranslated` **only reads source code**. Text that reaches the screen from the database — onboarding steps, workspaces, report names, notification subjects — is never detected by it.

### What it does not do

| Out of scope | Note |
|---|---|
| Translating | Translations are entered by people or an external process |
| Machine translation | A candidate for a later version |
| Crawling rendered screens | Not implemented in v0.1.0 |
| Print format (APITemplate) localization | Requires work on the external service |

**This app does not replace looking at the screen.** Its value is not in removing the need to check, but in **narrowing what needs checking and reducing how much can be missed**.

---

## 2. How Frappe / ERPNext handle translation

This app sits **on top of** Frappe's translation machinery. What it adds only
makes sense against what is already there, so here is the mechanism first.

### 2-1. Where translations live

Three places.

| Location | Form | Belongs to |
|---|---|---|
| PO / MO files | `<app>/locale/<lang>.po` → `sites/assets/locale/<lang>/LC_MESSAGES/<app>.mo` | The app (standard since v15) |
| CSV files | `<app>/translations/<lang>.csv` | The app (older, still read) |
| Translation records | The site database | That site alone |

### 2-2. Order of resolution

When `_("Save")` is called, Frappe assembles one dictionary per language and
looks the string up in it. The layers, in order:

1. the parent language's app translations (each installed app in turn, CSV then MO)
2. that language's app translations
3. the parent language's Translation records
4. **that language's Translation records**
5. country names

**Later layers win.** Translation records come last, so they can always override
what an app ships. That is the mechanism behind Apply to Site.

### 2-3. Falling back to the parent language

A variant such as `zh-TW` loads the parent `zh` first and lays `zh-TW` over it.
The parent is whatever precedes the `-` or `_`.

Useful, but **it does not reach siblings**. Hong Kong's `zh-HK` has `zh`
(Simplified) as its parent, and Traditional `zh-TW` is a sibling, so it is never
consulted. The Fallback Locale field exists to close that gap.

### 2-4. The key is the source string itself

Dictionary keys are the source strings verbatim, or `source:context` where a
context is given.

**The match is exact.** `"Save"` and `"Save "` are different keys. This is the
usual reason a translation exists but never appears, and why this app checks
leading and trailing whitespace.

### 2-5. What becomes translatable

Strings that pass through `_()` in Python or `__()` in JavaScript. In addition,
these are picked up without any code:

- DocType labels, descriptions and Select options
- Page and Report names
- Workflow state names
- Custom field labels

Conversely, **a literal handed straight to `frappe.throw("...")` is never
translated in any language**. That is what the app reports as Not Wrapped.

### 2-6. The standard commands

```bash
bench generate-pot-file --app <app>       # extract source strings into .pot
bench create-po-file <lang> --app <app>   # start a .po for translation
bench update-po-files --app <app>         # fold .pot changes into the .po
bench compile-po-to-mo --app <app>        # build the .mo, which is what is read
bench get-untranslated <lang> out.txt     # list untranslated strings (CSV route)
```

**Both `generate-pot-file` and `get-untranslated` read source code only.** Text
held in the database is outside their reach, which is why this app has a
database route.

### 2-7. How the display language is chosen

`User.language`, then the system-wide language, then `en`. **Different users can
run the same site in different languages.**

### 2-8. Date and number formats

**Formats belong to the Language record** — `date_format`, `time_format`,
`number_format` and `first_day_of_the_week` — and are read from there whenever
something is rendered, falling back to the site default. That is why Apply to
Site writes to the Language record.

**Currency is independent of language.** Each Currency carries its own format and
precision, and amounts are formatted from that. A document in US dollars renders
in the dollar format even on a Japanese screen. **A Locale Profile keeps language
and currency as separate fields because the platform keeps them separate.**

### 2-9. Caching

The per-language dictionary is held in Redis. Changing a translation requires
`frappe.translate.clear_cache()`, which Apply to Site runs for you.

### 2-10. What is missing, and what this app adds

| Concern | Frappe | This app |
|---|---|---|
| Somewhere to put translations | yes, three places | uses them as they are |
| A ledger of what is to be translated | **no** | Translation Entry |
| Untranslated strings in source code | yes | same route, kept as a ledger |
| Untranslated strings in the database | **no** | database route |
| Messages that never reach `_()` | **no** | code message route |
| A glossary and a check against it | **no** | Glossary Term |
| A coverage figure | **no** | two of them |
| Placeholder, HTML and whitespace checks | **no** | Translation Issue |
| Parent-language fallback | yes | uses it as it is |
| Sibling-language fallback | **no** | Fallback Locale |
| Telling inherited from own | **no** | Translation Source (Own / Fallback / Inherited) |

**This app does not replace Frappe's translation machinery.** Translations still
end up in standard Translation records and app files; what this app owns is the
ledger, the checks and the measurement that come *before* that. Uninstall it and
the translations already applied remain on the site.

---

## 3. Layout

Workspace: **`/app/localization`** (listed as *Localization* in the app switcher)

> There is no `/apps/lifegence_i18n` URL. Frappe has no `/apps/<app name>` route at all.

### DocTypes

| DocType | Purpose |
|---|---|
| Locale Profile | Country, language, currency and display formats as one record. **Everything starts here** |
| Translation Entry | Source text, translation, origin and status, one row each |
| Glossary Term | Terms per locale, and renderings that must not be used |
| Translation Scan | One scan run |
| Translation Issue | What was found |
| I18n Settings | Detection settings (single record) |

### This app's own interface

**The app is built the way it asks you to build.**

- Field and button labels are written in **English**
- Japanese is supplied by `lifegence_i18n/translations/ja.csv`
- Under any other display language the app renders **in English**, not in Japanese

To add a language, add `translations/<code>.csv`. Exporting *App Translation CSV* from the ledger produces exactly that format.

> **The shipped keys are chosen deliberately.** An app's translation CSV applies to the whole site, so including a generic word such as `Status` or `Draft` **would rewrite that label everywhere in ERPNext**. 56 keys that frappe or erpnext already translate are left to them. Not overriding a curated core translation is the same principle this app enforces elsewhere.

### On the workspace

- **Number cards** — Ledger Rows / Untranslated Strings / Open Issues
- **Shortcuts** — Locales / Translation Ledger / Issues / Glossary
- **Report** — Localization Coverage

---

## 4. Setting up

### 4-1. I18n Settings

`/app/i18n-settings`

| Field | Meaning | Default |
|---|---|---|
| Source Language | The language translated from | `en` |
| Create Missing Languages | Creates the `Language` record when a locale is saved | on |
| Enable Disabled Currencies | Enables the `Currency` when a locale is saved | on |
| Minimum String Length | Shorter strings are not put in the ledger | 2 |
| Ignore Patterns | Regular expressions, one per line | 5 defaults |
| Terms Allowed in Latin Script | Brand names, units, abbreviations, one per line | Acme, ERPNext, SKU, kg, … |

**Grow the allowed-terms list as you go.** Latin residue reports a lot to begin with, and drops each time a brand name or abbreviation is added.

### 4-2. Creating a locale

`/app/locale-profile/new`

**Four fields are required.**

| Field | Japan | Croatia |
|---|---|---|
| Locale Code | `ja-JP` | `hr-HR` |
| Country | Japan | Croatia |
| Language | ja | hr |
| Currency | JPY | EUR |

The locale code is BCP-47 (`language-COUNTRY`) and becomes the record name.

**On save the app:**

- creates the `Language` record if it is missing, and enables it if it is disabled
- enables the `Currency` if it is disabled
- derives from the language code **whether the language is written in Latin script**
- takes the time zone from the country

#### Display formats

| Field | Note |
|---|---|
| Date Format | Varies by country (Japan `yyyy-mm-dd`, Hong Kong `dd/mm/yyyy`, Croatia `dd.mm.yyyy`) |
| Number Format | **Croatia uses `#.###,##`** — comma for the decimal point, period for grouping, the reverse of Japan |
| Decimal Places | **The yen takes 0** — it has no minor unit |
| First Day of Week | Sunday for Japan, Taiwan and Hong Kong; Monday for Croatia |

#### Fallback locale

Consulted **when this locale has no translation of its own**.

**Set Hong Kong (`zh-HK`) to fall back to Taiwan (`zh-TW`).** Frappe drops to the parent language, `zh` — Simplified Chinese. Hong Kong needs Traditional, and since `zh-TW` is a sibling rather than a parent, **Frappe will never take that route by itself.**

The order of resolution is:

| # | Source | Shown in the ledger as |
|---|---|---|
| 1 | translations belonging to the exact language code | `Own` |
| 2 | the fallback locale's ledger (chained, up to 5 deep) | `Fallback` |
| 3 | whatever Frappe resolves today, including the parent language | `Inherited` |

**Only what the fallback source genuinely holds is passed on.** Most of the Taiwanese ledger is itself inherited Simplified Chinese; forwarding that to Hong Kong would turn inheritance into ownership.

**Scan order matters.** Hong Kong reads the Taiwanese ledger, so Taiwan must be measured first. The scheduled run works this out automatically.

#### What to measure

| Field | Meaning |
|---|---|
| Scan Source Code | Translatable strings in `.py` / `.js` / `.json` |
| Scan Database | Strings that reach the screen but are not in code |
| Detect Messages Without a Translation Function | Literals passed straight to `frappe.throw` |
| Target Apps | **Empty means every app installed on the site** |

**A custom app installed later.** With Target Apps empty it is **measured from the next scan onwards**, with no configuration change.

If Target Apps names specific apps, a new one stays outside them. **That state is listed in every scan log as `NOT MEASURED (N): …`** — so that coverage cannot stay high while an entire application goes untranslated without anyone being told.

> Only apps **installed on the site** (`bench install-app`) can be measured. An app merely present in the bench cannot.

---

## 5. Measuring

Open a locale and press **Run Scan**.

It runs in the background and the page switches to the scan record. The status moves Queued → Running → Completed, and the page refreshes itself on completion.

> For reference: 22,526 strings across 23 installed apps takes about 35 seconds.

### Reading a scan

| Field | Meaning |
|---|---|
| Total / Translated / Untranslated / Coverage | The whole ledger for that locale |
| New Entries | Strings seen for the first time |
| Updated | Strings whose current rendering changed |
| Issues | Findings recorded by this run |
| Breakdown | **App × route.** The most important part |
| Log | Counts per route and elapsed time |

### How the ledger is written

A scan **does not overwrite**.

- Strings seen for the first time are added
- **A row with no translation adopts what Frappe currently resolves** and is marked Approved
- **A row someone has written is left alone**

The ledger therefore starts as a picture of reality rather than as an empty list.

---

## 6. Reading the results

`/app/query-report/Localization Coverage` (*Coverage* on the workspace)

### There are two coverage figures

| Column | Meaning |
|---|---|
| **Coverage on Screen** | Anything that renders. **Includes inheritance from the parent language** |
| **Own Coverage** | Only this locale's own translations (Own + Fallback) |
| Inherited from Parent | The difference |

**They can diverge sharply.**

| Locale | On screen | Own |
|---|---:|---:|
| ja-JP | 88.4% | 88.4% |
| hr-HR | 73.4% | 73.4% |
| zh-TW | **71.7%** | **13.9%** |
| zh-HK | **71.7%** | **13.9%** |

For a Traditional Chinese market, 71.7% does not describe reality: **the other 57.8% renders as Simplified Chinese**. Own Coverage is the figure to judge by.

Japanese and Croatian have no parent language, so the two figures agree.

### Always look at the routes

Measured for Japanese:

| Route | App | Coverage |
|---|---|---:|
| Source code | frappe | 96.5% |
| Source code | erpnext | 98.4% |
| **Database** | **erpnext** | **13.6%** |
| **Database** | **hrms** | **4.4%** |

**Measured with the standard tooling alone, only source code is visible, so it reads as 98% complete.** Nothing that reaches the screen from the database is counted at all.

---

## 7. Working through the issues

`/app/translation-issue` (*Issues* on the workspace)

Filter by locale, type, severity and status.

### Types

| Type | Severity | Meaning | What to do |
|---|---|---|---|
| Untranslated | Medium | No translation | Enter one |
| Empty Translation | Medium | Translation field is blank | Enter one |
| Placeholder Mismatch | High | `{0}` or `%s` dropped or added | **Always fix.** Values will not appear at runtime |
| HTML Mismatch | High | Tags dropped or added | **Always fix.** The layout breaks |
| Glossary Violation | Low | Differs from the glossary | Review, and use a bulk change if warranted |
| Forbidden Term | High | Contains a rendering marked as not to be used | Fix |
| Latin Residue | Low | Latin script left in the translation | Translate it, or add it to the allowed terms |
| Whitespace Mismatch | Medium | Leading or trailing whitespace differs from the source | Match the source |
| Not Wrapped | High | Passed straight to `frappe.throw` | **Needs a source change** |

### On "Not Wrapped"

This says the string is **not missing a translation — it is somewhere no translation file can reach**.

```python
frappe.throw("Invalid Name")  # no translation applies
frappe.throw(_("Invalid Name"))  # a translation applies
```

No amount of translation work fixes it. The application source has to change. An f-string (`f"{x} updated"`) has to become `_("{0} updated").format(x)`.

### On "Whitespace Mismatch"

**Frappe matches source strings exactly.** A string ending in a space is a different key from the same string without it. This is the usual reason a translation exists but never appears.

### On "Latin Residue"

**It is switched off automatically for languages written in Latin script**, since running it against Croatian or German would flag every row. The Locale Profile field *Written in Latin Script* decides.

### Issue status

| Status | Meaning |
|---|---|
| Open | Default |
| Ignored | **This decision survives the next scan** |
| Resolved | Rebuilt by the next scan |

**Issues are derived data.** Every scan rebuilds everything except Ignored. To keep a decision, mark it Ignored.

---

## 8. The glossary

`/app/glossary-term`

| Field | Meaning |
|---|---|
| Locale | Glossaries are per locale |
| Term (Source) | e.g. `Customer` |
| Translated Term | e.g. `得意先` |
| Do Not Translate | Brand names. **Checks that the source term appears unchanged** |
| Match Type | Word (not bounded by letters) or Substring |
| Case Sensitive | On by default |
| Report Violations as Issues | Off keeps the row as reference without checking it |
| Renderings Not to Use | One per line. Reported at High severity when present |

**"Renderings Not to Use" earns its keep.** Decide `Customer → 得意先`, list `顧客` as not to be used, and every inconsistency surfaces.

---

## 9. Entering and fixing translations

### 9-0. The status flow — read this first

```
Untranslated ──type a translation──▶ Draft ──approve──▶ Approved ──Apply to Site──▶ on screen
                     import a review sheet──▶ Reviewed ──┘
```

**Apply to Site writes Approved and Reviewed rows only. Draft rows are not applied.**

Editing a translation on screen leaves the row as Draft. Applying at that point **does not put that translation on screen**. When drafts are outstanding, applying says so with a count:

> Applied to the site
> 12 created / 3 updated
> **5 translations are still Draft and were not applied. Use Actions → Approve Drafts.**

**Actions → Approve Drafts** promotes every draft for the locale, after showing the count.

The Draft stage exists because **a translation someone typed and a translation someone agreed to are different things**. Letting the apply step approve as a side effect would erase that distinction.

### 9-1. One at a time

The working screen is the ledger (`/app/translation-entry`) filtered by locale and status Untranslated. Filtering on Has Issues instead gives the rows that have a translation but a problem with it.

Open a row and edit the translation. The status follows:

- entering a translation moves Untranslated → Draft
- clearing it returns to Untranslated

**To change several at once**, select rows in the list view and use bulk edit for the status. For entering the translations themselves, the next two routes are better.

### 9-2. Loading translations from CSV

The ledger supports Frappe's standard **Data Import**.

1. List view → menu → **Import**
2. Choose Update, and supply a CSV with `ID` and `Translation` columns
3. Imported rows become Draft → **Actions → Approve Drafts**

This is the shortest route when a volume of work goes to an external translator. The IDs come from Export → Review Sheet (CSV).

### 9-3. Adding a string by hand

To manage a string the scan cannot find — wording held in an external service, for instance — create a Translation Entry directly. It needs a locale, source text and translation, and is recorded as Found In: Manual.

**The same locale, source text and context cannot be entered twice.** The error links to the existing row.

### 9-4. Changing a term everywhere

Open the locale, then **Actions → Bulk Term Change**.

1. Enter the current and replacement text, then **Check Impact**
2. **The count and a before/after comparison appear before anything changes** (first 200 rows)
3. Confirm, then **Run Replacement**

**You see how many rows a glossary decision moves before you make it.**

---

## 10. Review round trip

### 10-1. Exporting

Open the locale, then **Export → Review Sheet (CSV)**.

| Column | Contents |
|---|---|
| ID | The ledger row. **Do not edit** |
| App / Found In / Status | Reference |
| Source Text / Context / Translation | Current contents |
| Issues | What has been found |
| **Proposed Change** | **For the reviewer** |
| **Reviewer Comment** | **For the reviewer** |

Written as UTF-8 with a BOM so it opens correctly in Excel. **The header is written in the reviewer's display language.**

### 10-2. Importing

**Import File → Review Sheet (CSV)**, attaching the completed file.

- **Only rows with an entry in the proposal column** are applied, and their status becomes Reviewed
- Blank rows are untouched. **A partially completed sheet is safe to load**
- Rows whose ID does not belong to this locale are reported as skipped, so uploading the wrong sheet is visible
- The proposal column is located by name and, failing that, by position — a sheet returned by a Japanese reviewer loads on an English session

---

## 11. Applying to the site

Open the locale, then **Actions → Apply to Site**.

Two things happen.

1. **The display formats are written to the `Language` record** — date format, number format, first day of week. That is where Frappe reads them
2. **Approved and Reviewed translations become `Translation` records**

Frappe resolves app CSV → app MO → Translation record, and **the last wins**, so this overrides what an app ships.

> **Rows identical to what is already on screen produce no record**, to avoid inflating the site with entries that change nothing.

**A translation in the ledger does not change the screen until this is run.** The two are separate on purpose.

### App translation CSV

**Export → App Translation CSV**, choosing an app, produces `<app>/translations/<lang>.csv` in exactly the form Frappe reads. It can be committed to the application repository as is.

**Rows whose translation equals the source are omitted** — Frappe resolves those to the source anyway, and they only make the diff noisy.

---

## 12. Adding a country

**The initial four are a starting set, not a fixed list.**

Create a Locale Profile with the four values and press Run Scan.

```python
from lifegence_i18n.localization.doctype.locale_profile.locale_profile import add_locale

add_locale(
	country="Korea, Republic of",
	language="ko",
	currency="KRW",
	locale_code="ko-KR",
)
```

**A language with no translations reads 0%.** That is the correct starting point: what has to be translated, and how much of it, is a number on day one.

---

## 13. Continuous measurement

`hooks.py` registers a weekly scan of every enabled locale, in fallback order.

**New strings keep arriving for as long as upstream development continues.** The app assumes the number moves, not that it is measured once.

```python
from lifegence_i18n.localization.doctype.translation_scan.translation_scan import run_scheduled_scans

run_scheduled_scans()
```

---

## 14. Reference

### Ledger status

| Value | Meaning |
|---|---|
| Untranslated | No translation |
| Draft | Translated but unreviewed |
| Reviewed | Passed review |
| Approved | Settled. Existing translations adopted by a scan land here |
| Not Applicable | **Excluded from the totals** |

### Where a string was found

| Value | Meaning |
|---|---|
| Source Code | Found in `.py` / `.js` / `.json` |
| Database | Found in a site record |
| Code Message | Never reaches a translation function |
| Screen | Not used in v0.1.0 |
| Manual | Added by hand |

### Translation source

| Value | Meaning | Counts towards Own Coverage |
|---|---|---|
| Own | Belongs to this language code | yes |
| Fallback | Taken from the fallback locale | yes |
| Inherited | Frappe inherited it from the parent language | no |
| (blank) | No translation | no |

### Scan status

Queued → Running → Completed / Failed. A failure leaves the traceback in the log.

---

## 15. When something looks wrong

| Symptom | Cause and remedy |
|---|---|
| The scan stays Queued | No background worker. Check `bench start` or the worker |
| Coverage looks too high | Check the target apps, and that Scan Database is on |
| A translation was entered but does not appear | ① **is the row still Draft** (section 9-0) ② was Apply to Site run ③ does the **leading and trailing whitespace** match the source |
| The display language was switched but the ledger's translations do not show | **Apply to Site is per locale.** A translation in the ledger alone does not change the screen |
| Hong Kong shows Simplified Chinese | Scan Taiwan, then Hong Kong, then **Apply to Site on Hong Kong** |
| Latin Residue reports a great deal | Add brand names and abbreviations to *Terms Allowed in Latin Script* |
| A locale will not save because the language is missing | *Create Missing Languages* is off in I18n Settings |
| A duplicate row cannot be added | The same locale, source text and context already exists. Edit the existing row |

---

## 16. Stated plainly

- **Latin Residue produces a lot and is not usable as it stands.** It needs the allowed-terms list to be grown. It is a list to review, not a list of errors.
- **It does not replace looking at the screen.** Crawling rendered screens is not implemented in v0.1.0.
- **Only apps installed on the site can be measured.**
- **Scan logs and issue findings are written in English** as diagnostic data. They are not translated for display.

End of document
