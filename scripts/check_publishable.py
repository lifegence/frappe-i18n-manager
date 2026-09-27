#!/usr/bin/env python3
"""Refuse to publish a file that was written for someone else.

Two different mistakes, found the same week, and neither would have caught the
other.

The first was a name. A `git grep` for the customer's name reported the
repository clean while five `.docx` files still carried it — one of them a talk
script quoting the price of an exclusivity clause — because grep reads text and
a `.docx` is a zip. So this reads every tracked file as bytes, and looks inside
the zip-shaped ones.

The second was an address. Two documents that named nobody were published with
`社外秘（CONFIDENTIAL）` at the top, and one of them also carried its author, its
addressee and the work-package number it answered. Nothing about a customer,
and still not ours to publish: a document marked confidential and addressed to
a person is correspondence, and a public repository is not where correspondence
goes. A reviewer found those, not this script, which is why they are in it now.

    python3 scripts/check_publishable.py
"""

import io
import re
import subprocess
import sys
import zipfile

# Names that may not appear outside the files listed against them. Add a
# customer here when an engagement starts, not when it ends.
NAMES = {
	# A customer who holds copyright is named in the notice and the readme.
	"lush": {"NOTICE", "README.md"},
	"lusherp": set(),
	"lush-jp-test": set(),
	"fc.lifegence.com": set(),
	"translation_review": set(),
}

# Words that say a document was written for a contract rather than for a
# reader. A file carrying one of these is either addressed to someone, marked
# as not for publication, or numbered against a plan nobody outside can see.
MARKINGS = (
	"社外秘",
	"CONFIDENTIAL",
	"Confidential",
	"部外秘",
	"取扱注意",
	"INTERNAL USE ONLY",
	"Internal use only",
	# `宛先` is left out on purpose: it is ordinary Japanese for the place
	# something is sent, and the user manual uses it that way about a password
	# the browser posts. A document's addressee is caught by the markings
	# around it, not by the word alone.
	"納品先",
	"発注書",
	"注文請書",
	"検収",
	"見積書",
	"受託者",
	# A work-package number answers to a project plan, not to a reader.
	r"\bWP-\d+\b",
)

# This file has to spell the words out to look for them, so it is the one place
# they are allowed to appear in full.
SELF = "scripts/check_publishable.py"

ZIP_SUFFIXES = (".docx", ".xlsx", ".pptx", ".zip", ".odt", ".ods")
TEXT_IN_ZIP = (".xml", ".rels", ".txt", ".json", ".md")


def tracked_files() -> list[str]:
	out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
	return [p.decode() for p in out.split(b"\0") if p]


def haystacks(path: str, data: bytes):
	"""The bytes to search: the file itself, plus the text inside a zip."""
	yield data
	# UTF-16 hides a word from a byte search of UTF-8; fold it down.
	yield data.replace(b"\x00", b"")
	if path.lower().endswith(ZIP_SUFFIXES):
		try:
			with zipfile.ZipFile(io.BytesIO(data)) as archive:
				for item in archive.namelist():
					if item.lower().endswith(TEXT_IN_ZIP):
						yield archive.read(item)
		except zipfile.BadZipFile:
			pass


def search(blobs, pattern: re.Pattern) -> bool:
	return any(pattern.search(blob) for blob in blobs)


def main() -> int:
	named: list[str] = []
	addressed: list[str] = []

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
		blobs = list(haystacks(path, data))

		for name, allowed in NAMES.items():
			if path in allowed:
				continue
			if search(blobs, re.compile(re.escape(name).encode(), re.IGNORECASE)):
				named.append(f"{path}: contains {name!r}")

		for marking in MARKINGS:
			expression = marking if marking.startswith(r"\b") else re.escape(marking)
			if search(blobs, re.compile(expression.encode())):
				addressed.append(f"{path}: carries {marking!r}")

	if named:
		print("Customer identifiers in files that may not carry them:\n")
		for line in sorted(set(named)):
			print(f"  {line}")
		print(
			"\nGeneralise the wording, or remove the file. A document that exists to "
			"name a customer does not belong in a public repository.\n"
		)

	if addressed:
		print("Files written for a contract rather than for a reader:\n")
		for line in sorted(set(addressed)):
			print(f"  {line}")
		print(
			"\nRewrite the document so it addresses whoever finds it, or move it to "
			"the private repository. A confidentiality marking on a file anyone can "
			"read is a contradiction, not a warning.\n"
		)

	if named or addressed:
		return 1

	print(f"Nothing addressed elsewhere in {len(tracked_files())} tracked files.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
