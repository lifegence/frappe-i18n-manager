import hashlib
import re
from typing import NamedTuple

import frappe


def text_hash(source_text: str, context: str | None = None) -> str:
	"""Stable identity for a ledger row.

	The source string is hashed verbatim, padding included, so the ledger can
	still show where a padded literal came from. Note that this is *not* the key
	a translation is resolved by — see `resolved_key`.
	"""
	payload = f"{source_text}\x00{context or ''}".encode()
	return hashlib.sha256(payload).hexdigest()[:32]


def translation_key(source_text: str, context: str | None = None) -> str:
	"""The dictionary key, formed the way Frappe writes one."""
	return f"{source_text}:{context}" if context else source_text


def resolved_key(source_text: str, context: str | None = None) -> str:
	"""The key a translation is actually looked up by on the server.

	`frappe._()` strips the message before consulting the dictionary
	(`frappe/utils/translations.py`), so a dictionary entry keyed " Save " can
	never match anything a Python caller asks for. The client is the exception:
	`frappe._` in `translate.js` looks the string up verbatim, so a padded key
	is reachable from JavaScript and nowhere else.

	Resolving by the stripped key is therefore right for everything except a
	string that only ever appears in a `__()` call with its padding intact —
	a case rare enough that reporting the padded entries (see
	`scanner/validate.py`) is a better answer than keying on them.
	"""
	stripped = (source_text or "").strip()
	return f"{stripped}:{context}" if context else stripped


def get_settings():
	return frappe.get_cached_doc("I18n Settings")


def as_lines(value: str | None) -> list[str]:
	if not value:
		return []
	return [line.strip() for line in value.splitlines() if line.strip()]


# --------------------------------------------------------------------- classify

NA_REASONS = [
	"Naming Series",
	"Acronym or Code",
	"Role Name",
	"Master Data",
	"Brand or Product Name",
	"Developer Note",
	"Placeholder Only",
	"Manual",
]


class Classification(NamedTuple):
	"""What a scanner should do with one collected string.

	`keep` false means the string is not worth a ledger row at all — empty,
	shorter than the configured minimum, or carrying no letters in any script.
	Everything else is kept, because a string that was excluded on purpose is
	a decision, and a decision that leaves no record cannot be explained to
	anyone who later asks why the number is what it is.
	"""

	keep: bool
	na_reason: str | None = None
	na_rule: str | None = None
	auto_apply: bool = False


KEEP = Classification(True)
DROP = Classification(False)


class ExclusionRule:
	"""One row of `I18n Settings.exclusion_rules`, compiled once per scan."""

	__slots__ = ("auto_apply", "na_reason", "pattern", "rule_name")

	def __init__(self, rule_name: str, pattern: re.Pattern, na_reason: str, auto_apply: bool):
		self.rule_name = rule_name
		self.pattern = pattern
		self.na_reason = na_reason
		self.auto_apply = auto_apply


def compiled_exclusion_rules() -> list[ExclusionRule]:
	rules: list[ExclusionRule] = []
	for row in get_settings().get("exclusion_rules") or []:
		if not row.enabled or not row.pattern:
			continue
		try:
			pattern = re.compile(row.pattern)
		except re.error:
			frappe.log_error(f"Invalid exclusion pattern: {row.pattern}", "I18n Settings")
			continue
		rules.append(
			ExclusionRule(row.rule_name or row.pattern, pattern, row.na_reason, bool(row.auto_apply))
		)
	return rules


def classify(text: str, rules: list[ExclusionRule], min_length: int = 2) -> Classification:
	"""Decide whether a collected string belongs in the ledger, and as what.

	Naming series, field codes and pure markup reach the message collectors but
	are never shown as prose. Dropping them outright — which is what this used
	to do — keeps the coverage figure honest but leaves nothing to point at when
	a customer asks what the excluded rows were. They are kept and marked.
	"""
	if not text or not text.strip():
		return DROP
	stripped = text.strip()
	if len(stripped) < min_length:
		return DROP
	# no letters at all — punctuation, numbers, symbols
	if not re.search(r"[^\W\d_]", stripped, re.UNICODE):
		return DROP

	for rule in rules:
		if rule.pattern.search(stripped):
			return Classification(True, rule.na_reason, rule.rule_name, rule.auto_apply)
	return KEEP


DEFAULT_EXCLUSION_RULES = [
	{
		"rule_name": "Naming Series",
		"pattern": r"^[A-Z]{2,}-\.?[A-Za-z#\.\-]*$",
		"na_reason": "Naming Series",
		"auto_apply": 1,
	},
	{
		"rule_name": "Lone Placeholder",
		"pattern": r"^\{[0-9a-zA-Z_]+\}$",
		"na_reason": "Placeholder Only",
		"auto_apply": 1,
	},
	{
		"rule_name": "URL",
		"pattern": r"^https?://",
		"na_reason": "Developer Note",
		"auto_apply": 1,
	},
	{
		"rule_name": "Dotted Path",
		"pattern": r"^[a-z_]+\.[a-z_.]+$",
		"na_reason": "Developer Note",
		"auto_apply": 1,
	},
	{
		"rule_name": "Lone HTML Tag",
		"pattern": r"^<[^>]+>$",
		"na_reason": "Placeholder Only",
		"auto_apply": 1,
	},
	# Settings hold values that are not prose: a condition an app evaluates, an
	# API path, a colour. They reach the collectors as strings all the same.
	{
		"rule_name": "Expression",
		"pattern": r"^eval:",
		"na_reason": "Developer Note",
		"auto_apply": 1,
	},
	{
		"rule_name": "API Path",
		"pattern": r"^/api/",
		"na_reason": "Developer Note",
		"auto_apply": 1,
	},
	{
		"rule_name": "Colour Code",
		"pattern": r"^#[0-9a-fA-F]{3,6}$",
		"na_reason": "Developer Note",
		"auto_apply": 1,
	},
	# A bare acronym ("SKU", "GRNI") is recorded with its likely reason but left
	# counting as untranslated until someone confirms it: half of them are codes
	# and half are words a translator would render (S-6 decides each one later).
	{
		"rule_name": "Acronym",
		"pattern": r"^[A-Z][A-Z0-9]{1,7}$",
		"na_reason": "Acronym or Code",
		"auto_apply": 0,
	},
]


# ------------------------------------------------------------------- glossary

BRAND_REASON = "Brand or Product Name"


class BrandRule:
	"""A glossary term marked Do Not Translate, compiled to match a whole string.

	"Acme ERP" as a label is a brand name and not a translation target; "Acme
	ERP Sync Status" is interface text that must keep the brand inside it, which
	the glossary check on the translation enforces. Only the first is excluded.
	"""

	__slots__ = ("pattern", "term")

	def __init__(self, term: str, case_sensitive: bool):
		self.term = term
		flags = 0 if case_sensitive else re.IGNORECASE
		self.pattern = re.compile(r"^\s*" + re.escape(term) + r"\s*$", flags)


def brand_rules(locale: str) -> list[BrandRule]:
	rows = frappe.get_all(
		"Glossary Term",
		filters={"locale": locale, "do_not_translate": 1, "enforce": 1},
		fields=["source_term", "case_sensitive"],
	)
	return [BrandRule(row.source_term, bool(row.case_sensitive)) for row in rows if row.source_term]


def brand_match(text: str, rules: list[BrandRule]) -> str | None:
	"""The glossary term `text` is, in its entirety, or None."""
	for rule in rules:
		if rule.pattern.match(text or ""):
			return rule.term
	return None
