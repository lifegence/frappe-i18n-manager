#!/usr/bin/env python3
"""Refuse to publish anything that names a customer.

Written after a near miss. A `git grep` for the customer's name reported the
repository clean while five `.docx` files still carried it — one of them a talk
script quoting the price of an exclusivity clause — because grep reads text and
a `.docx` is a zip. So this reads every tracked file as bytes, and looks inside
the zip-shaped ones.

The exceptions are named, not inferred: a customer who holds copyright belongs
in LICENSE and README, and nowhere else.

    python3 scripts/check_no_customer_data.py
"""

import io
import re
import subprocess
import sys
import zipfile

# Names that may not appear outside the files listed against them. Add a
# customer here when an engagement starts, not when it ends.
FORBIDDEN = {
	# A customer who holds copyright is named in the notice and the readme.
	"lush": {"NOTICE", "README.md"},
	"lusherp": set(),
	"lush-jp-test": set(),
	"fc.lifegence.com": set(),
	"translation_review": set(),
}

# This file has to spell the names out to look for them, so it is the one place
# they are allowed to appear in full.
SELF = "scripts/check_no_customer_data.py"

ZIP_SUFFIXES = (".docx", ".xlsx", ".pptx", ".zip", ".odt", ".ods")
TEXT_IN_ZIP = (".xml", ".rels", ".txt", ".json", ".md")


def tracked_files() -> list[str]:
	out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
	return [p.decode() for p in out.split(b"\0") if p]


def haystacks(path: str, data: bytes):
	"""The bytes to search: the file itself, plus the text inside a zip."""
	yield data
	# UTF-16 hides a name from a byte search of UTF-8; fold it down.
	yield data.replace(b"\x00", b"")
	if path.lower().endswith(ZIP_SUFFIXES):
		try:
			with zipfile.ZipFile(io.BytesIO(data)) as archive:
				for item in archive.namelist():
					if item.lower().endswith(TEXT_IN_ZIP):
						yield archive.read(item)
		except zipfile.BadZipFile:
			pass


def main() -> int:
	findings: list[str] = []
	for path in tracked_files():
		if path == SELF:
			continue
		try:
			# Paths come from `git ls-files` in this repository. The script runs
			# in CI, never in a request.
			with open(path, "rb") as handle:  # nosemgrep
				data = handle.read()
		except OSError as exc:
			print(f"could not read {path}: {exc}", file=sys.stderr)
			return 2
		for name, allowed in FORBIDDEN.items():
			if path in allowed:
				continue
			pattern = re.compile(re.escape(name).encode(), re.IGNORECASE)
			for blob in haystacks(path, data):
				if pattern.search(blob):
					findings.append(f"{path}: contains {name!r}")
					break

	if findings:
		print("Customer identifiers found in files that may not carry them:\n")
		for line in sorted(set(findings)):
			print(f"  {line}")
		print(
			"\nGeneralise the wording, or remove the file. A document that exists to "
			"name a customer does not belong in a public repository."
		)
		return 1

	print(f"No customer identifiers in {len(tracked_files())} tracked files.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
