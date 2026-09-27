"""Put the demo site back to the state DEMO_EN.md assumes.

Run before a demo, from the bench directory. This file sits outside the Python package,
so it is loaded into the console rather than imported:

    cd ~/work/frappe-bench
    bench --site dev.localhost console <<'EOF'
    exec(open("apps/lifegence_i18n/docs/demo_reset.py").read()); run()
    EOF

Three things are undone, all of which the demo itself puts back:

1. The Hong Kong "Apply to Site" — deleted, so the before/after on screen is visible again.
2. The Japanese bulk term change — the ledger goes back to 在庫伝票 while the glossary
   stays 在庫エントリ, so Check Impact has something to find.
3. The Korean locale — removed, so it can be created live.

After running this, rescan ja-JP once so the Glossary Violation count reflects step 2.
"""

import frappe


def run():
	# 1) Undo the Hong Kong "Apply to Site"
	n = frappe.db.count("Translation", {"language": "zh-HK"})
	frappe.db.delete("Translation", {"language": "zh-HK"})
	print(f"deleted {n} Translation records for zh-HK")

	# 2) Put the Japanese ledger back before the bulk term change.
	#    The glossary keeps 在庫エントリ, so the ledger now violates it — which is the point.
	frappe.db.sql(
		"""update `tabTranslation Entry`
		set translated_text = replace(translated_text, '在庫エントリ', '在庫伝票')
		where locale = 'ja-JP' and translated_text like '%在庫エントリ%'"""
	)
	reverted = frappe.db.sql(
		"""select count(*) from `tabTranslation Entry`
		where locale = 'ja-JP' and translated_text like '%在庫伝票%'"""
	)[0][0]
	print(f"reverted {reverted} ledger rows to 在庫伝票")

	# 3) Remove the Korean locale so section 7 can create it live
	if frappe.db.exists("Locale Profile", "ko-KR"):
		scans = frappe.get_all("Translation Scan", filters={"locale": "ko-KR"}, pluck="name")
		if scans:
			frappe.db.sql("delete from `tabTranslation Scan Result` where parent in %(s)s", {"s": scans})
		frappe.db.set_value("Locale Profile", "ko-KR", "last_scan", None, update_modified=False)
		for doctype in ("Translation Issue", "Translation Entry", "Glossary Term"):
			count = frappe.db.count(doctype, {"locale": "ko-KR"})
			frappe.db.delete(doctype, {"locale": "ko-KR"})
			print(f"deleted {count} {doctype} rows for ko-KR")
		frappe.db.delete("Translation Scan", {"locale": "ko-KR"})
		frappe.db.delete("Locale Target App", {"parent": "ko-KR"})
		frappe.db.delete("Locale Profile", {"name": "ko-KR"})
		print("removed Locale Profile ko-KR")

	# A script run from `bench execute`: nothing else will commit for it.
	frappe.db.commit()  # nosemgrep
	print("\nNow rescan ja-JP: /app/locale-profile/ja-JP → Run Scan (about 25 seconds)")
