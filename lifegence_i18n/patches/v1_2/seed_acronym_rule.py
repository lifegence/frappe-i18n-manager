"""Add the Acronym rule to sites that were installed before it existed.

The rule only suggests a reason (auto_apply is off), so nothing changes status;
a bare acronym found by any route now carries "Acronym or Code" as a candidate
the way one found on screen already did.
"""

import frappe

from lifegence_i18n.setup.install import seed_exclusion_rules


def execute():
	if not frappe.db.exists("DocType", "I18n Exclusion Rule"):
		return
	settings = frappe.get_single("I18n Settings")
	if seed_exclusion_rules(settings):
		settings.save(ignore_permissions=True)
