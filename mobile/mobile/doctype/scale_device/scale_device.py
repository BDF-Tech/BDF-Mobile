import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, add_days

class ScaleDevice(Document):
    pass

def execute_dynamic_cleanup():
    print("🔥 FUNCTION STARTED")

    devices = frappe.get_all("Scale Device", fields=["name", "retention_days"])
    print("Devices:", devices)

    for d in devices:
        print("👉 Device:", d.name)

        keep_days = d.retention_days if d.retention_days is not None else 3
        print("Keep Days:", keep_days)

        threshold_date = add_days(now_datetime(), -keep_days)
        print("Threshold:", threshold_date)

        logs = frappe.db.sql("""
            SELECT name FROM `tabTanker Weight Log`
            WHERE device = %s AND creation < %s
        """, (d.name, threshold_date), as_dict=True)

        print("Logs Found:", len(logs))

        frappe.db.sql("""
            DELETE FROM `tabTanker Weight Log`
            WHERE device = %s AND creation < %s
        """, (d.name, threshold_date))

    frappe.db.commit()
    print("✅ DONE")