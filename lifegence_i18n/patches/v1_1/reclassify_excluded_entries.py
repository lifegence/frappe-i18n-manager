"""Apply the exclusion rules to the ledger that already exists.

Only rows nobody has ruled on are touched. A row someone approved, drafted or
reviewed carries a human decision, and a regular expression does not get to
overturn one.
"""

import frappe

from lifegence_i18n.utils import classify, compiled_exclusion_rules

CHUNK = 500


def execute():
	if not frappe.db.has_column("Translation Entry", "na_reason"):
		return

	rules = compiled_exclusion_rules()
	if not rules:
		return

	min_length = frappe.db.get_single_value("I18n Settings", "min_string_length") or 2
	roles = set(frappe.get_all("Role", pluck="name"))

	rows = frappe.get_all(
		"Translation Entry",
		filters={"status": "Untranslated"},
		fields=["name", "source_text", "origin", "reference_doctype"],
		limit_page_length=0,
	)

	updates: list[tuple[str, dict]] = []
	for row in rows:
		values = {}
		if row.source_text in roles or row.reference_doctype == "Role":
			values["string_class"] = "Role Name"

		verdict = classify(row.source_text, rules, min_length)
		if verdict.na_reason:
			values["na_reason"] = verdict.na_reason
			values["na_rule"] = verdict.na_rule
			if verdict.auto_apply:
				values["status"] = "Not Applicable"
		if values:
			updates.append((row.name, values))

	for name, values in updates:
		frappe.db.set_value("Translation Entry", name, values, update_modified=False)

	frappe.db.commit()
