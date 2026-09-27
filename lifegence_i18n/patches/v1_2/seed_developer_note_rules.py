"""Add the Expression, API Path and Colour Code rules to sites installed
before they existed. They apply automatically, so a settings value the
collectors picked up stops counting as an untranslated string.
"""

import frappe

from lifegence_i18n.setup.install import seed_exclusion_rules


def execute():
	if not frappe.db.exists("DocType", "I18n Exclusion Rule"):
		return
	settings = frappe.get_single("I18n Settings")
	if seed_exclusion_rules(settings):
		settings.save(ignore_permissions=True)
