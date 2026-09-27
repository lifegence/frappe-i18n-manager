"""Reports that put the ledger in front of a customer: coverage by string
class (S-3) and the list of exclusions with their reasons (S-2)."""

import frappe
from frappe.desk.query_report import run

from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, entry, remove_locale


def column_labels(report):
	return [c.split(":")[0] if isinstance(c, str) else c.get("label") for c in report["columns"]]


def key(label):
	return label.lower().replace(" ", "_")


class TestCoverageReport(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		entry("Zzz Save", "Zzz 保存", string_class="UI Text")
		entry("Zzz Draft", "", status="Untranslated", string_class="UI Text")
		entry("Zzz Sales User", "", status="Untranslated", string_class="Role Name")
		entry("Zzz Spare Parts", "", status="Untranslated", string_class="Master Data")
		entry(
			"Zzz SINV-.YYYY.-",
			"",
			status="Not Applicable",
			na_reason="Naming Series",
			na_rule="Naming Series",
		)

	def tearDown(self):
		frappe.db.delete("Translation Entry", {"locale": LOCALE})

	def rows(self, name):
		report = run(name, filters={}, ignore_prepared_report=True)
		labels = [key(c) for c in column_labels(report)]
		return [dict(zip(labels, r, strict=False)) if isinstance(r, list) else r for r in report["result"]]

	def test_coverage_is_reported_per_string_class(self):
		rows = [r for r in self.rows("Localization Coverage") if r.get("locale") == LOCALE]
		by_class = {r["string_class"]: r for r in rows}
		self.assertEqual(set(by_class), {"UI Text", "Role Name", "Master Data"})
		self.assertEqual(by_class["UI Text"]["total"], 2)
		self.assertEqual(by_class["UI Text"]["on_screen"], 1)
		self.assertEqual(by_class["Role Name"]["total"], 1)
		# the excluded row is in no class's denominator
		self.assertEqual(sum(r["total"] for r in rows), 4)

	def test_exclusions_are_listed_with_their_reason_and_rule(self):
		rows = [r for r in self.rows("Localization Exclusions") if r.get("locale") == LOCALE]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["reason"], "Naming Series")
		self.assertEqual(rows[0]["rule"], "Naming Series")
		self.assertEqual(rows[0]["strings"], 1)
		self.assertEqual(rows[0]["example"], "Zzz SINV-.YYYY.-")
