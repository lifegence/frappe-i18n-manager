"""Route 3 — user-facing messages that no translation file can reach.

A translation only applies to a string that passes through `_()` / `__()`.
Anything handed to `frappe.throw` or `msgprint` as a bare literal is emitted
verbatim, so these need a source change before any language ever shows them.
Adding them to the ledger as untranslated would be misleading — they are not
missing a translation, they are missing a call.

Python is parsed with `ast` so the first argument of each call is classified
accurately. JavaScript has no parser here and is matched with a regex.
"""

import ast
import os
import re

import frappe

USER_FACING = {"throw", "msgprint", "show_alert"}
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "public/dist"}

# The opening quote is captured so it can be back-referenced by name; `\1` would
# point at the call name. DOTALL lets the argument sit on the line after the "(".
JS_CALL = re.compile(
	r"frappe\.(throw|msgprint|show_alert)\s*\(\s*(?P<q>[\"'`])(?P<text>(?:\\.|(?!(?P=q)).)*)(?P=q)",
	re.DOTALL,
)


def collect(apps: list[str]) -> list[dict]:
	findings: list[dict] = []
	for app in apps:
		try:
			root = frappe.get_app_path(app)
		except Exception:
			continue
		for dirpath, dirnames, filenames in os.walk(root):
			dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
			for filename in filenames:
				full = os.path.join(dirpath, filename)
				relative = os.path.relpath(full, os.path.dirname(root))
				if filename.endswith(".py"):
					_scan_python(full, relative, app, findings)
				elif filename.endswith(".js"):
					_scan_javascript(full, relative, app, findings)
	return findings


def _call_name(node: ast.Call) -> str | None:
	func = node.func
	if isinstance(func, ast.Attribute):
		return func.attr
	if isinstance(func, ast.Name):
		return func.id
	return None


def _is_translated(node: ast.AST) -> bool:
	"""True when the expression already goes through _() — possibly .format()ed."""
	if isinstance(node, ast.Call):
		name = _call_name(node)
		if name == "_":
			return True
		if name == "format" and isinstance(node.func, ast.Attribute):
			return _is_translated(node.func.value)
	if isinstance(node, ast.BinOp):
		return _is_translated(node.left) or _is_translated(node.right)
	return False


def _classify(node: ast.AST) -> tuple[str, str] | None:
	"""Return (kind, text) for an untranslated user-facing argument."""
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return ("plain", node.value) if node.value.strip() else None
	if isinstance(node, ast.JoinedStr):
		parts = []
		for value in node.values:
			if isinstance(value, ast.Constant) and isinstance(value.value, str):
				parts.append(value.value)
			else:
				parts.append("{…}")
		text = "".join(parts)
		# An f-string cannot be wrapped usefully: the key varies at runtime, so
		# it needs rewriting as _("… {0}").format(…) rather than a translation.
		return ("fstring", text) if text.strip(" {…}") else None
	if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
		for side in (node.left, node.right):
			found = _classify(side)
			if found:
				return ("concat", found[1])
	if isinstance(node, ast.Call) and _call_name(node) == "format":
		if isinstance(node.func, ast.Attribute):
			found = _classify(node.func.value)
			if found:
				return ("format", found[1])
	return None


def _scan_python(path: str, relative: str, app: str, findings: list[dict]) -> None:
	try:
		# `path` is produced by walking an installed app's own directory; it is
		# never taken from a request.
		with open(path, encoding="utf-8") as handle:  # nosemgrep
			tree = ast.parse(handle.read())
	except (SyntaxError, UnicodeDecodeError, OSError):
		return

	for node in ast.walk(tree):
		if not isinstance(node, ast.Call) or _call_name(node) not in USER_FACING:
			continue
		targets = [a for a in node.args[:1] if not isinstance(a, ast.Starred)]
		for keyword in node.keywords:
			if keyword.arg in ("title", "msg"):
				targets.append(keyword.value)
		for target in targets:
			if _is_translated(target):
				continue
			found = _classify(target)
			if found:
				findings.append(
					{
						"app": app,
						"source_text": found[1][:500],
						"source_path": relative[:140],
						"line_no": getattr(target, "lineno", 0),
						"kind": f"py/{found[0]}",
						"call": _call_name(node),
					}
				)


def _scan_javascript(path: str, relative: str, app: str, findings: list[dict]) -> None:
	try:
		# As above: walked from the app directory, not supplied by a caller.
		with open(path, encoding="utf-8") as handle:  # nosemgrep
			text = handle.read()
	except (UnicodeDecodeError, OSError):
		return

	for match in JS_CALL.finditer(text):
		body = match.group("text")
		if not body.strip():
			continue
		line_start = text.rfind("\n", 0, match.start()) + 1
		if "//" in text[line_start : match.start()]:
			continue
		# In a template literal only the parts outside ${...} are hard-coded; if
		# those carry no words, every visible token already came from __().
		literal = re.sub(r"\$\{[^}]*\}", "", body) if "${" in body else body
		if not re.search(r"[A-Za-z]", re.sub(r"<[^>]+>", "", literal)):
			continue
		findings.append(
			{
				"app": app,
				"source_text": body[:500],
				"source_path": relative[:140],
				"line_no": text.count("\n", 0, match.start()) + 1,
				"kind": "js/template" if "${" in body else "js/plain",
				"call": f"frappe.{match.group(1)}",
			}
		)
