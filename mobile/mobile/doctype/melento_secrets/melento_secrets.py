# Copyright (c) 2026, Qunatbit and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document



class MelentoSecrets(Document):
	def get_melento_secrets():
		doc = frappe.get_single("Melento Secrets")
		return {
        "stamping": {
            "api_key": doc.get_password("stamping_api_key"),
            "application_id": doc.get_password("stamping_application_id"),
        },
        "signing": {
            "api_key": doc.get_password("signing_api_key"),
            "application_id": doc.get_password("signing_application_id"),
        }
    }
