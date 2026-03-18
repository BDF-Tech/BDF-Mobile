import frappe
import requests
import json
import base64
from frappe.model.document import Document

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
        payload = {
            "reference_id": self.reference_id,
            "content": self.request_content,
            "force_sync": "true",
            "stamp_state": self.stamp_state,
            "stamp_amount": [str(self.stamp_amount)],
            "document_category": [str(self.document_category)],
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
            signers_list.append({
                "document_to_be_signed": d.document_to_be_signed,
                "signer_ref_id": d.signer_ref_id,
                "signer_name": d.signer_name,
                "signer_email": d.signer_email,
                "signer_mobile": str(d.signer_mobile_number),
                "sequence": int(d.sequence),
                "page_number": d.page_number or "all",
                "signer_position": {"appearance": d.appearance or "bottom-right"},
                "signature_type": d.signature_type or "aadhaar",
                "esign_type": d.esign_type or "otp",
                "trigger_esign_request": d.trigger_esign_request or "true"
            })

        payload = {
            "docket_title": self.document_title or "E-Stamping and Signing",
            "reference_id": self.reference_id_sign,
            "documents": [{
                "reference_doc_id": self.reference_doc_id,
                "content_type": self.content_type or "pdf",
                "content": self.only_content,
                "signature_sequence": self.signature_sequence or "parallel"
            }],
            "signers_info": signers_list
        }

        req_json = json.dumps(payload, indent=2)

        try:
            response = requests.post(
                ESIGN_CONFIG["URL"], json=payload, headers=ESIGN_CONFIG["HEADERS"])
            res_data = response.json()
            res_json = json.dumps(res_data, indent=2)

            self.request_body = req_json
            self.response_body = res_json
            self.full_response = (self.full_response or "") + \
                f"\n\n--- ESIGN REQUEST ---\n{req_json}\n\n--- ESIGN RESPONSE ---\n{res_json}"

            self.save()

            return {
                "request": req_json,
                "response": res_json,
                "status": str(res_data.get("status") or "").lower(),
                "error": res_data.get("message") or res_data.get("error")
            }
        except Exception as e:
            frappe.throw(f"API Connection Error: {str(e)}")
