"""Is the approved translation actually on the screen?

Everything else in this app measures what *should* be translated. Nothing
measured whether the answer ever arrived. On the engagement this app was built
for, 1,181 approved rows sat merged in `develop` for a week while production
served English, and the first person to notice was the customer.

Three dictionaries answer it, and the distinction between the second and the
third is the whole point:

    L  the ledger          approved rows
    F  the files           <app>/translations/<lang>.csv and the .mo catalogues,
                           read from disk without touching the cache
    R  the running site    what Frappe resolves right now, cache included

    in L, in R                          Live
    in L, in F, not in R                Cache Stale     -> bench clear-cache
    in L, in some app's file, but a
      later file or a Translation
      record wins                       Overridden      -> fix the merge order
    in L, in no file                    Not Deployed    -> not exported, merged
                                                           or deployed yet

"In F" means the value the files resolve to once merged in app order, read
from disk. A row whose approved value is in no file at all is Not Deployed
whatever the site shows meanwhile — an older value of the same string, or an
upstream translation — because nothing has been delivered yet.

Reading F from disk is what separates "the file never got here" from "the file
is here and the site is serving a stale copy", which are the same symptom and
completely different fixes.
"""

import frappe

from lifegence_i18n.utils import resolved_key

LIVE = "Live"
STALE = "Cache Stale"
NOT_DEPLOYED = "Not Deployed"
OVERRIDDEN = "Overridden"

# Worst first: the state a locale reports is the worst state any of its rows is
# in, because one undelivered string is a delivery that did not happen.
SEVERITY = [NOT_DEPLOYED, OVERRIDDEN, STALE, LIVE]

CHUNK = 500


def verify(locale: str) -> dict:
	"""Compare the ledger against the files and the running site.

	Writes `delivery_status` onto each approved entry and returns the counts.
	Nothing else on the ledger is touched — this is a measurement, not an edit.
	"""
	profile = frappe.get_doc("Locale Profile", locale)
	language = profile.language

	entries = frappe.get_all(
		"Translation Entry",
		filters={
			"locale": locale,
			"status": ("in", ["Approved", "Reviewed"]),
			"translated_text": ("is", "set"),
		},
		fields=["name", "source_text", "context", "translated_text", "delivery_status"],
		limit_page_length=0,
	)

	from frappe.translate import get_all_translations

	from_files, in_any_file = _file_translations(language)
	resolved = get_all_translations(language)
	# A site Translation record outranks every file. When the files resolve to
	# the approved value and the site still shows another, this is what wins.
	overriding_records = {
		resolved_key(row.source_text, row.context)
		for row in frappe.get_all(
			"Translation", filters={"language": language}, fields=["source_text", "context"]
		)
	}

	counts = dict.fromkeys(SEVERITY, 0)
	updates: list[tuple[str, str]] = []

	for entry in entries:
		# `_()` strips before it looks anything up, so a padded ledger entry is
		# served by the stripped key. Comparing on the padded one would report a
		# delivered translation as Not Deployed for ever.
		key = resolved_key(entry.source_text, entry.context)
		wanted = entry.translated_text
		on_disk = from_files.get(key)
		on_screen = resolved.get(key)

		if on_screen == wanted:
			state = LIVE
		elif on_disk == wanted:
			# The files resolve to it and the site does not serve it: the cache
			# predates the file, unless a Translation record replaces it.
			state = OVERRIDDEN if key in overriding_records else STALE
		elif wanted in in_any_file.get(key, ()):
			# Some app's file carries it, and a file later in the merge order
			# carries something else.
			state = OVERRIDDEN
		else:
			state = NOT_DEPLOYED

		counts[state] += 1
		if entry.delivery_status != state:
			updates.append((entry.name, state))

	for offset in range(0, len(updates), CHUNK):
		for name, state in updates[offset : offset + CHUNK]:
			frappe.db.set_value("Translation Entry", name, "delivery_status", state, update_modified=False)

	approved = len(entries)
	pending = counts[NOT_DEPLOYED] + counts[STALE] + counts[OVERRIDDEN]
	return {
		"approved": approved,
		"live": counts[LIVE],
		"pending": pending,
		"not_deployed": counts[NOT_DEPLOYED],
		"stale": counts[STALE],
		"overridden": counts[OVERRIDDEN],
		"state": _worst(counts) if approved else "Unknown",
	}


def _worst(counts: dict[str, int]) -> str:
	for state in SEVERITY:
		if counts.get(state):
			return state
	return "Unknown"


def _file_translations(language: str) -> tuple[dict[str, str], dict[str, set[str]]]:
	"""What the installed apps' files hold, read past the cache.

	`get_all_translations` would answer from Redis, which is precisely the thing
	being tested. `get_translations_from_csv` reads the file every time.

	Returns the merged view (later apps win, the order Frappe applies) and,
	per key, every value any app's file carries, so a value a later file
	replaced can still be told apart from one no file has.
	"""
	from frappe.gettext.translate import get_translations_from_mo
	from frappe.translate import get_translations_from_csv

	merged: dict[str, str] = {}
	values: dict[str, set[str]] = {}
	for app in frappe.get_installed_apps():
		for reader in (get_translations_from_mo, get_translations_from_csv):
			try:
				found = reader(language, app) or {}
			except Exception:
				continue
			merged.update(found)
			for key, value in found.items():
				values.setdefault(key, set()).add(value)
	return merged, values


def summarise(locale: str, result: dict) -> None:
	"""Record the outcome on the Locale Profile."""
	frappe.db.set_value(
		"Locale Profile",
		locale,
		{
			"approved_strings": result["approved"],
			"live_strings": result["live"],
			"pending_strings": result["pending"],
			"delivery_state": result["state"],
			"last_verified_on": frappe.utils.now_datetime(),
		},
		update_modified=False,
	)
