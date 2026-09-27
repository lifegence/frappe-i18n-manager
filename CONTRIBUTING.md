# Contributing

Thank you for looking at this. The app measures how much of a Frappe site is
translated and where the gaps are, so most contributions are one of three
kinds: a measurement route that misses something, a rule that reports a false
gap, or support for a language nobody has tried yet.

## Setting up

The app supports **version-15 and version-16** of Frappe, and every change has
to work on both. Two benches are the simplest way to keep that honest.

```bash
bench get-app https://github.com/lifegence/lifegence-i18n
bench --site <site> install-app lifegence_i18n
```

The screen route (route 4) drives a browser and is an optional extra:

```bash
pip install -e "apps/lifegence_i18n[screen]"
playwright install chromium
```

Without it the other three routes run unchanged and the scan log says the
screen route was skipped.

## Running the tests

```bash
bench --site <site> run-tests --app lifegence_i18n
```

They must pass on both supported versions before a pull request. A test that
only passes on one version is the defect, not the version — the app's own
history has two of those, both caught late, and the notes in
`lifegence_i18n/tests/` say what they were.

Tests must not depend on what the bench happens to contain. A site has
workspaces someone made by hand, apps you do not have, and translation files
you did not install. Assert the property, not the count.

## What must never enter this repository

This app is used on live customer systems. The following do not belong in the
repository, its history, its tests, its fixtures, or its logs:

- Any customer's translation data, review sheets, or glossary
- Customer names, site names, host names, app names, or record names
- Screenshots of customer screens
- Credentials of any kind

Use synthetic data. `lifegence_i18n/tests/` shows the shape: a `zz-TEST`
locale, a `zz_app` application, and source strings prefixed `Zzz`.

Nor does a document written for someone else. If a file is marked confidential,
addressed to a person, or numbered against a project plan, it answers to a
contract rather than to whoever finds it here, and it belongs somewhere private.
`scripts/check_publishable.py` refuses both — a name where it does not belong,
and a marking that contradicts the repository it sits in — and runs in CI.

## Translations of the app's own interface

The app ships its own Japanese in `lifegence_i18n/translations/ja.csv`.
Frappe merges every installed app's translations in install order and the last
one wins, so **a row whose value differs from what another installed app ships
for the same source string rewrites that word across the whole site.**

`test_translations_file.py` enforces this. If it refuses a row, the fix is one
of:

- Make the value match what is already in effect, when the wording is not
  yours to change (a generic word like `Importing...`)
- Rename the source string to something specific to this app
  (`Match Type` → `Term Match Type`)
- Add it to `SHARED_SOURCES` with the reason, if the source is a stored value
  and renaming it would mean migrating data

## Adding a language

Nothing in the app is specific to Japanese. A locale profile names a language
and a set of applications; the rules that decide whether a string is
translated look at the script of the target language, not at Japanese. See
"Adding a country" in the README.

One limitation to know before you start: the app checks whether the target
language's **script** is present, not which language it is. It cannot tell
Korean from Japanese, or Russian from Mongolian. This is documented, not a
bug to report.

## Pull requests

- One subject per pull request. A branch that fixes a rule and renames a field
  is two reviews wearing one hat
- Say in the message what the change makes true that was not true before, and
  what you did to see it
- Comments explain *why*, in prose. The code already says what it does
- Keep the diff in the style of its surroundings

## Reporting a problem

Open an issue with the Frappe version, the app versions installed
(`bench version`), the locale, and the scan log line if there is one. For a
wrong measurement, the source string and what the screen showed are worth more
than a description of either.
