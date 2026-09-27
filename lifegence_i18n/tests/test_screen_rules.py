"""The screen route's judgement, exercised without a browser.

Every case here is a false positive or a miss that turned up while the route
was being validated against a real site (see docs/ for the log). The rules are
kept honest by the examples that broke them.
"""

import unittest

from lifegence_i18n.scanner.screen import (
	LEADING_COUNT,
	Ledger,
	fragments,
	label_part,
	normalise,
	strip_timezone,
)


def ledger(rows, allowed=()):
	rows = [
		{
			"name": f"row{i}",
			"source_text": src,
			"translated_text": tr,
			"status": "Untranslated" if not tr else "Approved",
			"origin": "Source Code",
			"app": "frappe",
		}
		for i, (src, tr) in enumerate(rows)
	]
	return Ledger(rows, set(allowed))


JA = [
	("Save", "保存"),
	("Item", "アイテム"),
	("Show {0} List", ""),
	("You haven't created a {0} yet", ""),
	("Add {0}", ""),
	("New {0}", ""),
	("Asset", ""),
	("GMail", "Gmail"),
	("Filters", "フィルター"),
	("{0}", ""),
	("{0} {1}", ""),
	("Search or type a command ({0})", ""),
	("Learn about {0}", ""),
	("Quick Access", ""),
	("Wiki Page Revision", ""),
	("Date after which this file should be considered stale. Expires timestamp is converted to UTC.", ""),
]


class TestCandidateFilter(unittest.TestCase):
	def setUp(self):
		self.ledger = ledger(JA, allowed=["Acme", "POS", "ERPNext"])

	def test_japanese_on_screen_is_translated(self):
		self.assertFalse(self.ledger.is_candidate("POS設定", False))
		self.assertFalse(self.ledger.is_candidate("ERPNextの設定", False))

	def test_untranslated_template_around_translated_value_is_reported(self):
		# the value was translated, the template was not
		self.assertTrue(self.ledger.is_candidate("Show アイテム List", False))

	def test_brands_and_units_are_not_gaps(self):
		self.assertFalse(self.ledger.is_candidate("POS", False))
		self.assertFalse(self.ledger.is_candidate("Acme ERPNext", False))

	def test_numbers_codes_and_paths_are_noise(self):
		for text in ("1,234.00", "¥ 184,293.00 Cr", "Asia/Tokyo", "AB", "---", "Ctrl+E", "⌘ + G"):
			self.assertFalse(self.ledger.is_candidate(text, False), text)

	def test_slash_labels_are_not_mistaken_for_paths(self):
		for text in ("Yes/No", "In/Out"):
			self.assertTrue(self.ledger.is_candidate(text, False), text)

	def test_half_width_kana_counts_as_japanese(self):
		self.assertFalse(self.ledger.is_candidate("ｶﾅ Save", False))

	def test_truncated_widget_text_is_skipped(self):
		self.assertFalse(self.ledger.is_candidate("Finished Goods - ...", False))

	def test_a_rendered_translation_is_not_a_gap(self):
		# "GMail" ships as "Gmail": what is on screen is the translation itself
		self.assertFalse(self.ledger.is_candidate("Gmail", False))

	def test_plain_english_is_a_candidate(self):
		self.assertTrue(self.ledger.is_candidate("Quick Access", False))
		self.assertTrue(self.ledger.is_candidate("Customer naming and default values", False))


class TestLatinScriptTarget(unittest.TestCase):
	"""Croatian: 'contains Latin letters' says nothing, so vocabulary decides."""

	def setUp(self):
		self.ledger = ledger(
			[("Save", "Spremi"), ("Customer", "Kupac"), ("Item", "Artikl"), ("Timesheets", "")]
		)

	def test_diacritics_belong_to_the_target_language(self):
		self.assertFalse(self.ledger.is_candidate("Srž", True))

	def test_target_vocabulary_is_not_english(self):
		self.assertFalse(self.ledger.is_candidate("Spremi", True))

	def test_source_vocabulary_is_english(self):
		self.assertTrue(self.ledger.is_candidate("Save Item", True))


class TestLedgerMatching(unittest.TestCase):
	def setUp(self):
		self.ledger = ledger(JA)

	def test_exact_and_normalised(self):
		self.assertEqual(self.ledger.find("Save")["source_text"], "Save")
		self.assertEqual(self.ledger.find("  Save ")["source_text"], "Save")
		self.assertEqual(self.ledger.find("Quick&nbsp;Access")["source_text"], "Quick Access")

	def test_values_put_back_into_placeholders(self):
		self.assertEqual(
			self.ledger.find("Search or type a command (⌘ + G)")["source_text"],
			"Search or type a command ({0})",
		)

	def test_template_with_literal_text(self):
		self.assertEqual(
			self.ledger.find("You haven't created a Asset Capitalization yet")["source_text"],
			"You haven't created a {0} yet",
		)

	def test_placeholder_only_templates_never_match(self):
		# "{0}" and "{0} {1}" would otherwise swallow every string on every screen
		self.assertIsNone(self.ledger.find("Customer naming and default values"))

	def test_short_template_needs_a_known_value_inside(self):
		self.assertEqual(self.ledger.find("Add Asset")["source_text"], "Add {0}")  # "Asset" is a ledger row
		self.assertIsNone(self.ledger.find("Add a Filter"))  # "a Filter" is not
		self.ledger.data = {"Bath Bomb Sea Salt"}
		self.assertEqual(self.ledger.find("New Bath Bomb Sea Salt")["source_text"], "New {0}")  # a page value

	def test_leading_symbols_are_ignored(self):
		self.assertEqual(self.ledger.find("+ Save")["source_text"], "Save")

	def test_a_count_rendered_beside_a_label_still_finds_the_label(self):
		# the form dashboard puts the number of linked records next to the
		# doctype's name, on either side of it depending on the version
		self.assertEqual(self.ledger.find("1 Wiki Page Revision")["source_text"], "Wiki Page Revision")
		self.assertEqual(self.ledger.find("Wiki Page Revision 1")["source_text"], "Wiki Page Revision")
		self.assertIsNone(self.ledger.find("1 Customer naming and default values"))


DESCRIPTION = (
	"# Fixed Asset Accounts\n\nWith the company, a host of fixed asset accounts are "
	"pre-configured.\n - Fixed asset accounts (Asset account)\n - Accumulated depreciation\n"
)


class TestRenderedFragments(unittest.TestCase):
	"""A description is markdown and an HTML field is markup: Frappe translates
	each as one string and the browser shows it as several. The pieces are not
	new strings, and none of them can be translated on its own."""

	def test_the_lines_of_a_description_are_indexed(self):
		self.assertEqual(
			list(fragments(DESCRIPTION)),
			[
				"Fixed Asset Accounts",
				"With the company, a host of fixed asset accounts are pre-configured.",
				"Fixed asset accounts (Asset account)",
				"Accumulated depreciation",
			],
		)

	def test_markup_is_split_on_its_blocks(self):
		self.assertEqual(
			list(fragments("<h4>Weekly Summary</h4><p>Totals refresh every Monday</p>")),
			["Weekly Summary", "Totals refresh every Monday"],
		)

	def test_a_string_of_one_line_has_no_fragments(self):
		self.assertEqual(list(fragments("Please pick a warehouse first")), [])

	def test_short_pieces_are_not_indexed(self):
		# "Save" inside a description must not swallow the button called Save
		self.assertEqual(list(fragments("# Save\n\nPress Save to keep it.")), ["Press Save to keep it."])

	def test_a_line_on_screen_finds_the_description_it_came_from(self):
		led = ledger([*JA, (DESCRIPTION, "")])
		self.assertEqual(led.find("Accumulated depreciation")["source_text"], DESCRIPTION)
		self.assertEqual(led.find("Fixed asset accounts (Asset account)")["source_text"], DESCRIPTION)

	def test_markup_around_one_label_is_not_a_composite(self):
		# "<b>Continue to checkout</b>" is that label, not a row with pieces
		led = ledger([*JA, ("<b>Continue to checkout</b>", "")])
		self.assertIsNone(led.fragments.get("Continue to checkout"))

	def test_a_short_heading_still_makes_the_rest_a_piece(self):
		# "<h3>HR Settings</h3>\n\nHr Settings consists of ..." — the heading is
		# too short to index, and the paragraph is still part of this row
		row = ("<h3>HR Settings</h3>\n\nHr Settings consists of major settings related to leave.", "")
		self.assertEqual(
			list(fragments(row[0])), ["Hr Settings consists of major settings related to leave."]
		)
		led = ledger([*JA, row])
		self.assertEqual(
			led.find("Hr Settings consists of major settings related to leave.")["source_text"], row[0]
		)

	def test_a_description_with_markup_is_found_as_the_line_it_becomes(self):
		# frappe stores "… series. <br><br>Warning: …" and the browser shows it
		# as one line; the string is the row, not the line
		row = ("Change the number of an existing series. <br><br>Warning: this can stop documents.", "")
		led = ledger([*JA, row])
		self.assertEqual(
			led.find("Change the number of an existing series. Warning: this can stop documents.")[
				"source_text"
			],
			row[0],
		)

	def test_an_inline_tag_leaves_no_space_where_it_stood(self):
		# "(eg <code>https://frappe.io</code>)" is "(eg https://frappe.io)" on
		# screen, with no space before the bracket
		row = (
			"New line separated list of allowed URLs (eg <code>https://frappe.io</code>), or <code>*</code> "
			"to accept all.\n<br>\nPublic clients are restricted by default.",
			"",
		)
		led = ledger([*JA, row])
		self.assertEqual(
			led.find(
				"New line separated list of allowed URLs (eg https://frappe.io), or * to accept all. "
				"Public clients are restricted by default."
			)["source_text"],
			row[0],
		)

	def test_a_string_that_only_shares_words_is_still_a_gap(self):
		led = ledger([*JA, (DESCRIPTION, "")])
		self.assertIsNone(led.find("Fixed asset accounts are missing"))


class TestTimeZoneSuffix(unittest.TestCase):
	"""Frappe appends the site's time zone to every Datetime field's
	description, so the sentence on screen is the ledger's sentence plus it."""

	def test_a_trailing_time_zone_is_not_part_of_the_string(self):
		described = "Expires timestamp is converted to UTC."
		self.assertEqual(strip_timezone(described + " Asia/Tokyo"), described)
		self.assertEqual(strip_timezone(described + " America/Argentina/Buenos_Aires"), described)

	def test_anything_that_is_not_a_time_zone_is_left_alone(self):
		for text in ("Save and/or Submit", "Item Code/Name", "Delivery Note", "and/or"):
			self.assertEqual(strip_timezone(text), text)

	def test_the_ledger_finds_the_row_once_the_zone_is_gone(self):
		row = ledger(JA).find(
			strip_timezone(
				"Date after which this file should be considered stale. "
				"Expires timestamp is converted to UTC. Asia/Tokyo"
			)
		)
		self.assertIsNotNone(row)


class TestLabelValue(unittest.TestCase):
	def test_hash_names_and_page_values_are_split_off(self):
		self.assertEqual(label_part("ID: 0ru39kd5oj", set()), "ID")
		self.assertEqual(label_part("ID: abcdefghij", set()), "ID")  # a hash without digits is still a hash
		self.assertEqual(label_part("Company: Acme Trading", {"Acme Trading"}), "Company")
		self.assertEqual(label_part("Note: keep this", set()), "Note: keep this")
		self.assertEqual(label_part("Status: OK", set()), "Status: OK")  # a short value is not a hash
		self.assertEqual(label_part("Total: 1,234.00", set()), "Total")

	def test_leading_count_becomes_a_placeholder(self):
		self.assertEqual(LEADING_COUNT.sub("{0} ", "4 To Receive"), "{0} To Receive")
		self.assertEqual(LEADING_COUNT.sub("{0} ", "exchange.com/2021-08-01"), "exchange.com/2021-08-01")
		self.assertEqual(LEADING_COUNT.sub("{0} ", "There are 3 variables"), "There are 3 variables")

	def test_a_count_in_front_of_a_phrase_is_put_back(self):
		# erpnext draws "0/4 steps completed" as a count and __("steps completed")
		for text, stored in (
			("0/4 steps completed", "{0} steps completed"),
			("0% completed", "{0} completed"),
			("0 % since yesterday", "{0} since yesterday"),
			("12,000 Items", "{0} Items"),
		):
			self.assertEqual(LEADING_COUNT.sub("{0} ", text), stored, text)
		# and a date or a version is not a count in front of a phrase
		for text in ("2021-08-01 release", "1.2.3", "3/4"):
			self.assertEqual(LEADING_COUNT.sub("{0} ", text), text, text)

	def test_the_phrase_alone_is_found_in_the_ledger(self):
		led = ledger([*JA, ("steps completed", "")])
		self.assertEqual(led.find("0/4 steps completed")["source_text"], "steps completed")

	def test_normalise(self):
		self.assertEqual(
			normalise("System will do <br>\nan implicit -&gt; conversion"),
			"System will do <br> an implicit -> conversion",
		)
