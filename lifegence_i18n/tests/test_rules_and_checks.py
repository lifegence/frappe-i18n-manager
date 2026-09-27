"""Pure logic: exclusion rules (S-2), translation checks (FR-13), route 3."""

import os
import re
import tempfile
import unittest

import frappe

from lifegence_i18n.scanner import messages, validate
from lifegence_i18n.utils import DEFAULT_EXCLUSION_RULES, ExclusionRule, classify


def default_rules():
	return [
		ExclusionRule(r["rule_name"], re.compile(r["pattern"]), r["na_reason"], bool(r["auto_apply"]))
		for r in DEFAULT_EXCLUSION_RULES
	]


class TestExclusionRules(unittest.TestCase):
	def setUp(self):
		self.rules = default_rules()

	def test_worthless_strings_are_dropped_not_recorded(self):
		for text in ("", "   ", "a", "123", "---"):
			self.assertFalse(classify(text, self.rules).keep, repr(text))

	def test_excluded_strings_are_kept_with_a_reason(self):
		cases = {
			"SINV-.YYYY.-": ("Naming Series", "Naming Series"),
			"{name}": (
				"Placeholder Only",
				"Lone Placeholder",
			),  # "{0}" has no letters and is dropped outright
			"https://example.com/x": ("Developer Note", "URL"),
			"frappe.utils.now": ("Developer Note", "Dotted Path"),
			"<br>": ("Placeholder Only", "Lone HTML Tag"),
		}
		for text, (reason, rule) in cases.items():
			verdict = classify(text, self.rules)
			self.assertTrue(verdict.keep, text)
			self.assertEqual(verdict.na_reason, reason, text)
			self.assertEqual(verdict.na_rule, rule, text)
			self.assertTrue(verdict.auto_apply, text)

	def test_interface_text_carries_no_reason(self):
		verdict = classify("Save", self.rules)
		self.assertTrue(verdict.keep)
		self.assertIsNone(verdict.na_reason)

	def test_a_bare_acronym_is_a_candidate_on_every_route(self):
		# shipped as a default rule, so the source and database routes agree
		# with the screen route about "SKU"
		for text in ("SKU", "GRNI", "PLU", "API2"):
			verdict = classify(text, self.rules)
			self.assertEqual((verdict.na_reason, verdict.auto_apply), ("Acronym or Code", False), text)
		for text in ("Sku", "SKU Code", "ABCDEFGHI", "S"):
			self.assertNotEqual(classify(text, self.rules).na_reason, "Acronym or Code", text)

	def test_settings_values_that_are_not_prose_are_developer_notes(self):
		cases = {
			"eval:doc.status == 'Open'": "Expression",
			"/api/method/frappe.ping": "API Path",
			"#f5f5f5": "Colour Code",
			"#FFF": "Colour Code",
		}
		for text, rule in cases.items():
			verdict = classify(text, self.rules)
			self.assertEqual(
				(verdict.na_reason, verdict.na_rule, verdict.auto_apply), ("Developer Note", rule, True), text
			)
		for text in ("#Tag", "evaluate the claim", "API Path", "Open /api docs"):
			self.assertNotEqual(classify(text, self.rules).na_reason, "Developer Note", text)

	def test_a_do_not_translate_term_excludes_the_whole_string_only(self):
		from lifegence_i18n.utils import BrandRule, brand_match

		rules = [BrandRule("Acme ERP", True), BrandRule("APITemplate", False)]
		self.assertEqual(brand_match("Acme ERP", rules), "Acme ERP")
		self.assertEqual(brand_match(" Acme ERP ", rules), "Acme ERP")
		self.assertEqual(brand_match("apitemplate", rules), "APITemplate")
		self.assertIsNone(brand_match("acme erp", rules))  # case-sensitive term
		self.assertIsNone(brand_match("Acme ERP Sync Status", rules))  # interface text that keeps the brand
		self.assertIsNone(brand_match("", rules))

	def test_a_rule_without_auto_apply_only_suggests(self):
		rules = [ExclusionRule("Acronym", re.compile(r"^[A-Z][A-Z0-9]{1,7}$"), "Acronym or Code", False)]
		verdict = classify("SKU", rules)
		self.assertEqual(verdict.na_reason, "Acronym or Code")
		self.assertFalse(verdict.auto_apply)


class TestChecks(unittest.TestCase):
	def check(self, source, translated, glossary=(), allowed=(), latin=False):
		return [
			i["issue_type"]
			for i in validate.check(
				source, translated, glossary=list(glossary), allowed_latin=set(allowed), latin_script=latin
			)
		]

	def test_placeholders(self):
		self.assertEqual(self.check("Hello {0}", "こんにちは"), ["Placeholder Mismatch"])
		self.assertEqual(self.check("%s items", "個の品目"), ["Placeholder Mismatch"])
		self.assertEqual(self.check("Hello {0}", "こんにちは {0}"), [])

	def test_html(self):
		self.assertEqual(self.check("<b>Save</b>", "保存"), ["HTML Mismatch"])

	def test_padded_source_is_unreachable_from_python(self):
		self.assertEqual(self.check(" Save ", "保存"), ["Unreachable Whitespace"])
		self.assertEqual(self.check("Save", " 保存 "), [])  # padding on the translation is harmless

	def test_glossary(self):
		rows = [
			frappe._dict(
				source_term="Item",
				translated_term="品目",
				do_not_translate=0,
				forbidden_terms="アイテム",
				match_type="Word",
				case_sensitive=1,
				enforce=1,
			),
			frappe._dict(
				source_term="Acme",
				translated_term="",
				do_not_translate=1,
				forbidden_terms="",
				match_type="Word",
				case_sensitive=1,
				enforce=1,
			),
		]
		glossary = validate.compile_glossary(rows)
		self.assertEqual(
			sorted(self.check("Item Code", "アイテムコード", glossary)),
			["Forbidden Term", "Glossary Violation"],
		)
		self.assertEqual(self.check("Item Code", "品目コード", glossary), [])
		self.assertEqual(self.check("Acme Store", "アクメ店舗", glossary), ["Glossary Violation"])
		self.assertEqual(self.check("Acme Store", "Acme 店舗", glossary, allowed=["Acme"]), [])

	def test_latin_residue_respects_allowed_terms_and_script(self):
		self.assertEqual(self.check("Print PDF", "PDF を印刷"), ["Latin Residue"])
		self.assertEqual(self.check("Print PDF", "PDF を印刷", allowed=["PDF"]), [])
		self.assertEqual(self.check("Print PDF", "Ispis PDF", latin=True), [])  # Croatian: skipped


class TestMessagesRoute(unittest.TestCase):
	def scan(self, code):
		with tempfile.TemporaryDirectory() as tmp:
			path = os.path.join(tmp, "x.py")
			with open(path, "w", encoding="utf-8") as fh:
				fh.write(code)
			findings = []
			messages._scan_python(path, "x.py", "app", findings)
		return findings

	def test_bare_literal_is_reported(self):
		found = self.scan('import frappe\nfrappe.throw("Inspection notes are required")\n')
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0]["source_text"], "Inspection notes are required")
		self.assertEqual(found[0]["kind"], "py/plain")
		self.assertEqual(found[0]["line_no"], 2)

	def test_translated_literal_is_not(self):
		self.assertEqual(self.scan('frappe.throw(_("Saved"))\n'), [])
		self.assertEqual(self.scan('frappe.throw(_("Saved {0}").format(x))\n'), [])

	def test_fstring_is_flagged_as_needing_a_rewrite(self):
		found = self.scan('frappe.msgprint(f"Row {i} is empty")\n')
		self.assertEqual(found[0]["kind"], "py/fstring")
