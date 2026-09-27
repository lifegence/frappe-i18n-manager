"""Taking a review sheet back (FR-16): the one path that writes translations.

Everything else in the app reads. This writes, from a file a person edited in a
spreadsheet, so each way the sheet can come back has to land correctly: the
header in the reviewer's language, a BOM from Excel, blank cells from a partial
review, and — the one that matters most — a sheet belonging to another locale,
which must be counted and refused rather than applied to whatever rows it names.
"""

import csv
import io

import frappe

from lifegence_i18n import api
from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, entry, remove_locale

HEADERS = [
	"ID",
	"App",
	"Found In",
	"Status",
	"Source Text",
	"Context",
	"Translation",
	"Issues",
	"Proposed Change",
	"Reviewer Comment",
]
HEADERS_JA = ["ID", "アプリ", "検出元", "状態", "原文", "文脈", "訳文", "指摘", "修正案", "査読コメント"]


def sheet(rows: list[list[str]], headers: list[str] | None = None, bom: bool = False) -> str:
	buffer = io.StringIO()
	writer = csv.writer(buffer, lineterminator="\n")
	writer.writerow(headers or HEADERS)
	for row in rows:
		writer.writerow(row)
	return ("﻿" if bom else "") + buffer.getvalue()


def row_for(name: str, proposal: str, headers: list[str] | None = None) -> list[str]:
	"""A sheet line: only the ID and the proposal column are ever read."""
	line = [""] * len(headers or HEADERS)
	line[0] = name
	line[8] = proposal
	return line


class TestImportReviewSheet(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		self.alpha = entry("Zzz Alpha", "Zzz アルファ").name
		self.beta = entry("Zzz Beta", "").name

	def tearDown(self):
		frappe.db.delete("Translation Entry", {"locale": LOCALE})

	def load(self, content: str) -> dict:
		"""Stand in for the File doctype: the function only needs get_content()."""
		from unittest.mock import patch

		doc = frappe._dict(get_content=lambda: content)
		with patch.object(frappe, "get_doc", side_effect=self._get_doc(doc)):
			return api.import_review_sheet(LOCALE, "/files/review.csv")

	def _get_doc(self, stub):
		real = frappe.get_doc

		def fake(*args, **kwargs):
			if args and args[0] == "File":
				return stub
			return real(*args, **kwargs)

		return fake

	def translation(self, name: str) -> tuple[str, str]:
		row = frappe.db.get_value("Translation Entry", name, ["translated_text", "status"], as_dict=True)
		return row.translated_text, row.status

	# ------------------------------------------------------------------ writing

	def test_a_proposal_is_applied_and_marked_reviewed(self):
		result = self.load(sheet([row_for(self.beta, "Zzz ベータ")]))
		self.assertEqual(result, {"applied": 1, "skipped": 0})
		self.assertEqual(self.translation(self.beta), ("Zzz ベータ", "Reviewed"))

	def test_a_blank_proposal_leaves_the_row_alone(self):
		"""A reviewer may return the sheet halfway through."""
		result = self.load(sheet([row_for(self.alpha, ""), row_for(self.beta, "Zzz ベータ")]))
		self.assertEqual(result, {"applied": 1, "skipped": 0})
		self.assertEqual(
			self.translation(self.alpha),
			("Zzz アルファ", "Approved"),
			"a blank cell is not an instruction to erase",
		)

	def test_the_same_value_is_not_written_again(self):
		result = self.load(sheet([row_for(self.alpha, "Zzz アルファ")]))
		self.assertEqual(
			result, {"applied": 0, "skipped": 0}, "an unchanged proposal must not move the row to Reviewed"
		)
		self.assertEqual(self.translation(self.alpha), ("Zzz アルファ", "Approved"))

	def test_surrounding_spaces_are_dropped(self):
		self.load(sheet([row_for(self.beta, "  Zzz ベータ  ")]))
		self.assertEqual(self.translation(self.beta)[0], "Zzz ベータ")

	def test_a_row_without_an_id_is_ignored(self):
		result = self.load(sheet([row_for("", "Zzz ベータ")]))
		self.assertEqual(result, {"applied": 0, "skipped": 0})

	# ------------------------------------------------- the sheet as it comes back

	def test_a_japanese_header_finds_the_proposal_column(self):
		"""The header is written in the reviewer's language; the sheet must still
		load on an English session."""
		result = self.load(sheet([row_for(self.beta, "Zzz ベータ", HEADERS_JA)], HEADERS_JA))
		self.assertEqual(result, {"applied": 1, "skipped": 0})
		self.assertEqual(self.translation(self.beta)[0], "Zzz ベータ")

	def test_a_header_in_neither_language_falls_back_to_the_column_position(self):
		headers = ["ID", "a", "b", "c", "d", "e", "f", "g", "Vorschlag", "h"]
		result = self.load(sheet([row_for(self.beta, "Zzz ベータ", headers)], headers))
		self.assertEqual(result, {"applied": 1, "skipped": 0})

	def test_a_byte_order_mark_from_excel_does_not_hide_the_id_column(self):
		result = self.load(sheet([row_for(self.beta, "Zzz ベータ")], bom=True))
		self.assertEqual(
			result, {"applied": 1, "skipped": 0}, "Excel writes a BOM; the first header must still read as ID"
		)

	# --------------------------------------------------------- the wrong sheet

	def test_a_row_belonging_to_another_locale_is_refused_and_counted(self):
		"""The only guard against loading the wrong locale's sheet. If this
		stops working, one locale's translations land in another's rows without
		a word of complaint."""
		other_locale = "zz-OTHER"
		frappe.get_doc(
			{
				"doctype": "Locale Profile",
				"locale_code": other_locale,
				"locale_label": "Other test locale",
				"country": "Japan",
				"language": "en",
				"currency": "JPY",
			}
		).insert(ignore_permissions=True)
		try:
			other = (
				frappe.get_doc(
					{
						"doctype": "Translation Entry",
						"locale": other_locale,
						"source_text": "Zzz Alpha",
						"translated_text": "Zzz 別ロケール",
						"status": "Approved",
						"origin": "Manual",
						"app": "zz_app",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			result = self.load(sheet([row_for(other, "Zzz 取り違え")]))
			self.assertEqual(result, {"applied": 0, "skipped": 1})
			self.assertEqual(
				frappe.db.get_value("Translation Entry", other, "translated_text"),
				"Zzz 別ロケール",
				"the other locale's row must be untouched",
			)
		finally:
			frappe.db.delete("Translation Entry", {"locale": other_locale})
			frappe.db.delete("Locale Profile", {"name": other_locale})

	def test_an_id_that_no_longer_exists_is_counted_not_raised(self):
		result = self.load(sheet([row_for("zz-does-not-exist", "Zzz ベータ")]))
		self.assertEqual(result, {"applied": 0, "skipped": 1})

	def test_a_sheet_with_only_a_header_applies_nothing(self):
		self.assertEqual(self.load(sheet([])), {"applied": 0, "skipped": 0})
