"""Route 2 — strings that reach the screen from the database, not from code.

`bench get-untranslated` only parses source files. A large part of what a user
reads is stored as data: onboarding steps, workspace cards, report names,
notification subjects, group and unit names. Those never appear in that command,
which is how an onboarding page can stay in English through three rounds of
measurement and still be reported as fully translated.

Not all of it is interface text, though. A role name and an item group are
records the customer owns, and folding them into the same denominator as button
labels makes the coverage figure argue with itself. Each target therefore
carries a class, and only `ui` is measured by default.
"""

import re

import frappe
from frappe import _

from lifegence_i18n.utils import classify, compiled_exclusion_rules, get_settings

UI = "UI Text"
MASTER_DATA = "Master Data"
ROLE = "Role Name"

# doctype -> (fields whose stored value is shown to the user, class)
TARGETS: dict[str, tuple[list[str], str]] = {
	"Module Onboarding": (["title", "subtitle", "success_message"], UI),
	"Onboarding Step": (["title", "action_label", "description", "callback_message"], UI),
	"Workspace": (["label", "title"], UI),
	"Workspace Link": (["label"], UI),
	"Workspace Shortcut": (["label", "format"], UI),
	"Workspace Number Card": (["label"], UI),
	"Workspace Chart": (["label"], UI),
	"Workspace Quick List": (["label"], UI),
	# version-16 keeps a workspace's sidebar as a document of its own, with the
	# entries in a child table; neither exists on version-15 and both are
	# skipped there, like any doctype a version does not have
	"Workspace Sidebar": (["title"], UI),
	"Workspace Sidebar Item": (["label"], UI),
	"Report": (["report_name"], UI),
	"Dashboard Chart": (["chart_name"], UI),
	"Number Card": (["label"], UI),
	"Dashboard": (["dashboard_name"], UI),
	"Notification": (["subject"], UI),
	"Email Template": (["subject"], UI),
	"Print Format": (["name"], UI),
	"Custom Field": (["label", "description"], UI),
	"Workflow State": (["workflow_state_name"], UI),
	"Workflow Action Master": (["workflow_action_name"], UI),
	"Role": (["name"], ROLE),
	"Item Group": (["name"], MASTER_DATA),
	"Customer Group": (["name"], MASTER_DATA),
	"Supplier Group": (["name"], MASTER_DATA),
	"Territory": (["name"], MASTER_DATA),
	"UOM": (["name"], MASTER_DATA),
	"Warehouse Type": (["name"], MASTER_DATA),
	"Sales Stage": (["stage_name"], MASTER_DATA),
	"Designation": (["name"], MASTER_DATA),
	"Department": (["department_name"], MASTER_DATA),
	"Gender": (["name"], MASTER_DATA),
	"Salutation": (["name"], MASTER_DATA),
}

LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def quoted(identifier: str) -> str:
	"""A table or column name as it may be written into SQL.

	These names come from the site's own schema, never from a request, so this
	is a belt on top of braces — but a name that could close the quoting would
	turn a scan into an injection, and the check costs nothing.
	"""
	if "`" in identifier:
		frappe.throw(_("{0} is not a name this scan can read").format(identifier))
	return f"`{identifier}`"


def table_columns(doctype: str) -> set[str]:
	"""The columns the table really has, which is not what the fields say.

	A doctype's shape changes between Frappe versions: version-16's Module
	Onboarding has neither `subtitle` nor `success_message`. Asking for a
	column that is not there fails the whole query, and this route used to
	answer that by skipping the doctype without a word — nine onboarding
	titles went unmeasured on version-16 and nothing said so.
	"""
	try:
		return set(frappe.db.get_table_columns(doctype))
	except Exception:
		return {column[0] for column in frappe.db.sql(f"desc {quoted(f'tab{doctype}')}")}  # nosemgrep


def collect(apps: list[str] | None = None, *, classes: tuple[str, ...] = (UI,), log=None) -> list[dict]:
	"""Return one record per distinct display string held in the site database."""
	rules = compiled_exclusion_rules()
	min_length = get_settings().min_string_length or 2
	module_to_app = _module_to_app()

	collected: dict[tuple[str, str], dict] = {}
	# A row of a child table belongs to the app its parent belongs to: a
	# shortcut on the Selling workspace is erpnext's, a link on a workspace
	# the customer's app ships is that app's. Child tables carry no module of
	# their own, and calling every one of them the site's left a customer's
	# hundred-odd workspace links out of the app's export.
	parent_modules: dict[str, dict[str, str]] = {}

	def parent_module(parenttype: str | None, parent: str | None) -> str | None:
		if not parenttype or not parent:
			return None
		if parenttype not in parent_modules:
			try:
				if "module" in table_columns(parenttype):
					parent_modules[parenttype] = dict(
						frappe.db.sql(  # nosemgrep
							f"select `name`, `module` from {quoted(f'tab{parenttype}')}"
						)
					)
				else:
					parent_modules[parenttype] = {}
			except Exception:
				parent_modules[parenttype] = {}
		return parent_modules[parenttype].get(parent)

	def add(text, app, doctype, name, fieldname, string_class):
		text = (text or "").strip()
		if not LATIN_WORD.search(text):
			return
		verdict = classify(text, rules, min_length)
		if not verdict.keep:
			return
		key = (text, "")
		existing = collected.get(key)
		if existing:
			existing["occurrences"] += 1
			return
		collected[key] = {
			"source_text": text,
			"context": None,
			"app": app or "site",
			"origin": "Database",
			"string_class": string_class,
			"na_reason": verdict.na_reason,
			"na_rule": verdict.na_rule,
			"auto_apply": verdict.auto_apply,
			"reference_doctype": doctype,
			"reference_name": name,
			"reference_field": fieldname,
			"occurrences": 1,
		}

	# A workspace keeps its section headings inside the `content` JSON, where
	# no field-level scan can see them. They are the first thing on the page.
	if UI in classes:
		for ws in frappe.get_all("Workspace", fields=["name", "module", "content"]):
			app = module_to_app.get(ws.module)
			if apps and app and app not in apps:
				continue
			for block in _content_blocks(ws.content):
				data = block.get("data")
				if block.get("type") == "header" and isinstance(data, dict):
					add(_strip_tags(data.get("text")), app, "Workspace", ws.name, "content", UI)

	for doctype, (fields, string_class) in TARGETS.items():
		if string_class not in classes:
			continue
		if not frappe.db.exists("DocType", doctype) or not frappe.db.table_exists(doctype):
			continue

		present = table_columns(doctype)
		usable = [field for field in fields if field in present]
		if missing := [field for field in fields if field not in present]:
			note = f"Database: {doctype} has no {', '.join(missing)} on this version"
			if log is not None:
				log.append(note + (" — nothing left to read" if not usable else ""))
		if not usable:
			continue
		wanted = list(dict.fromkeys(["name", *usable]))
		meta = frappe.get_meta(doctype)
		has_module = meta.has_field("module") and "module" in present
		if has_module:
			wanted.append("module")
		is_child = bool(meta.istable) and "parent" in present and "parenttype" in present
		if is_child and not has_module:
			wanted.extend(["parent", "parenttype"])

		columns = ", ".join(quoted(column) for column in dict.fromkeys(wanted))
		try:
			rows = frappe.db.sql(  # nosemgrep
				f"select {columns} from {quoted(f'tab{doctype}')}", as_dict=True
			)
		except Exception as exc:
			# The columns were checked, so this is rare; but a target that went
			# unread must be said, never swallowed (that is how nine onboarding
			# titles went unmeasured for a month).
			if log is not None:
				log.append(f"Database: {doctype} could not be read — {str(exc)[:120]}")
			continue

		for row in rows:
			if has_module:
				app = module_to_app.get(row.get("module"))
			elif is_child:
				app = module_to_app.get(parent_module(row.get("parenttype"), row.get("parent")))
			else:
				app = None
			if apps and app and app not in apps:
				continue
			for fieldname in usable:
				value = row.get(fieldname)
				if not isinstance(value, str):
					continue
				text = value.strip()
				if not LATIN_WORD.search(text):
					continue
				verdict = classify(text, rules, min_length)
				if not verdict.keep:
					continue

				key = (text, "")
				existing = collected.get(key)
				if existing:
					existing["occurrences"] += 1
					continue

				collected[key] = {
					"source_text": text,
					"context": None,
					"app": app or "site",
					"origin": "Database",
					"string_class": string_class,
					"na_reason": verdict.na_reason,
					"na_rule": verdict.na_rule,
					"auto_apply": verdict.auto_apply,
					"reference_doctype": doctype,
					"reference_name": row.get("name"),
					"reference_field": fieldname,
					"occurrences": 1,
				}

	return list(collected.values())


def _content_blocks(content: str | None) -> list[dict]:
	import json

	try:
		blocks = json.loads(content or "[]")
	except (TypeError, ValueError):
		return []
	if not isinstance(blocks, list):
		return []
	return [b for b in blocks if isinstance(b, dict)]


def _strip_tags(value: str | None) -> str:
	import html

	return html.unescape(re.sub(r"<[^>]+>", "", value or ""))


def _module_to_app() -> dict[str, str]:
	rows = frappe.get_all("Module Def", fields=["name", "app_name"])
	return {row.name: row.app_name for row in rows}
