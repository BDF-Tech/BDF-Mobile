import frappe
import json
from frappe.utils import today, add_days, get_first_day, get_last_day, getdate, flt, formatdate
from frappe.utils.nestedset import get_descendants_of
from erpnext.accounts.party import get_dashboard_info
from collections import defaultdict  # <--- THIS WAS MISSING

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
        # ==========================================
        # 1️⃣ OPTIMIZED: Price List Logic
        # ==========================================
        customer_id = get_logged_in_customer()

        # Fetch Customer & Group details in one go to reduce db calls
        customer_details = frappe.db.get_value("Customer", customer_id, [
                                               "default_price_list", "customer_group"], as_dict=True)

        price_list = customer_details.get("default_price_list")

        if not price_list and customer_details.get("customer_group"):
            price_list = frappe.db.get_value(
                "Customer Group", customer_details["customer_group"], "default_price_list")

        if not price_list:
            # Typically cached by Frappe, so this is fast
            price_list = frappe.db.get_value(
                "Selling Settings", None, "selling_price_list") or "Standard Selling"

        # ==========================================
        # 2️⃣ OPTIMIZED: Item Groups
        # ==========================================
        all_groups = []

        # get_descendants_of is cached by Frappe, so this is okay
        if frappe.db.exists("Item Group", "Finished Goods"):
            all_groups.extend(get_descendants_of(
                "Item Group", "Finished Goods"))
            all_groups.append("Finished Goods")

        if frappe.db.exists("Item Group", "Trading"):
            all_groups.extend(get_descendants_of("Item Group", "Trading"))
            all_groups.append("Trading")

        if not all_groups:
            return []

        # Clean list of groups
        groups = tuple(set(g.get("name") if isinstance(
            g, dict) else g for g in all_groups))

        # ==========================================
        # 3️⃣ MAIN QUERY: Fetch Items
        # ==========================================
        items = frappe.db.sql("""
            SELECT
                i.item_code,
                i.item_name,
                i.image,
                i.item_group,
                i.stock_uom,
                i.sales_uom,
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
            "price_list": price_list
        }, as_dict=True)

        if not items:
            return []

        # ==========================================
        # 4️⃣ OPTIMIZED: Bulk Fetch UOMs (The Fix)
        # ==========================================

        # Extract all item codes to fetch their UOMs in ONE query
        item_codes = [item.item_code for item in items]

        # Fetch ALL UOM conversion details for these items at once
        all_uoms = frappe.db.get_all(
            "UOM Conversion Detail",
            filters={"parent": ["in", item_codes]},
            fields=["parent", "uom", "conversion_factor"]
        )

        # Organize UOMs into a dictionary for fast lookup
        # Structure: { 'ITEM-001': [ {uom: 'Box', conversion_factor: 10}, ... ] }
        uom_lookup = defaultdict(list)
        for u in all_uoms:
            uom_lookup[u.parent].append(u)

        result = []

        # ==========================================
        # 5️⃣ PROCESSING: Map UOMs in Memory
        # ==========================================
        for item in items:
            # Get UOMs for this specific item from our pre-fetched dictionary
            # No database call happens here!
            item_uom_rows = uom_lookup.get(item.item_code, [])

            # Create a quick map for conversion factors
            uom_map = {row.uom: row.conversion_factor for row in item_uom_rows}

            # Always ensure Stock UOM is present
            if item.stock_uom not in uom_map:
                uom_map[item.stock_uom] = 1.0

            final_uoms_list = []

            # --- 🛑 CONTROL LOGIC (Logic Preserved) 🛑 ---

            # CASE A: Strict Default Sales UOM
            if item.sales_uom:
                factor = uom_map.get(item.sales_uom, 1.0)
                final_uoms_list.append({
                    "uom": item.sales_uom,
                    "conversion_factor": factor
                })

            # CASE B: Show All UOMs
            else:
                for uom, factor in uom_map.items():
                    final_uoms_list.append({
                        "uom": uom,
                        "conversion_factor": factor
                    })

            result.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "image": item.image,
                "item_group": item.item_group,
                "stock_uom": item.stock_uom,
                "base_rate": flt(item.base_rate),
                "uoms": final_uoms_list
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
def place_order(items, req_date=None, req_shift=None, po_no=None):
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

        # 1️⃣ VALIDATION CHECK
        # Check if ANY order (Draft or Submitted) exists for this slot
        existing_so = frappe.db.get_value("Sales Order", {
            "customer": customer_id,
            "delivery_date": target_date,
            "delivery_shift": target_shift,
            "docstatus": ["<", 2] # 0 = Draft, 1 = Submitted
        }, ["name", "docstatus"], as_dict=True)

        if existing_so:
            # 🛑 STOP: Do not create/overwrite. Return Error.
            status_msg = "Draft" if existing_so.docstatus == 0 else "Confirmed"
            return {
                "status": "error", 
                "message": f"A {status_msg} Order ({existing_so.name}) already exists for {formatdate(target_date)} ({target_shift})."
            }

        # 2️⃣ CREATE NEW ORDER (Only if validation passes)
        so = frappe.new_doc("Sales Order")
        so.customer = customer_id
        so.transaction_date = today()
        so.delivery_date = target_date
        so.delivery_shift = target_shift
        so.order_type = "Sales"
        so.company = frappe.defaults.get_user_default("Company")
        
        if po_no:
            so.po_no = po_no 

        for row in cart_items:
            so.append("items", {
                "item_code": row.get("item_code"),
                "qty": row.get("qty"),
                "delivery_date": target_date,
                "uom": row.get("uom"),
                "rate": row.get("rate", 0)
            })

        so.save(ignore_permissions=True)
        return {"status": "success", "order_name": so.name}

    except Exception as e:
        frappe.log_error(f"Order Error: {str(e)}")
        return {"status": "error", "message": str(e)}    # =========================================================
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
