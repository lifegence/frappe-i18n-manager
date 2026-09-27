"""Number cards for the workspace.

The workspace itself is a file in the app, but Number Card records are not
exported by Frappe in developer mode, so they are created on install instead of
being carried as fixtures.
"""

import json

import frappe

CARDS = [
	{
		"name": "Ledger Rows",
		"document_type": "Translation Entry",
		"filters_json": "[]",
	},
	{
		"name": "Untranslated Strings",
		"document_type": "Translation Entry",
		"filters_json": json.dumps([["Translation Entry", "status", "=", "Untranslated", False]]),
	},
	{
		"name": "Open Issues",
		"document_type": "Translation Issue",
		"filters_json": json.dumps([["Translation Issue", "status", "=", "Open", False]]),
	},
]


def create_number_cards():
	for card in CARDS:
		if frappe.db.exists("Number Card", card["name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Number Card",
				"module": "Localization",
				"type": "Document Type",
				"function": "Count",
				"is_public": 1,
				"show_percentage_stats": 0,
				"label": card["name"],
				**card,
			}
		).insert(ignore_permissions=True)
