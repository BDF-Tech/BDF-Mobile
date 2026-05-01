from mobile.mobile.doctype.tanker_weight_log.tanker_weight_log import capture_scale_data
import frappe
import json
from frappe.utils import today, add_days, get_first_day, get_last_day, getdate, flt, formatdate
from frappe.utils.nestedset import get_descendants_of
from erpnext.accounts.party import get_dashboard_info
from collections import defaultdict
from frappe.utils import flt, now_datetime


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
        # --- STEP 1: Get Customer ---
        customer_id = get_logged_in_customer()

        if not customer_id:
            return {"error": f"No Customer linked to user {frappe.session.user}. Please contact support."}

        # --- STEP 2: Get Price List ---
        customer_details = frappe.db.get_value(
            "Customer",
            customer_id,
            ["default_price_list", "customer_group", "custom_app_template"],
            as_dict=True
        )

        price_list = customer_details.get("default_price_list")

        if not price_list and customer_details.get("customer_group"):
            price_list = frappe.db.get_value(
                "Customer Group",
                customer_details["customer_group"],
                "default_price_list"
            )

        if not price_list:
            price_list = frappe.db.get_value(
                "Selling Settings",
                None,
                "selling_price_list"
            ) or "Standard Selling"

        # --- STEP 3: GET TEMPLATE ITEMS ---
        template = customer_details.get("custom_app_template")

        if not template:
            return []

        allowed_rows = frappe.get_all(
            "Item Template Item",
            filters={
                "parent": template,
                "allow_on_app": 1
            },
            fields=["item as item_code", "uom"]
        )

        if not allowed_rows:
            return []

        # 🔥 OPTIMIZED SETS
        allowed_item_codes = tuple(set(r.item_code for r in allowed_rows))
        allowed_uom_map = set(f"{r.item_code}_{r.uom}" for r in allowed_rows)

        # --- STEP 4: Main Item Query ---
        items = frappe.db.sql("""
            SELECT
                i.item_code, i.item_name, i.image, i.item_group,
                i.stock_uom, i.sales_uom,
                COALESCE(ip.price_list_rate, 0) AS base_rate
            FROM `tabItem` i
            LEFT JOIN `tabItem Price` ip
                ON ip.item_code = i.item_code AND ip.price_list = %(price_list)s 
            WHERE
                i.item_code IN %(allowed_items)s
                AND i.is_sales_item = 1 
                AND i.disabled = 0
            ORDER BY i.item_name ASC
        """, {
            "price_list": price_list,
            "allowed_items": allowed_item_codes
        }, as_dict=True)

        if not items:
            return []

        # --- STEP 5: Bulk Fetch UOMs ---
        all_uoms = frappe.db.get_all(
            "UOM Conversion Detail",
            filters={"parent": ["in", allowed_item_codes]},
            fields=["parent", "uom", "conversion_factor"]
        )

        from collections import defaultdict
        uom_lookup = defaultdict(list)
        for u in all_uoms:
            uom_lookup[u.parent].append(u)

        result = []

        # --- STEP 6: Processing ---
        for item in items:
            item_uom_rows = uom_lookup.get(item.item_code, [])

            uom_map = {row.uom: row.conversion_factor for row in item_uom_rows}

            if item.stock_uom not in uom_map:
                uom_map[item.stock_uom] = 1.0

            final_uoms_list = []

            for uom, factor in uom_map.items():
                key = f"{item.item_code}_{uom}"

                if key in allowed_uom_map:
                    final_uoms_list.append({
                        "uom": uom,
                        "conversion_factor": factor
                    })

            if not final_uoms_list:
                continue

            if not item.item_code:
                continue

            result.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "image": item.image,
                "item_group": item.item_group,
                "stock_uom": item.stock_uom,
                "base_rate": flt(item.base_rate),
                "uoms": final_uoms_list,
                "price_list": price_list
            })

        # =========================================================
        # 🔥 STEP 7: GROUP-WISE SORTING (NEW LOGIC)
        # =========================================================

        category_priority = {
            "Milk FG": 1,
            "Dahi FG": 2,
            "Paneer FG": 3,
            "Paneer FG": 4
        }

        result.sort(key=lambda x: (
            category_priority.get(x.get("item_group"), 999),
            x.get("item_name", "")
        ))

        # =========================================================

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_item_list Error")
        # =========================================================
        return {"error": str(e)}
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
        # 1️⃣ RESOLVE CUSTOMER
        # Using the helper logic to find the Customer ID linked to the user email
        customer_id = get_logged_in_customer()
        
        # Parse items safely
        cart_items = json.loads(items) if isinstance(items, str) else items
        if not cart_items:
            frappe.throw("Cannot place empty order")

        target_date = req_date or add_days(today(), 1)
        target_shift = req_shift or "Morning"

        # 2️⃣ VALIDATION CHECK: Prevent duplicate orders for same date/shift
        existing_so = frappe.db.get_value(
            "Sales Order",
            {
                "customer": customer_id,
                "delivery_date": target_date,
                "delivery_shift": target_shift,
                "docstatus": ["<", 2]
            },
            "name"
        )

        if existing_so:
            return {
                "status": "error",
                "message": f"An Order ({existing_so}) already exists for {formatdate(target_date)} ({target_shift})."
            }

        # 3️⃣ INITIALIZE SALES ORDER
        so = frappe.new_doc("Sales Order")
        so.customer = customer_id
        
        # Pulls in default currency, price list, etc.
        so.run_method("set_missing_values")

        customer_doc = frappe.get_doc("Customer", customer_id)
        price_list = so.selling_price_list or customer_doc.default_price_list or "Standard Selling"

        so.update({
            "transaction_date": today(),
            "delivery_date": target_date,
            "delivery_shift": target_shift,
            "order_type": "Sales",
            "company": frappe.defaults.get_user_default("Company") or "Bastar Dairy Farm",
            "po_no": po_no or None,
            "territory": customer_doc.territory
        })

        # 4️⃣ MERGING LOGIC (Summing Cart + Mandatory)
        # Using a dictionary to group by (item_code, uom)
        merged_items = {}

        # A. Add Cart Items
        for row in cart_items:
            key = (row.get("item_code"), row.get("uom"))
            qty = flt(row.get("qty"))
            if qty > 0:
                merged_items[key] = merged_items.get(key, 0) + qty

        # B. Add Mandatory Items (Cumulative)
        if customer_doc.get("custom_minimumn_order"):
            for m in customer_doc.get("custom_minimumn_order"):
                key = (m.item, m.uom)
                m_qty = flt(m.qty)
                # This performs a mathematical addition (1 from cart + 1 mandatory = 2)
                merged_items[key] = merged_items.get(key, 0) + m_qty

        # 5️⃣ ADD MERGED ROWS TO SALES ORDER
        for (item_code, uom), total_qty in merged_items.items():
            # Calculate Price with UOM Conversion (Crate vs Nos)
            base_rate = frappe.db.get_value("Item Price", 
                {"item_code": item_code, "price_list": price_list}, "price_list_rate") or 0.0

            conversion_factor = frappe.db.get_value("UOM Conversion Detail", 
                {"parent": item_code, "uom": uom}, "conversion_factor") or 1.0
            
            actual_rate = flt(base_rate) * flt(conversion_factor)

            so.append("items", {
                "item_code": item_code,
                "qty": total_qty,
                "uom": uom,
                "rate": actual_rate,
                "delivery_date": target_date
            })

        # 6️⃣ FINAL CALCULATIONS & SAVE
        so.set_missing_values()
        so.calculate_taxes_and_totals()
        
        # insert() ensures the document and child tables are written to DB
        so.insert(ignore_permissions=True)

        return {
            "status": "success",
            "order_name": so.name
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Order Placement Error")
        return {"status": "error", "message": str(e)}  # =========================================================
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
def get_invoice_details(invoice_id=None):

    # 🔥 If not provided → return safe response
    if not invoice_id:
        return {
            "status": "error",
            "message": "Invoice ID not provided"
        }

    if not frappe.db.exists("Sales Invoice", invoice_id):
        return {
            "status": "error",
            "message": "Invoice not found"
        }

    doc = frappe.get_doc("Sales Invoice", invoice_id)
    current_customer = get_logged_in_customer()

    # 🔒 Security check
    if doc.customer != current_customer:
        return {
            "status": "error",
            "message": "Unauthorized access"
        }

    return {
        "status": "success",

        "name": doc.name,
        "date": doc.posting_date,
        "status_label": doc.status,
        "grand_total": float(doc.grand_total or 0),
        "outstanding": float(doc.outstanding_amount or 0),

        "items": [
            {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": float(item.qty or 0),
                "rate": float(item.rate or 0),
                "amount": float(item.amount or 0)
            }
            for item in doc.items
        ]
    }

# =========================================================
# 📒 LEDGER REPORT
# =========================================================
@frappe.whitelist()
def get_customer_ledger(filter_type="This Year", start_date=None, end_date=None, voucher_type=None, selected_company=None):
    # (Assuming get_logged_in_customer and get_date_range are defined elsewhere in your file)
    customer_id = get_logged_in_customer()

    # 1. Get resolved dates
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    # 🔥 DEBUG (remove later)
    frappe.log_error(f"Company received: {selected_company}", "Ledger Debug")

    # 2. Build SQL Conditions
    conditions = """
        WHERE party_type = 'Customer'
        AND party = %s
        AND posting_date BETWEEN %s AND %s
        AND is_cancelled = 0
    """

    params = [customer_id, from_date, to_date]

    # 🔥 Company filter (STRICT) - Updated variable name
    if selected_company:
        conditions += " AND company = %s"
        params.append(selected_company)

    # 3. Voucher Type Filter
    if voucher_type:
        conditions += " AND voucher_type = %s"
        params.append(voucher_type)
    else:
        conditions += " AND voucher_type != 'Payment Ledger Entry'"

    # 4. Fetch GL Entries (STRICT SQL)
    gl_entries = frappe.db.sql(f"""
        SELECT
            posting_date,
            voucher_type,
            voucher_no,
            debit,
            credit,
            remarks
        FROM `tabGL Entry`
        {conditions}
        ORDER BY posting_date ASC, creation ASC
    """, tuple(params), as_dict=True)

    # 5. Opening Balance (STRICT SQL)
    opening_conditions = """
        WHERE party_type = 'Customer'
        AND party = %s
        AND posting_date < %s
        AND is_cancelled = 0
    """

    opening_params = [customer_id, from_date]

    # 🔥 Apply the same selected_company filter to Opening Balance
    if selected_company:
        opening_conditions += " AND company = %s"
        opening_params.append(selected_company)

    opening_balance_data = frappe.db.sql(f"""
        SELECT SUM(debit - credit) as balance
        FROM `tabGL Entry`
        {opening_conditions}
    """, tuple(opening_params), as_dict=True)

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
            "balance": running_balance
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
            customer_doc = frappe.db.get_value(
                "Customer",
                customer_id,
                [
                    "custom_starting_date_of_the_contract",
                    "food_license_number",
                    "food_license_validity",
                    "custom_security_deposit_amount",   # ✅ added
                    "custom_rent_amount"                # ✅ added
                ],
                as_dict=True
            )

            if customer_doc:
                customer_data = {
                    "contract_date": formatdate(customer_doc.get("custom_starting_date_of_the_contract")) if customer_doc.get("custom_starting_date_of_the_contract") else None,
                    "license_no": customer_doc.get("food_license_number"),
                    "license_validity": formatdate(customer_doc.get("food_license_validity")) if customer_doc.get("food_license_validity") else None,

                    # 🔥 NEW FIELDS
                    "security_deposit": customer_doc.get("custom_security_deposit_amount"),
                    "rent_amount": customer_doc.get("custom_rent_amount")
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

'''@frappe.whitelist()
def fetch_customer_catalog(customer_id):

    # 1. Security Check
    if not frappe.has_permission("Customer", "write"):
        frappe.throw("You do not have permission to edit Customers.")

    # 2. Fetch Items + UOMs + Sales/Stock Preference
    # We added 'i.sales_uom' and 'i.stock_uom' to the query
    data = frappe.db.sql("""
        SELECT 
            i.item_code, 
            i.item_name, 
            i.sales_uom,
            i.stock_uom,
            u.uom
        FROM `tabItem` i
        JOIN `tabUOM Conversion Detail` u ON u.parent = i.item_code
        WHERE 
            i.is_sales_item = 1 
            AND i.disabled = 0
        ORDER BY i.item_name ASC
    """, as_dict=True)

    if not data:
        return "No sales items found"

    # 3. Get the Customer Doc
    doc = frappe.get_doc("Customer", customer_id)

    # 4. Clear existing table
    doc.set("custom_app_item_setting", [])

    # 5. Fill the table with Smart Logic
    enabled_count = 0

    for row in data:
        should_enable = 0

        # Priority 1: Exact match with Sales UOM
        if row.sales_uom and row.uom == row.sales_uom:
            should_enable = 1

        # Priority 2: If no Sales UOM defined, fallback to Stock UOM
        elif not row.sales_uom and row.uom == row.stock_uom:
            should_enable = 1

        doc.append("custom_app_item_setting", {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "uom": row.uom,
            "allow_on_app": should_enable  # 1 or 0 based on logic above
        })

        if should_enable:
            enabled_count += 1

    # 6. Save (bypassing permissions since we already checked write access above)
    doc.save(ignore_permissions=True)

    return f"Successfully fetched catalog. Auto-enabled {enabled_count} default UOMs."
'''

@frappe.whitelist(allow_guest=True)
def s(v=None):
    # Pass 'v' from the URL to your main function
    return capture_scale_data(w=v)

@frappe.whitelist()
def fetch_template_items(template_name):

    # 1. Permission Check
    if not frappe.has_permission("Item Template Master", "write"):
        frappe.throw("No permission to edit Item Template")

    # 2. Fetch Items + UOMs + Sales/Stock Preference
    data = frappe.db.sql("""
        SELECT 
            i.item_code, 
            i.item_name, 
            i.sales_uom,
            i.stock_uom,
            i.custom_allow_on_app,
            u.uom,
            u.conversion_factor
        FROM `tabItem` i
        JOIN `tabUOM Conversion Detail` u ON u.parent = i.item_code
        WHERE 
            i.is_sales_item = 1 
            AND i.disabled = 0
            AND i.custom_allow_on_app = 1   -- 🔥 NEW FILTER
        ORDER BY i.item_name ASC
    """, as_dict=True)

    if not data:
        return "No allowed items found"

    # 3. Get Template Doc
    doc = frappe.get_doc("Item Template Master", template_name)

    # 4. Clear existing table
    doc.set("items", [])

    added_count = 0

    # 5. Loop through data
    for row in data:

        allow_on_app = 0

        # ✅ Check if UOM matches sales_uom
        if row.sales_uom and row.uom == row.sales_uom:
            allow_on_app = 1

        # (Optional fallback if no sales_uom)
        elif not row.sales_uom and row.uom == row.stock_uom:
            allow_on_app = 1

        # 🔥 Append ALL rows, but mark allow_on_app accordingly
        doc.append("items", {
            "item": row.item_code,
            "item_name": row.item_name,
            "uom": row.uom,
            "conversion_factor": row.conversion_factor,
            "allow_on_app": allow_on_app   # ✅ your new field
        })

        added_count += 1

    # 6. Save
    doc.save(ignore_permissions=True)

    return f"{added_count} rows added. Default UOM auto-selected."
