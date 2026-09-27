"""Checks that a translation is not merely present but usable.

Every check here corresponds to a failure that actually happened on a
production localization: a placeholder dropped from a message, a translation
that never applied because the source string carried a trailing space, a
glossary term rendered three different ways across five apps.
"""

import collections
import re

from lifegence_i18n.utils import as_lines

BRACE_PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")
PERCENT_PLACEHOLDER = re.compile(r"%(?:\([0-9a-zA-Z_]+\))?[sdfr]")
HTML_TAG = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)")
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def check(
	source_text: str, translated_text: str, *, glossary, allowed_latin, latin_script: bool
) -> list[dict]:
	"""Return the issues found for one ledger row."""
	if not translated_text:
		return []

	issues: list[dict] = []
	issues.extend(_placeholders(source_text, translated_text))
	issues.extend(_html(source_text, translated_text))
	issues.extend(_whitespace(source_text, translated_text))
	issues.extend(_glossary(source_text, translated_text, glossary))
	if not latin_script:
		issues.extend(_latin_residue(source_text, translated_text, allowed_latin))
	return issues


def _placeholders(source_text: str, translated_text: str) -> list[dict]:
	for pattern, label in ((BRACE_PLACEHOLDER, "{}"), (PERCENT_PLACEHOLDER, "%")):
		in_source = collections.Counter(pattern.findall(source_text))
		in_translation = collections.Counter(pattern.findall(translated_text))
		if in_source == in_translation:
			continue
		missing = in_source - in_translation
		extra = in_translation - in_source
		detail = []
		if missing:
			detail.append("missing from translation: " + ", ".join(sorted(missing.elements())))
		if extra:
			detail.append("only in translation: " + ", ".join(sorted(extra.elements())))
		return [
			{
				"issue_type": "Placeholder Mismatch",
				"severity": "High",
				"detail": f"Placeholders ({label}) do not match. " + " / ".join(detail),
			}
		]
	return []


def _html(source_text: str, translated_text: str) -> list[dict]:
	in_source = collections.Counter(HTML_TAG.findall(source_text))
	in_translation = collections.Counter(HTML_TAG.findall(translated_text))
	if in_source == in_translation:
		return []

	def render(counter):
		return ", ".join(sorted(f"<{slash}{tag}>" for slash, tag in counter))

	missing = in_source - in_translation
	extra = in_translation - in_source
	detail = []
	if missing:
		detail.append("missing from translation: " + render(missing))
	if extra:
		detail.append("only in translation: " + render(extra))
	return [
		{
			"issue_type": "HTML Mismatch",
			"severity": "High",
			"detail": "HTML tags do not match. " + " / ".join(detail),
		}
	]


def _whitespace(source_text: str, translated_text: str) -> list[dict]:
	"""A source string with padding cannot be reached from Python.

	`frappe._()` strips the message before consulting the dictionary
	(`frappe/utils/translations.py`), so an entry keyed " Save " is dead weight
	as far as the server is concerned — the caller asks for "Save" and never
	finds it. Only `__()` in the browser looks a string up verbatim, so such an
	entry is reachable from JavaScript and nowhere else.

	This used to compare the padding on the source against the padding on the
	translation and report any difference. That was wrong in the ordinary case:
	Frappe returns the translation as written, so the padding is dropped by
	Frappe rather than by the translator, and the check fired on entries that
	were perfectly correct.
	"""
	if source_text == source_text.strip():
		return []
	return [
		{
			"issue_type": "Unreachable Whitespace",
			"severity": "Medium",
			"detail": (
				"The source string carries leading or trailing whitespace. "
				"_() strips the message before looking it up, so this entry can only "
				"be reached from a __() call in the browser that keeps the padding. "
				"Key it on the stripped string unless that is what it is for."
			),
		}
	]


def _glossary(source_text: str, translated_text: str, glossary) -> list[dict]:
	issues = []
	for term in glossary:
		if not term.pattern.search(source_text):
			continue

		if term.do_not_translate:
			if term.source_term not in translated_text:
				issues.append(
					{
						"issue_type": "Glossary Violation",
						"severity": "Medium",
						"detail": f'"{term.source_term}" must not be translated, but the source term is absent from the translation',
					}
				)
		elif term.translated_term and term.translated_term not in translated_text:
			issues.append(
				{
					"issue_type": "Glossary Violation",
					"severity": "Low",
					"detail": (
						f'The glossary renders "{term.source_term}" as "{term.translated_term}", '
						"which the translation does not contain"
					),
				}
			)

		for forbidden in term.forbidden:
			if forbidden in translated_text:
				issues.append(
					{
						"issue_type": "Forbidden Term",
						"severity": "High",
						"detail": f'Contains "{forbidden}", a rendering marked as not to be used (term: {term.source_term})',
					}
				)
	return issues


def _latin_residue(source_text: str, translated_text: str, allowed_latin: set[str]) -> list[dict]:
	leftover = []
	for word in LATIN_RUN.findall(translated_text):
		if word in allowed_latin or word.lower() in allowed_latin or word.upper() in allowed_latin:
			continue
		leftover.append(word)
	if not leftover:
		return []
	unique = sorted(set(leftover))
	# A translation identical to the source is untranslated, not "residual".
	if translated_text.strip() == source_text.strip():
		return []
	return [
		{
			"issue_type": "Latin Residue",
			"severity": "Low",
			"detail": "Latin script left in the translation: " + ", ".join(unique[:8]),
		}
	]


class GlossaryRule:
	"""A glossary row compiled once per scan rather than per string."""

	__slots__ = ("do_not_translate", "forbidden", "pattern", "source_term", "translated_term")

	def __init__(self, row):
		self.source_term = row.source_term
		self.translated_term = (row.translated_term or "").strip()
		self.do_not_translate = bool(row.do_not_translate)
		self.forbidden = as_lines(row.forbidden_terms)
		flags = 0 if row.case_sensitive else re.IGNORECASE
		if row.match_type == "Substring":
			expression = re.escape(row.source_term)
		else:
			expression = r"(?<![A-Za-z])" + re.escape(row.source_term) + r"(?![A-Za-z])"
		self.pattern = re.compile(expression, flags)


def compile_glossary(rows) -> list[GlossaryRule]:
	return [GlossaryRule(row) for row in rows if row.enforce]
