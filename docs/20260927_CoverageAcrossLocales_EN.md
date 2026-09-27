# Four languages on one site

A translation file that looks finished is not the same as a site that is
translated. This is one measurement of four languages on a single Frappe
version-15 site, taken on 27 September 2026, and what it says about reading
translation files to judge how far a language has got.

## What was measured

| | |
|---|---|
| Site | one Frappe version-15 site, seven applications installed |
| Versions | frappe 15.121.0, erpnext 15.121.3 |
| Locales | German, Japanese, Korean, Mongolian |
| Target strings | 15,928 — interface text only, after exclusions |
| Routes | source code, database, code messages (the screen route was run separately) |
| Tool | `lifegence_i18n` 0.1.0, one scan per locale |

The 15,928 strings are 6,050 from frappe, 8,629 from erpnext, 988 from five
applications written for this site, and 261 held only in the site's own
database. Role names and master data are classed separately and are not in the
figure. Strings ruled out by an exclusion rule — naming series, bare
placeholders — are not in it either.

## The result

| Locale | Overall | frappe + erpnext | Custom apps | Untranslated | of those, found only in the database |
|---|---:|---:|---:|---:|---:|
| German | 87.0% | 93.0% | 1.0% | 2,073 | 113 |
| Japanese | 94.7% | 94.6% | 97.9% | 843 | 37 |
| Korean | 53.9% | 58.1% | 1.2% | 7,350 | 306 |
| Mongolian | 37.7% | 40.6% | 0.0% | 9,931 | 297 |

Same site, same strings, same moment. The only difference is the language.

## Reading the files gives the wrong answer — in both directions

Frappe version-15 ships a `.po` file for each of 36 languages. Every one of
them lists the same 6,292 source strings, because a `.po` file enumerates the
strings whether or not anyone has translated them. Counting lines therefore
tells you nothing. Counting *filled* entries tells you something, but not what
you would expect:

| Language | frappe `locale/*.po` filled | erpnext `translations/*.csv` | Measured on the site (frappe + erpnext) |
|---|---:|---:|---:|
| German | 6,152 of 6,292 (97.8%) | 12,089 rows | 93.0% |
| Mongolian | **6,285 of 6,292 (99.9%)** | **no file at all** | **40.6%** |
| Korean | **27 of 6,292 (0.4%)** | 8,744 rows | **58.1%** |

Mongolian has the most complete frappe file of any language measured here —
99.9% — and the lowest coverage on the site, because erpnext ships no
Mongolian at all. Korean has an essentially empty frappe file — 27 entries —
and still reaches 58.1%, because erpnext's Korean file is full.

Judge Mongolian by frappe and you will call it finished. Judge Korean by
frappe and you will call it untranslated. Both conclusions are wrong, and they
are wrong in opposite directions. Only measuring the site answers the
question.

## Three more things the numbers say

**The best-resourced language still has holes.** German is the most complete of
the four and still leaves 1,024 strings untranslated in frappe and erpnext
alone.

**Some gaps are invisible to the standard tool.** Between 37 and 306 strings
per language are held in the database — DocType labels, workspace headings,
report names, select options — and never appear in source code. `bench
get-untranslated` reads source code, so nothing in that column can be found
with it.

**Applications written for one site are translated by nobody.** The five
applications here contribute 988 strings. Japanese reaches 97.9% of them
because someone was paid to do the work. German reaches 1.0%, Korean 1.2%,
Mongolian 0.0%. No community will translate an application it cannot see.

## Reproducing this

On a site with the app installed:

```bash
bench --site <site> execute lifegence_i18n.setup.demo.install   # optional sample locales
# then, for each locale, open /app/locale-profile/<locale> and press Run Scan
```

The figures above are what the Locale Profile list then shows in its Coverage
column, and what `Localization Coverage` breaks down by string class. Nothing
here was computed by hand.

## What this measurement does not tell you

- **Nothing about quality.** A string counts as translated when a translation
  exists. Whether it is a *good* translation, or even in the right language, is
  not checked (see the limitations in the README).
- **Nothing about screens not visited.** These figures come from the source,
  database and code-message routes. The screen route was run separately and
  found four more strings that none of the three could see.
- **One site.** Another site with different applications would give different
  numbers. The point is the method, not the four percentages.

The five site-specific applications are counted but not named. They belong to
the organisation that commissioned this work, and nothing about them is needed
to follow the argument.
