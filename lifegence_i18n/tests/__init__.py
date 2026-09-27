"""Test support shared by the app's test modules.

Frappe renamed its test base between the two versions this app supports:
version-15 ships `frappe.tests.utils.FrappeTestCase`, version-16 ships
`frappe.tests.IntegrationTestCase`. Every test module imports the base from
here so the suite runs unchanged on both.
"""

try:
	from frappe.tests import IntegrationTestCase as FrappeTestCase  # version-16
except ImportError:  # version-15
	from frappe.tests.utils import FrappeTestCase

__all__ = ["FrappeTestCase"]
