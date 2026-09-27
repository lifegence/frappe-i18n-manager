"""The app's own Japanese file: well-formed, and never differing from what the
other installed apps ship.

An unquoted comma inside a row turns it into three or more columns: Frappe
then either discards it with an Error Log or reads the tail as a
`source:context` key, and the label silently stays English. A row whose
value differs from what another installed app already ships for the same
key would rewrite that label across the whole site (README, "This app's own
interface").
"""

import csv
import re
import unittest

import frappe

CJK = re.compile(r"[぀-ヿ㐀-鿿]")


def rows():
	path = frappe.get_app_path("lifegence_i18n", "translations", "ja.csv")
	with open(path, encoding="utf-8") as fh:
		return list(csv.reader(fh))


# Source strings this app knowingly shares with another installed app, and why
# it cannot simply rename its own out of the way. Everything else that differs
# fails the check below, so a new clash is never silent.
SHARED_SOURCES = {
	# A delivery state stored in Translation Entry.delivery_status and Locale
	# Profile, and named directly in the Localization Delivery report's query.
	# Renaming the source would mean rewriting stored values across a ledger of
	# ~90,000 rows. lifegence_agent (internal, never published) uses the same
	# word for a live session; the two only ever meet on a Lifegence dev bench.
	"Live",
}


class TestJapaneseFile(unittest.TestCase):
	def test_every_row_is_source_and_translation(self):
		for row in rows():
			self.assertEqual(len(row), 2, row)
			self.assertTrue(row[0].strip() and row[1].strip(), row)
			self.assertTrue(
				CJK.search(row[1]) or row[1] == row[0] or not re.search(r"[A-Za-z]{3,}", row[0]),
				f"translation does not look Japanese: {row}",
			)

	def test_keys_are_unique(self):
		keys = [r[0] for r in rows()]
		self.assertEqual(len(keys), len(set(keys)))

	def test_no_translation_that_differs_from_the_apps_already_in_effect(self):
		"""Translations are merged in install order and the last app wins, so a
		row whose value differs from what another installed app ships would
		rewrite that word across the whole site. A row that repeats the same
		value is harmless and allowed. The comparison is against every other
		installed app's Japanese, whatever supplies it on this bench — frappe's
		own file on version-15, a distributed translation app, nothing at all
		on a bare version-16.

		Where nothing supplies Japanese there is nothing to override, so the
		check is skipped rather than failed. The blind spot this replaced was
		different in kind: the old version looked at two hard-coded paths and
		skipped when *those* files were missing, even on a bench where other
		installed apps did supply Japanese, and a clash sat there unseen. Asking
		every installed app closes that. Requiring one of them to answer closes
		nothing, and makes the check impossible to run on a clean version-16
		site — which is what continuous integration builds (PM, 27 September;
		this reverses the instruction of 25 September, which was wrong).

		Two things are not a clash. A row another app leaves untranslated — its
		value is the source string itself — is a gap, not a translation in
		effect: refusing to fill it would stop this app translating anything any
		other app happens to list in English. And a word this app cannot rename
		out of the way is allowed by name in SHARED_SOURCES, with its reason;
		anything not listed still fails, which is how a new clash gets caught
		(PM, 27 September)."""
		from frappe.translate import get_translations_from_apps

		others = [app for app in frappe.get_installed_apps() if app != "lifegence_i18n"]
		in_effect = get_translations_from_apps("ja", apps=others)
		if not in_effect:
			self.skipTest(f"no other installed app supplies Japanese on this bench ({others})")
		differing = sorted(
			f"{key}: ours {ours!r}, theirs {theirs!r}"
			for key, ours in rows()
			if (theirs := in_effect.get(key)) is not None
			and theirs != ours.strip()
			and theirs.strip() != key.strip()  # the other app leaves it in English: a gap, not a translation
			and key not in SHARED_SOURCES
		)
		self.assertEqual(
			differing,
			[],
			"a value that differs from another app's rewrites the site; use an app-specific source string instead, or list it in SHARED_SOURCES with the reason",
		)
