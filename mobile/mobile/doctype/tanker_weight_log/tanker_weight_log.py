import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

class TankerWeightLog(Document):
    pass

@frappe.whitelist(allow_guest=True)
def capture_scale_data(stringnew=None):
    """
    URL: http://bdf.test:8000/api/method/mobile.mobile.doctype.tanker_weight_log.tanker_weight_log.capture_scale_data
    """
    if not stringnew:
        return {"status": "error", "message": "No payload received"}

    try:
        # 1. Parsing
        parts = stringnew.split('|')
        if len(parts) < 5:
            return {"status": "error", "message": "Malformed data string"}

        device_id = parts[0].strip()
        data_status = parts[1].strip()
        raw_weight = parts[4].strip()

        # 2. Validation from Master (Scale Device)
        if not frappe.db.exists("Scale Device", device_id):
            return {"status": "unauthorized", "message": f"Device {device_id} not registered"}

        device_data = frappe.db.get_value("Scale Device", device_id, ["active"], as_dict=True)

        if not device_data or not device_data.active:
            return {"status": "inactive", "message": "Device is deactivated"}

        # 3. Create Log Entry
        current_weight = flt(raw_weight)
        log = frappe.get_doc({
            "doctype": "Tanker Weight Log",
            "device": device_id,
            "weight": current_weight, 
            "status": data_status,
            "raw_payload": stringnew
        })
        log.insert(ignore_permissions=True)
        
        # 4. Update Last Ping on Master
        frappe.db.set_value("Scale Device", device_id, "last_ping", now_datetime())

        frappe.db.commit()
        return "OK"

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Scale API Error Detail")
        return {"status": "error", "message": str(e)}