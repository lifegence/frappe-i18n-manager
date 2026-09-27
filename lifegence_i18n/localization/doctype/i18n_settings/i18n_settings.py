import ipaddress
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document


class I18nSettings(Document):
	def validate(self):
		self._validate_crawl_url()

	def _validate_crawl_url(self):
		"""A browser on this server will send the stored password to this URL.
		Only the site itself, or an HTTPS site the operator has allowed in
		site_config (`i18n_allow_remote_crawl`), may receive it."""
		url = (self.screen_site_url or "").strip()
		if not url:
			return
		parts = urlparse(url)
		host = (parts.hostname or "").lower()
		if parts.scheme not in ("http", "https") or not host:
			frappe.throw(_("Site URL to Crawl must be an http(s) URL"))
		local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
		if parts.scheme == "http" and not local:
			frappe.throw(_("Site URL to Crawl must use https unless it is localhost"))
		try:
			address = ipaddress.ip_address(host)
		except ValueError:
			address = None
		if (
			address
			and not address.is_loopback
			and (address.is_private or address.is_link_local or address.is_reserved)
		):
			frappe.throw(_("Site URL to Crawl may not point at a private or link-local address"))
		configured = frappe.conf.host_name or ""
		own_hosts = {
			frappe.local.site.lower(),
			(urlparse(configured if "//" in configured else "//" + configured).hostname or "").lower(),
		}
		if host not in own_hosts and not local and not frappe.conf.get("i18n_allow_remote_crawl"):
			frappe.throw(
				_(
					"Crawling another site is off. Set i18n_allow_remote_crawl in site_config.json to allow {0}"
				).format(host)
			)
