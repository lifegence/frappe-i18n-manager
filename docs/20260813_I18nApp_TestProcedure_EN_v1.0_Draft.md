# Multilingual Management App — Test Procedure

**lifegence_i18n v0.1.0 / 13 August 2026 / v1.0 / CONFIDENTIAL**

Copyright © 2026 Lifegence Corporation. All rights reserved. This document and the software it describes are proprietary and are licensed, not sold, under a separate written agreement.

---

## 0. Before starting

### Environment

| Item | Value |
|---|---|
| Frappe / ERPNext | v16 |
| App | lifegence_i18n v0.1.0 |
| Environment | |
| Date | |
| Tester | |

### Starting up

```bash
cd ~/work/frappe-bench
bench start
BROWSER=echo bench browse <site> --user Administrator   # prints a login URL
```

**A background worker must be running.** Scans are asynchronous; without a worker they stay Queued.

### Reference figures

Measured across all 23 installed apps. **These vary by environment.** Use them as a guide except where a test asks for an exact value.

| Locale | Total | Coverage on Screen | Own Coverage | Untranslated |
|---|---:|---:|---:|---:|
| ja-JP | 22,526 | 88.4% | 88.4% | 2,607 |
| hr-HR | 22,526 | 73.4% | 73.4% | 6,001 |
| zh-TW | 22,526 | 71.7% | **13.9%** | 6,381 |
| zh-HK | 22,526 | 71.7% | **13.9%** | 6,380 |
| ko-KR | 22,526 | 0.0% | 0.0% | 22,526 |

**The gap in the Chinese locales is not a defect.** It is the difference between counting a parent-language translation as translated and not counting it.

### Recording results

Enter **OK / NG** under Result, and describe anything that fails under Notes.

---

## A. Installation

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| A-1 | `bench --site <site> list-apps` | `lifegence_i18n` is listed | | |
| A-2 | Open `/app/localization` | The Localization workspace appears | | |
| A-3 | Look at the number cards | Ledger Rows / Untranslated Strings / Open Issues | | |
| A-4 | Open `/app/i18n-settings` | Source Language is `en`; ignore patterns and allowed terms have defaults | | |
| A-5 | Open the app switcher | Localization is listed | | |

> If A-5 fails, check the `add_to_apps_screen` hook and `bench build --app lifegence_i18n`.
>
> **`/apps/lifegence_i18n` returns 404.** That is correct — Frappe has no `/apps/<app name>` route.

---

## B. Creating locales

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| B-1 | Create a locale: `ja-JP` / Japan / ja / JPY | Saves. The record name is `ja-JP` | | |
| B-2 | Set Decimal Places to `0` and save | Saves (correct for the yen, which has no minor unit) | | |
| B-3 | Create `zh-HK` / Hong Kong / **zh-HK** / HKD | Saves, with **"Created language zh-HK"** | | |
| B-4 | Check `Language` for `zh-HK` | Exists, enabled, `based_on` is `zh` | | |
| B-5 | Check `Currency` for HKD | Enabled (disabled by default) | | |
| B-6 | Create `hr-HR` / Croatia / hr / **EUR** | Saves, and **Written in Latin Script turns on by itself** | | |
| B-7 | Open `ja-JP` | Written in Latin Script is **off** | | |
| B-8 | Check the time zone on `ja-JP` | `Asia/Tokyo`, filled in automatically | | |
| B-9 | Set the fallback locale on `zh-HK` to `zh-TW` | Saves | | |
| B-10 | Set any locale's fallback to **itself** | **Error**: "A locale cannot fall back to itself" | | |

> **B-3 matters most.** `zh-HK` is not a stock Language code, and link validation would normally reject the record. The app creates the Language first.

---

## C. Scanning

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| C-1 | Open `ja-JP` and press Run Scan | Moves to the scan record, status Queued | | |
| C-2 | Wait | Status becomes Running, then Completed, refreshing by itself | | |
| C-3 | Read the log | Counts for all three routes | | |
| C-4 | Read the results | Total, translated, untranslated, coverage, new, updated, issues | | |
| C-5 | Read the breakdown | App × route rows, with coverage differing by route | | |
| C-6 | Return to the locale | Coverage, untranslated, open issues and last scanned are updated | | |
| C-7 | The dashboard table | Up to 10 apps, most untranslated first | | |
| C-8 | Run the scan **again** | **New Entries is 0** on an unchanged environment | | |
| C-9 | Compare totals | C-8 total **equals** C-4 total | | |

> **C-8 and C-9 test idempotence.** If they diverge, suspect Frappe's `frappe.flags.scanned_files`, which suppresses re-reading a file within a process. The app resets it before every scan.

### Target apps

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| C-10 | Name a single target app and scan | The source-code rows cover only that app | | |
| C-11 | Clear the target apps and scan | Every installed app is measured | | |
| C-12 | Reopen the locale after C-10 | **The configured rows are still there** — a scan updates counts, it does not replace the list | | |
| C-13 | Read the scan log while C-10 is in force | **`NOT MEASURED (N): …`**, naming every installed app outside the list | | |
| C-14 | Clear Target Apps and scan | **No** `NOT MEASURED` line; every installed app is covered | | |
| C-15 | Install a new custom app and scan with Target Apps empty | **It appears in the breakdown**, with no configuration change | | |

> **C-13 is the point.** With Target Apps named, an app installed later drops out of measurement silently — coverage stays high while an entire application goes untranslated. Every scan therefore lists what it did not measure.

> The database route covers the whole site. Records without a module (Role, UOM and so on) are grouped as `site` regardless of the app filter.

---

## C-2. Fallback (Chinese locales)

**Register both zh-TW and zh-HK, and set zh-HK to fall back to zh-TW, before starting.**

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| C2-1 | Call `scan_order()` with every locale | **zh-TW comes before zh-HK** | | |
| C2-2 | Scan zh-TW, then zh-HK | Both complete | | |
| C2-3 | Read the zh-HK log | "Fallback : N taken from zh-TW" | | |
| C2-4 | Find `Item` in the zh-HK ledger | Translation is **項目** (Traditional); currently on screen is **物料** (Simplified) | | |
| C2-5 | The Translation Source column | Split across `Own` / `Fallback` / `Inherited` | | |
| C2-6 | Apply to Site on zh-HK | Several thousand records created | | |
| C2-7 | Switch the display language to zh-HK and open the Item list | Headings read **項目 / 項目名稱 / 啟用** (Traditional) | | |
| C2-8 | Switch the display language **before** applying | **Still Simplified** — a ledger entry alone does not change the screen. This is correct | | |

> **C2-8 must be verified.** The ledger and the running site are separate; nothing changes until Apply to Site.

---

## C-3. The app's own interface

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| C3-1 | Open a locale with the display language set to Japanese | Labels in Japanese (表示名 / フォールバック先 / 測定対象) | | |
| C3-2 | Switch to zh-HK and open the same screen | **English** (`Locale Name` / `Fallback Locale` / `Run Scan`). **Not Japanese** | | |
| C3-3 | Open a standard ERPNext screen in Japanese | `ステータス`, `下書き` and so on are **unchanged** by installing this app | | |
| C3-4 | Count the rows in `translations/ja.csv` | About 134. **Does not contain** generic words such as `Status`, `Draft`, `Total` | | |

> **C3-3 matters.** An app's translation CSV applies site-wide. Generic words are deliberately not shipped, so that installing this app cannot change ERPNext's own wording.

---

## D. Coverage report

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| D-1 | Open `/app/query-report/Localization Coverage` | Locale × app × route | | |
| D-2 | Compare the routes | Source code and database differ **sharply** for the same app | | |
| D-3 | Against the reference environment | erpnext source code ~98.4%, database ~13.6% | | |
| D-4 | Compare Coverage on Screen with Own Coverage | Japanese and Croatian **agree** | | |
| D-5 | Compare them for zh-TW / zh-HK | **71.7% on screen against 13.9% own** | | |
| D-6 | The Inherited from Parent column | About 13,000 for zh-TW / zh-HK | | |

> **D-5 is what a Chinese-language rollout is judged on.** Coverage on screen suggests it is nearly ready; most of the interface is in the wrong script.
>
> **D-2 is why the app exists.** `bench get-untranslated` reads only source code, so the database route is invisible to the standard tooling.

---

## E. Issues

### Types present

Filter `/app/translation-issue` by locale and check the counts by type.

| # | Type | Expected | Result | Notes |
|---|---|---|---|---|
| E-1 | Untranslated | Roughly matches the untranslated count | | |
| E-2 | Glossary Violation | At least one, given a glossary | | |
| E-3 | Forbidden Term | At least one, given renderings not to use | | |
| E-4 | Not Wrapped | At least one, at High severity | | |
| E-5 | Whitespace Mismatch | Present where applicable | | |

### E-6 Placeholder mismatch, introduced deliberately

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| E-6-1 | Open a ledger row whose source contains `{0}` | The translation contains `{0}` too | | |
| E-6-2 | Delete `{0}` from the translation and save | Saves | | |
| E-6-3 | Run a scan | **Placeholder Mismatch** increases by one, at High severity | | |
| E-6-4 | Read the finding | "missing from translation: {0}" | | |
| E-6-5 | Restore the translation and scan | The finding disappears | | |

### E-7 Latin residue by language

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| E-7-1 | Filter ja-JP by Latin Residue | Findings present | | |
| E-7-2 | Filter hr-HR by Latin Residue | **Zero** — Croatian is written in Latin script | | |

### E-8 Ignored survives

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| E-8-1 | Set an issue to Ignored and save | Saves | | |
| E-8-2 | Run a scan | **That issue is still there**; other open issues are rebuilt | | |

> Issues are derived data. Every scan deletes and rebuilds everything except Ignored, so only human decisions persist.

---

## F. Glossary and bulk change

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| F-1 | Open `/app/glossary-term` | Terms listed per locale | | |
| F-2 | Actions → Bulk Term Change | The dialog opens | | |
| F-3 | Enter both values and press Check Impact | **The count** and a before/after table (first 200) | | |
| F-4 | Inspect the ledger at this point | **Nothing has changed yet** | | |
| F-5 | Run Replacement | "Changed N rows" | | |
| F-6 | Inspect the ledger | Translations have changed | | |
| F-7 | Run a scan | Glossary Violation has **fallen** | | |

> **F-4 is the point.** You see how many rows a glossary decision moves before you make it.

---

## G. Export and import

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| G-1 | Export → Review Sheet (CSV) | `<locale>_review.csv` downloads | | |
| G-2 | Open it in Excel | **No mojibake** (UTF-8 with BOM) | | |
| G-3 | Check the columns | ID / App / Found In / Status / Source Text / Context / Translation / Issues / **Proposed Change** / **Reviewer Comment** | | |
| G-4 | Fill in Proposed Change on two rows | — | | |
| G-5 | Import File → Review Sheet (CSV) | "Applied 2 / skipped 0" | | |
| G-6 | Check the ledger | Those two rows changed, status **Reviewed** | | |
| G-7 | Check the rows left blank | **Unchanged** | | |
| G-8 | Import a sheet from another locale | Reported as skipped, so the mistake is visible | | |
| G-9 | Export a sheet in Japanese, import it on an English session | **Loads** — the proposal column is found by name or position | | |
| G-10 | Export → App Translation CSV | `<app>_<lang>.csv` downloads | | |
| G-11 | Inspect it | Three columns. **No row whose translation equals its source** | | |

---

## G-2. Entering and approving translations

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| G2-1 | Open an untranslated row, enter a translation, save | The status becomes **Draft** | | |
| G2-2 | Apply to Site in that state | Warns **"N translations are still Draft and were not applied"** (orange) | | |
| G2-3 | Check the `Translation` records | **That translation was not created** | | |
| G2-4 | Actions → Approve Drafts | Confirmation with a count, then "Approved N" | | |
| G2-5 | Check the status | Approved | | |
| G2-6 | Apply to Site again | No warning. **The `Translation` record exists** | | |
| G2-7 | Approve Drafts with none outstanding | "No drafts to approve" | | |
| G2-8 | Create a Translation Entry with locale, source text and translation | Saves, recorded as Found In: Manual | | |
| G2-9 | Data Import a CSV of `ID` and `Translation` in Update mode | Imports, rows become Draft | | |

> **G2-2 and G2-3 are the point.** Entering a translation does not put it on screen. This used to fail silently; the count is now reported.

## H. Applying to the site

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| H-1 | Actions → Apply to Site | A confirmation appears | | |
| H-2 | Confirm | "N created / M updated" | | |
| H-3 | Open the `Language` record | Date format, number format and first day of week **match the locale** | | |
| H-4 | Filter `/app/translation` by language | Records have been created | | |
| H-5 | Inspect them | **None duplicate what is already on screen** — differences only | | |
| H-6 | Switch the display language and open a real screen | The changed wording appears | | |

> Frappe resolves app CSV → app MO → Translation record, and the last wins, so this overrides what an app ships.

---

## I. Adding a country afterwards

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| I-1 | Create `ko-KR` / Korea, Republic of / ko / KRW | Saves | | |
| I-2 | Check `Language` for `ko` | Enabled | | |
| I-3 | Check `Currency` for KRW | Enabled | | |
| I-4 | Run a scan | Completes | | |
| I-5 | Read the results | **Same total as the other locales, 0% coverage, untranslated equals total** | | |
| I-6 | The coverage report | `ko-KR` rows, all zero | | |

> **I-5 is the correct outcome.** Korean translations are not shipped, so the scale of the work is a number on day one.

---

## J. Scheduled runs

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| J-1 | Call `run_scheduled_scans()` | One scan per enabled locale | | |
| J-2 | Wait | All complete | | |
| J-3 | Disable a locale and repeat | **No scan is created for it** | | |
| J-4 | Check the order | A locale is scanned **after** its fallback source | | |

```python
from lifegence_i18n.localization.doctype.translation_scan.translation_scan import run_scheduled_scans

run_scheduled_scans()
```

---

## K. Error handling

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| K-1 | Add a ledger row duplicating an existing locale, source text and context | **Error** naming the existing row, with a link | | |
| K-2 | Set status to Approved with no translation | The status returns to Untranslated | | |
| K-3 | Enter a translation leaving status Untranslated | The status becomes Draft | | |
| K-4 | Turn off Create Missing Languages, then create a locale for an unknown language | **Error**: "Language xx is not registered" | | |
| K-5 | Export App Translation CSV for a locale with no translations | **Error**: "There is nothing to export" — no empty file | | |
| K-6 | Run a scan with the worker stopped | Stays Queued (expected) | | |

---

## L. Known limitations

Not defects.

| # | Item |
|---|---|
| L-1 | **Crawling rendered screens is not implemented.** |
| L-2 | **Latin Residue produces a great deal.** It needs the allowed-terms list to be grown. It is a list to review, not a list of errors |
| L-3 | Only apps installed on the site can be measured |
| L-4 | The database route reads a defined set of DocTypes and fields. It is not exhaustive |
| L-5 | `/apps/lifegence_i18n` returns 404. Frappe has no such route |
| L-6 | Machine translation and print format localization are out of scope |
| L-7 | **A ledger translation does not reach the screen until Apply to Site is run**, per locale |
| L-8 | The app's own interface is **sourced in English**. Under a display language with no `translations/<code>.csv` it renders in English, which is correct |
| L-9 | Scan logs and issue findings are written in English as diagnostic data, and are not translated for display |

---

## Overall

| Item | |
|---|---|
| Completed on | |
| Verdict (pass / pass with conditions / fail) | |
| Unresolved failures | |
| Notes | |

End of document
