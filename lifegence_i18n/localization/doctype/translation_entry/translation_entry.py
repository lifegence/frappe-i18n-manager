import frappe
from frappe.model.document import Document

from lifegence_i18n.utils import text_hash


class TranslationEntry(Document):
	def validate(self):
		self.text_hash = text_hash(self.source_text, self.context)
		self._reject_duplicate()
		if self.translated_text and self.status == "Untranslated":
			self.status = "Draft"
		if not self.translated_text and self.status in ("Draft", "Reviewed", "Approved"):
			self.status = "Untranslated"

	def _reject_duplicate(self):
		duplicate = frappe.db.exists(
			"Translation Entry",
			{"locale": self.locale, "text_hash": self.text_hash, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				frappe._("A row with the same source text and context already exists: {0}").format(
					frappe.utils.get_link_to_form("Translation Entry", duplicate)
				)
			)
