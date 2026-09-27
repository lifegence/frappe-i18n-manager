"""Move `ignore_patterns` onto the Exclusion Rules table.

The old field dropped a matching string before it ever reached the ledger, so
the reason it was excluded existed nowhere. The rules carry a reason and the
row is kept, which is the whole point of the change; the patch therefore has to
guess a reason for whatever the operator had written by hand. Anything that is
not one of the shipped defaults is filed as Manual for someone to look at.
"""

import frappe

from lifegence_i18n.setup.install import seed_exclusion_rules
from lifegence_i18n.utils import DEFAULT_EXCLUSION_RULES


def execute():
	if not frappe.db.exists("DocType", "I18n Exclusion Rule"):
		return

	settings = frappe.get_single("I18n Settings")
	known = {rule["pattern"] for rule in DEFAULT_EXCLUSION_RULES}
	present = {row.pattern for row in settings.get("exclusion_rules") or []}

	for line in (settings.get("ignore_patterns") or "").splitlines():
		pattern = line.strip()
		if not pattern or pattern in known or pattern in present:
			continue
		settings.append(
			"exclusion_rules",
			{
				"rule_name": pattern[:60],
				"pattern": pattern,
				"na_reason": "Manual",
				"auto_apply": 1,
				"enabled": 1,
			},
		)
		present.add(pattern)

	seed_exclusion_rules(settings)
	settings.save(ignore_permissions=True)

	# Roles and master data were measured alongside interface text, so every
	# existing coverage figure mixes three kinds of string. Turning them off
	# forces the next scan to produce a number that means one thing.
	frappe.db.sql("update `tabLocale Profile` set scan_master_data = 0, scan_roles = 0")
