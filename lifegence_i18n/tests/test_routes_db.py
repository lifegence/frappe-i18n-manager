"""Routes that read the site: the database route (S-3, plus the workspace
headings and shortcut formats route 4 showed it was missing) and delivery
verification (S-1)."""

import json
import unittest
from unittest.mock import patch

import frappe

from lifegence_i18n.scanner import database, delivery
from lifegence_i18n.tests import FrappeTestCase

LOCALE = "zz-TEST"


def ensure_locale():
	if not frappe.db.exists("Locale Profile", LOCALE):
		frappe.get_doc(
			{
				"doctype": "Locale Profile",
				"locale_code": LOCALE,
				"locale_label": "Test locale",
				"country": "Japan",
				"language": "en",
				"currency": "JPY",
			}
		).insert(ignore_permissions=True)
	return LOCALE


def remove_locale():
	"""Leave the site as it was: the test locale and everything filed under it."""
	for doctype in ("Translation Issue", "Translation Entry", "Glossary Term", "Translation Scan"):
		frappe.db.delete(doctype, {"locale": LOCALE})
	frappe.db.delete("Locale Target App", {"parent": LOCALE})
	frappe.db.delete("Locale Profile", {"name": LOCALE})


def entry(source, translated, status="Approved", **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Translation Entry",
			"locale": LOCALE,
			"source_text": source,
			"translated_text": translated,
			"status": status,
			"origin": "Manual",
			"app": "zz_app",
			**extra,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestDatabaseRoute(FrappeTestCase):
	def setUp(self):
		self.ws = frappe.get_doc(
			{
				"doctype": "Workspace",
				"title": "Zzz Route Test",
				"label": "Zzz Route Test",
				"module": "Localization",
				"public": 1,
				"is_hidden": 1,
				"content": json.dumps(
					[
						{
							"id": "h1",
							"type": "header",
							"data": {"text": '<span class="h4"><b>Zzz Daily Checks</b></span>', "col": 12},
						},
						{"id": "s1", "type": "shortcut", "data": {"shortcut_name": "Zzz Open", "col": 4}},
					]
				),
				"shortcuts": [
					{"label": "Zzz Open", "type": "DocType", "link_to": "ToDo", "format": "{} Zzz Waiting"}
				],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.delete_doc("Workspace", self.ws.name, force=True, ignore_permissions=True)

	def test_headings_and_shortcut_formats_are_collected(self):
		found = {r["source_text"]: r for r in database.collect(["lifegence_i18n"])}
		self.assertIn("Zzz Daily Checks", found)
		self.assertEqual(found["Zzz Daily Checks"]["reference_field"], "content")
		self.assertEqual(found["Zzz Daily Checks"]["string_class"], "UI Text")
		self.assertIn("{} Zzz Waiting", found)
		self.assertEqual(found["{} Zzz Waiting"]["reference_doctype"], "Workspace Shortcut")
		self.assertIn("Zzz Open", found)

	def test_a_field_this_version_does_not_have_is_skipped_not_the_doctype(self):
		# version-16's Module Onboarding has no subtitle and no success_message;
		# asking for them failed the query and dropped the titles with it
		real = database.table_columns

		def without_a_column(doctype):
			columns = real(doctype)
			return columns - {"format"} if doctype == "Workspace Shortcut" else columns

		log = []
		with patch.object(database, "table_columns", without_a_column):
			found = {r["source_text"] for r in database.collect(["lifegence_i18n"], log=log)}
		self.assertIn("Zzz Open", found, "the label is still read")
		self.assertNotIn("{} Zzz Waiting", found, "the missing column is not")
		self.assertTrue([line for line in log if "Workspace Shortcut has no format" in line], log)

	def test_a_doctype_with_no_usable_field_says_so(self):
		log = []
		with patch.object(database, "table_columns", lambda doctype: set()):
			found = database.collect(["lifegence_i18n"], log=log)
		# the workspace headings are read from the content JSON, not a column
		self.assertEqual([r for r in found if r["reference_doctype"] != "Workspace"], [])
		self.assertTrue([line for line in log if "nothing left to read" in line], log[:3])

	def test_a_child_row_belongs_to_its_parent_s_app(self):
		# the shortcut is a child row of a workspace in the Localization module,
		# which is this app's; it used to be filed as the site's
		found = {r["source_text"]: r for r in database.collect(["lifegence_i18n"])}
		self.assertEqual(found["Zzz Open"]["app"], "lifegence_i18n")
		self.assertEqual(found["{} Zzz Waiting"]["app"], "lifegence_i18n")
		self.assertEqual(found["Zzz Daily Checks"]["app"], "lifegence_i18n")

	def test_a_child_of_a_workspace_without_a_module_is_the_site_s(self):
		ws = frappe.get_doc(
			{
				"doctype": "Workspace",
				"title": "Zzz Site Made",
				"label": "Zzz Site Made",
				"public": 1,
				"is_hidden": 1,
				"shortcuts": [{"label": "Zzz Site Shortcut", "type": "DocType", "link_to": "ToDo"}],
			}
		).insert(ignore_permissions=True)
		try:
			found = {r["source_text"]: r for r in database.collect()}
			self.assertEqual(found["Zzz Site Shortcut"]["app"], "site")
		finally:
			frappe.delete_doc("Workspace", ws.name, force=True, ignore_permissions=True)

	@unittest.skipUnless(
		frappe.db.exists("DocType", "Workspace Sidebar"), "version-16 keeps a sidebar; version-15 does not"
	)
	def test_the_sidebar_and_its_entries_are_read_on_version_16(self):
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": "Zzz Side",
				"module": "Localization",
				"items": [
					{"label": "Zzz Side Entry", "type": "Link", "link_type": "DocType", "link_to": "ToDo"}
				],
			}
		).insert(ignore_permissions=True)
		try:
			found = {r["source_text"]: r for r in database.collect(["lifegence_i18n"])}
			self.assertEqual(found["Zzz Side"]["reference_doctype"], "Workspace Sidebar")
			self.assertEqual(found["Zzz Side Entry"]["app"], "lifegence_i18n")
		finally:
			frappe.delete_doc("Workspace Sidebar", sidebar.name, force=True, ignore_permissions=True)

	def test_classes_are_selected_explicitly(self):
		self.assertEqual({r["string_class"] for r in database.collect(["frappe"])}, {"UI Text"})
		with_roles = database.collect(["frappe"], classes=(database.UI, database.ROLE))
		self.assertIn("Role Name", {r["string_class"] for r in with_roles})
		roles = [r for r in with_roles if r["string_class"] == "Role Name"]
		self.assertTrue(roles and all(r["reference_doctype"] == "Role" for r in roles))


class TestScanBookkeeping(FrappeTestCase):
	"""What Translation Scan writes about itself when two routes write in turn."""

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation Issue", {"locale": LOCALE})
		self.profile = frappe.get_doc("Locale Profile", LOCALE)
		self.scan = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)

	def tearDown(self):
		frappe.db.delete("Translation Issue", {"locale": LOCALE})
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.delete_doc("Translation Scan", self.scan.name, force=True, ignore_permissions=True)

	def item(self, text, origin="Source Code"):
		return {
			"source_text": text,
			"context": None,
			"app": "zz_app",
			"origin": origin,
			"string_class": "UI Text",
			"source_path": "x",
			"line_no": 0,
			"occurrences": 1,
		}

	def test_counts_accumulate_across_routes(self):
		self.scan.new_entries = self.scan.updated_entries = 0
		self.scan._upsert(self.profile, [self.item("Zzz One"), self.item("Zzz Two")])
		self.scan._upsert(self.profile, [self.item("Zzz Three", "Screen")])
		self.assertEqual(self.scan.new_entries, 3)
		self.assertEqual(
			frappe.db.get_value(
				"Translation Entry", {"locale": LOCALE, "source_text": "Zzz Three"}, "origin"
			),
			"Screen",
		)

	def test_rendered_untranslated_becomes_an_issue(self):
		row = entry("Zzz Export", "Zzz 書き出し")
		count = self.scan._rebuild_issues(
			self.profile,
			[],
			[
				{
					"entry": row.name,
					"source_text": "Zzz Export",
					"translated_text": "Zzz 書き出し",
					"route": "/app/data-export",
					"app": "zz_app",
					"kind": "button",
					"shown": "Zzz Export",
				}
			],
		)
		issues = frappe.get_all(
			"Translation Issue",
			filters={"locale": LOCALE, "issue_type": "Not Wrapped"},
			fields=["translation_entry", "location", "severity"],
		)
		self.assertEqual(len(issues), 1)
		self.assertEqual(issues[0].translation_entry, row.name)
		self.assertEqual(issues[0].location, "/app/data-export")
		self.assertEqual(issues[0].severity, "High")
		self.assertGreaterEqual(count, 1)


class TestDeliveryVerification(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation", {"source_text": ("like", "Zzz %")})
		self.live = entry("Zzz Alpha", "Zzz A")
		self.missing = entry("Zzz Beta", "Zzz B")
		self.overridden = entry("Zzz Gamma", "Zzz G")
		self.changed = entry("Zzz Delta", "Zzz D new")
		self.later_file_wins = entry("Zzz Epsilon", "Zzz E")
		# A site Translation record is what Frappe resolves; it stands in for a
		# deployed file here, and a different value for a later source winning.
		for source, value in (
			("Zzz Alpha", "Zzz A"),
			("Zzz Gamma", "Zzz other"),
			("Zzz Delta", "Zzz D old"),
			("Zzz Epsilon", "Zzz E2"),
		):
			frappe.get_doc(
				{"doctype": "Translation", "language": "en", "source_text": source, "translated_text": value}
			).insert(ignore_permissions=True)
		frappe.translate.clear_cache()
		# what the files hold, read past the cache: Gamma's file is right and a
		# Translation record outranks it; Delta's file still has the old value;
		# Epsilon is in two files and the later one wins
		self.files = (
			{"Zzz Gamma": "Zzz G", "Zzz Delta": "Zzz D old", "Zzz Epsilon": "Zzz E2"},
			{"Zzz Gamma": {"Zzz G"}, "Zzz Delta": {"Zzz D old"}, "Zzz Epsilon": {"Zzz E", "Zzz E2"}},
		)

	def tearDown(self):
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation", {"source_text": ("like", "Zzz %")})
		frappe.translate.clear_cache()

	def test_each_state_is_told_apart(self):
		with patch.object(delivery, "_file_translations", return_value=self.files):
			result = delivery.verify(LOCALE)
		self.assertEqual(result["approved"], 5)
		states = {
			name: frappe.db.get_value("Translation Entry", name, "delivery_status")
			for name in (
				self.live.name,
				self.missing.name,
				self.overridden.name,
				self.changed.name,
				self.later_file_wins.name,
			)
		}
		self.assertEqual(states[self.live.name], "Live")
		self.assertEqual(states[self.missing.name], "Not Deployed")
		self.assertEqual(states[self.overridden.name], "Overridden")
		# an approved value no file carries yet is not deployed, whatever the
		# site shows meanwhile (the old value here)
		self.assertEqual(states[self.changed.name], "Not Deployed")
		self.assertEqual(states[self.later_file_wins.name], "Overridden")
		self.assertEqual(result["state"], "Not Deployed")  # the worst state wins

	def test_verification_does_not_edit_the_ledger(self):
		before = frappe.db.get_value(
			"Translation Entry", self.missing.name, ["translated_text", "status", "modified"]
		)
		delivery.verify(LOCALE)
		after = frappe.db.get_value(
			"Translation Entry", self.missing.name, ["translated_text", "status", "modified"]
		)
		self.assertEqual(before, after)
