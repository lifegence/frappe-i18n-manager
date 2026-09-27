import frappe


def after_install():
	"""Seed the settings singleton. Tolerant of a first install where the
	DocTypes are not on disk yet (the app is installed before they are created)."""
	if not frappe.db.exists("DocType", "I18n Settings"):
		return

	from lifegence_i18n.setup.desk import create_number_cards

	settings = frappe.get_single("I18n Settings")
	if not settings.source_language:
		settings.source_language = "en"
	if not settings.allowed_latin_terms:
		settings.allowed_latin_terms = "\n".join(DEFAULT_ALLOWED_LATIN)
	seed_exclusion_rules(settings)
	settings.save(ignore_permissions=True)

	create_number_cards()


# Brand names, units and identifiers that legitimately stay in Latin script in
# every target language. Without this list the "Latin residue" check reports
# every correct translation that mentions a product name.
DEFAULT_ALLOWED_LATIN = [
	"ERPNext",
	"Frappe",
	"SKU",
	"BOM",
	"MRP",
	"WMS",
	"EDI",
	"CSV",
	"PDF",
	"URL",
	"API",
	"ID",
	"QR",
	"UOM",
	"FIFO",
	"HTML",
	"JSON",
	"kg",
	"cm",
	"mm",
	"ml",
]


def seed_exclusion_rules(settings) -> int:
	"""Fill in the default exclusion rules, leaving any the operator added.

	Matching is by pattern rather than name so a renamed rule is not duplicated.
	"""
	from lifegence_i18n.utils import DEFAULT_EXCLUSION_RULES

	present = {row.pattern for row in settings.get("exclusion_rules") or []}
	added = 0
	for rule in DEFAULT_EXCLUSION_RULES:
		if rule["pattern"] in present:
			continue
		settings.append("exclusion_rules", {**rule, "enabled": 1})
		added += 1
	return added
