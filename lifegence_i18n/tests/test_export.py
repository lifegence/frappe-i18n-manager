"""The app CSV (FR-16): deliberate non-translations survive (S-4), context-less
rows have two columns (S-5), and a merely copied source is dropped."""

import csv
import io

import frappe

from lifegence_i18n import api
from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, entry, remove_locale


class TestAppTranslationCsv(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Glossary Term", {"locale": LOCALE})
		entry("Zzz Alpha", "Zzz アルファ")
		entry("Zzz Beta", "Zzz ベータ", context="menu")
		entry("Zzz Brand", "Zzz Brand", status="Not Applicable", na_reason="Brand or Product Name")
		entry("Zzz Copied", "Zzz Copied")  # forgot to translate: must be dropped
		entry("Zzz Draft", "Zzz 下書き", status="Draft")  # not agreed yet: must be dropped
		entry(" Zzz Padded ", "Zzz 余白")  # unreachable key: shipped stripped
		entry("Zzz Glossary", "Zzz Glossary")
		frappe.get_doc(
			{
				"doctype": "Glossary Term",
				"locale": LOCALE,
				"source_term": "Zzz Glossary",
				"do_not_translate": 1,
				"match_type": "Word",
				"case_sensitive": 1,
				"enforce": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Glossary Term", {"locale": LOCALE})

	def export(self):
		api.export_app_translations(LOCALE, "zz_app")
		content = frappe.response["filecontent"].decode("utf-8-sig")
		return list(csv.reader(io.StringIO(content)))

	def test_rows_and_columns(self):
		rows = {r[0]: r for r in self.export()}
		self.assertEqual(rows["Zzz Alpha"], ["Zzz Alpha", "Zzz アルファ"])  # two columns without context
		self.assertEqual(rows["Zzz Beta"], ["Zzz Beta", "Zzz ベータ", "menu"])  # three with
		self.assertEqual(rows["Zzz Brand"], ["Zzz Brand", "Zzz Brand"])  # a decision, kept
		self.assertEqual(rows["Zzz Glossary"], ["Zzz Glossary", "Zzz Glossary"])  # do_not_translate, kept
		self.assertEqual(rows["Zzz Padded"], ["Zzz Padded", "Zzz 余白"])  # key stripped
		self.assertNotIn("Zzz Copied", rows)
		self.assertNotIn("Zzz Draft", rows)
		self.assertNotIn(" Zzz Padded ", rows)

	def test_write_into_the_app_folder(self):
		import os
		import tempfile
		from unittest.mock import patch

		entry("Zzz Own", "Zzz 自分", app="lifegence_i18n")
		with (
			tempfile.TemporaryDirectory() as tmp,
			patch.object(api.frappe, "get_app_path", lambda app, *parts: os.path.join(tmp, *parts)),
		):
			api.export_app_translations(LOCALE, "lifegence_i18n", write_to_app=1)
			path = os.path.join(tmp, "translations", "en.csv")
			self.assertTrue(os.path.exists(path))
			with open(path, encoding="utf-8") as fh:
				on_disk = fh.read()
		self.assertEqual(on_disk, frappe.response["filecontent"].decode("utf-8-sig"))

	def test_writing_needs_the_app_on_this_bench(self):
		self.assertRaises(frappe.ValidationError, api.export_app_translations, LOCALE, "zz_app", 1)

	def test_review_sheet_leaves_not_applicable_out(self):
		api.export_review_sheet(LOCALE)
		content = frappe.response["filecontent"].decode("utf-8-sig")
		sources = {r[4] for r in list(csv.reader(io.StringIO(content)))[1:]}
		self.assertIn("Zzz Alpha", sources)
		self.assertNotIn("Zzz Brand", sources)
