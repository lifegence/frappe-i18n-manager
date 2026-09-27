"""The DocTypes' own rules: what a Locale
Profile derives on save, what a Translation Entry refuses, how scans order
locales, and how a role name on the source route is told from a label."""

from unittest.mock import patch

import frappe

from lifegence_i18n.localization.doctype.translation_scan import translation_scan as scan_module
from lifegence_i18n.localization.doctype.translation_scan.translation_scan import TranslationScan, scan_order
from lifegence_i18n.scanner import delivery
from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, entry, remove_locale


class TestLocaleProfile(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		for name in ("zz-HR", "zz-JA", "zz-FB"):
			if frappe.db.exists("Locale Profile", name):
				frappe.delete_doc("Locale Profile", name, force=True, ignore_permissions=True)
		super().tearDownClass()

	def make(self, code, language, fallback=None):
		if frappe.db.exists("Locale Profile", code):
			return frappe.get_doc("Locale Profile", code)
		return frappe.get_doc(
			{
				"doctype": "Locale Profile",
				"locale_code": code,
				"locale_label": code,
				"country": "Japan",
				"language": language,
				"currency": "JPY",
				"fallback_locale": fallback,
			}
		).insert(ignore_permissions=True)

	def test_latin_script_is_derived_from_the_language(self):
		self.assertEqual(self.make("zz-HR", "hr").uses_latin_script, 1)
		self.assertEqual(self.make("zz-JA", "ja").uses_latin_script, 0)

	def test_a_locale_cannot_fall_back_to_itself(self):
		doc = frappe.get_doc(
			{
				"doctype": "Locale Profile",
				"locale_code": "zz-FB",
				"locale_label": "zz-FB",
				"country": "Japan",
				"language": "en",
				"currency": "JPY",
			}
		).insert(ignore_permissions=True)
		doc.fallback_locale = doc.name
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_fallback_sources_are_scanned_first(self):
		self.make("zz-JA", "ja")
		hr = self.make("zz-HR", "hr")
		hr.fallback_locale = "zz-JA"
		hr.save(ignore_permissions=True)
		order = scan_order(["zz-HR", "zz-JA"])
		self.assertLess(order.index("zz-JA"), order.index("zz-HR"))


class TestTranslationEntry(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})

	def test_duplicate_source_and_context_is_refused(self):
		entry("Zzz Twice", "")
		self.assertRaises(frappe.ValidationError, entry, "Zzz Twice", "")

	def test_status_follows_the_translation(self):
		row = entry("Zzz Status", "", status="Untranslated")
		row.translated_text = "Zzz 訳"
		row.save(ignore_permissions=True)
		self.assertEqual(row.status, "Draft")
		row.translated_text = ""
		row.save(ignore_permissions=True)
		self.assertEqual(row.status, "Untranslated")


class TestSourceRoles(FrappeTestCase):
	"""A role name arriving on the source route is only a role when the
	database route did not also find it stored as a label."""

	def item(self, text):
		return {"source_text": text, "string_class": "UI Text"}

	def run_with(self, scan_roles, from_source, from_database, field_labels=frozenset()):
		scan = frappe.get_doc({"doctype": "Translation Scan", "locale": ensure_locale()})
		scan.scan_roles = scan_roles
		# which labels the site's fields carry is a property of the site; each
		# test states the one it is about
		with (
			patch.object(frappe, "get_all", return_value=["System Manager", "Customer"]),
			patch.object(scan_module, "_field_labels", return_value=set(field_labels)),
		):
			dropped = TranslationScan._class_source_roles(scan, from_source, from_database)
		return dropped, from_source

	def test_role_only_on_source_route_is_dropped_by_default(self):
		dropped, left = self.run_with(
			0, [self.item("System Manager"), self.item("Save")], [self.item("Save")]
		)
		self.assertEqual(dropped, 1)
		self.assertEqual([i["source_text"] for i in left], ["Save"])

	def test_role_that_is_also_a_label_is_kept(self):
		dropped, left = self.run_with(0, [self.item("Customer")], [self.item("Customer")])
		self.assertEqual(dropped, 0)
		self.assertEqual(left[0]["string_class"], "UI Text")

	def test_with_scan_roles_the_row_is_classed_not_dropped(self):
		dropped, left = self.run_with(1, [self.item("System Manager")], [self.item("Save")])
		self.assertEqual(dropped, 0)
		self.assertEqual(left[0]["string_class"], "Role Name")

	def test_nothing_is_dropped_without_the_database_route(self):
		dropped, left = self.run_with(0, [self.item("System Manager")], [])
		self.assertEqual((dropped, len(left)), (0, 1))

	def test_field_labels_are_read_from_the_field_tables(self):
		# the database route reads the site's customisations and never an app's
		# own DocType JSON, so a shipped label is only visible here
		self.assertEqual(scan_module._field_labels(set()), set())
		found = scan_module._field_labels({"Status", "Zzz Nothing Is Labelled This"})
		self.assertEqual(found, {"Status"})

	def test_a_role_that_labels_a_shipped_field_is_interface_text(self):
		# "Stock Auditor" as a Role and as a field's label: the label must live
		dropped, left = self.run_with(
			0, [self.item("System Manager")], [self.item("Save")], field_labels={"System Manager"}
		)
		self.assertEqual(dropped, 0)
		self.assertEqual(left[0]["string_class"], "UI Text")


class TestCacheStale(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation", {"source_text": ("like", "Zzz %")})
		frappe.translate.clear_cache()

	def test_a_translation_in_the_files_but_not_served_is_cache_stale(self):
		row = entry("Zzz Stale", "Zzz 古い")
		with patch.object(
			delivery,
			"_file_translations",
			return_value=({"Zzz Stale": "Zzz 古い"}, {"Zzz Stale": {"Zzz 古い"}}),
		):
			result = delivery.verify(LOCALE)
		self.assertEqual(frappe.db.get_value("Translation Entry", row.name, "delivery_status"), "Cache Stale")
		self.assertEqual(result["stale"], 1)
		self.assertEqual(result["state"], "Cache Stale")


class TestUniqueLedgerRows(FrappeTestCase):
	"""The patch that folds duplicate ledger rows before the constraint lands."""

	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def test_duplicates_are_merged_keeping_the_translated_row(self):
		from lifegence_i18n.patches.v1_2 import unique_ledger_rows
		from lifegence_i18n.utils import text_hash

		ensure_locale()
		frappe.db.delete("Translation Issue", {"locale": LOCALE})
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		digest = text_hash("Zzz Twin", None)
		fields = [
			"name",
			"creation",
			"modified",
			"modified_by",
			"owner",
			"docstatus",
			"idx",
			"locale",
			"source_text",
			"text_hash",
			"translated_text",
			"status",
			"origin",
		]
		stamp = frappe.utils.now_datetime()
		# the constraint may already exist on this site: drop it for the test, restore after
		had_constraint = frappe.db.sql(
			"select 1 from information_schema.TABLE_CONSTRAINTS where table_name='tabTranslation Entry' and CONSTRAINT_NAME='unique_locale_text_hash'"
		)
		if had_constraint:
			frappe.db.sql_ddl("alter table `tabTranslation Entry` drop index unique_locale_text_hash")
		frappe.db.bulk_insert(
			"Translation Entry",
			fields=fields,
			values=[
				[
					"zzdup1",
					stamp,
					stamp,
					"Administrator",
					"Administrator",
					0,
					0,
					LOCALE,
					"Zzz Twin",
					digest,
					"",
					"Untranslated",
					"Manual",
				],
				[
					"zzdup2",
					stamp,
					stamp,
					"Administrator",
					"Administrator",
					0,
					0,
					LOCALE,
					"Zzz Twin",
					digest,
					"Zzz 訳",
					"Approved",
					"Manual",
				],
			],
		)
		frappe.get_doc(
			{
				"doctype": "Translation Issue",
				"locale": LOCALE,
				"issue_type": "Untranslated",
				"severity": "Medium",
				"status": "Open",
				"translation_entry": "zzdup1",
				"source_text": "Zzz Twin",
			}
		).insert(ignore_permissions=True)
		unique_ledger_rows.execute()  # folds the twins, repoints the issue, and puts the constraint back
		rows = frappe.get_all(
			"Translation Entry",
			filters={"locale": LOCALE, "text_hash": digest},
			fields=["name", "translated_text"],
		)
		self.assertEqual([(r.name, r.translated_text) for r in rows], [("zzdup2", "Zzz 訳")])
		self.assertEqual(
			frappe.db.get_value(
				"Translation Issue", {"locale": LOCALE, "source_text": "Zzz Twin"}, "translation_entry"
			),
			"zzdup2",
		)
