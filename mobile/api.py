import frappe
import json
from frappe.utils import today, add_days, get_first_day, get_last_day, getdate, flt, formatdate
from frappe.utils.nestedset import get_descendants_of
from erpnext.accounts.party import get_dashboard_info

# =========================================================
# 🛠️ HELPER: RESOLVE CUSTOMER FROM LOGGED-IN USER
# =========================================================

def get_logged_in_customer():
    """
    Finds the Customer linked to the current session user.
    Logic: Checks 'Portal User' child table inside Customer doctype.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)

    # 1. Primary Lookup: 'Portal User' Child Table
    customer_id = frappe.db.get_value("Portal User", {"user": user}, "parent")

    if customer_id:
        return customer_id

    # 2. Fallback: Standard Contact Link
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        customer_id = frappe.db.get_value("Dynamic Link", {
            "parent": contact_name,
            "link_doctype": "Customer"
        }, "link_name")
    
    if customer_id:
        return customer_id

    frappe.throw(f"No Customer linked to user {user}. Please contact support.")

# =========================================================
# 📅 HELPER: DATE FILTERS (UPDATED)
# =========================================================

def get_date_range(filter_type, start_date=None, end_date=None):
    today_date = today()

    if filter_type == "Custom" and start_date and end_date:
        # ✅ Correctly handle custom dates passed from Flutter
        return start_date, end_date

    elif filter_type == "This Week":
        from_date = add_days(today_date, -getdate(today_date).weekday())
        to_date = add_days(from_date, 6)
    elif filter_type == "This Month":
        from_date = get_first_day(today_date)
        to_date = get_last_day(today_date)
    elif filter_type == "This Year":
        year = getdate(today_date).year
        from_date = f"{year}-01-01"
        to_date = f"{year}-12-31"
    else:
        # Default fallback (Last 30 Days)
        from_date = add_days(today_date, -30)
        to_date = today_date

    return from_date, to_date

# =========================================================
# 📦 ITEM CATALOG API
# =========================================================

    
# =========================================================
# 📊 DASHBOARD API
# =========================================================

@frappe.whitelist()
def get_my_dashboard_stats():
    customer_id = get_logged_in_customer()
    user_email = frappe.session.user
    stats_data = get_dashboard_info(party=customer_id, party_type="Customer")

    return {
        "user_name": frappe.utils.get_fullname(user_email),
        "customer_id": customer_id,
        "stats": stats_data
    }

# =========================================================
# 🛒 ORDER PLACEMENT API
# =========================================================

# =========================================================
# 📜 SALES ORDER LIST (UPDATED)
# =========================================================

# =========================================================
# 🧾 SALES INVOICE LIST (UPDATED)
# =========================================================

# =========================================================
# 📒 LEDGER REPORT
# =========================================================

# =========================================================
# 👤 PROFILE API
# =========================================================

@frappe.whitelist()
def get_user_profile():
    try:
        try:
            customer_id = get_logged_in_customer()
        except Exception:
            customer_id = None

        user = frappe.session.user
        if user == "Guest":
            return {"error": "Not Logged In"}

        user_doc = frappe.get_doc("User", user)
        
        customer_data = {}
        if customer_id:
            customer_doc = frappe.db.get_value("Customer", customer_id, 
                ["custom_starting_date_of_the_contract", "food_license_number", "food_license_validity"], 
                as_dict=True
            )
            
            if customer_doc:
                customer_data = {
                    "contract_date": formatdate(customer_doc.get("custom_starting_date_of_the_contract")) if customer_doc.get("custom_starting_date_of_the_contract") else None,
                    "license_no": customer_doc.get("food_license_number"),
                    "license_validity": formatdate(customer_doc.get("food_license_validity")) if customer_doc.get("food_license_validity") else None
                }

        return {
            "full_name": user_doc.full_name,
            "email": user_doc.email,
            "gender": user_doc.gender,
            "dob": formatdate(user_doc.birth_date) if user_doc.birth_date else None,
            "image": user_doc.user_image,
            "customer_id": customer_id,
            **customer_data
        }

    except Exception as e:
        frappe.log_error(f"Profile Error: {str(e)}")
        return {"error": str(e)}