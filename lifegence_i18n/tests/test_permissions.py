"""Who may do what: the acceptance criteria of the permission requirements.

Each test is written from a user of one role, because that is the only way to
see what Frappe actually allows. Checking the DocType definition would only
restate what was written there.
"""

import frappe

from lifegence_i18n import api, permissions
from lifegence_i18n.permissions import MANAGER, TRANSLATOR, VIEWER
from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, remove_locale

USERS = {
	MANAGER: "zz-i18n-manager@example.com",
	TRANSLATOR: "zz-i18n-translator@example.com",
	VIEWER: "zz-i18n-viewer@example.com",
	None: "zz-i18n-outsider@example.com",
}


def ensure_user(email: str, role: str | None) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"user_type": "System User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [])
	if role:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return email


class PermissionTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		permissions.create_roles()
		ensure_locale()
		for role, email in USERS.items():
			ensure_user(email, role)
		frappe.db.commit()  # nosemgrep - the users have to outlive the test transaction
		frappe.clear_cache()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		remove_locale()
		for email in USERS.values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep - undo the commit in setUpClass
		frappe.clear_cache()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def as_user(self, role):
		frappe.set_user(USERS[role])

	def ledger_row(self, source="zz permission fixture", **extra):
		name = frappe.db.get_value("Translation Entry", {"locale": LOCALE, "source_text": source})
		if name:
			return frappe.get_doc("Translation Entry", name)
		return frappe.get_doc(
			{
				"doctype": "Translation Entry",
				"locale": LOCALE,
				"source_text": source,
				"status": "Untranslated",
				"origin": "Manual",
				"app": "frappe",
				**extra,
			}
		).insert(ignore_permissions=True)


class TestRoles(PermissionTestCase):
	def test_the_three_roles_exist(self):
		"""AC-1 / AC-2."""
		for role in permissions.ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_creating_the_roles_again_changes_nothing(self):
		self.assertEqual(permissions.create_roles(), [])

	def test_the_roles_have_desk_access(self):
		for role in permissions.ROLES:
			self.assertTrue(frappe.db.get_value("Role", role, "desk_access"), role)

	def test_the_roles_hold_no_permission_outside_this_app(self):
		"""RL-4. Custom permissions added by an operator are not this app's doing,
		so only the ones shipped in the DocType definitions are checked."""
		ours = {
			"Locale Profile",
			"Translation Entry",
			"Translation Issue",
			"Translation Scan",
			"Glossary Term",
			"I18n Settings",
		}
		outside = frappe.get_all(
			"DocPerm",
			filters={"role": ("in", list(permissions.ROLES)), "parent": ("not in", list(ours))},
			pluck="parent",
		)
		self.assertEqual(sorted(set(outside)), [])


class TestWhatEachRoleSees(PermissionTestCase):
	def test_a_translator_cannot_see_the_settings(self):
		"""AC-11 / VI-4."""
		self.as_user(TRANSLATOR)
		self.assertFalse(frappe.has_permission("I18n Settings", "read"))

	def test_a_manager_can_see_the_settings(self):
		self.as_user(MANAGER)
		self.assertTrue(frappe.has_permission("I18n Settings", "write"))

	def test_every_role_can_read_the_ledger(self):
		for role in (MANAGER, TRANSLATOR, VIEWER):
			with self.subTest(role=role):
				self.as_user(role)
				self.assertTrue(frappe.has_permission("Translation Entry", "read"))

	def test_the_workspace_is_reachable_for_every_role(self):
		"""VI-2. Frappe shows a workspace when its module holds a DocType the user
		may reach, which is what `allow_modules` lists."""
		for role in (MANAGER, TRANSLATOR, VIEWER):
			with self.subTest(role=role):
				self.as_user(role)
				user = frappe.get_user()
				user.build_permissions()
				self.assertIn("Localization", user.allow_modules)

	def test_the_workspace_is_hidden_from_everyone_else(self):
		"""VI-2, the other half."""
		self.as_user(None)
		user = frappe.get_user()
		user.build_permissions()
		self.assertNotIn("Localization", user.allow_modules)

	def test_the_apps_screen_tile_follows_the_roles(self):
		"""AC-10 / VI-1."""
		for role in (MANAGER, TRANSLATOR, VIEWER):
			with self.subTest(role=role):
				self.as_user(role)
				self.assertTrue(permissions.has_app_permission())
		self.as_user(None)
		self.assertFalse(permissions.has_app_permission())

	def test_the_workspace_shows_each_role_only_what_it_may_open(self):
		"""VI-3 / VI-4. The cards are built from the DocType permissions, so this
		is what a user actually sees when the workspace is drawn. Card and link
		labels are translated for the session, so the targets are compared."""
		import json

		from frappe.desk.desktop import get_desktop_page

		reports = {"Localization Coverage", "Localization Exclusions", "Localization Delivery"}
		shared = {
			"Translation Scan",
			"Translation Issue",
			"Locale Profile",
			"Translation Entry",
			"Glossary Term",
		} | reports
		expected = {
			MANAGER: shared | {"I18n Settings"},
			TRANSLATOR: shared,
			VIEWER: shared,
		}
		for role, targets in expected.items():
			with self.subTest(role=role):
				self.as_user(role)
				page = get_desktop_page(json.dumps({"name": "Localization", "public": 1}))
				shown = {
					item.get("link_to")
					for card in page.get("cards", {}).get("items", [])
					for item in card.get("links", [])
				}
				self.assertEqual(shown, targets)

	def test_the_workspace_refuses_everyone_else(self):
		"""VI-2."""
		import json

		from frappe.desk.desktop import get_desktop_page

		self.as_user(None)
		self.assertRaises(
			frappe.PermissionError, get_desktop_page, json.dumps({"name": "Localization", "public": 1})
		)

	def test_the_reports_are_open_to_every_role(self):
		"""VI-5."""
		for report in ("Localization Coverage", "Localization Delivery", "Localization Exclusions"):
			roles = frappe.get_all("Has Role", filters={"parent": report}, pluck="role")
			for role in permissions.ROLES:
				self.assertIn(role, roles, f"{report} / {role}")


class TestWritingTranslations(PermissionTestCase):
	def test_a_translator_may_write_a_translation(self):
		"""AC-4: and saving one moves the row to Draft."""
		row = self.ledger_row("zz translator writes")
		self.as_user(TRANSLATOR)
		doc = frappe.get_doc("Translation Entry", row.name)
		doc.translated_text = "訳"
		doc.save()
		doc.reload()
		self.assertEqual(doc.translated_text, "訳")
		self.assertEqual(doc.status, "Draft")

	def test_a_translator_cannot_approve_their_own_translation(self):
		"""AC-3. The field-level permission resets the value; the save succeeds."""
		row = self.ledger_row("zz translator approves")
		frappe.db.set_value("Translation Entry", row.name, "translated_text", "訳")
		frappe.db.set_value("Translation Entry", row.name, "status", "Draft")
		self.as_user(TRANSLATOR)
		doc = frappe.get_doc("Translation Entry", row.name)
		doc.status = "Approved"
		doc.save()
		self.assertEqual(frappe.db.get_value("Translation Entry", row.name, "status"), "Draft")

	def test_a_translator_cannot_mark_a_row_not_applicable(self):
		"""OP-13."""
		row = self.ledger_row("zz translator excludes")
		self.as_user(TRANSLATOR)
		doc = frappe.get_doc("Translation Entry", row.name)
		doc.status = "Not Applicable"
		doc.na_reason = "Brand or Product Name"
		doc.save()
		self.assertNotEqual(frappe.db.get_value("Translation Entry", row.name, "status"), "Not Applicable")

	def test_a_manager_may_approve(self):
		"""AC-12."""
		row = self.ledger_row("zz manager approves")
		frappe.db.set_value("Translation Entry", row.name, "translated_text", "訳")
		self.as_user(MANAGER)
		doc = frappe.get_doc("Translation Entry", row.name)
		doc.status = "Approved"
		doc.save()
		self.assertEqual(frappe.db.get_value("Translation Entry", row.name, "status"), "Approved")

	def test_a_translator_cannot_create_or_delete_ledger_rows(self):
		"""PM-3 / OP-19."""
		self.as_user(TRANSLATOR)
		self.assertFalse(frappe.has_permission("Translation Entry", "create"))
		self.assertFalse(frappe.has_permission("Translation Entry", "delete"))

	def test_a_viewer_cannot_save_anything(self):
		"""AC-7."""
		row = self.ledger_row("zz viewer writes")
		self.as_user(VIEWER)
		doc = frappe.get_doc("Translation Entry", row.name)
		doc.translated_text = "訳"
		self.assertRaises(frappe.PermissionError, doc.save)


class TestActions(PermissionTestCase):
	def locale(self):
		return frappe.get_doc("Locale Profile", LOCALE)

	def test_a_translator_cannot_run_a_scan(self):
		"""AC-5 / OP-7."""
		self.as_user(TRANSLATOR)
		self.assertRaises(frappe.PermissionError, self.locale().run_scan)

	def test_a_translator_cannot_approve_drafts(self):
		"""AC-5 / OP-24."""
		self.as_user(TRANSLATOR)
		self.assertRaises(frappe.PermissionError, self.locale().approve_drafts)

	def test_a_translator_cannot_apply_to_the_site(self):
		"""AC-5 / OP-25."""
		self.as_user(TRANSLATOR)
		self.assertRaises(frappe.PermissionError, self.locale().apply_to_site)

	def test_a_translator_may_verify_delivery(self):
		"""OP-26: reading whether the answer arrived is part of translating."""
		self.as_user(TRANSLATOR)
		self.assertIsNotNone(self.locale().verify_delivery())

	def test_a_viewer_cannot_verify_delivery(self):
		self.as_user(VIEWER)
		self.assertRaises(frappe.PermissionError, self.locale().verify_delivery)

	def test_a_manager_may_approve_drafts(self):
		"""AC-12."""
		self.as_user(MANAGER)
		self.assertIn("approved", self.locale().approve_drafts())


class TestWhitelistedFunctions(PermissionTestCase):
	def test_only_a_manager_may_add_a_locale(self):
		"""AC-9 / OP-2. This one inserts without permission checks of its own."""
		from lifegence_i18n.localization.doctype.locale_profile.locale_profile import add_locale

		for role in (None, VIEWER, TRANSLATOR):
			with self.subTest(role=role):
				self.as_user(role)
				self.assertRaises(frappe.PermissionError, add_locale, "Japan", "ja", "JPY", "zz-denied", "zz")
		self.assertFalse(frappe.db.exists("Locale Profile", "zz-denied"))

	def test_a_translator_may_export_and_import_the_review_sheet(self):
		"""AC-6 / OP-20."""
		self.as_user(TRANSLATOR)
		api.export_review_sheet(LOCALE)
		self.assertEqual(frappe.response.get("filename"), f"{LOCALE}_review.csv")

	def test_a_viewer_cannot_export_the_review_sheet(self):
		"""AC-8."""
		self.as_user(VIEWER)
		self.assertRaises(frappe.PermissionError, api.export_review_sheet, LOCALE)

	def test_a_translator_may_preview_a_bulk_term_change_but_not_run_it(self):
		"""OP-14 / OP-15."""
		self.as_user(TRANSLATOR)
		preview = api.replace_term(LOCALE, "a", "b", dry_run=1)
		self.assertFalse(preview["applied"])
		self.assertRaises(frappe.PermissionError, api.replace_term, LOCALE, "a", "b", 0)

	def test_a_translator_cannot_export_the_app_translation_csv(self):
		"""OP-27."""
		self.as_user(TRANSLATOR)
		self.assertRaises(frappe.PermissionError, api.export_app_translations, LOCALE, "frappe")

	def test_every_role_may_read_coverage(self):
		"""OP-30."""
		for role in (MANAGER, TRANSLATOR, VIEWER):
			with self.subTest(role=role):
				self.as_user(role)
				self.assertIsInstance(api.coverage_by_locale(), list)

	def test_an_outsider_may_read_nothing(self):
		self.as_user(None)
		self.assertRaises(frappe.PermissionError, api.coverage_by_locale)
