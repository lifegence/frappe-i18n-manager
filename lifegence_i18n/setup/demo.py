"""Initial locale set and glossary seed.

The four countries here are the starting set, not a fixed list. `add_locale`
on Locale Profile creates any further country from four values (country,
language, currency, locale code); nothing in the app is keyed to these four.
"""

import frappe

from lifegence_i18n.setup.install import DEFAULT_ALLOWED_LATIN, seed_exclusion_rules

LOCALES = [
	{
		"locale_code": "ja-JP",
		"locale_label": "日本語（日本）",
		"country": "Japan",
		"language": "ja",
		"currency": "JPY",
		"date_format": "yyyy-mm-dd",
		"time_format": "HH:mm:ss",
		"number_format": "#,###.##",
		# The yen has no minor unit, so a 2-decimal display is wrong on every
		# amount, not merely untidy.
		"float_precision": 0,
		"first_day_of_week": "Sunday",
		"time_zone": "Asia/Tokyo",
	},
	{
		"locale_code": "zh-TW",
		"locale_label": "繁體中文（台灣）",
		"country": "Taiwan",
		"language": "zh-TW",
		"currency": "TWD",
		"date_format": "yyyy-mm-dd",
		"time_format": "HH:mm",
		"number_format": "#,###.##",
		"float_precision": 2,
		"first_day_of_week": "Sunday",
		"time_zone": "Asia/Taipei",
	},
	{
		"locale_code": "zh-HK",
		"locale_label": "繁體中文（香港）",
		"country": "Hong Kong",
		"language": "zh-HK",
		"currency": "HKD",
		"date_format": "dd/mm/yyyy",
		"time_format": "HH:mm",
		"number_format": "#,###.##",
		"float_precision": 2,
		"first_day_of_week": "Sunday",
		"time_zone": "Asia/Hong_Kong",
		# Frappe falls back zh-HK -> zh (Simplified). For Hong Kong the useful
		# fallback is Traditional Chinese, which Frappe will not do on its own.
		"fallback_locale": "zh-TW",
	},
	{
		"locale_code": "hr-HR",
		"locale_label": "Hrvatski (Hrvatska)",
		"country": "Croatia",
		"language": "hr",
		# Croatia replaced the kuna with the euro on 1 January 2023.
		"currency": "EUR",
		"date_format": "dd.mm.yyyy",
		"time_format": "HH:mm",
		"number_format": "#.###,##",
		"float_precision": 2,
		"first_day_of_week": "Monday",
		"time_zone": "Europe/Zagreb",
	},
]

GLOSSARY = {
	"ja-JP": [
		("Item", "品目", {"forbidden_terms": "アイテム"}),
		("Customer", "得意先", {"forbidden_terms": "顧客"}),
		("Supplier", "仕入先", {}),
		("Warehouse", "倉庫", {}),
		("Sales Order", "受注", {"match_type": "Substring"}),
		("Purchase Order", "発注", {"match_type": "Substring"}),
		("Delivery Note", "納品書", {"match_type": "Substring"}),
		("Stock Entry", "在庫エントリ", {"match_type": "Substring"}),
		("Acme", None, {"do_not_translate": 1}),
	],
	"zh-TW": [
		("Item", "項目", {}),
		("Customer", "客戶", {}),
		("Supplier", "供應商", {}),
		("Warehouse", "倉庫", {}),
		("Sales Order", "銷售訂單", {"match_type": "Substring"}),
		("Purchase Order", "採購訂單", {"match_type": "Substring"}),
		("Acme", None, {"do_not_translate": 1}),
	],
	"zh-HK": [
		("Item", "項目", {}),
		("Customer", "客戶", {}),
		("Supplier", "供應商", {}),
		("Warehouse", "倉庫", {}),
		("Acme", None, {"do_not_translate": 1}),
	],
	"hr-HR": [
		("Item", "Artikl", {}),
		("Customer", "Kupac", {}),
		("Supplier", "Dobavljač", {}),
		("Warehouse", "Skladište", {}),
		("Sales Order", "Prodajni nalog", {"match_type": "Substring"}),
		("Acme", None, {"do_not_translate": 1}),
	],
}


def setup_initial_locales():
	_settings()
	created = []
	# Two passes: zh-HK points at zh-TW, which must exist first.
	for payload in LOCALES:
		created.append(_locale(dict(payload, fallback_locale=None)))
	for payload in LOCALES:
		if payload.get("fallback_locale"):
			frappe.db.set_value(
				"Locale Profile", payload["locale_code"], "fallback_locale", payload["fallback_locale"]
			)

	for locale_code, terms in GLOSSARY.items():
		_glossary(locale_code, terms)

	# A setup script run from `bench execute`.
	frappe.db.commit()  # nosemgrep
	print(f"{len(created)} locales, {sum(len(v) for v in GLOSSARY.values())} glossary terms")
	return created


def _settings():
	settings = frappe.get_single("I18n Settings")
	settings.source_language = "en"
	settings.min_string_length = 2
	if not settings.allowed_latin_terms:
		settings.allowed_latin_terms = "\n".join(DEFAULT_ALLOWED_LATIN)
	seed_exclusion_rules(settings)
	settings.save(ignore_permissions=True)


def _locale(payload: dict) -> str:
	code = payload["locale_code"]
	if frappe.db.exists("Locale Profile", code):
		profile = frappe.get_doc("Locale Profile", code)
		profile.update({k: v for k, v in payload.items() if v is not None})
	else:
		profile = frappe.get_doc({"doctype": "Locale Profile", **payload})
	profile.save(ignore_permissions=True)
	return code


def _glossary(locale_code: str, terms: list[tuple]):
	if not frappe.db.exists("Locale Profile", locale_code):
		return
	for source_term, translated_term, extra in terms:
		if frappe.db.exists("Glossary Term", {"locale": locale_code, "source_term": source_term}):
			continue
		frappe.get_doc(
			{
				"doctype": "Glossary Term",
				"locale": locale_code,
				"source_term": source_term,
				"translated_term": translated_term,
				"enforce": 1,
				"case_sensitive": 1,
				"match_type": "Word",
				**extra,
			}
		).insert(ignore_permissions=True)
