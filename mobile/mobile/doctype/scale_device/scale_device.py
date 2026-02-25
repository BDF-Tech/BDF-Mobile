import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, add_days

class ScaleDevice(Document):
    pass

def execute_dynamic_cleanup():
    """
    This is called by the scheduler. It looks at 'retention_days' for each scale.
    """
    try:
        devices = frappe.get_all("Scale Device", fields=["name", "retention_days"])
        for d in devices:
            keep_days = d.retention_days if d.retention_days else 3
            threshold_date = add_days(now_datetime(), -keep_days)
            
            # Delete logs for this specific device only
            frappe.db.sql("""
                DELETE FROM `tabTanker Weight Log` 
                WHERE device = %s 
                AND creation < %s
            """, (d.name, threshold_date))
            
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scale Cleanup Error")