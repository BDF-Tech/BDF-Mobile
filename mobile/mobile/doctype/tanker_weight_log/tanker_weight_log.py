import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

class TankerWeightLog(Document):
    pass

@frappe.whitelist(allow_guest=True)
def capture_scale_data(w=None):
    if not w:
        return {"status": "error", "message": "No payload received"}

    try:
        # 1. Parsing
        parts = w.split('|')
        if len(parts) < 5:
            return {"status": "error", "message": "Malformed data string"}

        device_id = parts[0].strip()
        data_status = parts[1].strip()
        # Clean up the weight (handles extra spaces like in ' 03195.0')
        raw_weight = parts[4].strip()

        # 2. Validation from Master (Scale Device)
        if not frappe.db.exists("Scale Device", device_id):
            return {"status": "unauthorized", "message": f"Device {device_id} not registered"}

        device_data = frappe.db.get_value("Scale Device", device_id, ["active"], as_dict=True)

        if not device_data or not device_data.active:
            return {"status": "inactive", "message": "Device is deactivated"}

        # 3. Create Log Entry with Server Time
        current_server_time = now_datetime() # Capture exact server time
        current_weight = flt(raw_weight)
        
        log = frappe.get_doc({
            "doctype": "Tanker Weight Log",
            "device": device_id,
            "weight": current_weight, 
            "status": data_status,
            "raw_payload": w,
            "log_time": current_server_time  # Ensure you have this field in your DocType
        })
        log.insert(ignore_permissions=True)
        
        # 4. Update Last Ping on Master
        frappe.db.set_value("Scale Device", device_id, "last_ping", current_server_time)

        frappe.db.commit()
        return {"message": "OK"} # Return as JSON for better API standards

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Scale API Error Detail")
        return {"status": "error", "message": str(e)}