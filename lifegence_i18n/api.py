import csv
import io

import frappe
from frappe import _

from lifegence_i18n import permissions


@frappe.whitelist()
def export_review_sheet(locale: str, only_untranslated: int = 0):
	"""The sheet a reviewer fills in.

	The review column is separate from the translation column on purpose: a
	reviewer's edit should be visible as a proposal until someone accepts it,
	not silently overwrite the ledger.
	"""
	permissions.only_translate()
	filters = {"locale": locale, "status": ("!=", "Not Applicable")}
	if int(only_untranslated or 0):
		filters["translated_text"] = ("in", ["", None])

	rows = frappe.get_all(
		"Translation Entry",
		filters=filters,
		fields=[
			"name",
			"app",
			"origin",
			"status",
			"source_text",
			"context",
			"translated_text",
			"issue_summary",
		],
		order_by="app asc, source_text asc",
		limit_page_length=0,
	)

	buffer = io.StringIO()
	writer = csv.writer(buffer, lineterminator="\n")
	writer.writerow(
		[
			"ID",
			_("App"),
			_("Found In"),
			_("Status"),
			_("Source Text"),
			_("Context"),
			_("Translation"),
			_("Issues"),
			_("Proposed Change"),
			_("Reviewer Comment"),
		]
	)
	for row in rows:
		writer.writerow(
			[
				row.name,
				row.app,
				row.origin,
				row.status,
				row.source_text,
				row.context or "",
				row.translated_text or "",
				row.issue_summary or "",
				"",
				"",
			]
		)

	_download(f"{locale}_review.csv", buffer.getvalue())


@frappe.whitelist()
def export_app_translations(locale: str, app: str, write_to_app: int = 0):
	"""Emit the file an app ships: `<app>/translations/<lang>.csv`.

	Frappe reads this format directly, so the output can be committed to the
	application repository as-is. With `write_to_app` the file is also written
	into the app's own translations folder on this bench, so a developer with a
	checkout of the app can commit it straight from there; the download still
	happens, so the two never differ.
	"""
	permissions.only_manage()
	language = frappe.db.get_value("Locale Profile", locale, "language")
	base = {"locale": locale, "app": app, "translated_text": ("is", "set")}
	fields = ["source_text", "translated_text", "context", "status", "na_reason"]

	rows = frappe.get_all(
		"Translation Entry",
		filters={**base, "status": ("in", ["Approved", "Reviewed"])},
		fields=fields,
		order_by="source_text asc",
		limit_page_length=0,
	)
	# A brand name is shipped as its own translation on purpose: it tells Frappe
	# the string was considered and left alone, so it stops turning up in every
	# gap report from then on. Those rows are Not Applicable, so the query above
	# does not see them.
	rows += frappe.get_all(
		"Translation Entry",
		filters={
			**base,
			"status": "Not Applicable",
			"na_reason": ("in", ["Brand or Product Name", "Acronym or Code"]),
		},
		fields=fields,
		order_by="source_text asc",
		limit_page_length=0,
	)
	rows.sort(key=lambda row: row.source_text)

	keep_as_is = _do_not_translate_rules(locale)

	buffer = io.StringIO()
	writer = csv.writer(buffer, lineterminator="\n")
	written = 0
	emitted: set[str] = set()
	for row in rows:
		# A "translation" identical to its source usually changes nothing on
		# screen and only makes the file's diff noisy — unless leaving it alone
		# was the decision, in which case dropping it loses that decision.
		if row.translated_text == row.source_text and not _is_deliberate(row, keep_as_is):
			continue
		# `_()` strips the message before looking it up, so an entry keyed with
		# padding is unreachable from Python. Ship the stripped key, and skip it
		# if that collides with one already written — the padded and unpadded
		# variants resolve to the same lookup.
		key = row.source_text.strip()
		if key in emitted:
			continue
		emitted.add(key)

		# Frappe reads a non-empty third column as a `source:context` key, so an
		# empty one must not be written: it would only rewrite every line of an
		# existing two-column file for no change in meaning.
		writer.writerow(
			[key, row.translated_text, row.context] if row.context else [key, row.translated_text]
		)
		written += 1

	if not written:
		frappe.throw(_("There is nothing to export for {0} / {1}").format(app, language))

	if int(write_to_app or 0):
		path = _write_into_app(app, language, buffer.getvalue())
		frappe.msgprint(_("Written to {0}").format(path), alert=True)

	_download(f"{app}_{language}.csv", buffer.getvalue())


def _write_into_app(app: str, language: str, content: str) -> str:
	"""Write `<app>/translations/<lang>.csv` on this bench.

	Only an app installed on this bench has a folder to write into. Frappe Cloud
	sites cannot reach their apps' folders this way; there the download is the
	only route, and the caller is told so rather than left with a silent no-op.
	"""
	import os

	if app not in frappe.get_installed_apps():
		frappe.throw(
			_("{0} is not installed on this bench, so its translations folder cannot be written").format(app)
		)
	import re

	if not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", language or ""):
		frappe.throw(_("{0} is not a language code").format(language))
	# `app` arrives from the browser. `get_app_path` imports the module, so a
	# traversal string would not resolve, but the file is written to disk and a
	# name that is not an installed app has no business naming the folder.
	if app not in frappe.get_installed_apps():
		frappe.throw(_("{0} is not installed on this site").format(app))
	folder = frappe.get_app_path(app, "translations")  # nosemgrep
	os.makedirs(folder, exist_ok=True)
	path = os.path.join(folder, f"{language}.csv")
	with open(path, "w", encoding="utf-8", newline="") as fh:  # nosemgrep
		fh.write(content)
	return path


def _do_not_translate_rules(locale: str):
	from lifegence_i18n.scanner.validate import compile_glossary

	rows = frappe.get_all(
		"Glossary Term",
		filters={"locale": locale, "do_not_translate": 1},
		fields=[
			"source_term",
			"translated_term",
			"do_not_translate",
			"forbidden_terms",
			"match_type",
			"case_sensitive",
		],
		limit_page_length=0,
	)
	# `enforce` decides whether a violation is *reported*. Whether a term is left
	# untranslated is stated by `do_not_translate` alone, and that is the only
	# question being asked here.
	for row in rows:
		row.enforce = 1
	return compile_glossary(rows)


def _is_deliberate(row, keep_as_is) -> bool:
	"""True when source == translation is a decision rather than an omission."""
	if row.status == "Not Applicable" and row.na_reason in (
		"Brand or Product Name",
		"Acronym or Code",
	):
		return True
	return any(rule.pattern.search(row.source_text) for rule in keep_as_is)


@frappe.whitelist()
def import_review_sheet(locale: str, file_url: str):
	"""Take back a filled-in review sheet.

	Only the proposal column is read. Rows left blank are untouched, so a partial
	review is safe to load — a reviewer can return the sheet halfway through.

	The header is written in the reviewer's language, so the column is located by
	any of its known names before falling back to its position. A sheet that came
	back from a Japanese reviewer must still load on an English session.
	"""
	permissions.only_translate()
	content = frappe.get_doc("File", {"file_url": file_url}).get_content()
	if isinstance(content, bytes):
		content = content.decode("utf-8-sig")

	applied = 0
	skipped = 0
	reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
	column = _proposal_column(reader.fieldnames or [])
	for row in reader:
		proposal = (row.get(column) or "").strip()
		name = (row.get("ID") or "").strip()
		if not proposal or not name:
			continue
		# A row that no longer matches this locale is reported rather than
		# silently dropped: it usually means the wrong sheet was uploaded.
		if not frappe.db.exists("Translation Entry", {"name": name, "locale": locale}):
			skipped += 1
			continue
		entry = frappe.get_doc("Translation Entry", name)
		if entry.translated_text == proposal:
			continue
		entry.translated_text = proposal
		entry.status = "Reviewed"
		entry.save(ignore_permissions=True)
		applied += 1

	return {"applied": applied, "skipped": skipped}


@frappe.whitelist()
def replace_term(locale: str, find: str, replace: str, dry_run: int = 1):
	"""Change one term everywhere it was used.

	Returns the affected rows before touching anything: a glossary decision that
	moves 400 strings should be seen before it is made.
	"""
	permissions.only_translate()
	rows = frappe.get_all(
		"Translation Entry",
		filters={"locale": locale, "translated_text": ("like", f"%{find}%")},
		fields=["name", "source_text", "translated_text", "app"],
		limit_page_length=0,
	)

	preview = [
		{
			"name": row.name,
			"app": row.app,
			"source_text": row.source_text,
			"before": row.translated_text,
			"after": row.translated_text.replace(find, replace),
		}
		for row in rows
	]

	if int(dry_run or 0):
		return {"count": len(preview), "rows": preview[:200], "applied": False}

	# Seeing what a replacement would do is part of translating. Doing it moves
	# every one of those rows at once, so it is the manager's call.
	permissions.only_manage(
		_("Running a bulk term change is reserved for {0}. You can still check its impact.").format(
			_("Localization Manager")
		)
	)
	for row in preview:
		frappe.db.set_value("Translation Entry", row["name"], "translated_text", row["after"])
	return {"count": len(preview), "rows": preview[:200], "applied": True}


@frappe.whitelist()
def coverage_by_locale():
	"""Coverage for every enabled locale, for the workspace chart."""
	permissions.only_read()
	return frappe.get_all(
		"Locale Profile",
		filters={"enabled": 1},
		fields=[
			"name",
			"locale_label",
			"language",
			"currency",
			"total_strings",
			"translated_strings",
			"untranslated_strings",
			"coverage",
			"open_issues",
			"last_scanned_on",
		],
		order_by="coverage desc",
	)


PROPOSAL_COLUMNS = ("Proposed Change", "修正案")


def _proposal_column(headers: list[str]) -> str:
	for name in PROPOSAL_COLUMNS:
		if name in headers:
			return name
	# Position is the last resort: the sheet has a fixed layout, and a header
	# translated into a language not listed above still has the column here.
	return headers[8] if len(headers) > 8 else PROPOSAL_COLUMNS[0]


def _download(filename: str, content: str):
	frappe.response["type"] = "binary"
	frappe.response["filename"] = filename
	# BOM so the file opens correctly in Excel, which is where reviews happen
	frappe.response["filecontent"] = content.encode("utf-8-sig")
