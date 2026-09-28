app_name = "lifegence_i18n"
app_title = "I18n Manager"
app_publisher = "Lifegence Corporation"
app_description = "Multilingual management for Frappe/ERPNext"
app_email = "info@lifegence.co.jp"
app_license = "agpl-3.0"

after_install = "lifegence_i18n.setup.install.after_install"

add_to_apps_screen = [
	{
		"name": "lifegence_i18n",
		"logo": "/assets/lifegence_i18n/images/i18n-logo.svg",
		"title": "Localization",
		"route": "/app/localization",
	}
]

scheduler_events = {
	"weekly": [
		"lifegence_i18n.localization.doctype.translation_scan.translation_scan.run_scheduled_scans",
	],
}
