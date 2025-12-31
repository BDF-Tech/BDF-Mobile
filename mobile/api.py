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

@frappe.whitelist()
def get_item_list():
    try:
        all_groups = []

        # 1. Fetch descendants for "Finished Goods"
        if frappe.db.exists("Item Group", "Finished Goods"):
            fg_children = get_descendants_of("Item Group", "Finished Goods")
            for item in fg_children:
                if isinstance(item, dict):
                    all_groups.append(item.get("name"))
                else:
                    all_groups.append(item) 
            all_groups.append("Finished Goods") 

        # 2. Fetch descendants for "Trading"
        if frappe.db.exists("Item Group", "Trading"):
            trading_children = get_descendants_of("Item Group", "Trading")
            for item in trading_children:
                if isinstance(item, dict):
                    all_groups.append(item.get("name"))
                else:
                    all_groups.append(item)
            all_groups.append("Trading")

        if not all_groups:
            return []

        groups_tuple = tuple(set(all_groups))

        query = """
            SELECT 
                i.item_code, 
                i.item_name, 
                i.image, 
                i.item_group,
                COALESCE(ip.price_list_rate, 0) as price
            FROM 
                `tabItem` i
            LEFT JOIN 
                `tabItem Price` ip 
            ON 
                i.item_code = ip.item_code 
                AND ip.price_list = 'All Franchise Price'
            WHERE 
                i.item_group IN %(groups)s
                AND i.disabled = 0
                AND i.is_sales_item = 1
            ORDER BY 
                i.item_name ASC
        """
        items = frappe.db.sql(query, {"groups": groups_tuple}, as_dict=True)
        return items

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Catalog SQL Error")
        return {"error": str(e)}
    
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

@frappe.whitelist()
def get_order_list(filter_type="This Year", start_date=None, end_date=None):
    """
    Returns list of Sales Orders. 
    Added start_date and end_date params for Custom filtering.
    """
    customer_id = get_logged_in_customer()
    
    # 1. Get resolved dates based on filter type or custom input
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    orders = frappe.db.get_list("Sales Order",
        filters={
            "customer": customer_id,
            "transaction_date": ["between", [from_date, to_date]],
            "docstatus": ["!=", 2]
        },
        fields=["name", "transaction_date", "grand_total", "status", "delivery_date", "total_qty"],
        order_by="transaction_date desc"
    )
    return orders

@frappe.whitelist()
def get_order_details(order_id):
    if not frappe.db.exists("Sales Order", order_id):
        frappe.throw("Order not found")
    
    doc = frappe.get_doc("Sales Order", order_id)
    current_customer = get_logged_in_customer()
    
    if doc.customer != current_customer:
        frappe.throw("Unauthorized access to this order")

    return {
        "name": doc.name,
        "date": doc.transaction_date,
        "status": doc.status,
        "grand_total": doc.grand_total,
        "taxes": doc.total_taxes_and_charges,
        "items": [{
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "rate": item.rate,
            "amount": item.amount,
            "image": frappe.db.get_value("Item", item.item_code, "image")
        } for item in doc.items]
    }

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