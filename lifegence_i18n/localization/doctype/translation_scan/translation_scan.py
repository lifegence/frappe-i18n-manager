import time
from collections import Counter

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from lifegence_i18n import permissions
from lifegence_i18n.scanner import database as db_route
from lifegence_i18n.scanner import delivery as delivery_route
from lifegence_i18n.scanner import messages as message_route
from lifegence_i18n.scanner import resolve, validate
from lifegence_i18n.scanner import screen as screen_route
from lifegence_i18n.scanner import source as source_route
from lifegence_i18n.utils import (
	BRAND_REASON,
	as_lines,
	brand_match,
	brand_rules,
	get_settings,
	text_hash,
	translation_key,
)

CHUNK = 500
UI_TEXT = "UI Text"
STALE_AFTER_MINUTES = 15  # a Running scan quieter than this is a job that died


def _status_for(item: dict, preferred: str | None) -> str:
	"""The status a newly collected string starts life with.

	A rule that fires with `auto_apply` states the string is not a translation
	target, and the row is filed that way rather than dropped — the exclusion
	stays visible and can be explained. A rule without `auto_apply` records its
	reason as a suggestion and leaves the string counting as untranslated until
	someone confirms it.
	"""
	if item.get("na_reason") and item.get("auto_apply"):
		return "Not Applicable"
	return "Approved" if preferred else "Untranslated"


class TranslationScan(Document):
	def before_insert(self):
		profile = frappe.get_doc("Locale Profile", self.locale)
		if not self.get("scan_source") and not self.get("scan_database") and not self.get("scan_messages"):
			self.scan_source = profile.scan_source
			self.scan_database = profile.scan_database
			self.scan_messages = profile.scan_messages
		# These are off by default, so "unset" is a real answer rather than
		# a missing one and they are copied unconditionally.
		self.scan_master_data = profile.scan_master_data
		self.scan_roles = profile.scan_roles
		self.scan_screens = profile.scan_screens

	def heartbeat(self) -> None:
		"""Say that this scan is still alive.

		The crawl leaves the scan's own row untouched for as long as it takes,
		so without this a run that is working would be indistinguishable from
		one whose job died — and the next scan would be refused for hours.
		"""
		# db_set keeps the document in hand in step with the row; writing the
		# column alone would make the save at the end of the scan fail with a
		# timestamp mismatch, and the report would be lost with it.
		self.db_set("modified", now_datetime(), update_modified=False, commit=True)

	def another_running(self) -> str | None:
		"""The name of a scan of this locale that is executing, if any.

		Two scans of one locale writing the ledger at the same time deadlock in
		_upsert, and one of them is killed by the server; it happened during the
		public-app validation. Only a scan that is actually running blocks:
		a Queued row has written nothing, and a Running row that has not said
		anything for a quarter of an hour is a job that died (see `heartbeat`,
		which a crawl calls every twenty-five screens).
		"""
		from frappe.utils import add_to_date

		return frappe.db.get_value(
			"Translation Scan",
			{
				"locale": self.locale,
				"status": "Running",
				"name": ("!=", self.name),
				"modified": (">", add_to_date(now_datetime(), minutes=-STALE_AFTER_MINUTES)),
			},
			"name",
		)

	@frappe.whitelist()
	def enqueue_run(self):
		"""Scanning frappe + erpnext parses several thousand files, so this never
		runs inside a web request."""
		permissions.only_manage()
		other = self.another_running()
		if other:
			frappe.throw(_("Scan {0} is still running for this locale. Wait for it to finish.").format(other))
		self.db_set("status", "Queued")
		# A screen crawl adds about three seconds per screen on top of the scan
		# itself, so the job's timeout follows the configured limit.
		timeout = 7200
		if self.scan_screens:
			from lifegence_i18n.scanner import screen as screen_route

			cap = int(get_settings().screen_max_screens or 0) or None
			profile = frappe.get_doc("Locale Profile", self.locale)
			screens = len(screen_route.discover_routes(target_apps(profile), cap))
			timeout = max(7200, 4 * screens + 1800)
		frappe.enqueue(
			"lifegence_i18n.localization.doctype.translation_scan.translation_scan.execute",
			queue="long",
			timeout=timeout,
			scan=self.name,
			# The worker loads this record by name. Without waiting for the
			# commit it can start before the row exists and fail on a scan the
			# operator just asked for.
			enqueue_after_commit=True,
		)
		return self.name

	def run(self):
		started = time.monotonic()
		lines: list[str] = []
		self.new_entries = self.updated_entries = 0
		other = self.another_running()
		if other:
			self.status = "Failed"
			self.log = f"Not started: scan {other} is still running for this locale."
			self.finished_on = now_datetime()
			self.save(ignore_permissions=True)
			# The refusal has to survive: the caller sees a Failed scan, not an
			# empty one that looks like it never ran.
			frappe.db.commit()  # nosemgrep
			return
		self.db_set({"status": "Running", "started_on": now_datetime()}, commit=True)

		try:
			profile = frappe.get_doc("Locale Profile", self.locale)
			apps = target_apps(profile)
			lines.append(f"Target apps ({len(apps)}): {', '.join(apps)}")

			# An app installed after the target list was written would otherwise be
			# measured as if it did not exist — coverage would stay high while a
			# whole application went untranslated. Silence is the one thing this
			# app must not do about a gap.
			uncovered = [a for a in frappe.get_installed_apps() if a not in apps]
			if uncovered:
				lines.append(
					f"NOT MEASURED ({len(uncovered)}): {', '.join(uncovered)} "
					"— installed on this site but absent from Target Apps"
				)

			collected: list[dict] = []
			from_source: list[dict] = []
			from_database: list[dict] = []

			if self.scan_source:
				from_source = source_route.collect(apps)
				lines.append(f"Source code      : {len(from_source):>6}")
			if self.scan_database:
				classes = [db_route.UI]
				if self.scan_master_data:
					classes.append(db_route.MASTER_DATA)
				if self.scan_roles:
					classes.append(db_route.ROLE)
				from_database = db_route.collect(apps, classes=tuple(classes), log=lines)
				lines.append(f"Database         : {len(from_database):>6} ({', '.join(classes)})")

			dropped = self._class_source_roles(from_source, from_database)
			if dropped:
				lines.append(f"Roles from DocPerm: {dropped:>5} excluded (Scan Role Names is off)")
			collected.extend(from_source)
			collected.extend(from_database)

			new_count, updated_count, fallback_used = self._upsert_safely(profile, collected)
			lines.append(f"Ledger: {new_count} new / {updated_count} updated")
			if self.claims_line():
				lines.append(self.claims_line())
			if profile.fallback_locale:
				lines.append(
					f"Fallback         : {fallback_used:>6} taken from {profile.fallback_locale} "
					"(where it differs from what is on screen)"
				)

			unwrapped = []
			if self.scan_messages:
				unwrapped = message_route.collect(apps)
				lines.append(f"Not wrapped in _(): {len(unwrapped):>6}")

			# Route 4 runs after the ledger holds the other routes' results, so
			# that "new" means new to every route, not just to this one.
			rendered_untranslated = None
			if self.scan_screens:
				if screen_route.is_available():
					# The crawl takes minutes; the ledger rows written so far must
					# not stay locked for its whole duration.
					frappe.db.commit()
					try:
						from_screen, rendered_untranslated, report = screen_route.collect(
							profile, apps, log=lines, heartbeat=self.heartbeat
						)
						screen_route.keep_connection()
					except Exception as exc:
						# A missing browser, a certificate the browser will not
						# accept, a login that never reaches the desk: the screen
						# route did not run, and the scan says so in one line.
						# The other routes' results are already committed.
						reason = str(exc).splitlines()[0][:160] if str(exc) else exc.__class__.__name__
						screen_route.keep_connection()
						lines.append(f"Screen           : not run — {reason}")
						from_screen, report, rendered_untranslated = [], None, None
					if report:
						screen_new, screen_updated, _ = self._upsert_safely(profile, from_screen)
						for item in rendered_untranslated:
							if item.get("entry") is None:
								item["entry"] = frappe.db.get_value(
									"Translation Entry",
									{"locale": profile.name, "text_hash": text_hash(item["source_text"])},
									"name",
								)
						new_count += screen_new
						updated_count += screen_updated
						lines.append(screen_route.summary_line(report))
						# what was not delivered, what could not be opened
						lines.extend(report.get("details") or [])
						lines.append(f"Ledger (screen): {screen_new} new / {screen_updated} updated")
						if self.claims_line():
							lines.append(self.claims_line())
						# The execution report FR-08 asks for: which screens were
						# visited (records cut to their DocType) and what was
						# normalised before it was stored (PM's rulings 3-3, 5-3).
						for shown, stored in report.get("normalised") or []:
							lines.append(f"Screen normalised: {shown!r} -> {stored!r}")
						routes = report.get("routes") or []
						lines.append(f"Screens visited ({len(routes)}):")
						lines.extend(f"  {r}" for r in routes)
				else:
					lines.append("Screen           : skipped — Playwright is not installed on this server")

			issue_count = self._rebuild_issues(profile, unwrapped, rendered_untranslated)
			lines.append(f"Issues: {issue_count}")

			before = (profile.coverage, profile.total_strings)
			self._summarise(profile)
			if before[1]:
				lines.append(
					f"Coverage         : {before[0]:.1f}% of {before[1]} before this scan, "
					f"{profile.coverage:.1f}% of {profile.total_strings} after"
				)

			# Measuring what should be translated says nothing about whether the
			# answer arrived. This is the line that would have caught a week of
			# production serving English.
			delivered = delivery_route.verify(self.locale)
			delivery_route.summarise(self.locale, delivered)
			lines.append(
				f"Delivery         : {delivered['live']:>6} live / "
				f"{delivered['not_deployed']} not deployed / {delivered['stale']} stale / "
				f"{delivered['overridden']} overridden"
			)

			lines.append(f"Took {time.monotonic() - started:.1f}s")

			self.status = "Completed"
		except Exception:
			self.status = "Failed"
			lines.append(frappe.get_traceback())
			# The failure may be the connection itself, and the report below has
			# to reach the database whatever happened.
			screen_route.keep_connection()
			frappe.db.rollback()

		self.finished_on = now_datetime()
		self.log = "\n".join(lines)
		try:
			self.save(ignore_permissions=True)
		except frappe.TimestampMismatchError:
			# Something else touched the row while the scan ran. The scan's own
			# report is the newer truth and must not be thrown away.
			self.modified = frappe.db.get_value("Translation Scan", self.name, "modified")
			self.save(ignore_permissions=True)
		# The scan runs in a worker for minutes. Its report has to be readable
		# the moment it finishes, not whenever the job happens to end.
		frappe.db.commit()  # nosemgrep

	def _class_source_roles(self, from_source: list[dict], from_database: list[dict]) -> int:
		"""Separate DocPerm role names from the interface text they look like.

		Frappe's doctype collector emits the role of every DocPerm row
		(`frappe/translate.py:341`), so role names arrive on the source route as
		if they were interface text — 43 of them in one customer's gap report,
		the single largest reason it read 2.6x the real figure.

		Matching on the text alone is not enough: "Customer", "Supplier" and
		"Leave Approver" are role names *and* workspace and field labels, and
		dropping those would delete translations the interface genuinely needs.
		A string is only treated as a role when the database route, which knows
		where each string was stored, did not also find it as interface text.
		"""
		try:
			roles = set(frappe.get_all("Role", pluck="name"))
		except Exception:
			return 0
		if not roles:
			return 0

		# Without the database route there is no evidence either way, and
		# guessing would silently drop interface text. Leave them alone.
		if not from_database:
			return 0

		also_interface = {
			item["source_text"] for item in from_database if item.get("string_class") == UI_TEXT
		}
		# The database route reads the site's customisations, not an app's own
		# DocType JSON, so a role that is also a shipped field's label ("Stock
		# Auditor" as a role and as a Data field) needs the field tables asked.
		also_interface |= _field_labels(roles)

		dropped = 0
		for item in list(from_source):
			if item["source_text"] not in roles or item["source_text"] in also_interface:
				continue
			if self.scan_roles:
				item["string_class"] = "Role Name"
			else:
				from_source.remove(item)
				dropped += 1
		return dropped

	# ------------------------------------------------------------------ ledger

	def _upsert_safely(self, profile, collected: list[dict]) -> tuple[int, int, int]:
		"""Write the ledger, retrying a transient lock conflict.

		The ledger is one table per site and a scan writes thousands of rows
		into it in one transaction; anyone editing a translation at that moment
		can deadlock with it, and the loser is chosen by the server. Losing a
		scan that has just spent twenty minutes in a browser to a lock that
		would succeed a second later is not a result anybody wants, so the write
		is attempted again from its own reads.
		"""
		attempts = 3
		for attempt in range(1, attempts + 1):
			new_entries, updated_entries = self.new_entries or 0, self.updated_entries or 0
			try:
				return self._upsert(profile, collected)
			except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
				if attempt == attempts:
					raise
				self.new_entries, self.updated_entries = new_entries, updated_entries
				frappe.db.rollback()
				screen_route.keep_connection()
				time.sleep(2 * attempt)
		raise AssertionError("unreachable")

	def _upsert(self, profile, collected: list[dict]) -> tuple[int, int, int]:
		"""Write the collected strings into the ledger.

		Existing rows keep whatever translation the ledger already holds; a row
		with no translation of its own adopts what Frappe currently resolves, so
		the ledger starts out reflecting reality rather than empty.
		"""
		existing = {
			row.text_hash: row
			for row in frappe.get_all(
				"Translation Entry",
				filters={"locale": profile.name},
				fields=[
					"name",
					"text_hash",
					"translated_text",
					"status",
					"upstream_translation",
					"translation_source",
					"string_class",
					"na_reason",
					"na_rule",
					"app",
				],
				limit_page_length=0,
			)
		}
		# What Frappe puts on screen today, including the parent language it
		# falls back to on its own.
		resolved = frappe.translate.get_all_translations(profile.language)
		# What belongs to this language code alone, and what the configured
		# fallback locale offers. See scanner/resolve.py for the ordering.
		own = resolve.own_translations(profile.language)
		fallback = resolve.fallback_ledger(profile.name)
		# Rows the site held that this scan attributes to an app, per app: the
		# log says how many moved where, since a customer's ledger can see a
		# hundred rows change hands in one scan and wants to trace it later.
		claimed: Counter[str] = Counter()
		# A glossary term marked Do Not Translate, met as a whole string, is a
		# brand name: recorded as Not Applicable with that reason, so the
		# export can ship it as its own translation on purpose.
		brands = brand_rules(profile.name)
		stamp = now_datetime()

		inserts: list[list] = []
		seen: set[str] = set()
		touched: list[str] = []
		updates: list[tuple] = []
		fallback_used = 0

		for item in collected:
			digest = text_hash(item["source_text"], item.get("context"))
			if digest in seen:
				continue
			seen.add(digest)

			if brands and not item.get("na_reason"):
				brand = brand_match(item["source_text"], brands)
				if brand:
					item = {
						**item,
						"na_reason": BRAND_REASON,
						"na_rule": f"Glossary: {brand}",
						"auto_apply": True,
					}

			key = translation_key(item["source_text"], item.get("context"))
			upstream = resolved.get(key)
			own_value = own.get(key)
			fallback_value = fallback.get(digest)
			preferred = own_value or fallback_value or upstream

			# Where the value came from decides whether it counts towards this
			# locale's own coverage. An inherited parent-language string is on
			# screen, but it is not this locale's translation.
			if own_value:
				value_source = "Own"
			elif fallback_value:
				value_source = "Fallback"
				if preferred != upstream:
					fallback_used += 1
			elif upstream:
				value_source = "Inherited"
			else:
				value_source = None

			row = existing.get(digest)

			if row:
				touched.append(row.name)
				# A ledger value identical to what Frappe shows was adopted by a
				# previous scan, not authored by anyone, so a better source may
				# replace it. Anything a person wrote is left alone.
				adopted = not row.translated_text or row.translated_text == row.upstream_translation
				wants = preferred if adopted else row.translated_text
				source = value_source if adopted else "Own"
				values = {}
				if (
					row.upstream_translation != upstream
					or row.translated_text != wants
					or row.translation_source != source
				):
					values.update(
						{
							"upstream_translation": upstream,
							"translated_text": wants,
							"status": "Approved" if wants else "Untranslated",
							"translation_source": source,
						}
					)
					# An exclusion rule must not overturn a decision someone made.
					# It classifies a row that nobody has ruled on yet.
					if row.status == "Not Applicable":
						values.pop("status")
				if row.get("string_class") != item.get("string_class"):
					values["string_class"] = item.get("string_class")
				# "site" is what a route writes when it cannot tell whose string
				# this is. The first scan that can tell may say so; an app already
				# named is not replaced by another, since the first finder owns it.
				if row.get("app") == "site" and item.get("app") and item["app"] != "site":
					values["app"] = item["app"]
					claimed[item["app"]] += 1
				# A rule added since the row was filed applies to a row nobody has
				# decided on: untranslated, and with no translation of its own.
				if (
					row.status == "Untranslated"
					and not row.translated_text
					and not wants
					and item.get("na_reason")
					and item.get("auto_apply")
				):
					values["status"] = "Not Applicable"
				# A reason on a row someone (or a rule) already ruled Not Applicable
				# is a decision; a scan that no longer matches a rule must not erase it.
				if row.status != "Not Applicable" or item.get("na_reason"):
					for field in ("na_reason", "na_rule"):
						if row.get(field) != item.get(field):
							values[field] = item.get(field)
				if values:
					updates.append((row.name, values))
				continue

			inserts.append(
				[
					frappe.generate_hash(length=10),
					stamp,
					stamp,
					frappe.session.user,
					frappe.session.user,
					0,
					0,
					profile.name,
					item["source_text"],
					item.get("context"),
					digest,
					upstream or "",
					preferred or "",
					_status_for(item, preferred),
					value_source,
					item.get("string_class") or "UI Text",
					item.get("na_reason"),
					item.get("na_rule"),
					item["origin"],
					item.get("app"),
					item.get("source_path"),
					item.get("line_no") or 0,
					item.get("reference_doctype"),
					item.get("reference_name"),
					item.get("reference_field"),
					item.get("occurrences") or 1,
					stamp,
				]
			)

		if inserts:
			frappe.db.bulk_insert(
				"Translation Entry",
				fields=[
					"name",
					"creation",
					"modified",
					"modified_by",
					"owner",
					"docstatus",
					"idx",
					"locale",
					"source_text",
					"context",
					"text_hash",
					"upstream_translation",
					"translated_text",
					"status",
					"translation_source",
					"string_class",
					"na_reason",
					"na_rule",
					"origin",
					"app",
					"source_path",
					"line_no",
					"reference_doctype",
					"reference_name",
					"reference_field",
					"occurrences",
					"last_seen_on",
				],
				values=inserts,
				chunk_size=CHUNK,
			)

		for name, values in updates:
			frappe.db.set_value("Translation Entry", name, values, update_modified=False)

		for offset in range(0, len(touched), CHUNK):
			frappe.db.set_value(
				"Translation Entry",
				{"name": ("in", touched[offset : offset + CHUNK])},
				"last_seen_on",
				stamp,
				update_modified=False,
			)

		# Two routes write in turn (screens after the rest), so counts accumulate.
		self.new_entries = (self.new_entries or 0) + len(inserts)
		self.updated_entries = (self.updated_entries or 0) + len(updates)
		self.claimed_from_site = claimed
		return len(inserts), len(updates), fallback_used

	def claims_line(self) -> str | None:
		"""The log line for rows the last write took from the site, or None."""
		claimed = getattr(self, "claimed_from_site", None)
		if not claimed:
			return None
		by_app = ", ".join(f"{app} {count}" for app, count in claimed.most_common())
		return f"Claimed from site: {sum(claimed.values())} ({by_app})"

	# ------------------------------------------------------------------ issues

	def _rebuild_issues(
		self, profile, unwrapped: list[dict], rendered_untranslated: list[dict] | None = None
	) -> int:
		"""Issues are derived data: every scan replaces the ones it owns.

		Rows a reviewer marked Ignored are kept, so a decision is not undone by
		the next run. `rendered_untranslated` is None when the screen route
		did not run, and its findings from the last run are then kept too.
		"""
		kept = frappe.get_all(
			"Translation Issue",
			filters={"locale": profile.name, "status": "Ignored"},
			fields=["issue_type", "source_text"],
			limit_page_length=0,
		)
		ignored = {(row.issue_type, row.source_text) for row in kept}

		# Each route owns its issues; a route that did not run this time leaves
		# its findings from the last time it did. "Not Wrapped" is raised by two
		# routes — code messages (location "file:line") and the screen crawl
		# (location "/app/...") — so they are told apart by where they point.
		frappe.db.delete(
			"Translation Issue",
			{"locale": profile.name, "status": ("!=", "Ignored"), "issue_type": ("!=", "Not Wrapped")},
		)
		if self.scan_messages:
			frappe.db.delete(
				"Translation Issue",
				{
					"locale": profile.name,
					"status": ("!=", "Ignored"),
					"issue_type": "Not Wrapped",
					"location": ("not like", "/app/%"),
				},
			)
		if rendered_untranslated is not None:
			frappe.db.delete(
				"Translation Issue",
				{
					"locale": profile.name,
					"status": ("!=", "Ignored"),
					"issue_type": "Not Wrapped",
					"location": ("like", "/app/%"),
				},
			)

		glossary = validate.compile_glossary(
			frappe.get_all(
				"Glossary Term",
				filters={"locale": profile.name},
				fields=[
					"source_term",
					"translated_term",
					"do_not_translate",
					"match_type",
					"case_sensitive",
					"enforce",
					"forbidden_terms",
				],
				limit_page_length=0,
			)
		)
		allowed_latin = set(as_lines(get_settings().allowed_latin_terms))
		latin_script = bool(profile.uses_latin_script)
		stamp = now_datetime()
		rows: list[list] = []

		def add(
			issue_type, severity, source_text, translated_text, detail, entry=None, app=None, location=None
		):
			if (issue_type, source_text) in ignored:
				return
			rows.append(
				[
					frappe.generate_hash(length=10),
					stamp,
					stamp,
					frappe.session.user,
					frappe.session.user,
					0,
					0,
					profile.name,
					issue_type,
					severity,
					"Open",
					entry,
					self.name,
					app,
					source_text[:500],
					(translated_text or "")[:500],
					detail[:500],
					location,
				]
			)

		entries = frappe.get_all(
			"Translation Entry",
			filters={"locale": profile.name, "status": ("!=", "Not Applicable")},
			fields=[
				"name",
				"source_text",
				"translated_text",
				"status",
				"app",
				"source_path",
				"line_no",
				"reference_doctype",
				"reference_name",
			],
			limit_page_length=0,
		)

		flagged: list[str] = []
		for entry in entries:
			location = entry.source_path or (
				f"{entry.reference_doctype}: {entry.reference_name}" if entry.reference_doctype else None
			)
			if not entry.translated_text:
				add(
					"Untranslated",
					"Medium",
					entry.source_text,
					"",
					"No translation",
					entry.name,
					entry.app,
					location,
				)
				continue

			found = validate.check(
				entry.source_text,
				entry.translated_text,
				glossary=glossary,
				allowed_latin=allowed_latin,
				latin_script=latin_script,
			)
			if found:
				flagged.append(entry.name)
			for issue in found:
				add(
					issue["issue_type"],
					issue["severity"],
					entry.source_text,
					entry.translated_text,
					issue["detail"],
					entry.name,
					entry.app,
					location,
				)

		for item in unwrapped:
			add(
				"Not Wrapped",
				"High",
				item["source_text"],
				"",
				f"A literal is passed straight to {item['call']} ({item['kind']}). It never reaches a "
				"translation function, so it appears as written in every language.",
				None,
				item["app"],
				f"{item['source_path']}:{item['line_no']}",
			)

		# A translation the site resolves that the screen nevertheless shows in
		# English: the code that renders it never asked for the translation.
		# Same cause as a bare literal in frappe.throw, so the same issue type
		# (PM's ruling 3-1); the detail says it came from the screen and where.
		for item in rendered_untranslated or []:
			add(
				"Not Wrapped",
				"High",
				item["source_text"],
				item["translated_text"],
				f"screen: {item['route']} ({item.get('kind', 'text')}). Rendered as {item.get('shown', item['source_text'])!r} "
				f"although the site resolves it to {item['translated_text']!r}: the screen was drawn without "
				"asking for the translation. Seen with a workspace heading drawn from its content JSON, a "
				"button whose label is set without __(), and a form served from a cached English copy of its "
				"doctype. Translating the string will not change the screen until the code that draws it asks.",
				item["entry"],
				item["app"],
				item["route"],
			)

		if rows:
			frappe.db.bulk_insert(
				"Translation Issue",
				fields=[
					"name",
					"creation",
					"modified",
					"modified_by",
					"owner",
					"docstatus",
					"idx",
					"locale",
					"issue_type",
					"severity",
					"status",
					"translation_entry",
					"scan",
					"app",
					"source_text",
					"translated_text",
					"detail",
					"location",
				],
				values=rows,
				chunk_size=CHUNK,
			)

		frappe.db.set_value(
			"Translation Entry", {"locale": profile.name}, "has_issues", 0, update_modified=False
		)
		for offset in range(0, len(flagged), CHUNK):
			frappe.db.set_value(
				"Translation Entry",
				{"name": ("in", flagged[offset : offset + CHUNK])},
				"has_issues",
				1,
				update_modified=False,
			)

		self.issues_found = len(rows)
		return len(rows)

	# ----------------------------------------------------------------- summary

	def _summarise(self, profile):
		counts = frappe.db.sql(
			"""
			select app, origin, coalesce(nullif(string_class, ''), 'UI Text') as string_class,
				count(*) as total,
				sum(case when translated_text is null or translated_text = '' then 0 else 1 end) as translated
			from `tabTranslation Entry`
			where locale = %s and status != 'Not Applicable'
			group by app, origin, string_class
			""",
			profile.name,
			as_dict=True,
		)

		self.set("results", [])
		total = translated = 0
		for row in sorted(counts, key=lambda r: (r.app or "", r.origin or "", r.string_class or "")):
			row_total = int(row.total or 0)
			row_translated = int(row.translated or 0)
			# Roles and master data are reported, never folded into the headline.
			# A single percentage across three kinds of string is the figure that
			# made a 98-string gap read as 255.
			if row.string_class == UI_TEXT:
				total += row_total
				translated += row_translated
			self.append(
				"results",
				{
					"app_name": row.app,
					"source_kind": row.origin,
					"string_class": row.string_class,
					"total_strings": row_total,
					"translated_strings": row_translated,
					"untranslated_strings": row_total - row_translated,
					"coverage": (row_translated / row_total * 100) if row_total else 0,
				},
			)

		self.total_strings = total
		self.translated_strings = translated
		self.untranslated_strings = total - translated
		self.coverage = (translated / total * 100) if total else 0

		open_issues = frappe.db.count("Translation Issue", {"locale": profile.name, "status": "Open"})
		by_app = {}
		for row in self.results:
			if row.string_class != UI_TEXT:
				continue
			bucket = by_app.setdefault(row.app_name, [0, 0])
			bucket[0] += row.total_strings
			bucket[1] += row.translated_strings

		# The app list is configuration when the operator set one, so the scan
		# updates its numbers rather than replacing the rows. An empty list means
		# "everything installed", and there the scan fills it in.
		configured = [row.app_name for row in profile.target_apps if row.app_name]
		if configured:
			for row in profile.target_apps:
				app_total, app_translated = by_app.get(row.app_name, (0, 0))
				row.total_strings = app_total
				row.translated_strings = app_translated
				row.untranslated_strings = app_total - app_translated
				row.coverage = (app_translated / app_total * 100) if app_total else 0
		else:
			for app_name, (app_total, app_translated) in sorted(by_app.items()):
				profile.append(
					"target_apps",
					{
						"app_name": app_name,
						"total_strings": app_total,
						"translated_strings": app_translated,
						"untranslated_strings": app_total - app_translated,
						"coverage": (app_translated / app_total * 100) if app_total else 0,
					},
				)

		# A parent-language string is on screen but is not this locale's
		# translation. For zh-HK the two figures differ by a factor of five, and
		# only the second one says whether Hong Kong can go live.
		own_translated = frappe.db.count(
			"Translation Entry",
			{
				"locale": profile.name,
				"status": ("!=", "Not Applicable"),
				"string_class": UI_TEXT,
				"translation_source": ("in", ["Own", "Fallback"]),
			},
		)

		profile.total_strings = total
		profile.translated_strings = translated
		profile.untranslated_strings = total - translated
		profile.coverage = self.coverage
		profile.own_translated_strings = own_translated
		profile.own_coverage = (own_translated / total * 100) if total else 0
		profile.open_issues = open_issues
		profile.last_scan = self.name
		profile.last_scanned_on = now_datetime()
		profile.save(ignore_permissions=True)


def _field_labels(texts: set[str]) -> set[str]:
	"""Those of `texts` that are the label of a shipped or custom field."""
	if not texts:
		return set()
	found: set[str] = set()
	for table in ("tabDocField", "tabCustom Field"):
		# `table` is one of the two literals above; the texts are a parameter.
		rows = frappe.db.sql(  # nosemgrep
			f"select distinct `label` from `{table}` where `label` in %(texts)s", {"texts": list(texts)}
		)
		found.update(row[0] for row in rows if row[0])
	return found


def target_apps(profile) -> list[str]:
	"""Apps named on the profile, or every app installed on the site."""
	named = [row.app_name for row in profile.target_apps if row.app_name]
	installed = frappe.get_installed_apps()
	if not named:
		return installed
	return [app for app in named if app in installed]


def execute(scan: str):
	frappe.get_doc("Translation Scan", scan).run()


def scan_order(locales: list[str]) -> list[str]:
	"""Fallback sources first.

	zh-HK takes its translations from the zh-TW ledger, so measuring Hong Kong
	before Taiwan would read an empty or stale source.
	"""
	fallbacks = {
		row.name: row.fallback_locale
		for row in frappe.get_all(
			"Locale Profile", filters={"name": ("in", locales)}, fields=["name", "fallback_locale"]
		)
	}

	ordered: list[str] = []

	def place(locale, guard):
		if locale in ordered or locale in guard or locale not in fallbacks:
			return
		guard.add(locale)
		if fallbacks.get(locale):
			place(fallbacks[locale], guard)
		if locale not in ordered:
			ordered.append(locale)

	for locale in locales:
		place(locale, set())
	return ordered


def run_scheduled_scans():
	"""Weekly measurement for every enabled locale.

	The point of the app is that coverage is a number that moves as upstream
	development continues, not a one-off report.
	"""
	locales = frappe.get_all("Locale Profile", filters={"enabled": 1}, pluck="name")
	for locale in scan_order(locales):
		scan = frappe.get_doc({"doctype": "Translation Scan", "locale": locale}).insert(
			ignore_permissions=True
		)
		scan.enqueue_run()
