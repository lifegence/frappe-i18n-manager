#!/usr/bin/env python3
"""Refuse a release that Frappe Cloud would refuse.

Written after shipping an app whose `pyproject.toml` had no
`[tool.bench.frappe-dependencies]`. A local bench installs such an app without
complaint; Frappe Cloud does not, so the first person to find out was the
customer installing it on their staging site — and it was the second time, on a
second app, with the answer already sitting in a sibling repository.

Everything here is a declaration that only a real deployment checks. Each one
has to be verified by something that runs on every push, because none of them
is exercised by the tests.

    python3 scripts/check_packaging.py
"""

import pathlib
import re

import tomllib


def main() -> int:
	root = pathlib.Path(__file__).resolve().parent.parent
	data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
	hooks = (root / "lifegence_i18n" / "hooks.py").read_text(encoding="utf-8")
	failures: list[str] = []

	# Frappe Cloud reads this to decide which framework versions the app may be
	# installed on. Without it an install on Frappe Cloud is refused.
	bench = data.get("tool", {}).get("bench", {})
	frappe_deps = bench.get("frappe-dependencies")
	if not frappe_deps:
		failures.append(
			"pyproject.toml has no [tool.bench.frappe-dependencies]. Frappe Cloud "
			"refuses an app that does not say which framework versions it runs on."
		)
	elif "frappe" not in frappe_deps:
		failures.append("[tool.bench.frappe-dependencies] does not name `frappe`.")

	project = data.get("project", {})
	for field, why in [
		("name", "bench installs the app by this name"),
		("description", "the Marketplace listing shows it"),
		("license", "a public repository without one is not publishable"),
		("requires-python", "a bench on an older Python has to be told"),
	]:
		if not project.get(field):
			failures.append(f"pyproject.toml [project] has no `{field}` — {why}.")

	for key, why in [
		("app_title", "shown in the app switcher and the Marketplace listing"),
		("app_publisher", "shown in the Marketplace listing"),
		("app_description", "shown in the Marketplace listing"),
		("app_license", "should agree with pyproject and LICENSE"),
		("app_email", "the Marketplace asks for a contact"),
	]:
		if not re.search(rf"^{key}\s*=\s*[\"'][^\"']+[\"']", hooks, re.M):
			failures.append(f"hooks.py has no `{key}` — {why}.")

	for name in ("LICENSE", "NOTICE", "README.md", "CHANGELOG.md", "CONTRIBUTING.md"):
		if not (root / name).exists():
			failures.append(f"{name} is missing.")

	if failures:
		print("This release would be refused, or would list badly:\n")
		for line in failures:
			print(f"  {line}")
		print(
			"\nEach of these is read by a deployment rather than by a test, which is "
			"why nothing else here would catch it."
		)
		return 1

	print("Packaging declarations are complete.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
