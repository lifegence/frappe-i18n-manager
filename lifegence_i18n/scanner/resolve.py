"""Work out which translation a locale should actually use.

Frappe resolves a variant language by falling back to its parent: `zh-HK` has
no files of its own, so it takes `zh` — Simplified Chinese. For Hong Kong that
is the wrong script. The useful fallback is `zh-TW`, and Frappe will never do
that on its own because the two are siblings, not parent and child.

So a locale's translation is decided in this order:

    1. translations belonging to the exact language code
    2. the ledger of the locale's fallback locale
    3. whatever Frappe resolves today (which includes the parent language)

Step 3 is kept as `upstream_translation` — the string on screen right now — so
that "apply to site" can write exactly the rows where the ledger disagrees.
"""

import frappe

MAX_FALLBACK_DEPTH = 5


def own_translations(language: str) -> dict[str, str]:
	"""Translations that belong to this language code and no other.

	`get_all_translations` merges the parent language in, which is precisely the
	behaviour we need to see past: a value inherited from `zh` must not look
	like a value that exists for `zh-HK`.
	"""
	from frappe.translate import get_translations_from_csv

	translations: dict[str, str] = {}
	for app in frappe.get_installed_apps():
		# The CSV path is literal, so it never picks up another language.
		translations.update(get_translations_from_csv(language, app) or {})
		translations.update(_exact_mo(language, app))

	for row in frappe.get_all(
		"Translation",
		filters={"language": language},
		fields=["source_text", "translated_text", "context"],
		limit_page_length=0,
	):
		key = f"{row.source_text}:{row.context}" if row.context else row.source_text
		translations[key] = row.translated_text

	return translations


def _exact_mo(language: str, app: str) -> dict[str, str]:
	"""Compiled translations for this exact language code.

	`gettext.find` expands the language before searching: asked for `zh_HK` it
	happily returns the `zh` catalogue. That is the right behaviour for
	rendering a page and the wrong one here — it makes an inherited translation
	indistinguishable from one the locale actually has, which is the single
	distinction this module exists to draw.
	"""
	import gettext

	from frappe.gettext.translate import get_locale_dir, get_translations_from_mo

	code = language.replace("-", "_")
	found = gettext.find(app, get_locale_dir(), (code,))
	if not found or f"/{code}/LC_MESSAGES/" not in found:
		return {}
	return get_translations_from_mo(language, app) or {}


def fallback_ledger(locale: str) -> dict[str, str]:
	"""The translations of the fallback chain, keyed by text hash.

	Walks the chain so zh-HK -> zh-TW -> … resolves, with a depth limit rather
	than a visited set alone, because a chain someone edits into a loop should
	stop rather than hang.
	"""
	translations: dict[str, str] = {}
	seen = {locale}
	current = frappe.db.get_value("Locale Profile", locale, "fallback_locale")

	depth = 0
	while current and current not in seen and depth < MAX_FALLBACK_DEPTH:
		seen.add(current)
		depth += 1
		for row in frappe.get_all(
			"Translation Entry",
			filters={
				"locale": current,
				"translated_text": ("is", "set"),
				# Only what that locale genuinely has. Most of the zh-TW ledger is
				# itself inherited Simplified Chinese; passing that on to zh-HK
				# would launder an inherited string into an owned one and make
				# Hong Kong look five times readier than it is.
				"translation_source": ("in", ["Own", "Fallback"]),
			},
			fields=["text_hash", "translated_text"],
			limit_page_length=0,
		):
			# Nearer links in the chain win, so do not overwrite what is set.
			translations.setdefault(row.text_hash, row.translated_text)
		current = frappe.db.get_value("Locale Profile", current, "fallback_locale")

	return translations
