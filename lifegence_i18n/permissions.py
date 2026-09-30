"""Who may do what.

The permissions this application grants live in two places that have to agree:
the DocType definitions, which decide what a user sees and can save, and the
checks in this module, which decide what a whitelisted call may do.

Both are needed. Frappe runs a whitelisted document method after checking only
that the caller may *read* the document (`frappe.handler.run_doc_method` asks
for `check_permission=True`, which is read). A role given read access so that a
form opens would otherwise be able to press every button on it — including the
one that changes what the whole site sees.

Role names are written here once so that changing them later is one edit.
"""

import frappe
from frappe import _

MANAGER = "Localization Manager"
TRANSLATOR = "Localization Translator"
VIEWER = "Localization Viewer"

#: Every role this application defines, in descending order of authority.
ROLES = (MANAGER, TRANSLATOR, VIEWER)

# System Manager administers the site and keeps the access it always had.
_MANAGE = (MANAGER, "System Manager")
_TRANSLATE = (MANAGER, TRANSLATOR, "System Manager")
_READ = (MANAGER, TRANSLATOR, VIEWER, "System Manager")


def only_manage(message: str | None = None):
	"""Settings, scans, approval, applying to the site, the app translation CSV."""
	_require(_MANAGE, message)


def only_translate(message: str | None = None):
	"""The review sheet, delivery verification, previewing a bulk term change."""
	_require(_TRANSLATE, message)


def only_read(message: str | None = None):
	"""Reading what has been measured."""
	_require(_READ, message)


def can_manage(user: str | None = None) -> bool:
	return _has_any(_MANAGE, user)


def can_translate(user: str | None = None) -> bool:
	return _has_any(_TRANSLATE, user)


def can_read(user: str | None = None) -> bool:
	return _has_any(_READ, user)


def has_app_permission() -> bool:
	"""Whether to show this application on the apps screen.

	Without this hook Frappe shows the tile to every desk user, and pressing it
	is how they find out they have no access.
	"""
	return can_read()


def _require(roles: tuple[str, ...], message: str | None):
	if _has_any(roles):
		return
	frappe.throw(
		message or _("You are not permitted to do this. It is reserved for {0}.").format(_(roles[0])),
		frappe.PermissionError,
	)


def _has_any(roles: tuple[str, ...], user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return not set(roles).isdisjoint(frappe.get_roles(user))


def create_roles() -> list[str]:
	"""Create the roles this application's permissions refer to.

	Called both on install and from a patch, so that a site upgraded from an
	earlier version ends up with the same roles as a fresh one.
	"""
	created = []
	for role in ROLES:
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)
		created.append(role)
	return created
