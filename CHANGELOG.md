# Changelog

## Unreleased

### Three roles of its own

Until now the only role that could reach the application was System Manager,
which administers the whole site: handing translation work to somebody meant
handing them the site. The application now ships three roles, and nobody holds
one until an operator grants it.

| Role | Covers |
|---|---|
| Localization Manager | Settings, locales, running scans, approving, applying to the site |
| Localization Translator | Writing translations, the glossary, the review sheet, working through findings |
| Localization Viewer | Reading the ledger and the reports |

Two people still need no role at all: a reviewer works from the review sheet
and never opens the application, and the crawl user reads the screens of the
site being measured, not this application's.

**Writing a translation and agreeing to it are now separate acts.** The ledger's
status and not-applicable reason are held at a higher permission level, so a
translator's edit leaves the row Draft however they save it. Approving is the
manager's.

**Permissions are enforced where the work happens.** Frappe runs a whitelisted
document method after checking only that the caller may *read* the document, so
a role given read access to open a form could otherwise press every button on
it — including Apply to Site, which changes what everyone sees. Every
whitelisted call now states who it is for.

**`add_locale()` checked nothing.** It is whitelisted and inserts without
permission checks, so any user with a session could create a locale. It now
requires Localization Manager.

The application's tile on the apps screen was shown to every desk user, and
pressing it was how they found out they had no access. It now follows the roles,
as the buttons on each form do.

Upgrading an existing site creates the three roles and grants none of them.
Nothing changes for a user who holds System Manager.

## 0.1.0 — first public release

Runs a Frappe or ERPNext site in a language Frappe does not ship, across every
application installed on it — frappe, ERPNext, marketplace applications, and
the ones written for that business alone, which nobody upstream will ever
translate. Frappe offers 83 languages and translates 36; ERPNext ships 71.

The
app finds what is untranslated, hands the gaps over as a spreadsheet, takes the
filled-in sheet back, writes the agreed translations to the site and into the
files an application ships, and then checks that they reached the screen. One
step is not the app's — somebody who knows the language writes the translations.
Everything on either side of that is.

### Four ways of measuring

| Route | Reads | Finds |
|---|---|---|
| Source code | `.py`, `.js`, `.json`, `.html` of the target apps | strings passed to a translation function |
| Database | DocType labels, workspaces, reports, print formats, select options | strings stored as records, invisible to `bench get-untranslated` |
| Code message | literals passed to `throw`, `msgprint`, `_` with no wrapper | strings that never reach a translation function at all |
| Screen | the rendered page, through a browser | strings that no other route sees — a heading inside a JSON blob, a label set without `__()` |

The screen route needs Playwright and is an optional extra; where it is not
installed the other three run unchanged. It can crawl a site on another
machine, which is how a Frappe Cloud site is measured.

### Telling three failures apart

A word showing in English has three different causes and three different
fixes. The app reports them separately by comparing the ledger against the
dictionary the site actually serves:

- **Untranslated** — nobody has translated it
- **Not Wrapped** — the site holds a translation and the screen still shows the
  source: a defect in the code that drew it
- **Not Deployed** — the translation exists but has not been shipped

### Classification, exclusions, and checks

Every string is classed as interface text, a role name, or master data, and
only interface text counts towards coverage. Exclusion rules file a naming
series or a bare placeholder as *not applicable* with a reason and the rule
that applied, rather than dropping it silently. Nine checks run over the
ledger, including placeholder and HTML mismatches, glossary violations and
Latin residue.

### Handing work out and taking it back

A review sheet goes out as CSV and comes back the same way; only the proposal
column is read, so a partial review is safe to return. The app also generates
the `translations/<lang>.csv` an application ships, so the result can be
committed to the application's own repository.

### Supported versions

Frappe version-15 and version-16. The test suite runs on both.

### Known limitations

- Writing the translations is step 3 of the loop and happens outside the app,
  on the CSV it hands out. No machine translation service is called
- Translation quality is not assessed. Whether a translation is in the right
  *language* is not checked either: the test is whether the target language's
  script is present, so Korean in a Japanese locale, or Russian in a Mongolian
  one, passes as translated
- The screen route reads the page as it stands. It does not click, so menus and
  dialogs are not measured
- Screens the crawl user may not open are reported as not measured, not as
  translated
