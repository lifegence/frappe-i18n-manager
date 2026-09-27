"""One ledger row per (locale, text_hash), enforced by the database.

The ledger's identity has always been (locale, source text, context), which
`text_hash` encodes, but only the application layer checked it and
`bulk_insert` does not. Two scans running at once could therefore write the
same string twice. This patch folds any such duplicates into one row — the
one that holds a translation or the earliest — repoints the issues that
referred to the others, and then adds the constraint.
"""

import frappe

RANK = {"Approved": 0, "Reviewed": 1, "Draft": 2, "Not Applicable": 3, "Untranslated": 4}


def execute():
	groups = frappe.db.sql(
		"""select locale, text_hash, count(*) as n from `tabTranslation Entry`
		   where text_hash is not null and text_hash != ''
		   group by locale, text_hash having n > 1""",
		as_dict=True,
	)
	for group in groups:
		rows = frappe.get_all(
			"Translation Entry",
			filters={"locale": group.locale, "text_hash": group.text_hash},
			fields=["name", "status", "translated_text", "creation"],
			order_by="creation asc",
		)
		rows.sort(key=lambda r: (not r.translated_text, RANK.get(r.status, 9), r.creation))
		keep, drop = rows[0], rows[1:]
		names = [r.name for r in drop]
		frappe.db.set_value(
			"Translation Issue",
			{"translation_entry": ("in", names)},
			"translation_entry",
			keep.name,
			update_modified=False,
		)
		frappe.db.delete("Translation Entry", {"name": ("in", names)})
	frappe.db.commit()
	frappe.db.add_unique("Translation Entry", ["locale", "text_hash"])
