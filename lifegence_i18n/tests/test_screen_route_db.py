"""The screen route's database side, and the scan's handling of it, without
a browser: route discovery, the report line, the scan's bookkeeping when the
route is missing, refuses to run, or returns findings, and the settings that
guard it."""

from unittest.mock import patch

import frappe

from lifegence_i18n.localization.doctype.translation_scan import translation_scan as scan_module
from lifegence_i18n.scanner import screen
from lifegence_i18n.tests import FrappeTestCase
from lifegence_i18n.tests.test_routes_db import LOCALE, ensure_locale, entry, remove_locale


class TestSlowScreens(FrappeTestCase):
	"""A screen whose network never falls quiet is still a screen: the ledger's
	own list view stopped settling once it held seventeen thousand rows."""

	class FakePage:
		url = "http://x/app/translation-entry"

		def __init__(self, idle_raises):
			self.idle_raises = idle_raises
			self.evaluated = False

		def goto(self, url, **kwargs):
			self.goto_kwargs = kwargs

		def wait_for_load_state(self, state, timeout=None):
			if self.idle_raises:
				raise TimeoutError("Timeout 15000ms exceeded.")

		def wait_for_selector(self, selector, **kwargs):
			self.waited_for = selector

		drawn = 1

		def locator(self, selector):
			count = 0 if ".message-page" in selector else self.drawn

			class Found:
				def count(_self):
					return count

			return Found()

		def evaluate(self, js):
			self.evaluated = True
			return {"labels": [{"text": "Zzz Heading", "kind": "heading"}], "data": []}

	def test_a_screen_that_never_falls_quiet_is_still_read(self):
		page = self.FakePage(idle_raises=True)
		with patch.object(screen.time, "sleep"):
			labels, _data = screen._collect_page(page, "http://x", "/app/translation-entry")
		self.assertTrue(page.evaluated, "the page must be read even when it never settles")
		self.assertEqual(labels, {"Zzz Heading": "heading"})
		self.assertEqual(page.goto_kwargs.get("wait_until"), "domcontentloaded")

	def test_a_screen_the_crawl_user_may_not_open_is_not_a_screen(self):
		# Frappe leaves the desk empty behind a dialog; reading it would collect
		# the dialog as the screen's own text and count a screen never seen
		page = self.FakePage(idle_raises=False)
		page.drawn = 0
		with patch.object(screen.time, "sleep"), self.assertRaises(RuntimeError) as caught:
			screen._collect_page(page, "http://x", "/app/sales-order")
		self.assertIn("not available", str(caught.exception))
		self.assertFalse(page.evaluated)

	def test_a_quiet_screen_is_read_the_same_way(self):
		page = self.FakePage(idle_raises=False)
		with patch.object(screen.time, "sleep"):
			labels, _data = screen._collect_page(page, "http://x", "/app/translation-entry")
		self.assertEqual(labels, {"Zzz Heading": "heading"})


class TestSiteDictionary(FrappeTestCase):
	"""What is on screen is judged by the crawled site's own dictionary, read
	from the desk after login, so a site crawled from another machine need not
	share this bench's translation files (PM, 22 September)."""

	class Desk:
		def __init__(self, boot):
			self.boot = boot

		def wait_for_function(self, js, timeout=None):
			if self.boot is None:
				raise TimeoutError("Timeout 15000ms exceeded.")

		def evaluate(self, js):
			return self.boot

	def test_the_dictionary_and_language_come_from_the_desk(self):
		desk = self.Desk({"lang": "ja", "messages": {"Zzz Save": "Zzz 保存"}})
		self.assertEqual(screen._site_dictionary(desk), ({"Zzz Save": "Zzz 保存"}, "ja"))

	def test_a_desk_that_cannot_be_read_says_so(self):
		self.assertEqual(screen._site_dictionary(self.Desk(None)), (None, None))
		self.assertEqual(screen._site_dictionary(self.Desk("garbage")), (None, None))
		self.assertEqual(
			screen._site_dictionary(self.Desk({"messages": {"a": "b"}})), (None, None), "no language, no boot"
		)

	def test_the_three_outcomes(self):
		approved = {"status": "Approved", "source_text": "Zzz Save", "translated_text": "Zzz 保存"}
		self.assertEqual(
			screen.judge(approved, "Zzz 保存"),
			screen.NOT_WRAPPED,
			"the site serves it, the screen shows English",
		)
		self.assertEqual(
			screen.judge(approved, None), screen.NOT_DELIVERED, "the ledger has it, the site does not"
		)
		self.assertEqual(
			screen.judge(approved, "Zzz 別の訳"), screen.NOT_DELIVERED, "the site serves an older one"
		)
		untranslated = {"status": "Untranslated", "source_text": "Zzz Save", "translated_text": ""}
		self.assertEqual(screen.judge(untranslated, None), screen.CONFIRMED)
		self.assertEqual(
			screen.judge(untranslated, "Zzz 保存"),
			screen.CONFIRMED,
			"what the ledger lacks is a gap, whatever the site holds",
		)
		same = {"status": "Approved", "source_text": "Zzz Save", "translated_text": "Zzz Save"}
		self.assertEqual(screen.judge(same, None), screen.CONFIRMED)
		draft = {"status": "Draft", "source_text": "Zzz Save", "translated_text": "Zzz 保存"}
		self.assertIsNone(screen.judge(draft, None), "a draft is not expected on any screen yet")
		excluded = {"status": "Not Applicable", "source_text": "ZZZ-.YYYY.-", "translated_text": ""}
		self.assertIsNone(screen.judge(excluded, None))


class TestConnectionKeptAlive(FrappeTestCase):
	"""A crawl asks the database nothing for minutes on end; a server that
	closes idle connections would otherwise take the scan down with it."""

	def test_a_live_connection_is_left_alone(self):
		with patch.object(frappe.db, "connect") as connect:
			screen.keep_connection()
		connect.assert_not_called()

	def test_a_dropped_connection_is_opened_again(self):
		with (
			patch.object(frappe.db, "sql", side_effect=Exception("server has gone away")),
			patch.object(frappe.db, "connect") as connect,
		):
			screen.keep_connection()
		connect.assert_called_once()

	def test_a_server_that_will_not_answer_is_reported_not_raised(self):
		with (
			patch.object(frappe.db, "sql", side_effect=Exception("server has gone away")),
			patch.object(frappe.db, "connect", side_effect=Exception("refused")),
			patch.object(frappe, "log_error") as log_error,
		):
			screen.keep_connection()  # must not raise: the caller is already handling a failure
		log_error.assert_called_once()


class TestRouteDiscovery(FrappeTestCase):
	def test_customer_apps_first_then_core_and_the_limit(self):
		routes = screen.discover_routes(["frappe", "lifegence_i18n"], None)
		# A workspace the site made for itself (no module, app "site") is visited
		# before any app's, and a site may or may not have one; so the order is
		# checked among the target apps' own screens, whatever comes before them.
		own = [(r, a) for r, a in routes if a != "site"]
		self.assertEqual(own[0], ("/app/localization", "lifegence_i18n"), "workspaces first, own app first")
		self.assertEqual(
			[a for _, a in routes[: len(routes) - len(own)]],
			["site"] * (len(routes) - len(own)),
			"the site's own workspaces, if any, come first",
		)
		forms = [(r, a) for r, a in routes if r.endswith("/new")]
		self.assertEqual(forms[0][1], "lifegence_i18n")
		self.assertEqual(forms[-1][1], "frappe")
		self.assertLess([a for _, a in forms].index("frappe"), len(forms) - 1)
		self.assertNotIn("lifegence_i18n", [a for _, a in forms][[a for _, a in forms].index("frappe") :])
		self.assertIn("/app/locale-profile", [r for r, _ in routes])
		self.assertIn("/app/locale-profile/new", [r for r, _ in routes])
		self.assertEqual(screen.discover_routes(["frappe", "lifegence_i18n"], 5), routes[:5])

	def test_public_route_cuts_a_record_route_to_its_doctype(self):
		self.assertEqual(screen.public_route("/app/customer/Acme Trading Co."), "/app/customer")
		self.assertEqual(screen.public_route("/app/item/A%2FB-100"), "/app/item")  # names are URL-encoded
		self.assertEqual(screen.public_route("/app/customer/new"), "/app/customer/new")
		self.assertEqual(screen.public_route("/app/selling"), "/app/selling")

	def test_summary_line(self):
		report = {
			"new": 3,
			"rendered_untranslated": 1,
			"confirmed": 20,
			"screens": 12,
			"seconds": 40.0,
			"failed": 0,
		}
		line = screen.summary_line(report)
		self.assertIn("0 not delivered", line)
		report["not_delivered"] = 4
		self.assertIn("4 not delivered", screen.summary_line(report))
		line = screen.summary_line(report)
		self.assertIn("3 new", line)
		self.assertIn("1 not wrapped on screen", line)
		self.assertNotIn("could not be opened", line)
		report["failed"] = 2
		self.assertIn("(2 could not be opened)", screen.summary_line(report))


class TestScanWithScreens(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation Issue", {"locale": LOCALE})
		frappe.db.set_value("Locale Profile", LOCALE, "scan_screens", 1)
		self.scan = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)
		self.scan.scan_source = self.scan.scan_database = self.scan.scan_messages = 0
		self.scan.scan_screens = 1

	def tearDown(self):
		frappe.delete_doc("Translation Scan", self.scan.name, force=True, ignore_permissions=True)
		frappe.db.set_value("Locale Profile", LOCALE, "scan_screens", 0)

	def test_without_playwright_the_route_is_skipped_and_the_scan_completes(self):
		with patch.object(scan_module.screen_route, "is_available", return_value=False):
			self.scan.run()
		self.assertEqual(self.scan.status, "Completed")
		self.assertIn("Screen           : skipped", self.scan.log)

	def test_a_configuration_problem_is_one_line_not_a_failure(self):
		def refuse(*args, **kwargs):
			frappe.throw("Set a dedicated crawl user in I18n Settings (not Administrator)")

		with (
			patch.object(scan_module.screen_route, "is_available", return_value=True),
			patch.object(scan_module.screen_route, "collect", side_effect=refuse),
		):
			self.scan.run()
		self.assertEqual(self.scan.status, "Completed")
		self.assertIn("Screen           : not run — Set a dedicated crawl user", self.scan.log)

	def test_a_new_string_frappe_already_translates_is_a_rendering_defect_at_once(self):
		found = [
			{
				"source_text": "Zzz Shown Raw",
				"context": None,
				"app": "zz_app",
				"origin": "Screen",
				"string_class": "UI Text",
				"source_path": "/app/zz",
				"line_no": 0,
				"occurrences": 1,
				"na_reason": None,
				"na_rule": None,
				"auto_apply": False,
			}
		]
		rendered = [
			{
				"entry": None,
				"source_text": "Zzz Shown Raw",
				"translated_text": "Zzz 訳あり",
				"route": "/app/zz",
				"app": "zz_app",
				"kind": "heading",
				"shown": "Zzz Shown Raw",
			}
		]
		report = {
			"new": 1,
			"rendered_untranslated": 1,
			"confirmed": 0,
			"screens": 1,
			"seconds": 3.0,
			"failed": 0,
		}
		with (
			patch.object(scan_module.screen_route, "is_available", return_value=True),
			patch.object(scan_module.screen_route, "collect", return_value=(found, rendered, report)),
		):
			self.scan.run()
		self.assertEqual(self.scan.status, "Completed", self.scan.log)
		issue = frappe.get_all(
			"Translation Issue",
			filters={"locale": LOCALE, "issue_type": "Not Wrapped"},
			fields=["translation_entry", "source_text", "location", "detail"],
		)
		self.assertEqual(len(issue), 1)
		self.assertEqual(issue[0].location, "/app/zz")
		self.assertTrue(issue[0].detail.startswith("screen: /app/zz (heading)"), issue[0].detail)
		self.assertEqual(
			issue[0].translation_entry,
			frappe.db.get_value(
				"Translation Entry", {"locale": LOCALE, "source_text": "Zzz Shown Raw"}, "name"
			),
		)

	def test_findings_reach_the_ledger_with_exclusion_rules_applied(self):
		agreed = entry("Zzz Export", "Zzz 書き出し")
		found = [
			{
				"source_text": "Zzz Quick Access",
				"context": None,
				"app": "zz_app",
				"origin": "Screen",
				"string_class": "UI Text",
				"source_path": "/app/selling",
				"line_no": 0,
				"occurrences": 1,
				"na_reason": None,
				"na_rule": None,
				"auto_apply": False,
			},
			{
				"source_text": "ZZZ-.YYYY.-",
				"context": None,
				"app": "zz_app",
				"origin": "Screen",
				"string_class": "UI Text",
				"source_path": "/app/selling",
				"line_no": 0,
				"occurrences": 1,
				"na_reason": "Naming Series",
				"na_rule": "Naming Series",
				"auto_apply": True,
			},
		]
		rendered = [
			{
				"entry": agreed.name,
				"source_text": "Zzz Export",
				"translated_text": "Zzz 書き出し",
				"route": "/app/data-export",
				"app": "zz_app",
				"kind": "button",
				"shown": "Zzz Export",
			}
		]
		report = {
			"new": 2,
			"rendered_untranslated": 1,
			"confirmed": 0,
			"screens": 2,
			"seconds": 6.0,
			"failed": 0,
			"routes": ["/app/selling", "/app/item"],
			"normalised": [("4 Zzz", "{0} Zzz")],
			"details": [
				"Not delivered to the site (1): translated in the ledger, not served by the site",
				"  'Zzz Later' on /app/item",
			],
		}
		with (
			patch.object(scan_module.screen_route, "is_available", return_value=True),
			patch.object(scan_module.screen_route, "collect", return_value=(found, rendered, report)),
		):
			self.scan.run()
		self.assertEqual(self.scan.status, "Completed", self.scan.log)
		self.assertIn("Screen           :      2 new", self.scan.log)
		# the detail lines sit under the summary line, before the ledger line
		summary = self.scan.log.index("Screen           :      2 new")
		self.assertLess(summary, self.scan.log.index("Not delivered to the site (1)"))
		self.assertLess(
			self.scan.log.index("  'Zzz Later' on /app/item"), self.scan.log.index("Ledger (screen):")
		)
		self.assertIn("Screens visited (2):\n  /app/selling\n  /app/item", self.scan.log)
		self.assertIn("Screen normalised: '4 Zzz' -> '{0} Zzz'", self.scan.log)
		self.assertIn("Ledger (screen): 2 new / 0 updated", self.scan.log)
		self.assertEqual(self.scan.new_entries, 2)
		rows = {
			r.source_text: r
			for r in frappe.get_all(
				"Translation Entry",
				filters={"locale": LOCALE, "origin": "Screen"},
				fields=["source_text", "status", "na_reason", "source_path"],
			)
		}
		self.assertEqual(rows["Zzz Quick Access"].status, "Untranslated")
		self.assertEqual(rows["ZZZ-.YYYY.-"].status, "Not Applicable")
		self.assertEqual(rows["ZZZ-.YYYY.-"].na_reason, "Naming Series")
		self.assertEqual(rows["Zzz Quick Access"].source_path, "/app/selling")
		self.assertEqual(
			frappe.db.count(
				"Translation Issue",
				{"locale": LOCALE, "issue_type": "Not Wrapped", "location": "/app/data-export"},
			),
			1,
		)


class TestCrawlSettings(FrappeTestCase):
	def setUp(self):
		self.settings = frappe.get_single("I18n Settings")
		self.original = {k: self.settings.get(k) for k in ("screen_site_url", "screen_user")}

	def tearDown(self):
		frappe.db.set_single_value("I18n Settings", self.original)
		frappe.clear_cache(doctype="I18n Settings")

	def check(self, **values):
		doc = frappe.get_single("I18n Settings")
		doc.screen_user = "zz-crawler@example.com"  # any dedicated user; the URL rules are under test here
		doc.update(values)
		doc.validate()

	def test_site_url_rules(self):
		self.check(screen_site_url="")
		self.check(screen_site_url="http://localhost:8000")
		self.check(screen_site_url=f"https://{frappe.local.site}:8443")  # this site, with a port
		self.assertRaises(frappe.ValidationError, self.check, screen_site_url="ftp://x")
		self.assertRaises(frappe.ValidationError, self.check, screen_site_url="http://example.com")
		self.assertRaises(frappe.ValidationError, self.check, screen_site_url="https://10.0.0.5")
		self.assertRaises(frappe.ValidationError, self.check, screen_site_url="https://169.254.169.254")
		# another site is allowed only when site_config says so
		self.assertRaises(frappe.ValidationError, self.check, screen_site_url="https://other.example.com")
		frappe.conf.i18n_allow_remote_crawl = 1
		try:
			self.check(screen_site_url="https://other.example.com")
		finally:
			frappe.conf.pop("i18n_allow_remote_crawl", None)

	def test_collect_refuses_to_run_without_a_password(self):
		profile = frappe.get_doc("Locale Profile", ensure_locale())
		with patch.object(
			screen,
			"get_settings",
			return_value=frappe._dict(
				screen_site_url="",
				screen_user="",
				get_password=lambda *a, **k: None,
				screen_max_screens=1,
				min_string_length=2,
				allowed_latin_terms="",
			),
		):
			self.assertRaises(frappe.ValidationError, screen.collect, profile, ["frappe"])


class TestScanKeepsDecisions(FrappeTestCase):
	"""What a scan must leave alone: a reason someone recorded, and the
	findings of a route that did not run this time."""

	@classmethod
	def tearDownClass(cls):
		remove_locale()
		super().tearDownClass()

	def setUp(self):
		ensure_locale()
		frappe.db.delete("Translation Entry", {"locale": LOCALE})
		frappe.db.delete("Translation Issue", {"locale": LOCALE})
		self.profile = frappe.get_doc("Locale Profile", LOCALE)
		self.scan = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)
		self.scan.new_entries = self.scan.updated_entries = 0

	def tearDown(self):
		frappe.delete_doc("Translation Scan", self.scan.name, force=True, ignore_permissions=True)

	def item(self, text, **extra):
		return {
			"source_text": text,
			"context": None,
			"app": "zz_app",
			"origin": "Source Code",
			"string_class": "UI Text",
			"source_path": "x",
			"line_no": 0,
			"occurrences": 1,
			**extra,
		}

	def test_a_hand_recorded_reason_survives_the_next_scan(self):
		row = entry("Zzz Brand", "Zzz Brand", status="Not Applicable", na_reason="Manual")
		self.scan._upsert(self.profile, [self.item("Zzz Brand")])  # no rule matches this time
		self.assertEqual(
			frappe.db.get_value("Translation Entry", row.name, ["status", "na_reason"]),
			("Not Applicable", "Manual"),
		)

	def test_a_glossary_brand_is_filed_not_applicable(self):
		term = frappe.get_doc(
			{
				"doctype": "Glossary Term",
				"locale": LOCALE,
				"source_term": "Zzz ERP",
				"do_not_translate": 1,
				"match_type": "Word",
				"case_sensitive": 1,
				"enforce": 1,
			}
		)
		term.insert(ignore_permissions=True)
		try:
			self.scan._upsert(self.profile, [self.item("Zzz ERP"), self.item("Zzz ERP Sync Status")])
		finally:
			frappe.delete_doc("Glossary Term", term.name, force=True, ignore_permissions=True)
		brand = frappe.db.get_value(
			"Translation Entry",
			{"locale": LOCALE, "source_text": "Zzz ERP"},
			["status", "na_reason", "na_rule"],
			as_dict=True,
		)
		self.assertEqual(
			(brand.status, brand.na_reason, brand.na_rule),
			("Not Applicable", "Brand or Product Name", "Glossary: Zzz ERP"),
		)
		text = frappe.db.get_value(
			"Translation Entry",
			{"locale": LOCALE, "source_text": "Zzz ERP Sync Status"},
			["status", "na_reason"],
			as_dict=True,
		)
		self.assertEqual((text.status, text.na_reason), ("Untranslated", None))

	def test_a_new_rule_applies_to_a_row_nobody_decided_on(self):
		undecided = entry("ZZZ-.YYYY.-", "", status="Untranslated")
		decided = entry("ZZZ-.MM.-", "ZZZ-.MM.-", status="Approved")
		self.scan._upsert(
			self.profile,
			[
				self.item("ZZZ-.YYYY.-", na_reason="Naming Series", na_rule="Naming Series", auto_apply=True),
				self.item("ZZZ-.MM.-", na_reason="Naming Series", na_rule="Naming Series", auto_apply=True),
			],
		)
		self.assertEqual(frappe.db.get_value("Translation Entry", undecided.name, "status"), "Not Applicable")
		# someone wrote a translation: the rule may suggest, not overturn
		self.assertEqual(
			frappe.db.get_value("Translation Entry", decided.name, ["status", "na_reason"]),
			("Approved", "Naming Series"),
		)

	def test_the_ledger_write_is_attempted_again_after_a_deadlock(self):
		# a scan that has spent twenty minutes in a browser must not be lost to
		# a lock conflict that would succeed a moment later
		outcomes = [frappe.QueryDeadlockError("1213"), (7, 3, 0)]

		def flaky(_scan, profile, collected):
			self.scan.new_entries = (self.scan.new_entries or 0) + 7  # a partial write, then the rollback
			outcome = outcomes.pop(0)
			if isinstance(outcome, Exception):
				raise outcome
			return outcome

		with (
			patch.object(scan_module.TranslationScan, "_upsert", flaky),
			patch.object(scan_module.time, "sleep"),
			patch.object(frappe.db, "rollback"),
			patch.object(screen, "keep_connection"),
		):
			self.assertEqual(self.scan._upsert_safely(self.profile, []), (7, 3, 0))
		self.assertFalse(outcomes, "the second attempt must have run")
		# the counters of the attempt that was rolled back are not kept
		self.assertEqual(self.scan.new_entries, 7)

	def test_a_deadlock_that_never_clears_still_fails_the_scan(self):
		with (
			patch.object(
				scan_module.TranslationScan, "_upsert", side_effect=frappe.QueryDeadlockError("1213")
			),
			patch.object(scan_module.time, "sleep"),
			patch.object(frappe.db, "rollback"),
			patch.object(screen, "keep_connection"),
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				self.scan._upsert_safely(self.profile, [])

	def test_a_scan_whose_job_died_stops_blocking(self):
		from frappe.utils import add_to_date

		self.scan.db_set({"status": "Running", "started_on": frappe.utils.now_datetime()})
		frappe.db.set_value(
			"Translation Scan",
			self.scan.name,
			"modified",
			add_to_date(frappe.utils.now_datetime(), minutes=-30),
			update_modified=False,
		)
		second = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)
		try:
			self.assertIsNone(second.another_running())
		finally:
			frappe.delete_doc("Translation Scan", second.name, force=True, ignore_permissions=True)
			self.scan.db_set({"status": "Completed"})

	def test_the_heartbeat_keeps_a_long_crawl_from_looking_dead(self):
		from frappe.utils import add_to_date

		self.scan.db_set({"status": "Running"})
		frappe.db.set_value(
			"Translation Scan",
			self.scan.name,
			"modified",
			add_to_date(frappe.utils.now_datetime(), minutes=-30),
			update_modified=False,
		)
		self.scan.heartbeat()
		second = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)
		try:
			self.assertEqual(second.another_running(), self.scan.name)
		finally:
			frappe.delete_doc("Translation Scan", second.name, force=True, ignore_permissions=True)
			self.scan.db_set({"status": "Completed"})
			frappe.db.commit()  # the heartbeat committed the Running status; undo it for the next test

	def test_the_heartbeat_does_not_break_the_scan_s_own_save(self):
		# a heartbeat that wrote only the column would make save() raise
		# TimestampMismatchError and lose the whole report
		self.scan.heartbeat()
		self.scan.log = "after the heartbeat"
		self.scan.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Translation Scan", self.scan.name, "log"), "after the heartbeat"
		)

	def test_a_second_scan_of_the_same_locale_does_not_start(self):
		self.scan.db_set({"status": "Running", "started_on": frappe.utils.now_datetime()})
		second = frappe.get_doc({"doctype": "Translation Scan", "locale": LOCALE}).insert(
			ignore_permissions=True
		)
		try:
			second.run()
			self.assertEqual(second.status, "Failed")
			self.assertIn(self.scan.name, second.log)
			with self.assertRaises(frappe.ValidationError):
				second.enqueue_run()
		finally:
			frappe.delete_doc("Translation Scan", second.name, force=True, ignore_permissions=True)
			self.scan.db_set({"status": "Completed"})

	def test_a_row_filed_as_the_site_s_is_claimed_by_its_app(self):
		unclaimed = entry("Zzz Unclaimed", "", status="Untranslated", app="site")
		owned = entry("Zzz Owned", "", status="Untranslated", app="erpnext")
		self.scan._upsert(
			self.profile, [self.item("Zzz Unclaimed"), self.item("Zzz Owned")]
		)  # zz_app finds both
		self.assertEqual(frappe.db.get_value("Translation Entry", unclaimed.name, "app"), "zz_app")
		self.assertEqual(
			frappe.db.get_value("Translation Entry", owned.name, "app"),
			"erpnext",
			"the first finder keeps it",
		)
		# and the log says how many rows moved where, so the change can be traced
		self.assertEqual(self.scan.claims_line(), "Claimed from site: 1 (zz_app 1)")
		self.scan._upsert(self.profile, [self.item("Zzz Unclaimed")])  # nothing left to claim
		self.assertIsNone(self.scan.claims_line())

	def test_a_rule_can_still_refine_a_reason(self):
		row = entry("ZZZ-.YYYY.-", "", status="Not Applicable", na_reason="Manual")
		self.scan._upsert(
			self.profile,
			[self.item("ZZZ-.YYYY.-", na_reason="Naming Series", na_rule="Naming Series", auto_apply=True)],
		)
		self.assertEqual(frappe.db.get_value("Translation Entry", row.name, "na_reason"), "Naming Series")

	def test_issues_of_a_route_that_did_not_run_are_kept(self):
		unwrapped = [
			{
				"source_text": "Zzz raw",
				"source_path": "x.py",
				"line_no": 1,
				"kind": "py/plain",
				"call": "throw",
				"app": "zz_app",
			}
		]
		self.scan.scan_messages = 1
		self.scan._rebuild_issues(self.profile, unwrapped, None)
		self.assertEqual(
			frappe.db.count("Translation Issue", {"locale": LOCALE, "issue_type": "Not Wrapped"}), 1
		)
		# the next scan runs without the messages route: its findings stay
		self.scan.scan_messages = 0
		self.scan._rebuild_issues(self.profile, [], None)
		self.assertEqual(
			frappe.db.count("Translation Issue", {"locale": LOCALE, "issue_type": "Not Wrapped"}), 1
		)
		# and a scan that runs it again replaces them
		self.scan.scan_messages = 1
		self.scan._rebuild_issues(self.profile, [], None)
		self.assertEqual(
			frappe.db.count("Translation Issue", {"locale": LOCALE, "issue_type": "Not Wrapped"}), 0
		)

	def test_screen_findings_are_kept_when_the_screens_did_not_run(self):
		row = entry("Zzz Export", "Zzz 書き出し")
		on_screen = {"locale": LOCALE, "issue_type": "Not Wrapped", "location": ("like", "/app/%")}
		self.scan.scan_messages = 0
		self.scan._rebuild_issues(
			self.profile,
			[],
			[
				{
					"entry": row.name,
					"source_text": "Zzz Export",
					"translated_text": "Zzz 書き出し",
					"route": "/app/x",
					"app": "zz_app",
					"kind": "button",
					"shown": "Zzz Export",
				}
			],
		)
		self.assertEqual(frappe.db.count("Translation Issue", on_screen), 1)
		self.scan._rebuild_issues(self.profile, [], None)  # screens off this time
		self.assertEqual(frappe.db.count("Translation Issue", on_screen), 1)
		self.scan._rebuild_issues(self.profile, [], [])  # screens ran, found nothing
		self.assertEqual(frappe.db.count("Translation Issue", on_screen), 0)
