import typing

import frappe
from frappe import _
from frappe.model.document import Document

from lifegence_i18n import permissions

LATIN_SCRIPT_LANGUAGES = {
	"af",
	"bs",
	"ca",
	"cs",
	"cy",
	"da",
	"de",
	"en",
	"eo",
	"es",
	"et",
	"eu",
	"fi",
	"fr",
	"ga",
	"gl",
	"hr",
	"hu",
	"id",
	"is",
	"it",
	"lt",
	"lv",
	"ms",
	"mt",
	"nb",
	"nl",
	"nn",
	"pl",
	"pt",
	"ro",
	"sk",
	"sl",
	"sq",
	"sv",
	"sw",
	"tl",
	"tr",
	"vi",
	"zu",
}


class LocaleProfile(Document):
	def _validate_links(self):
		"""Provision the Language record before the link check runs.

		Frappe validates links on insert *before* `before_insert` and `validate`,
		so a locale for a language it has never seen — zh-HK, for instance — would
		be rejected outright. This is the only hook that runs early enough.
		"""
		self._ensure_language()
		self._ensure_currency()
		return super()._validate_links()

	def validate(self):
		self.locale_code = (self.locale_code or "").strip()
		if not self.locale_label:
			self.locale_label = f"{self.country} ({self.language})"
		if self.fallback_locale == self.name:
			frappe.throw(_("A locale cannot fall back to itself"))

		if not self.time_zone and self.country:
			zones = frappe.db.get_value("Country", self.country, "time_zones") or ""
			self.time_zone = zones.split("\n")[0].strip() or None

		self.uses_latin_script = 1 if self._base_language() in LATIN_SCRIPT_LANGUAGES else 0

	def _base_language(self) -> str:
		code = (self.language or "").replace("_", "-")
		return code.split("-")[0].lower()

	def _ensure_language(self):
		"""A locale for a language Frappe has never seen must still be usable.

		Adding Hong Kong means adding `zh-HK`, which is not a stock Language
		record. Without this the profile could be saved and then silently
		measure nothing.
		"""
		if not self.language:
			return
		if frappe.db.exists("Language", self.language):
			# Frappe ships most languages disabled. A locale nobody can select is
			# not a locale, so managing one implies enabling it.
			if self.enabled and not frappe.db.get_value("Language", self.language, "enabled"):
				frappe.db.set_value("Language", self.language, "enabled", 1)
			return
		if not frappe.db.get_single_value("I18n Settings", "auto_create_language"):
			frappe.throw(_("Language {0} is not registered").format(self.language))

		base = self._base_language()
		frappe.get_doc(
			{
				"doctype": "Language",
				"language_code": self.language,
				"language_name": self.locale_label or self.language,
				"enabled": 1,
				"based_on": base if base != self.language and frappe.db.exists("Language", base) else None,
			}
		).insert(ignore_permissions=True)
		frappe.msgprint(_("Created language {0}").format(self.language), alert=True)

	def _ensure_currency(self):
		if not self.currency or not frappe.db.exists("Currency", self.currency):
			return
		if frappe.db.get_value("Currency", self.currency, "enabled"):
			return
		if not frappe.db.get_single_value("I18n Settings", "auto_enable_currency"):
			return
		frappe.db.set_value("Currency", self.currency, "enabled", 1)
		frappe.msgprint(_("Enabled currency {0}").format(self.currency), alert=True)

	# ------------------------------------------------------------------ actions

	@frappe.whitelist()
	def run_scan(self):
		permissions.only_manage()
		if self.scan_screens:
			from lifegence_i18n.scanner import screen

			if not screen.is_available():
				frappe.throw(
					_(
						"Playwright is required for the screen crawl. Install it on this server "
						'(pip install "lifegence_i18n[screen]") or turn off Rendered Screens.'
					)
				)
		scan = frappe.get_doc(
			{
				"doctype": "Translation Scan",
				"locale": self.name,
				"scan_source": self.scan_source,
				"scan_database": self.scan_database,
				"scan_messages": self.scan_messages,
				"scan_screens": self.scan_screens,
			}
		).insert(ignore_permissions=True)
		scan.enqueue_run()
		return scan.name

	@frappe.whitelist()
	def verify_delivery(self):
		"""Check whether the approved translations reached this site.

		Deliberately separate from a scan: a scan is slow and measures what
		*should* be translated, while this is quick and answers whether the
		answer arrived. After a deployment it is the only question worth asking.
		"""
		permissions.only_translate()
		from lifegence_i18n.scanner import delivery

		result = delivery.verify(self.name)
		delivery.summarise(self.name, result)
		return result

	@frappe.whitelist()
	def approve_drafts(self):
		"""Promote every reviewed-by-hand translation to Approved.

		Editing a row leaves it Draft on purpose — a translation someone typed
		is not the same as one anyone has agreed to. This is the deliberate act
		of agreeing to them, rather than a silent side effect of applying.
		"""
		permissions.only_manage()
		names = frappe.get_all(
			"Translation Entry",
			filters={"locale": self.name, "status": "Draft", "translated_text": ("is", "set")},
			pluck="name",
		)
		for name in names:
			frappe.db.set_value("Translation Entry", name, "status", "Approved", update_modified=False)
		return {"approved": len(names)}

	@frappe.whitelist()
	def draft_count(self):
		return frappe.db.count(
			"Translation Entry",
			{"locale": self.name, "status": "Draft", "translated_text": ("is", "set")},
		)

	@frappe.whitelist()
	def apply_to_site(self):
		"""Push the ledger onto the running site.

		Formats go onto the Language record — that is where Frappe reads them —
		and approved translations become Translation records, which win over
		anything shipped in an app.
		"""
		permissions.only_manage()
		formats = self._apply_formats()
		created, updated, drafts = self._apply_translations()
		frappe.translate.clear_cache()
		return {"created": created, "updated": updated, "drafts": drafts, "formats": formats}

	FORMAT_FIELDS: typing.ClassVar[dict[str, str]] = {
		"date_format": "date_format",
		"time_format": "time_format",
		"number_format": "number_format",
		"first_day_of_the_week": "first_day_of_week",
	}

	def _apply_formats(self) -> bool:
		"""Write the display formats onto the Language record.

		Frappe v15 has no such fields on Language — per-language formats arrived
		in v16. Assigning them there would be accepted by the Document object and
		dropped on save, so the operator would be told the locale had been
		applied while dates carried on rendering in the site default. Report it
		instead.
		"""
		language = frappe.get_doc("Language", self.language)
		language.enabled = 1

		meta = frappe.get_meta("Language")
		supported = all(meta.has_field(field) for field in self.FORMAT_FIELDS)
		if supported:
			for field, source in self.FORMAT_FIELDS.items():
				language.set(field, self.get(source))

		language.save(ignore_permissions=True)
		return supported

	def _apply_translations(self) -> tuple[int, int, int]:
		entries = frappe.get_all(
			"Translation Entry",
			filters={
				"locale": self.name,
				"status": ("in", ["Approved", "Reviewed"]),
				"translated_text": ("is", "set"),
			},
			fields=["source_text", "translated_text", "context", "upstream_translation"],
			limit_page_length=0,
		)

		# A translation typed into the ledger becomes a Draft, and Draft is not
		# applied. Saying nothing about that turns "I edited it and applied it"
		# into a change that never reached the screen and never reported why.
		drafts = frappe.db.count(
			"Translation Entry",
			{"locale": self.name, "status": "Draft", "translated_text": ("is", "set")},
		)

		existing = {
			(row.source_text, row.context or ""): row.name
			for row in frappe.get_all(
				"Translation",
				filters={"language": self.language},
				fields=["name", "source_text", "context"],
				limit_page_length=0,
			)
		}

		created = updated = 0
		for entry in entries:
			# Anything Frappe already resolves to the same string needs no record.
			if entry.translated_text == entry.upstream_translation:
				continue
			key = (entry.source_text, entry.context or "")
			if key in existing:
				frappe.db.set_value("Translation", existing[key], "translated_text", entry.translated_text)
				updated += 1
			else:
				frappe.get_doc(
					{
						"doctype": "Translation",
						"language": self.language,
						"source_text": entry.source_text,
						"translated_text": entry.translated_text,
						"context": entry.context,
					}
				).insert(ignore_permissions=True)
				created += 1
		return created, updated, drafts


@frappe.whitelist()
def add_locale(country: str, language: str, currency: str, locale_code: str, locale_label: str | None = None):
	"""Create a locale from the four things a new country needs.

	Exposed separately so adding Hong Kong later is one call, not a form the
	operator has to fill correctly from memory.

	It inserts without permission checks, so it has to make its own: this is a
	whitelisted call, reachable by anyone with a session.
	"""
	permissions.only_manage()
	if frappe.db.exists("Locale Profile", locale_code):
		return locale_code
	profile = frappe.get_doc(
		{
			"doctype": "Locale Profile",
			"locale_code": locale_code,
			"locale_label": locale_label or f"{country} ({language})",
			"country": country,
			"language": language,
			"currency": currency,
		}
	).insert(ignore_permissions=True)
	return profile.name
