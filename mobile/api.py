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
    """
    Logic: 
    1. If 'Custom' is selected AND dates are provided -> Use them.
    2. ANYTHING else (Default) -> Return Last 7 Days.
    """
    today_date = today()

    # 1. Custom Logic
    if filter_type == "Custom" and start_date and end_date:
        return start_date, end_date

    # 2. Default Fallback: Last 7 Days
    # logic: today minus 7 days covers the past week
    from_date = add_days(today_date, -7)
    to_date = today_date

    return from_date, to_date

# =========================================================
# 📦 ITEM CATALOG API
# =========================================================
@frappe.whitelist()
def get_item_list():
    try:
        # 1️⃣ DYNAMIC PRICE LIST LOGIC
        customer_id = get_logged_in_customer()
        
        # Priority A: Check if Customer has a specific Price List assigned
        price_list = frappe.db.get_value("Customer", customer_id, "default_price_list")
        
        # Priority B: If not, check the Customer Group's default
        if not price_list:
            cust_group = frappe.db.get_value("Customer", customer_id, "customer_group")
            if cust_group:
                price_list = frappe.db.get_value("Customer Group", cust_group, "default_price_list")

        # Priority C: Fallback to System Default (Selling Settings)
        if not price_list:
            price_list = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"

        # ---------------------------------------------------------

        all_groups = []

        # 2️⃣ Collect Item Groups
        if frappe.db.exists("Item Group", "Finished Goods"):
            fg_children = get_descendants_of("Item Group", "Finished Goods")
            for g in fg_children:
                all_groups.append(g.get("name") if isinstance(g, dict) else g)
            all_groups.append("Finished Goods")

        if frappe.db.exists("Item Group", "Trading"):
            trading_children = get_descendants_of("Item Group", "Trading")
            for g in trading_children:
                all_groups.append(g.get("name") if isinstance(g, dict) else g)
            all_groups.append("Trading")

        if not all_groups:
            return []

        groups = tuple(set(all_groups))

        # 3️⃣ Fetch Items with DYNAMIC Price List
        # We pass 'price_list' as a parameter to the query now
        items = frappe.db.sql("""
            SELECT
                i.item_code,
                i.item_name,
                i.image,
                i.item_group,
                i.stock_uom,
                COALESCE(ip.price_list_rate, 0) AS base_rate
            FROM `tabItem` i
            LEFT JOIN `tabItem Price` ip
                ON ip.item_code = i.item_code
                AND ip.price_list = %(price_list)s 
            WHERE
                i.item_group IN %(groups)s
                AND i.disabled = 0
                AND i.is_sales_item = 1
            ORDER BY i.item_name ASC
        """, {
            "groups": groups, 
            "price_list": price_list  # <--- Passing the dynamic variable
        }, as_dict=True)

        result = []

        # 4️⃣ Attach UOMs (Logic remains same)
        for item in items:
            uom_rows = frappe.get_all(
                "UOM Conversion Detail",
                filters={"parent": item.item_code},
                fields=["uom", "conversion_factor"]
            )

            uom_map = {}
            for row in uom_rows:
                uom_map[row.uom] = row.conversion_factor

            if item.stock_uom not in uom_map:
                uom_map[item.stock_uom] = 1

            uoms = [
                {
                    "uom": uom,
                    "conversion_factor": conversion_factor
                }
                for uom, conversion_factor in uom_map.items()
            ]

            result.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "image": item.image,
                "item_group": item.item_group,
                "stock_uom": item.stock_uom,
                "base_rate": flt(item.base_rate),
                "current_price_list": price_list, # Optional: Sent for debugging
                "uoms": uoms
            })

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_item_list Error")
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
def place_order(items, req_date=None, req_shift=None):
    try:
        customer_id = get_logged_in_customer()

        if isinstance(items, str):
            cart_items = json.loads(items)
        else:
            cart_items = items

        if not cart_items:
            frappe.throw("Cannot place empty order")

        target_date = req_date if req_date else add_days(today(), 1)
        target_shift = req_shift if req_shift else "Morning"

        # Check for existing draft order to update
        existing_so_name = frappe.db.get_value("Sales Order", {
            "customer": customer_id,
            "delivery_date": target_date,
            "delivery_shift": target_shift,
            "docstatus": ["<", 2]
        }, "name")

        if existing_so_name:
            so = frappe.get_doc("Sales Order", existing_so_name)
            if so.docstatus == 1:
                return {"status": "error", "message": "Order already submitted."}
            so.items = []  # Clear existing items to overwrite
        else:
            so = frappe.new_doc("Sales Order")
            so.customer = customer_id
            so.transaction_date = today()
            so.delivery_date = target_date
            so.delivery_shift = target_shift
            so.order_type = "Sales"
            so.company = frappe.defaults.get_user_default("Company")

        # --- UPDATED LOOP ---
        for row in cart_items:
            so.append("items", {
                "item_code": row.get("item_code"),
                "qty": row.get("qty"),
                "delivery_date": target_date,

                # 1. Map UOM (Crucial for inventory)
                "uom": row.get("uom"),

                # 2. Map Rate (Crucial for correct pricing)
                # We use "rate" here because the App sends key "rate"
                "rate": row.get("rate", 0)
            })

        so.save(ignore_permissions=True)
        return {"status": "success", "order_name": so.name}

    except Exception as e:
        frappe.log_error(f"Order Error: {str(e)}")
        return {"status": "error", "message": str(e)}
# =========================================================
# 📜 SALES ORDER LIST (UPDATED)
# =========================================================


@frappe.whitelist()
def get_order_list(filter_type="Last 7 Days", start_date=None, end_date=None):
    """
    Returns list of Sales Orders. 
    Default Filter: Last 7 Days
    """
    customer_id = get_logged_in_customer()

    # 1. Get resolved dates (Defaults to Last 7 Days if not Custom)
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    orders = frappe.db.get_list("Sales Order",
                                filters={
                                    "customer": customer_id,
                                    "transaction_date": ["between", [from_date, to_date]],
                                    "docstatus": ["!=", 2]
                                },
                                fields=["name", "transaction_date", "grand_total",
                                        "status", "delivery_date", "total_qty"],
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

# =========================================================
# 🧾 SALES INVOICE LIST (UPDATED)
# =========================================================


@frappe.whitelist()
def get_invoice_list(filter_type="Last 7 Days", start_date=None, end_date=None):
    """
    Returns list of Sales Invoices. 
    Default Filter: Last 7 Days
    """
    customer_id = get_logged_in_customer()

    # 1. Get resolved dates (Defaults to Last 7 Days if not Custom)
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    invoices = frappe.db.get_list("Sales Invoice",
                                  filters={
                                      "customer": customer_id,
                                      "posting_date": ["between", [from_date, to_date]],
                                      "docstatus": 1
                                  },
                                  fields=["name", "posting_date", "grand_total",
                                          "outstanding_amount", "status"],
                                  order_by="posting_date desc"
                                  )
    return invoices


@frappe.whitelist()
def get_invoice_details(invoice_id):
    if not frappe.db.exists("Sales Invoice", invoice_id):
        frappe.throw("Invoice not found")

    doc = frappe.get_doc("Sales Invoice", invoice_id)
    current_customer = get_logged_in_customer()

    if doc.customer != current_customer:
        frappe.throw("Unauthorized access")

    return {
        "name": doc.name,
        "date": doc.posting_date,
        "status": doc.status,
        "grand_total": doc.grand_total,
        "outstanding": doc.outstanding_amount,
        "items": [{
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "rate": item.rate,
            "amount": item.amount
        } for item in doc.items]
    }

# =========================================================
# 📒 LEDGER REPORT
# =========================================================


@frappe.whitelist()
def get_customer_ledger(filter_type="This Year", start_date=None, end_date=None, voucher_type=None):
    customer_id = get_logged_in_customer()

    # 1. Get resolved dates
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    # 2. Base Filters
    filters = {
        "party_type": "Customer",
        "party": customer_id,
        "posting_date": ["between", [from_date, to_date]],
        "is_cancelled": 0
    }

    # 3. Dynamic Filtering Logic
    if voucher_type:
        filters["voucher_type"] = voucher_type
    else:
        # Show Everything (Invoices + Payments), excluding internal tech entries
        filters["voucher_type"] = ["not in", ["Payment Ledger Entry"]]

    # 4. Fetch Data
    gl_entries = frappe.get_list("GL Entry",
                                 filters=filters,
                                 fields=["posting_date", "voucher_type",
                                         "voucher_no", "debit", "credit", "remarks"],
                                 order_by="posting_date asc, creation asc",
                                 ignore_permissions=True
                                 )

    # 5. Calculate Background Balance (Math only, no row added)
    opening_balance_data = frappe.db.sql("""
        SELECT SUM(debit - credit) as balance
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' 
        AND party = %s 
        AND posting_date < %s
        AND is_cancelled = 0
    """, (customer_id, from_date), as_dict=True)

    # We initialize the math here, but we DO NOT append a row to 'data'
    running_balance = opening_balance_data[0].balance or 0.0

    data = []

    # 6. Process Transactions
    for entry in gl_entries:
        running_balance += (entry.debit - entry.credit)
        data.append({
            "date": entry.posting_date,
            "voucher_type": entry.voucher_type,
            "voucher_no": entry.voucher_no,
            "debit": entry.debit,
            "credit": entry.credit,
            "balance": running_balance  # This will now be mathematically correct
        })

    return data

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
                                               ["custom_starting_date_of_the_contract",
                                                   "food_license_number", "food_license_validity"],
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
