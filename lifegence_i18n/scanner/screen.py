"""Route 4 — strings as they are actually rendered on the screen.

The three other routes measure what *should* be translated: strings in source
files, strings stored in the database, literals that never reach a translation
function. None of them sees the page. A workspace heading kept inside a JSON
blob, a shortcut's count format, a button whose label is set without `__()` —
all of those stay English on a Japanese screen and stay invisible to the other
routes. This route logs in with a browser, walks the screens, and reports the
text that a user of the locale really sees.

Two questions have to be answered for every string on a page, and both are
answered by *where it sits*, never by what it looks like:

1. Is it interface text or the customer's data? A form value, a list row, a
   grid row, a tree node, a chart label, the record name in the URL, the names
   of master records, the signed-in user's own name — those are data. Frappe's
   CSS classes for these regions have been stable across version-15 and 16.
2. Is it already translated? Japanese on screen means yes. A rendered string
   equal to some translation means yes. Otherwise it is matched against the
   ledger — as is, normalised, with values put back into placeholders, and
   against templates such as "You haven't created a {0} yet".

Playwright is an optional dependency: `is_available()` says whether this route
can run here. On Frappe Cloud it cannot, and the scan carries on without it.
"""

import html
import json
import re
import time
from collections import Counter
from urllib.parse import quote

import frappe
import frappe.utils
from frappe import _

from lifegence_i18n.utils import as_lines, classify, compiled_exclusion_rules, get_settings, resolved_key

ORIGIN = "Screen"
PING_EVERY = 25  # screens between keep-alive queries
IDLE_TIMEOUT = 4000  # ms to wait for the network to fall quiet
DRAWN_TIMEOUT = 15000  # ms to wait for the desk to have drawn the page
DRAWN = ".page-head, .layout-main-section, .message-page, .desk-page, .page-container"

LATIN = re.compile(r"[A-Za-z]{2,}")
CJK = re.compile(
	r"[぀-ヿ㐀-鿿가-힯･-ﾟ０-ｚ豈-﫿]"
)  # kana, han, hangul, half-width kana, full-width alnum, compat han
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
NON_ASCII_LETTER = re.compile(r"[À-ɏ]")
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,.:%]*")
NOISE = re.compile(
	r"^(?:[\d\s.,:/%¥$€£-]+(?:\s?(?:Cr|Dr))?|[A-Z]{1,2}|\W+)$"
)  # numbers, amounts, 1-2 letter codes, punctuation
try:
	from zoneinfo import available_timezones

	TIME_ZONES = available_timezones()  # "Asia/Tokyo" is a value, "Yes/No" is a label
except Exception:  # no tzdata on this system
	TIME_ZONES = set()
PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}|%s|%d|%\([a-z_]+\)s")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")
BLOCK_END = re.compile(r"</?(?:br|p|h[1-6]|li|ul|ol|div|tr|td|th|section)\b[^>]*>", re.IGNORECASE)
MD_MARKER = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)")
MD_EMPHASIS = re.compile(r"\*\*|__|`")
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
KEY_COMBO = re.compile(r"^(?:Ctrl|Cmd|Alt|Shift|Meta|⌘|⇧|⌥)(?:\s*\+\s*\S+)+$", re.IGNORECASE)
# "4 To Receive", "0/4 steps completed", "0% completed", "0 % since yesterday":
# a count the page put in front of a phrase. The phrase is the string.
LEADING_COUNT = re.compile(r"^[-+]?\d[\d,.]*\s*(?:/\s*\d[\d,.]*)?\s*%?\s+(?=[A-Za-z])")
HASH_NAME = re.compile(r"^[0-9a-z]{10}$")  # Frappe autoname=hash: ten lower-case alphanumerics
LABEL_VALUE = re.compile(r"^(?P<label>[^:：]{1,60}?)\s*[:：]\s*(?P<value>.+)$")
# Frappe appends the site's time zone to the description of every Datetime
# field (`controls/datetime.js`), so the sentence on screen is the sentence in
# the ledger plus " Asia/Tokyo". The source string is the sentence.
TZ_SUFFIX = re.compile(r"\s+([A-Za-z]{3,}(?:/[A-Za-z0-9_+-]+){1,2})$")
# A count rendered beside a label ("1 Wiki Page Revision" on the form
# dashboard): the label is the string, the number is data.
BARE_COUNT = re.compile(r"^\s*\d[\d,.]*\s+|\s+\d[\d,.]*\s*$")


def strip_timezone(text: str) -> str:
	match = TZ_SUFFIX.search(text)
	if match and match.group(1) in TIME_ZONES:
		return text[: match.start()].rstrip()
	return text


# Records the customer names. Their names are data wherever they are printed.
MASTER_DOCTYPES = [
	"Company",
	"Warehouse",
	"Account",
	"Cost Center",
	"Department",
	"Branch",
	"Item Group",
	"Customer Group",
	"Supplier Group",
	"Territory",
	"Sales Person",
	"UOM",
	"Designation",
	"Holiday List",
	"Fiscal Year",
	"Price List",
	"Brand",
	"Project",
	"Location",
]

COLLECT_JS = r"""
() => {
  const INLINE = new Set(['SPAN','B','I','U','EM','STRONG','SMALL','SUP','SUB','MARK','KBD','CODE','ABBR','A','LABEL','FONT','S','DEL','INS']);
  const SKIP_TAGS = new Set(['SCRIPT','STYLE','NOSCRIPT','TEXTAREA','SVG','PATH','TEMPLATE']);
  // Regions holding the user's data or system-generated text, not labels.
  const DATA = [
    '.control-value', '.control-input', '.like-disabled-input',
    '.list-row-container', '.dt-cell', '.grid-row:not(.grid-heading-row)',
    '.timeline', '.form-footer', '.comment-box', '.form-sidebar',
    '.datepicker', '.datepicker--nav', '.datepicker--days-names',
    '.list-sidebar .indicator-pill', '.list-sidebar .dropdown-menu', '.group-by-count', '.sidebar-stat',
    '.avatar', '.form-dashboard tbody', '.chart-container', 'svg',
    '.checkbox-options', '.multiselect-list', '.awesomplete ul', '.form-tags', 'input',
    '.tree-node', '.kanban-card', '.fc-event', '.fc-content', '.gantt', '.image-view-item',
    '.ace_editor', '.ace_content', '.CodeMirror', '.frappe-control[data-fieldtype="Code"]',
    '.frappe-control[data-fieldtype="Markdown Editor"]', '.frappe-control[data-fieldtype="HTML Editor"]',
    '.datatable .dt-cell--header', '.result-list', '.breadcrumb-container .breadcrumb .disabled',
    '.count', '.badge-count', '.list-count', '.comment-count', '.document-link-badge .count',
    '.form-builder', '.form-builder-container', '.customize-form .grid-body',
  ].join(',');
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const norm = (t) => t.replace(/\s+/g, ' ').trim();
  const hasDirectText = (el) => {
    for (const c of el.childNodes) if (c.nodeType === 3 && norm(c.textContent)) return true;
    return false;
  };
  const inlineText = (el) => {
    let out = '';
    for (const c of el.childNodes) {
      if (c.nodeType === 3) out += c.textContent;
      else if (c.nodeType === 1 && INLINE.has(c.tagName) && !SKIP_TAGS.has(c.tagName) && !c.matches(DATA)) out += inlineText(c);
      else if (c.nodeType === 1 && c.tagName === 'BR') out += ' ';
    }
    return out;
  };
  const labels = new Map(), data = new Set();
  const kindOf = (el) => {
    const tag = el.tagName;
    if (el.closest('button, .btn')) return 'button';
    if (/^H[1-6]$/.test(tag) || el.closest('h1,h2,h3,h4,h5,h6,.h4,.h5,.h6')) return 'heading';
    if (tag === 'A' || el.closest('a')) return 'link';
    if (tag === 'LABEL' || el.closest('label, .control-label')) return 'label';
    if (tag === 'TH' || el.closest('th')) return 'column heading';
    return 'text';
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const done = new Set();
  let n;
  while ((n = walker.nextNode())) {
    if (!norm(n.textContent)) continue;
    let p = n.parentElement;
    if (!p || SKIP_TAGS.has(p.tagName)) continue;
    // The unit of text is the nearest non-inline ancestor, but only while the
    // parent carries prose of its own: a button's access-key letter sits in
    // its own <span> and must be joined back to the rest of the label.
    let unit = p;
    while (unit.parentElement && INLINE.has(unit.tagName) && !unit.matches(DATA)
           && (hasDirectText(unit.parentElement) || unit.textContent.trim().length <= 2)) unit = unit.parentElement;
    if (done.has(unit)) continue;
    done.add(unit);
    if (!visible(p)) continue;
    const t = norm(inlineText(unit));
    if (!t) continue;
    if (unit.closest(DATA)) data.add(t); else if (!labels.has(t)) labels.set(t, kindOf(unit));
  }
  for (const el of document.querySelectorAll('[title], [placeholder]')) {
    if (!visible(el) || el.closest(DATA)) continue;
    for (const attr of ['title', 'placeholder']) {
      const v = norm(el.getAttribute(attr) || '');
      if (v && !labels.has(v)) labels.set(v, attr === 'title' ? 'tooltip' : 'placeholder');
    }
  }
  for (const el of document.querySelectorAll('input, textarea')) {
    if (el.value && norm(el.value)) data.add(norm(el.value));
  }
  // Options of a Select field are interface text; the chosen one is also a value.
  for (const el of document.querySelectorAll('select.form-control option, select[data-fieldtype="Select"] option')) {
    const t = norm(el.textContent);
    if (t) { if (!labels.has(t)) labels.set(t, 'option'); if (el.selected) data.add(t); }
  }
  return {labels: Array.from(labels, ([text, kind]) => ({text, kind})), data: Array.from(data)};
}
"""


def keep_connection() -> None:
	"""Make sure the scan still has a database connection.

	The three other routes commit before the crawl starts and the crawl itself
	asks the database nothing, so on a server that closes idle connections the
	first query afterwards fails with "server has gone away" — and a scan that
	has already spent twenty minutes in a browser dies holding results it has
	paid for. Observed on version-16 during the public-app validation.
	"""
	try:
		frappe.db.sql("select 1")
		return
	except Exception:
		pass
	try:
		frappe.db.connect()
	except Exception:
		frappe.log_error("Lost the database connection during a screen crawl", "I18n screen route")


def is_available() -> bool:
	try:
		import playwright.sync_api  # noqa: F401
	except ImportError:
		return False
	return True


# --------------------------------------------------------------------- ledger


def normalise(text: str) -> str:
	return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def fragments(text: str):
	"""The lines a stored string is rendered as, when it is not one line.

	A DocType description is markdown and an HTML field is markup; Frappe
	translates each as one string, and the browser shows it as a heading, a
	paragraph and a list of items. Every one of those pieces looks like an
	untranslated string that no route knows, and none of them can be
	translated on its own: the ledger already holds the whole of it.
	"""
	if "\n" not in text and "<" not in text:
		return
	plain = TAG.sub("", BLOCK_END.sub("\n", text))
	blocks = []
	for line in html.unescape(plain).split("\n"):
		line = MD_MARKER.sub("", line)
		line = MD_EMPHASIS.sub("", line)
		line = MD_LINK.sub(r"\1", line).strip()
		if line:
			blocks.append(line)
	# One block means markup wrapped around a single label ("<b>Save</b>"),
	# which is that label and not a row with pieces inside it.
	if len(blocks) < 2:
		return
	for line in blocks:
		# Short pieces are common words that would swallow a real gap; a piece
		# worth indexing is a sentence, a heading or a list item.
		if len(line) >= 12 and len(WORD.findall(line)) >= 2:
			yield normalise(line)


class Ledger:
	"""The locale's ledger, loaded once, matched several ways."""

	def __init__(self, rows, allowed_latin: set[str]):
		self.allowed_latin = {t.lower() for t in allowed_latin}
		self.data: set[str] = set()
		self.exact: dict[str, dict] = {}
		self.normal: dict[str, dict] = {}
		self.templates: list = []
		self.short_templates: list = []
		self.fragments: dict[str, dict] = {}
		self.flattened: dict[str, dict] = {}
		self.translated_values: set[str] = set()
		self.source_words: Counter = Counter()
		self.target_words: Counter = Counter()
		# rows without a context first, so a bare source text finds the bare row
		for row in sorted(rows, key=lambda r: bool(r.get("context"))):
			src = row["source_text"]
			self.exact.setdefault(src, row)
			self.normal.setdefault(normalise(src), row)
			if row.get("translated_text") and normalise(row["translated_text"]) != normalise(src):
				self.translated_values.add(normalise(row["translated_text"]))
			for piece in fragments(src):
				self.fragments.setdefault(piece, row)
			# A description with <br> in it arrives on screen as one line with
			# the markup gone. That line is this row, not a string of its own.
			if "<" in src:
				# the same flattening the browser does: a block tag becomes a
				# line break, an inline one (<code>, <b>) disappears without
				# leaving a space where it stood
				self.flattened.setdefault(normalise(TAG.sub("", BLOCK_END.sub("\n", src))), row)
			literal = PLACEHOLDER.sub("", src)
			if PLACEHOLDER.search(src) and WORD.findall(literal):
				pattern = re.escape(normalise(src))
				pattern = re.sub(r"\\\{[0-9a-zA-Z_]*\\\}|%s|%d|%\\\([a-z_]+\\\)s", r"(.+?)", pattern)
				try:
					compiled = re.compile("^" + pattern + "$")
				except re.error:
					continue
				# "{0}" alone would match everything; a template needs literal text.
				if len(WORD.findall(literal)) >= 2 and len(literal.strip()) >= 8:
					self.templates.append((compiled, row))
				else:
					self.short_templates.append((compiled, row))
			for w in WORD.findall(src):
				self.source_words[w.lower()] += 1
			for w in WORD.findall(row.get("translated_text") or ""):
				self.target_words[w.lower()] += 1
		self.target_only = {w for w, n in self.target_words.items() if self.source_words.get(w, 0) < n}

	def find(self, text: str):
		for key in (
			text,
			text.strip(),
			normalise(text),
			re.sub(r"^[\W_]+|[\W_]+$", "", text).strip(),
			NUMBER.sub("{0}", text).strip(),
			NUMBER.sub("{}", text).strip(),
			re.sub(r"\([^)]*\)", "({0})", text).strip(),
			re.sub(r"\s*\([^)]*\)\s*$", "", text).strip(),
			BARE_COUNT.sub("", text).strip(),
			# the ledger may hold the phrase alone: erpnext builds
			# "0/4 steps completed" as a count and __("steps completed")
			LEADING_COUNT.sub("", text).strip(),
		):
			row = self.exact.get(key) or self.normal.get(normalise(key))
			if row:
				return row
		norm = normalise(text)
		best = None
		for pattern, row in self.templates:
			if pattern.match(norm) and (best is None or len(row["source_text"]) > len(best["source_text"])):
				best = row
		if best:
			return best
		# "Add {0}" only when what was substituted is itself a known string or a value
		for pattern, row in self.short_templates:
			m = pattern.match(norm)
			if m and all(
				g.strip() in self.exact or normalise(g) in self.normal or g.strip() in self.data
				for g in m.groups()
			):
				return row
		# A description whose markup the browser turned into spaces, or one
		# line of a row the ledger holds whole: the gap is that row, and it is
		# already counted.
		return self.flattened.get(norm) or self.fragments.get(norm)

	def looks_english(self, text: str, target_is_latin: bool) -> bool:
		words = [w.lower() for w in WORD.findall(text)]
		if not words or all(w in self.allowed_latin for w in words):
			return False
		if NON_ASCII_LETTER.search(text):
			return False  # a diacritic belongs to the target language, or a name
		if not target_is_latin:
			return True
		known_en = sum(1 for w in words if w in self.source_words)
		known_target = sum(1 for w in words if w in self.target_only)
		return known_en >= max(1, len(words) * 0.6) and known_target == 0

	def is_candidate(self, text: str, target_is_latin: bool) -> bool:
		if not LATIN.search(text) or NOISE.match(text) or text in TIME_ZONES:
			return False
		if text.endswith(("...", "…")):
			return False  # truncated by the widget: not a whole string
		if KEY_COMBO.match(text):
			return False  # a keyboard shortcut hint, not prose
		if normalise(text) in self.translated_values:
			return False  # this is what a translation looks like
		if not target_is_latin and CJK.search(text):
			# Translated — unless only the value was: "Show アイテム List" is the
			# untranslated template "Show {0} List" around a translated value.
			row = self.find(text)
			return bool(row and not row.get("translated_text") and PLACEHOLDER.search(row["source_text"]))
		return self.looks_english(text, target_is_latin)


def label_part(text: str, data: set) -> str:
	"""'ID: 0ru39kd5oj' is the label 'ID' printed with a value."""
	m = LABEL_VALUE.match(text)
	if not m:
		return text
	value = m.group("value").strip()
	if value in data or HASH_NAME.match(value) or re.fullmatch(r"[\d\s.,:/%¥$€£-]+", value):
		return m.group("label").strip()
	return text


def load_ledger(locale: str) -> Ledger:
	rows = frappe.get_all(
		"Translation Entry",
		filters={"locale": locale},
		fields=["name", "source_text", "context", "translated_text", "status", "origin", "app"],
		limit_page_length=0,
	)
	return Ledger(rows, set(as_lines(get_settings().allowed_latin_terms)))


# --------------------------------------------------------------------- routes


CORE_APPS = ("frappe", "erpnext")


def discover_routes(apps: list[str], cap: int | None) -> list[tuple[str, str]]:
	"""(route, app) for the screens to visit: every public workspace, then for
	each DocType of the target apps a list view, a blank form and one record.

	The customer's own apps come first, frappe and erpnext last: when the
	crawl stops at its maximum, the screens nobody else has measured are the
	ones that must have been seen. A public workspace made in the UI has no
	module and belongs to no app; it is visited as the site's, and before
	any app's, since nothing but a crawl can measure what a site made for
	itself. So the first route is not always the customer app's workspace.
	"""
	module_app = {m.name: m.app_name for m in frappe.get_all("Module Def", fields=["name", "app_name"])}
	rank = {app: (1 if app in CORE_APPS else 0, app) for app in apps}
	routes: list[tuple[str, str]] = []

	def slug(name):
		return name.lower().replace(" ", "-")

	workspaces = []
	for ws in frappe.get_all("Workspace", filters={"public": 1, "is_hidden": 0}, fields=["name", "module"]):
		app = module_app.get(ws.module, "site")
		if app in apps or app == "site":
			workspaces.append((rank.get(app, (0, "")), ws.name, app))
	for _rank, name, app in sorted(workspaces):
		routes.append((f"/app/{slug(name)}", app))
	singles = [
		(rank[module_app[dt.module]], dt)
		for dt in frappe.get_all("DocType", filters={"issingle": 1}, fields=["name", "module"])
		if module_app.get(dt.module) in rank
	]
	for _rank, dt in sorted(singles, key=lambda x: (x[0], x[1].name)):
		routes.append((f"/app/{slug(dt.name)}", module_app[dt.module]))
	doctypes = [
		(rank[module_app[dt.module]], dt)
		for dt in frappe.get_all("DocType", filters={"istable": 0, "issingle": 0}, fields=["name", "module"])
		if module_app.get(dt.module) in rank
	]
	for _rank, dt in sorted(doctypes, key=lambda x: (x[0], x[1].name)):
		app = module_app[dt.module]
		routes.append((f"/app/{slug(dt.name)}", app))
		routes.append((f"/app/{slug(dt.name)}/new", app))
		try:
			first = frappe.get_all(dt.name, fields=["name"], limit_page_length=1)
		except Exception:
			first = []
		if first:
			routes.append((f"/app/{slug(dt.name)}/{quote(str(first[0].name), safe='')}", app))
	return routes[:cap] if cap else routes


def public_route(route: str) -> str:
	"""The route without the record it happened to show: a customer's record
	name is never written to the ledger or the log (PM's ruling 3-4)."""
	parts = route.split("/")
	if len(parts) == 4 and parts[3] != "new":  # "", "app", "<doctype>", "<name>"
		return "/".join(parts[:3])
	return route


def master_names() -> set[str]:
	names: set[str] = set()
	for doctype in MASTER_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			names.update(frappe.get_all(doctype, pluck="name", limit_page_length=5000))
	try:
		names.update(frappe.get_all("Installed Application", pluck="app_name"))
	except Exception:
		pass
	return names


# ---------------------------------------------------------------------- crawl


def collect(
	profile, apps: list[str], *, log=None, cap: int | None = None, heartbeat=None
) -> tuple[list[dict], list[dict], dict]:
	"""Crawl the configured site as a user of the profile's language.

	Returns (new_strings, rendered_untranslated, report):
	  new_strings — strings no other route knows, as ledger records
	  rendered_untranslated — ledger rows that showed up in English although
	                          the site serves their translation (a defect of
	                          the code that drew them)
	  report — screens, seconds, counts, and the detail lines that belong
	           under the summary line in the scan log
	"""
	settings = get_settings()
	base = (settings.screen_site_url or frappe.utils.get_url()).rstrip("/")
	from urllib.parse import urlparse

	if not settings.screen_site_url and frappe.conf.webserver_port and urlparse(base).port is None:
		base = f"{base}:{frappe.conf.webserver_port}"  # a bench without host_name serves on its port
	# Administrator when unset (PM's ruling 4-1); a read-only user is recommended
	# because any System Manager can read a stored password back.
	user = settings.screen_user or "Administrator"
	password = settings.get_password("screen_password", raise_exception=False)
	if not password:
		frappe.throw(_("Set the screen crawl password in I18n Settings"))
	# A crawl user who reads the site in another language would make every
	# screen look untranslated. On this site that is checked before a browser
	# is started; on a remote site the desk says, after login, which language
	# it serves, and the crawl stops there if it is the wrong one.
	if not settings.screen_site_url:
		language = frappe.db.get_value("User", user, "language") or frappe.db.get_single_value(
			"System Settings", "language"
		)
		if language and language != profile.language:
			frappe.throw(
				_("The crawl user {0} reads the site in {1}, not {2}").format(
					user, language, profile.language
				)
			)
	elif log is not None:
		log.append(f"Screen: crawling {base} as {user}")
	# 0 means no limit: the operator decides whether a scan walks every screen
	# or stops early. The default of 300 is provisional until the PM rules on it.
	if cap is None:
		cap = frappe.flags.get("screen_cap")
	if cap is None:
		cap = int(settings.screen_max_screens or 0) or None
	locale = profile.name
	target_is_latin = bool(profile.uses_latin_script)
	# What the site resolves right now: a translation the screen should show.
	# This bench's dictionary to begin with; replaced by the crawled site's own
	# as soon as the desk has been read after login (see _site_dictionary).
	resolved = frappe.translate.get_all_translations(profile.language)

	ledger = load_ledger(locale)
	rules = compiled_exclusion_rules()
	min_length = settings.min_string_length or 2
	session_data = master_names()
	me = (
		frappe.db.get_value("User", user, ["full_name", "first_name", "email", "username"], as_dict=True)
		or {}
	)
	session_data |= {v for v in me.values() if isinstance(v, str) and v}
	routes = discover_routes(apps, cap)

	started = time.monotonic()
	seen: set[str] = set()
	apps_seen: dict[str, set[str]] = {}
	normalised: list[tuple[str, str]] = []  # (as shown, as stored), for the log
	new_strings: list[dict] = []
	rendered_untranslated: list[dict] = []
	not_delivered: list[dict] = []
	confirmed = 0
	failed: list[str] = []
	visited: list[str] = []

	# Imported here, after the settings checks, so a misconfiguration is
	# reported as such even where Playwright is absent.
	from playwright.sync_api import sync_playwright

	with sync_playwright() as pw:
		browser = pw.chromium.launch()
		page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
		try:
			_login(page, base, user, password)
			site_dictionary, site_language = _site_dictionary(page)
			if site_language and site_language != profile.language:
				frappe.throw(
					_("The crawl user {0} reads the site in {1}, not {2}").format(
						user, site_language, profile.language
					)
				)
			if site_dictionary is not None:
				resolved = site_dictionary
				if log is not None:
					log.append(
						f"Screen: judging by the site's own dictionary, {len(resolved)} translations for {site_language}"
					)
			elif log is not None:
				log.append(
					"Screen: the site's dictionary could not be read from the desk; judging by this bench's"
				)
			for index, (route, app) in enumerate(routes):
				# Nothing here queries the database, and a crawl of a few hundred
				# screens outlasts the idle timeout of many servers. One cheap
				# query keeps the connection the scan will need afterwards.
				if index and not index % PING_EVERY:
					keep_connection()
					if heartbeat:
						heartbeat()
				# A record's name is the customer's data; what the ledger and the
				# log keep is the shape of the screen, not which record it was.
				shown = public_route(route)
				try:
					labels, data = _collect_page(page, base, route)
					visited.append(shown)
				except SessionExpired as exc:
					failed.append(f"{shown}: {exc}")
					break
				except Exception as exc:
					failed.append(f"{shown}: {str(exc)[:80]}")
					continue
				data |= session_data
				ledger.data = data
				for text, kind in labels.items():
					raw = text
					text = strip_timezone(label_part(text, data))
					if text in data:
						continue
					if text in seen:
						apps_seen[text].add(app)
						continue
					if not ledger.is_candidate(text, target_is_latin):
						continue
					seen.add(text)
					apps_seen[text] = {app}
					row = ledger.find(text)
					if row is None:
						# The same exclusion rules as the other routes: a naming
						# series or a lone placeholder found on screen is recorded
						# and marked, not filed as a gap.
						verdict = classify(text, rules, min_length)
						if not verdict.keep:
							continue
						stored = LEADING_COUNT.sub("{0} ", text)
						if stored != raw:
							normalised.append((raw, stored))
						served = resolved.get(resolved_key(stored))
						if served and normalise(served) != normalise(stored):
							# Frappe holds a translation for this string and the
							# screen still shows the source: a rendering defect,
							# reported from the first scan. The ledger row is
							# written a moment later; the scan links it by text.
							rendered_untranslated.append(
								{
									"entry": None,
									"source_text": stored,
									"translated_text": served,
									"route": shown,
									"app": app,
									"kind": kind,
									"shown": raw,
								}
							)
						new_strings.append(
							{
								"na_reason": verdict.na_reason,
								"na_rule": verdict.na_rule,
								"auto_apply": verdict.auto_apply,
								# "4 To Receive" is the format "{0} To Receive" with a
								# count in it; keying the row on the count would create
								# a new row every week. Store the template form.
								"source_text": stored,
								"context": None,
								"app": app,
								"origin": ORIGIN,
								"string_class": "UI Text",
								"source_path": shown[:140],
								"line_no": 0,
								"occurrences": 1,
							}
						)
					else:
						verdict = judge(
							row, resolved.get(resolved_key(row["source_text"], row.get("context")))
						)
						if verdict == NOT_WRAPPED:
							# The site serves this translation and the screen still
							# shows the source: the rendering code never asked for it.
							rendered_untranslated.append(
								{
									"entry": row["name"],
									"source_text": row["source_text"],
									"translated_text": row["translated_text"],
									"route": shown,
									"app": row.get("app") or app,
									"kind": kind,
									"shown": raw,
								}
							)
						elif verdict == CONFIRMED:
							confirmed += 1
						elif verdict == NOT_DELIVERED:
							# Translated in the ledger, and the site does not serve
							# it: the translation has not reached this site. Counted
							# and listed, not filed as a defect of the code.
							not_delivered.append(
								{
									"source_text": row["source_text"],
									"translated_text": row["translated_text"],
									"route": shown,
								}
							)
		finally:
			try:
				page.goto(f"{base}/api/method/logout", timeout=10000)  # leave no session behind
			except Exception:
				pass
			browser.close()

	# A string that appears on the screens of more than one app is the
	# framework's own chrome (navbar, sidebar, search), not the customer's.
	for item in new_strings:
		if (
			len(
				apps_seen.get(
					item["source_text"], apps_seen.get(item["source_text"].replace("{0} ", "", 1), set())
				)
			)
			> 1
		):
			item["app"] = "frappe"
	for item in rendered_untranslated:
		if item.get("entry") is None and len(apps_seen.get(item["source_text"], set())) > 1:
			item["app"] = "frappe"

	# The detail lines belong under the summary line, which the scan writes
	# once this returns; so they travel in the report rather than the log.
	details: list[str] = []
	if not_delivered:
		details.append(
			f"Not delivered to the site ({len(not_delivered)}): translated in the ledger, not served by the site"
		)
		details.extend(f"  {item['source_text'][:70]!r} on {item['route']}" for item in not_delivered[:40])
	if failed:
		# A crawl user who may not read a doctype meets a few hundred of these,
		# so the log says how many of each kind rather than naming five.
		reasons: Counter = Counter(item.split(": ", 1)[-1][:80] for item in failed)
		details.append(
			f"Screen: could not open {len(failed)} of {len(routes)} — "
			+ "; ".join(f"{count} x {reason}" for reason, count in reasons.most_common(4))
		)
		details.append(
			"Screens not opened: " + ", ".join(sorted({item.split(": ", 1)[0] for item in failed})[:40])
		)
	report = {
		"screens": len(visited),
		"failed": len(failed),
		"seconds": round(time.monotonic() - started, 1),
		"new": len(new_strings),
		"rendered_untranslated": len(rendered_untranslated),
		"not_delivered": len(not_delivered),
		"confirmed": confirmed,
		"routes": visited,
		"normalised": normalised,
		"details": details,
	}
	return new_strings, rendered_untranslated, report


class SessionExpired(RuntimeError):
	pass


def _login(page, base: str, user: str, password: str) -> None:
	page.goto(f"{base}/login")
	page.fill("#login_email", user)
	page.fill("#login_password", password)
	page.click(".btn-login")
	page.wait_for_url(re.compile(r"/(app|desk)"), timeout=30000)  # v15 lands on /app, v16 on /desk


def _site_dictionary(page) -> tuple[dict[str, str] | None, str | None]:
	"""The translations the crawled site serves to the crawl user, and the
	language it serves them in, read once from the desk after login.

	Frappe sends every translation of the user's language with the desk's
	boot data (frappe.boot.__messages, both supported versions), so this is
	the crawled site's own dictionary, not this bench's. A site crawled from
	another machine is judged by what it actually holds, and the two need not
	carry the same translation files. Returns (None, None) when the desk
	could not be read, and the caller says so and judges by this bench's."""
	try:
		page.wait_for_function(
			"() => window.frappe && frappe.boot && frappe.boot.__messages", timeout=DRAWN_TIMEOUT
		)
		boot = page.evaluate("() => ({lang: frappe.boot.lang, messages: frappe.boot.__messages})")
	except Exception:
		return None, None
	if not isinstance(boot, dict):
		return None, None
	messages = boot.get("messages")
	language = boot.get("lang")
	if not isinstance(messages, dict) or not isinstance(language, str):
		return None, None  # half a boot is not a boot
	return messages, language


NOT_WRAPPED, CONFIRMED, NOT_DELIVERED = "not wrapped", "confirmed", "not delivered"


def judge(row: dict, served: str | None) -> str | None:
	"""What a ledger row shown in its source language tells us, given what
	the site serves for it (PM's three outcomes, 22 September):

	  the site serves the translation      -> NOT_WRAPPED, a defect of the code
	  the ledger has one, the site does not -> NOT_DELIVERED, not shipped yet
	  the ledger has none                   -> CONFIRMED, the gap is real
	  a Draft, or Not Applicable            -> None, nothing expected on screen
	"""
	if row["status"] == "Not Applicable":
		return None
	translated = row["translated_text"]
	if not translated or normalise(translated) == normalise(row["source_text"]):
		return CONFIRMED
	if row["status"] not in ("Approved", "Reviewed"):
		return None
	if served and normalise(served) == normalise(translated):
		return NOT_WRAPPED
	return NOT_DELIVERED


def _collect_page(page, base: str, route: str) -> tuple[dict[str, str], set[str]]:
	"""Return {text: kind} for the interface text on the screen and the set of
	values shown as data. `kind` names the element the text sits in (button,
	heading, link, option, placeholder, tooltip, text) for the issue detail."""
	page.goto(f"{base}{route}", wait_until="domcontentloaded")
	# A screen whose network never settles is still a screen. The ledger's own
	# list view stopped settling once it held seventeen thousand rows, and
	# waiting for silence meant three of this app's own screens went
	# unmeasured. Wait for quiet, then for the desk to have drawn something,
	# and read whatever is there either way.
	try:
		page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT)
	except Exception:
		pass
	try:
		page.wait_for_selector(DRAWN, timeout=DRAWN_TIMEOUT, state="attached")
	except Exception:
		pass
	time.sleep(1.5)  # form scripts render after the network settles
	if "/login" in page.url:
		raise SessionExpired("the session ended; the remaining screens were not visited")
	# Frappe renders "Not Found" and "Not Permitted" as a message page (v15
	# and v16 alike); its heading says which, whatever the language.
	if page.locator(".message-page").count():
		heading = page.locator(".message-page").first.inner_text().strip().splitlines()
		raise RuntimeError("message page: " + (heading[0][:40] if heading else "?"))
	# A route the signed-in user may not open leaves the desk empty behind a
	# dialog instead. Reading it would collect the dialog and the navigation
	# bar as if they were the screen's own text, and count a screen that was
	# never seen. Whether the user may read a doctype is the customer's
	# decision; saying which screens went unmeasured is this route's job.
	if not page.locator(".page-container, .page-head, .layout-main-section").count():
		raise RuntimeError("not available to the crawl user (no permission, or no such page)")
	# The first version reads the page as it stands: text, placeholders,
	# tooltips and the options of a Select. Nothing is clicked, so menus and
	# dialogs are left for a later version (PM's ruling, 2026-09-19).
	found = page.evaluate(COLLECT_JS)
	labels = {item["text"]: item["kind"] for item in found["labels"]}
	data = set(found["data"])
	# the record name in the URL is data wherever it is printed
	from urllib.parse import unquote

	parts = [unquote(p) for p in route.split("/") if p]
	if len(parts) >= 3 and parts[-1] != "new":
		data.add(parts[-1])
	return labels, data


def summary_line(report: dict) -> str:
	return (
		f"Screen           : {report['new']:>6} new / {report['rendered_untranslated']} not wrapped on screen / "
		f"{report.get('not_delivered', 0)} not delivered / "
		f"{report['confirmed']} confirmed — {report['screens']} screens in {report['seconds']}s"
		+ (f" ({report['failed']} could not be opened)" if report["failed"] else "")
	)


def run(locale: str, cap: int | None = None) -> str:
	"""For `bench execute`: crawl one locale and record the result as a scan.

		bench --site <site> execute lifegence_i18n.scanner.screen.run --kwargs '{"locale": "ja-JP"}'

	This is the entry point for a machine that has Playwright and reaches the
	target site over HTTP — a developer's laptop, a verification server — when
	the site itself (Frappe Cloud) cannot run a browser. The other routes are
	left off so the scan measures the screens alone.
	"""
	if not is_available():
		frappe.throw(_("Playwright is not installed in this environment"))
	if cap is not None:
		frappe.flags.screen_cap = int(cap)  # read by collect(); the setting is left alone
	scan = frappe.get_doc({"doctype": "Translation Scan", "locale": locale}).insert(ignore_permissions=True)
	# before_insert copies the profile's routes; this run is the screens alone
	scan.scan_source = scan.scan_database = scan.scan_messages = 0
	scan.scan_screens = 1
	scan.db_update()
	# `bench execute`: the crawl below runs for a quarter of an hour, and the
	# scan record has to exist before it starts.
	frappe.db.commit()  # nosemgrep
	scan.run()
	print(scan.log)
	return scan.name


def dump_routes(locale: str, cap: int = 300) -> str:
	"""For `bench execute`: the screens a scan of this locale would visit."""
	from lifegence_i18n.localization.doctype.translation_scan.translation_scan import target_apps

	profile = frappe.get_doc("Locale Profile", locale)
	return json.dumps(discover_routes(target_apps(profile), cap), ensure_ascii=False, indent=1)
