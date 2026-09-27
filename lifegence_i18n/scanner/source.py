"""Route 1 — strings that appear in source code.

This is the same collection Frappe's own `bench get-untranslated` uses, so the
numbers are directly comparable. What the app adds is that the result is kept
as a ledger rather than a throwaway file, and measured per app.
"""

import frappe
from frappe.translate import get_messages_for_app

from lifegence_i18n.utils import classify, compiled_exclusion_rules, get_settings


def collect(apps: list[str]) -> list[dict]:
	"""Return one record per distinct (source, context) found in the app's code."""
	# `get_messages_from_file` remembers every path it has already read in
	# `frappe.flags.scanned_files` and returns nothing for a repeat. Frappe runs
	# that collection once per process, so it never notices; a background worker
	# that scans four locales in a row would measure the first one correctly and
	# report roughly half the strings for the rest.
	frappe.flags.scanned_files = set()

	rules = compiled_exclusion_rules()
	min_length = get_settings().min_string_length or 2

	collected: dict[tuple[str, str], dict] = {}
	for app in apps:
		try:
			messages = get_messages_for_app(app)
		except Exception as exc:
			frappe.log_error(f"{app}: {exc}", "I18n source scan")
			continue

		for message in messages:
			if not isinstance(message, list | tuple) or len(message) < 2:
				continue
			position = message[0] or ""
			text = message[1]
			context = message[2] if len(message) > 2 else None
			line_no = message[3] if len(message) > 3 else None

			if not isinstance(text, str):
				continue

			verdict = classify(text, rules, min_length)
			if not verdict.keep:
				continue

			key = (text, context or "")
			existing = collected.get(key)
			if existing:
				existing["occurrences"] += 1
				continue

			collected[key] = {
				"source_text": text,
				"context": context or None,
				"app": app,
				"origin": "Source Code",
				"string_class": "UI Text",
				"na_reason": verdict.na_reason,
				"na_rule": verdict.na_rule,
				"auto_apply": verdict.auto_apply,
				"source_path": str(position)[:140] or None,
				"line_no": line_no or 0,
				"occurrences": 1,
			}

	return list(collected.values())
