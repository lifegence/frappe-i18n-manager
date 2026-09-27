# Multilingual Management App — Demo Script

For `lifegence_i18n` v0.1.0 / Frappe v16 / `dev.localhost`

Four locales to begin with — Japan, Taiwan, Hong Kong, Croatia. A fifth (Korea) is added during the demo.

Copyright © 2026 Lifegence Corporation. All rights reserved. Confidential.

---

## 0. Starting up

```bash
cd ~/work/frappe-bench
bench start
BROWSER=echo bench browse dev.localhost --user Administrator   # prints a login URL
```

Workspace: **`/app/localization`**

> `/apps/lifegence_i18n` does not exist. Frappe has no `/apps/<app name>` route; `/apps` redirects to `/desk`. The app appears in the app switcher as Localization.

---

## 1. The locales (3 min)

`/app/locale-profile`

| Locale | Country | Language | Currency | Date | Number |
|---|---|---|---|---|---|
| ja-JP | Japan | ja | JPY | yyyy-mm-dd | #,###.## / 0 decimals |
| zh-TW | Taiwan | zh-TW | TWD | yyyy-mm-dd | #,###.## |
| zh-HK | Hong Kong | zh-HK | HKD | dd/mm/yyyy | #,###.## |
| hr-HR | Croatia | hr | EUR | dd.mm.yyyy | **#.###,##** |

**Points to make**

- **Currency and decimals are not decided by language.** The yen has no minor unit, so zero decimals; the euro takes two. That is why they sit on the locale.
- **Croatia's currency is the euro.** It replaced the kuna on 1 January 2023. Choosing a retired currency when adding a country is exactly the sort of mistake a record prevents.
- **Number formats invert between countries.** Croatia uses a comma for the decimal point and a period for grouping.
- **Hong Kong falls back to Taiwan.** Frappe drops `zh-HK` to `zh` — Simplified Chinese. Hong Kong needs Traditional, and `zh-TW` is a sibling rather than a parent, so Frappe will never take that route by itself.

---

## 2. Measurement (5 min)

Open a locale and press **Run Scan**. It runs in the background and refreshes on completion (about 25 seconds for four apps).

`/app/query-report/Localization Coverage` puts every locale side by side.

Measured across all 23 installed apps — 22,526 strings:

| Locale | On screen | Own | Untranslated |
|---|---:|---:|---:|
| ja-JP | 88.4% | 88.4% | 2,607 |
| hr-HR | 73.4% | 73.4% | 6,001 |
| zh-TW | 71.7% | **13.9%** | 6,381 |
| zh-HK | 71.7% | **13.9%** | 6,380 |

**This is the moment for a Chinese-language market.** 71.7% renders, but roughly 13,000 of those strings are inherited Simplified Chinese. As a Traditional Chinese deployment it is at 13.9%. The standard tooling has no such distinction and reports only the first figure.

> Explaining the underlying mechanism first — the three places translations live, the order of resolution, the parent-language fallback, the exact-match key — makes this land faster. Section 2 of the user manual covers it.

**And now the reason the app exists.** The routes disagree completely:

| Route | Japanese coverage |
|---|---:|
| Source code (frappe) | 96.5% |
| Source code (erpnext) | 98.4% |
| **Database (erpnext)** | **13.6%** |
| **Database (hrms)** | **4.4%** |

`bench get-untranslated` sees **only source code**. Measured with it alone the work looks 98% done, while nothing that reaches the screen from the database — onboarding, workspaces, report names, notification subjects — is counted at all.

That is the structure behind an onboarding page staying in English through three rounds of measurement.

---

## 3. Findings (5 min)

`/app/translation-issue`, filtered by locale. For Japanese, 5,312:

| Type | Count | Meaning |
|---|---:|---|
| Untranslated | 2,607 | No translation |
| Latin Residue | 1,644 | Latin script left in the translation |
| Not Wrapped | 468 | **Never reaches a translation function** |
| Glossary Violation | 344 | Differs from the glossary |
| Forbidden Term | 156 | A rendering marked as not to be used |
| Whitespace Mismatch | 91 | Leading or trailing whitespace differs |
| HTML / Placeholder Mismatch | 1 each | A tag or placeholder dropped |

**Worth opening**

- `Role Permission for Page and Report` → `Role Permission for Page andレポート`
  Half translated. The kind of thing only found by eye.
- A `Not Wrapped` finding
  A literal passed straight to `frappe.throw`. **Not a missing translation — a string in a place no translation file can reach.** It needs a source change; no amount of translation work fixes it.
- `Whitespace Mismatch`
  Frappe matches source strings exactly. A string ending in a space is a different key.

**The checks adapt to the language.** Latin Residue is switched off for Croatian, since it is written in Latin script — running it there would flag every row.

---

## 4. Glossary and bulk change (5 min)

`/app/glossary-term`, per locale. For Japanese: `Item → 品目`, `Customer → 得意先` (**not to be used: 顧客**), `Acme → do not translate`.

**Actions → Bulk Term Change**, changing 在庫伝票 to 在庫エントリ:

1. **Check Impact** lists every affected row **before anything changes** (19)
2. **Run Replacement** commits
3. Rescanning shows Glossary Violation falling

**The point.** You see how many rows a glossary decision moves before you make it.

---

## 4-2. Getting Traditional Chinese into Hong Kong (5 min)

**On Frappe alone, Hong Kong renders Simplified.** With no `zh-HK` translations it falls back to the parent `zh`, and `zh-TW` is a sibling that Frappe will never consult.

1. Show that zh-HK falls back to zh-TW
2. Scan **Taiwan first, then Hong Kong** — Hong Kong reads the Taiwanese ledger
3. Show the log: "Fallback : N taken from zh-TW"
4. Open `Item` in the ledger — translation **項目**, currently on screen **物料**
5. **Actions → Apply to Site**
6. Switch the display language to Hong Kong and open the Item list — **項目 / 項目名稱 / 啟用**

**Draw the distinction between steps 4 and 5.** A translation in the ledger and a translation on the screen are different things. Nothing changes until it is applied.

---

## 5. Deliverables (3 min)

From **Export**:

- **Review Sheet (CSV)** — with Proposed Change and Reviewer Comment columns, to send out and take back
- **App Translation CSV** — exactly `<app>/translations/<lang>.csv`, ready to commit to the application repository

**Actions → Apply to Site** writes approved translations as `Translation` records. They sit last in Frappe's resolution order, so they override what an app ships.

---

## 6. Adding a country afterwards (5 min)

**This is the substance.** The four are a starting set, not a fixed list.

`/app/locale-profile/new`, four values:

| Field | Value |
|---|---|
| Locale Code | ko-KR |
| Country | Korea, Republic of |
| Language | ko |
| Currency | KRW |

On save the app creates the Language record if needed and enables it, enables the currency (KRW ships disabled), derives the script, and takes the time zone from the country.

**Run Scan** reports **0% against the same 18,142 strings**. Korean is not shipped, so that is the correct starting point: the scale of the work is a number on day one.

> Hong Kong's `zh-HK` was not a language code Frappe knew. The app creates it. Without that the record cannot be saved at all.

---

## 6-2. The app is itself multilingual (2 min)

Switch the display language from Japanese to Hong Kong and show the same locale screen.

- Japanese: 表示名 / フォールバック先 / 走査を実行
- Hong Kong: `Locale Name` / `Fallback Locale` / `Run Scan`

**English is the source; Japanese comes from `translations/ja.csv`.** Under an unsupported language the source shows through — it never falls back to Japanese.

**The shipped keys are chosen.** Including a generic word such as `Status` or `Draft` would rewrite that label throughout ERPNext, so 56 keys already translated by frappe or erpnext are left to them. **Not overriding a curated core translation** is the same principle the app enforces on everyone else.

---

## 6-3. Apps installed later are covered too (3 min)

**With Target Apps empty, a new app is measured from the next scan onwards.** No configuration change.

Widening this environment from 4 apps to all 23 added **4,376 ledger rows** and showed what had been invisible:

| App | Total | Coverage |
|---|---:|---:|
| clefincode_chat | 506 | 0.2% |
| wiki | 300 | 0.3% |
| lifegence_customization | 92 | 0.0% |

**Naming Target Apps needs care.** An app installed later stays outside the list, so every scan log lists it: `NOT MEASURED (19): …`. Coverage must not stay high while an entire application goes untranslated without anyone being told.

## 7. Continuous measurement

`hooks.py` registers a weekly scan of every enabled locale, in fallback order.

**New strings keep arriving for as long as upstream development continues.** The design assumes the number moves, not that it is measured once.

---

## Not in this version

- **Crawling rendered screens.** Driving a browser to read what is actually painted is not implemented; it remains behind the feasibility gate set out in the proposal.
- **Machine translation.** This is a ledger and a detector, not a translator.
- **Print format (APITemplate) localization.** Requires work on the external service.

## Stated plainly

Latin Residue produces a great deal — 1,644 for Japanese — and is not usable as it stands. It needs brand names, units and abbreviations added to the allowed list as you go. **It is a list to review, not a list of errors.**

Nor does it replace looking at the screen. The value is not in removing the need to check, but in **narrowing what needs checking and reducing how much can be missed**.
