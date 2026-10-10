import secrets

import frappe
import requests
import json
import base64
from frappe.model.document import Document
import uuid

def get_melento_secrets():
    doc = frappe.get_single("Melento Secrets")
    return {
        "stamping": {
            "api_key": doc.get_password("stamping_api_key"),
            "application_id": doc.get_password("stamping_application_id"),
            "url": "https://in-stamp.signdesk.com/api/v2/estamp/requestStampPaper"
        },
        "esign": {
            "api_key": doc.get_password("signing_api_key"),
            "application_id": doc.get_password("signing_application_id"),
            "url": "https://api.signdesk.in/api/live/signRequest"
        }
    }

class Estampingandsigning(Document):
    @frappe.whitelist()
    def convert_pdf_to_base64(self):
        if not self.content:
            frappe.throw("Please upload a PDF file first.")
        file_doc = frappe.get_doc("File", {"file_url": self.content})
        self.request_content = base64.b64encode(
            file_doc.get_content()).decode("utf-8")
        self.save()
        return True

    @frappe.whitelist()
    def call_stamping_api(self):
        category_map = {
        "Branch Agreement": "1",
        "Shop Agreement": "186"
    }

    # 2. Get the specific code, defaulting to the original value if not in the map
    # (Using .get ensures the code doesn't crash if the field is empty)
        api_category_code = category_map.get(self.document_category, self.document_category)
        payload = {
            "reference_id": self.reference_id,
            "content": self.request_content,
            "force_sync": "true",
            "stamp_state": self.stamp_state,
            "stamp_amount": [str(self.stamp_amount)],
            "document_category": [str(api_category_code)],
            "stamp_duty_paid_by": self.stamp_duty_paid_by,
            "first_party_name": self.first_party_name,
            "first_party_address": {
                "street_address": self.street_address, "city": self.city,
                "state": self.state, "pincode": self.pincode, "country": self.country
            },
            "first_party_details": {
                "first_party_entity_type": self.first_party_entity_type,
                "first_party_id_type": self.first_party_id_type,
                "first_party_id_number": self.first_party_id_number
            },
            "second_party_name": self.second_party_name,
            "custom": {
                "agreement_date": self.agreement_date,
                "outlet_name": self.outlet_name,
                "outlet_place": self.outlet_place,
                "party_name": self.second_party_name,
                "party_aadhaar_number": self.second_party_aadhaar_number,
                "party_pan_number": self.second_party_pan_number,
                "party_gst_number": self.second_party_gst_number,
                "party_deposit_amount": self.second_party_deposit_amount,
                "party_bank_account": self.secound_party_bank_account_number,
                "transaction_number": self.transaction_number,
                "prepaid_balance_amount": self.prepaid_balance_amount
            }
        }

        req_json = json.dumps(payload, indent=2)
        secrets = get_melento_secrets()

        headers = {
            "x-parse-rest-api-key": secrets["stamping"]["api_key"],
            "x-parse-application-id": secrets["stamping"]["application_id"],
            "Content-Type": "application/json"
        }

        response = requests.post(
            secrets["stamping"]["url"],
            json=payload,
            headers=headers
        )
        res_data = response.json()
        res_json = json.dumps(res_data, indent=2)
        api_status = str(res_data.get("status") or "Failed").title()
        api_message = res_data.get("message") or "No message returned"
    
        self.db_set("status", api_status)
        self.db_set("message", api_message)

        self.request_body_stamping = req_json
        self.response_body_stamping = res_json
        self.full_response = f"--- STAMPING REQUEST ---\n{req_json}\n\n--- STAMPING RESPONSE ---\n{res_json}"

        # FIX: Normalize status so JS can read it properly
        api_status = str(res_data.get("status") or "").lower()

        if api_status == "success":
            self.only_content = res_data.get("content")

        
        self.save()
        return {
            "status": api_status,
            "error": res_data.get("message") or res_data.get("error"),
            "request": req_json,
            "response": res_json,
            "status": self.status,
            "message": self.message
        }

    @frappe.whitelist()
    def call_esign_api(self):
        total_pages = self.total_pages or 1
        all_pages = [str(p) for p in range(1, total_pages + 1)]

        signers_list = []
        for d in self.signer_info_table:
            signer_data = {
                "document_to_be_signed": d.document_to_be_signed or "DOC1",
                "signer_ref_id": d.signer_ref_id,
                "signer_name": d.signer_name,
                "signer_email": d.signer_email,
                "signer_mobile": str(d.signer_mobile_number),
                "sequence": int(d.sequence or 1),
                "signature_type": d.signature_type or "aadhaar",
                "esign_type": d.esign_type or "otp",
                "trigger_esign_request": d.trigger_esign_request or "true",
                "page_number": "all"
            }

            user_page = str(d.page_number) if d.page_number else "1"

            if d.type_of_signer == "First Party":
                appearance = []
                for page in range(1, min(3, total_pages + 1)):
                    appearance.append({
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 93, "y1": 560, "x2": 203, "y2": 600,
                        "page_height": 848.16, "page_width": 605.28,
                        "page": str(page)
                    })
                for page in range(3, total_pages + 1):
                    appearance.append({
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 72, "y1": 785, "x2": 182, "y2": 825,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": str(page)
                    })
                signer_data["signer_position"] = {
                    "page": all_pages,
                    "appearance": appearance
                }

            elif d.type_of_signer == "Second Party":
                appearance = []
                for page in range(1, min(3, total_pages + 1)):
                    appearance.append({
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 358, "y1": 557, "x2": 468, "y2": 597,
                        "page_height": 848.16, "page_width": 605.28,
                        "page": str(page)
                    })
                for page in range(3, total_pages + 1):
                    appearance.append({
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 336, "y1": 784, "x2": 446, "y2": 824,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": str(page)
                    })
                signer_data["signer_position"] = {
                    "page": all_pages,
                    "appearance": appearance
                }

            elif d.type_of_signer == "Witness 1":
                signer_data["signer_position"] = {
                    "page": [user_page],
                    "appearance": [{
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 82, "y1": 164, "x2": 192, "y2": 204,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": user_page
                    }]
                }

            elif d.type_of_signer == "Witness 2":
                signer_data["signer_position"] = {
                    "page": [user_page],
                    "appearance": [{
                        "id": f"_{uuid.uuid4().hex[:8]}",
                        "x1": 69, "y1": 583, "x2": 179, "y2": 623,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": user_page
                    }]
                }

            signers_list.append(signer_data)
        content_data = self.request_content if self.choose_actio == "signing" else self.only_content
        payload = {
        "docket_title": self.document_title,
        "reference_id": self.reference_id_sign,
        "documents": [{
            "reference_doc_id": self.reference_doc_id or "DOC1",
            "content_type": "pdf",
            "content": content_data,
            "signature_sequence": self.signature_sequence or "parallel"
        }],
        "signers_info": signers_list
    }

        req_json = json.dumps(payload, indent=2)
        try:
            secrets = get_melento_secrets()

            headers = {
                "x-parse-rest-api-key": secrets["esign"]["api_key"],
                "x-parse-application-id": secrets["esign"]["application_id"],
                "Content-Type": "application/json"
                }

            response = requests.post(
            secrets["esign"]["url"],
            json=payload,
            headers=headers
)
            res_data = response.json()
            res_json = json.dumps(res_data, indent=2)
            api_status = str(res_data.get("status") or "Failed").title()
        
            # Get error message (API uses 'error' for failures, otherwise NA)
            api_message = res_data.get("error") or "NA"
        
        # Get error code
            api_err_code = res_data.get("error_code") or "NA"

        # Direct database updates
            self.db_set("signing_status", api_status)
            self.db_set("signing_api_message", api_message)
            self.db_set("error_code_melento", api_err_code)

        # Log request and response to Frappe fields
            self.request_body = req_json
            self.response_body = res_json
            self.full_response = (self.full_response or "") + \
            f"\n\n--- ESIGN REQUEST ---\n{req_json}\n\n--- ESIGN RESPONSE ---\n{res_json}"

            self.save()

            return {
                "status": "success",
                "response": res_data
        }
        except Exception as e:
            frappe.throw(f"API Error: {str(e)}")
        

    def autoname(self):
        name = f"{self.second_party_name}-{self.category_of_agreement}-{self.date}"

        # Clean spaces
        name = name.replace(" ", "-")

        # Handle duplicate
        if frappe.db.exists(self.doctype, name):
            name = f"{name}-{frappe.generate_hash(length=4)}"

        self.name = name

    def before_insert(self):
        # Generate a unique short ID (e.g., 'ESS-5f3a2b') or a full UUID
        # Using uuid4().hex[:10] gives a 10-character unique string
        unique_ref = f"REF-{uuid.uuid4().hex[:8].upper()}"
        
        self.reference_id = unique_ref
        self.reference_id_sign = unique_ref

    def validate(self):
        if frappe.session.user != "sanskar@bastardairyfarm.com":
            self.request_body_stamping = None