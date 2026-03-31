import frappe
import requests
import json
import base64
from frappe.model.document import Document
import uuid

# GLOBAL CONFIGURATION
STAMP_CONFIG = {
    "URL": "https://in-stamp.staging-signdesk.com/api/v2/estamp/requestStampPaper",
    "HEADERS": {
        "x-parse-rest-api-key": "fed53dbaecc002e7914e74a20b8ce22f",
        "x-parse-application-id": "bastardairyfarmprivatelimited_user_2",
        "Content-Type": "application/json"
    }
}

ESIGN_CONFIG = {
    "URL": "https://uat.signdesk.in/api/sandbox/signRequest",
    "HEADERS": {
        "x-parse-rest-api-key": "68a6d6925379c7f349d1661302fe55ad",
        "x-parse-application-id": "bastardairyfarmprivatelimited_user_1",
        "Content-Type": "application/json"
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
        response = requests.post(
            STAMP_CONFIG["URL"], json=payload, headers=STAMP_CONFIG["HEADERS"])
        res_data = response.json()
        res_json = json.dumps(res_data, indent=2)

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
            "response": res_json
        }

    @frappe.whitelist()
    def call_esign_api(self):
        signers_list = []
        for d in self.signer_info_table:
        # 1. Base Signer Information
            signer_data = {
            "document_to_be_signed": d.document_to_be_signed or "DOC1",
            "signer_ref_id": d.signer_ref_id,
            "signer_name": d.signer_name,
            "signer_email": d.signer_email,
            "signer_mobile": str(d.signer_mobile_number),
            "sequence": int(d.sequence or 1),
            "signature_type": d.signature_type or "aadhaar",
            "esign_type": d.esign_type or "otp",
            "trigger_esign_request": d.trigger_esign_request or "true"
        }

        # Capture the dynamic input from the 'page_number' Data field
        # We convert to string to ensure the JSON handles it correctly
            user_page = str(d.page_number) if d.page_number else "1"

        # 2. Conditional Logic for Positions & Dynamic Pages
            if d.type_of_signer == "First Party":
                signer_data["page_number"] = "all"
                signer_data["signer_position"] = {
                "appearance": [
                    {
                        "x1": 40, "y1": 11.65, "x2": 161, "y2": 71.65
                    }
                ]
            }

            elif d.type_of_signer == "Second Party":
                signer_data["page_number"] = "all"
                signer_data["signer_position"] = {
                "appearance": [
                    {
                        "x1": 302,"y1": 11.65,"x2": 423,"y2": 71.65
                    }
                ]
            }

            elif d.type_of_signer == "Witness 1":
                signer_data["page_number"] = "all"
                signer_data["signer_position"] = {
                "page": [user_page],  # Dynamic page from user input
                "appearance": [
                    {
                        "id": "_a7e1z830r",
                        "x1": 82, "y1": 164, "x2": 192, "y2": 204,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": user_page  # Matches the outer page array
                    }
                ]
            }

            elif d.type_of_signer == "Witness 2":
                signer_data["page_number"] = "all"
                signer_data["signer_position"] = {
                "page": [user_page],  # Dynamic page from user input
                "appearance": [
                    {
                        "id": "_ril0b38h6",
                        "x1": 85, "y1": 235, "x2": 195, "y2": 275,
                        "page_height": 842.04, "page_width": 595.32,
                        "page": user_page  # Matches the outer page array
                    }
                ]
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
            response = requests.post(
            ESIGN_CONFIG["URL"], 
            json=payload, 
            headers=ESIGN_CONFIG["HEADERS"]
        )
            res_data = response.json()
            res_json = json.dumps(res_data, indent=2)

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
