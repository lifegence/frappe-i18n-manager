# Copyright (c) 2026, Lifegence and Contributors
# See license.txt

# import frappe
from lifegence_i18n.tests import FrappeTestCase

# On the Frappe test case, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestI18nSettings(FrappeTestCase):
	"""
	Integration tests for I18nSettings.
	Use this class for testing interactions between multiple components.
	"""

	pass
