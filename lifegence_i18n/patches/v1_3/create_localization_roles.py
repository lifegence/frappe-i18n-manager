"""Create the three localization roles on a site installed before they existed.

Until this version the only role that could reach the application was System
Manager, which administers the whole site. The permission definitions now name
three roles of their own; a site upgraded from an earlier version has the
definitions but not the roles, so they are made here.

No role is granted to anybody. Who gets which one is the operator's decision.
"""

import frappe

from lifegence_i18n.permissions import create_roles


def execute():
	created = create_roles()
	if created:
		frappe.logger().info(f"lifegence_i18n: created roles {', '.join(created)}")
