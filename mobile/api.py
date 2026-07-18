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
        customer_id = get_logged_in_customer()
        if not customer_id:
            return {"error": f"No Customer linked to user {frappe.session.user}. Please contact support."}

        customer_details = frappe.db.get_value(
            "Customer",
            customer_id,
            ["default_price_list", "customer_group", "custom_app_template"],
            as_dict=True
        )

        price_list = customer_details.get("default_price_list")
        if not price_list and customer_details.get("customer_group"):
            price_list = frappe.db.get_value("Customer Group", customer_details["customer_group"], "default_price_list")
        if not price_list:
            price_list = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"

        template = customer_details.get("custom_app_template")
        if not template:
            return []

        allowed_rows = frappe.get_all(
            "Item Template Item",
            filters={"parent": template, "allow_on_app": 1},
            fields=["item as item_code", "uom"]
        )

        if not allowed_rows:
            return []

        allowed_item_codes = tuple(set(r.item_code for r in allowed_rows))
        allowed_uom_map = set(f"{r.item_code}_{r.uom}" for r in allowed_rows)

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

        all_uoms = frappe.db.get_all(
            "UOM Conversion Detail",
            filters={"parent": ["in", allowed_item_codes]},
            fields=["parent", "uom", "conversion_factor"]
        )

        uom_lookup = defaultdict(list)
        for u in all_uoms:
            uom_lookup[u.parent].append(u)

        # --- Create MOQ & Mandatory Rules Mapping for Flutter ---
        moq_map = {}
        customer_doc = frappe.get_doc("Customer", customer_id)
        if customer_doc.get("custom_minimumn_order"):
            for m in customer_doc.get("custom_minimumn_order"):
                moq_map[m.item] = {
                    "min_qty": flt(m.qty),
                    "is_moq_only": m.get("minimum_qty", 0) # 1 = Checkbox Ticked (MOQ), 0 = Unticked (Mandatory)
                }

        result = []
        for item in items:
            item_uom_rows = uom_lookup.get(item.item_code, [])
            uom_map = {row.uom: row.conversion_factor for row in item_uom_rows}
            if item.stock_uom not in uom_map:
                uom_map[item.stock_uom] = 1.0

            final_uoms_list = []
            for uom, factor in uom_map.items():
                key = f"{item.item_code}_{uom}"
                if key in allowed_uom_map:
                    final_uoms_list.append({"uom": uom, "conversion_factor": factor})

            if not final_uoms_list or not item.item_code:
                continue
            
            # Identify if it is forced mandatory
            item_moq_data = moq_map.get(item.item_code, {})
            is_mandatory = 0
            if item.item_code in moq_map and item_moq_data.get("is_moq_only") == 0:
                is_mandatory = 1

            result.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "image": item.image,
                "item_group": item.item_group,
                "stock_uom": item.stock_uom,
                "base_rate": flt(item.base_rate),
                "uoms": final_uoms_list,
                "price_list": price_list,
                "min_qty": item_moq_data.get("min_qty", 0.0),
                "is_mandatory": is_mandatory
            })

        category_priority = {"Milk FG": 1, "Dahi FG": 2, "Paneer FG": 3}
        result.sort(key=lambda x: (category_priority.get(x.get("item_group"), 999), x.get("item_name", "")))
        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_item_list Error")
        return {"error": str(e)}
# 📊 DASHBOARD API
# =========================================================


def get_customer_dashboard_stats(customer):
    """Company-wise billing/unpaid for a customer, across every company.

    Mirrors erpnext's get_dashboard_info but reads the ledger directly instead of
    resolving each company's receivable account. get_dashboard_info permission-checks
    that account, which a logged-in customer (a portal user with no accounting access)
    always fails, so the dashboard 403'd for every customer.
    """
    from erpnext.accounts.utils import get_fiscal_year
    from frappe.utils import nowdate

    fiscal_year = get_fiscal_year(nowdate(), as_dict=True)

    companies = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "customer": customer},
        distinct=1,
        fields=["company"],
    )

    billing_this_year = frappe._dict(
        frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "customer": customer,
                "posting_date": ("between", [fiscal_year.year_start_date, fiscal_year.year_end_date]),
            },
            group_by="company",
            fields=["company", "sum(base_grand_total) as total"],
            as_list=1,
        )
    )

    total_unpaid = frappe._dict(
        frappe.db.sql(
            """
            select company, sum(debit_in_account_currency) - sum(credit_in_account_currency)
            from `tabGL Entry`
            where party_type = 'Customer' and party = %s and is_cancelled = 0
            group by company
            """,
            (customer,),
        )
    )

    stats = []
    for d in companies:
        currency = frappe.get_cached_value("Company", d.company, "default_currency")
        unpaid = flt(total_unpaid.get(d.company))
        info = {
            "company": d.company,
            "currency": currency,
            "billing_this_year": flt(billing_this_year.get(d.company)),
            "total_unpaid": unpaid,
        }
        if unpaid < 0:
            info["balance_label"] = "Total Advance Received"
            info["balance_amount"] = abs(unpaid)
        else:
            info["balance_label"] = "Total Unpaid"
            info["balance_amount"] = unpaid
        stats.append(info)

    return stats


@frappe.whitelist()
def get_my_dashboard_stats():
    customer_id = get_logged_in_customer()
    user_email = frappe.session.user
    stats_data = get_customer_dashboard_stats(customer_id)

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
        customer_doc = frappe.get_doc("Customer", customer_id)
        
        cart_items = json.loads(items) if isinstance(items, str) else items
        if not cart_items:
            frappe.throw("Cannot place empty order")

        target_date = req_date or add_days(today(), 1)
        target_shift = req_shift or "Morning"

        existing_so = frappe.db.get_value(
            "Sales Order",
            {"customer": customer_id, "delivery_date": target_date, "delivery_shift": target_shift, "docstatus": ["<", 2]},
            ["name", "docstatus"], as_dict=True
        )
        if existing_so:
            return {"status": "error", "message": f"A {'Draft' if existing_so.docstatus == 0 else 'Confirmed'} Order ({existing_so.name}) already exists for {formatdate(target_date)} ({target_shift})."}

        so = frappe.new_doc("Sales Order")
        so.customer = customer_id
        so.run_method("set_missing_values")
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

        # --- MERGING & VALIDATION LOGIC ---
        merged_items = {}

        # 1. Add Cart Items
        for row in cart_items:
            key = (row.get("item_code"), row.get("uom"))
            qty = flt(row.get("qty"))
            if qty > 0:
                merged_items[key] = merged_items.get(key, 0) + qty

        # 2. Process Rules (MOQ vs Mandatory)
        if customer_doc.get("custom_minimumn_order"):
            for m in customer_doc.get("custom_minimumn_order"):
                key = (m.item, m.uom)
                m_qty = flt(m.qty)
                is_moq_only = m.get("minimum_qty", 0) 

                if is_moq_only == 1:
                    # MOQ: Validate if in cart
                    if key in merged_items and merged_items[key] > 0:
                        if merged_items[key] < m_qty:
                            return {"status": "error", "message": f"Minimum order for {m.item} is {int(m_qty)} {m.uom}."}
                else:
                    # Mandatory: Always sum it
                    merged_items[key] = merged_items.get(key, 0) + m_qty

        # 3. Add rows to Sales Order
        for (item_code, uom), total_qty in merged_items.items():
            base_rate = frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list}, "price_list_rate") or 0.0
            conversion_factor = frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor") or 1.0
            actual_rate = flt(base_rate) * flt(conversion_factor)

            so.append("items", {
                "item_code": item_code,
                "qty": total_qty,
                "uom": uom,
                "rate": actual_rate,
                "delivery_date": target_date
            })

        so.set_missing_values()
        so.calculate_taxes_and_totals()

        # A customer's portal user has no accounting permissions, and erpnext's Sales
        # Order validation (set_payment_schedule) now permission-checks the company's
        # receivable account. ignore_permissions does not bypass that check, so we run
        # the insert with an elevated user and then restore the real owner for audit.
        placing_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            so.insert(ignore_permissions=True)
        finally:
            frappe.set_user(placing_user)
        frappe.db.set_value("Sales Order", so.name, "owner", placing_user, update_modified=False)

        return {"status": "success", "order_name": so.name, "territory": so.territory}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Order Placement Error")
        return {"status": "error", "message": str(e)}


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
            "uom": item.uom,
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
                "uom": item.uom,
                "rate": float(item.rate or 0),
                "amount": float(item.amount or 0),
                "image": frappe.db.get_value("Item", item.item_code, "image")
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


# =========================================================
# CRATE MODULE — EMAIL-BASED IDENTITY HELPERS
# =========================================================

MASTER_DEPARTMENTS = {"it", "md"}
DEPARTMENT_MAP = {
    "driver":     "driver",
    "dispatch":   "dispatch",
    "production": "production",
    "it":         "master",
    "md":         "master",
}


def _get_department(email):
    """Extract department from email: sanskar.driver@bastardairyfarm.com → driver"""
    try:
        local = email.split("@")[0]
        return local.split(".")[-1].lower()
    except Exception:
        return None


def _is_master(user=None):
    user = user or frappe.session.user
    return _get_department(user) in MASTER_DEPARTMENTS


def _require(*departments):
    """Allow if user's email department matches, or user is IT/MD (master)."""
    if frappe.session.user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)
    if _is_master():
        return
    dept = _get_department(frappe.session.user)
    if dept not in departments:
        frappe.throw("You don't have permission to access this.", frappe.PermissionError)


def get_logged_in_driver():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)
    driver = frappe.db.get_value("Driver", {"custom_user": user}, "name")
    if not driver:
        frappe.throw(f"No Driver linked to user {user}. Please contact admin.")
    return driver


# =========================================================
# GET USER INFO — called right after login
# =========================================================

@frappe.whitelist()
def get_user_info():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)

    full_name = frappe.utils.get_fullname(user)
    dept = _get_department(user)
    user_type = DEPARTMENT_MAP.get(dept, "customer")

    if user_type == "master":
        return {"user_type": "master", "full_name": full_name, "email": user}

    if user_type == "driver":
        driver = frappe.db.get_value("Driver", {"custom_user": user}, ["name", "full_name"], as_dict=True)
        return {
            "user_type": "driver",
            "full_name": full_name,
            "email": user,
            "driver_id": driver.name if driver else None,
            "driver_name": driver.full_name if driver else full_name
        }

    if user_type == "dispatch":
        return {"user_type": "dispatch", "full_name": full_name, "email": user}

    if user_type == "production":
        return {"user_type": "production", "full_name": full_name, "email": user}

    if user_type == "customer":
        try:
            customer_id = get_logged_in_customer()
        except Exception:
            customer_id = None
        return {"user_type": "customer", "full_name": full_name, "email": user, "customer_id": customer_id}

    return {"user_type": "unknown", "full_name": full_name, "email": user}


# =========================================================
# DRIVER ENDPOINTS
# =========================================================

@frappe.whitelist()
def get_driver_vmls(date=None):
    _require("driver")
    driver = get_logged_in_driver()

    # Active trips the driver acts on: still loading OR dispatched (crate
    # delivery is created once the trip is Submitted).
    filters = {
        "driver": driver,
        "workflow_state": ["in", ["Dispatch Loading", "Submitted"]],
    }
    if date:
        filters["date_and_time"] = ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]]

    return frappe.db.get_list(
        "Vehicle Movement Log",
        filters=filters,
        fields=["name", "date_and_time", "vehicle", "route", "workflow_state"],
        order_by="creation desc"
    )


@frappe.whitelist()
def get_driver_vml_details(vml):
    _require("driver", "dispatch")

    if not frappe.db.exists("Vehicle Movement Log", vml):
        frappe.throw("VML not found")

    doc = frappe.get_doc("Vehicle Movement Log", vml)

    # Drivers can only view their own VML
    if _get_department(frappe.session.user) == "driver" and not _is_master():
        driver = get_logged_in_driver()
        if doc.driver != driver:
            frappe.throw("You are not assigned to this VML", frappe.PermissionError)

    rows = []
    for row in doc.crate_summary:
        if row.sales_invoice:
            # Check for submitted CD first, then draft (OTP pending)
            cd = frappe.db.get_value(
                "Crate Delivery",
                {"sales_invoice": row.sales_invoice, "docstatus": 1},
                ["name", "crates_delivered", "crates_returned", "customer_confirmed"],
                as_dict=True
            )
            cd_is_draft = False
            if not cd:
                cd = frappe.db.get_value(
                    "Crate Delivery",
                    {"sales_invoice": row.sales_invoice, "docstatus": 0},
                    ["name", "crates_delivered", "crates_returned", "customer_confirmed"],
                    as_dict=True
                )
                if cd:
                    cd_is_draft = True
            si_data = frappe.db.get_value(
                "Sales Invoice", row.sales_invoice,
                ["customer", "customer_name"], as_dict=True
            )
            otp_confirmed = bool(cd and cd.customer_confirmed)
            customer_id = si_data.customer if si_data else None
            customer_crate_balance = flt(
                frappe.db.get_value("Customer", customer_id, "custom_current_crate_balance")
            ) if customer_id else 0
            rows.append({
                "row_type": "invoice",
                "sales_invoice": row.sales_invoice,
                "stock_entry": None,
                "customer": customer_id,
                "customer_name": si_data.customer_name if si_data else None,
                "customer_crate_balance": customer_crate_balance,
                "total_crate_out": flt(row.total_crate_out),
                "crate_delivery": cd.name if cd else None,
                "crates_delivered": flt(cd.crates_delivered) if cd else None,
                "crates_returned": flt(cd.crates_returned) if cd else None,
                "customer_confirmed": 1 if otp_confirmed else 0,
                # delivery_done = True only when customer has confirmed via OTP
                "delivery_done": otp_confirmed,
                # delivery_recorded = True once crate numbers have been entered
                "delivery_recorded": bool(cd),
                # otp_pending = CD exists but OTP not yet confirmed
                "otp_pending": bool(cd and not otp_confirmed),
            })
        elif row.stock_entry:
            try:
                se_cd = frappe.db.get_value(
                    "Crate Delivery",
                    {"stock_entry": row.stock_entry, "docstatus": 1},
                    ["name", "crates_delivered", "crates_returned"],
                    as_dict=True
                )
            except Exception:
                se_cd = None

            # Target (transit) warehouse of the stock entry, and the warehouse
            # it is mapped to in Crate Settings → Transit → Warehouse Mapping.
            target_warehouse = frappe.db.get_value(
                "Stock Entry", row.stock_entry, "to_warehouse"
            )
            if not target_warehouse:
                target_warehouse = frappe.db.get_value(
                    "Stock Entry Detail",
                    {"parent": row.stock_entry, "t_warehouse": ["is", "set"]},
                    "t_warehouse"
                )
            mapped_warehouse = frappe.db.get_value(
                "Crate Transit Warehouse Map",
                {"parenttype": "Crate Settings", "transit_warehouse": target_warehouse},
                "warehouse"
            ) if target_warehouse else None

            rows.append({
                "row_type": "stock_entry",
                "sales_invoice": None,
                "stock_entry": row.stock_entry,
                "customer": None,
                "target_warehouse": target_warehouse,
                "mapped_warehouse": mapped_warehouse,
                "total_crate_out": flt(row.total_crate_out),
                "crate_delivery": se_cd.name if se_cd else None,
                "crates_delivered": flt(se_cd.crates_delivered) if se_cd else None,
                "crates_returned": flt(se_cd.crates_returned) if se_cd else None,
                "customer_confirmed": 0,
                "delivery_done": bool(se_cd)
            })

    loose_crates = []
    for lc in doc.loose_crate_detail:
        loose_crates.append({
            "crate_type": lc.crate_item,
            "crates_out": flt(lc.crates_out),
            "crates_in": flt(lc.crates_in),
            "balance": flt(lc.balance)
        })

    driver_crate_balance = flt(frappe.db.get_value("Driver", doc.driver, "custom_invoice_crate_balance"))

    return {
        "name": doc.name,
        "date": str(doc.date_and_time),
        "driver": doc.driver,
        "vehicle": doc.vehicle,
        "route": doc.route,
        "workflow_state": doc.workflow_state,
        "invoice_crate_balance": driver_crate_balance,
        "deliveries": rows,
        "loose_crates": loose_crates
    }


@frappe.whitelist()
def get_driver_profile():
    _require("driver")
    driver = get_logged_in_driver()

    d = frappe.db.get_value(
        "Driver", driver,
        ["full_name", "license_number", "cell_number", "issuing_date", "expiry_date",
         "custom_invoice_crate_balance"],
        as_dict=True
    )
    user = frappe.session.user
    user_doc = frappe.db.get_value("User", user, ["full_name", "user_image"], as_dict=True)

    return {
        "driver_id": driver,
        "full_name": d.full_name,
        "license_number": d.license_number,
        "cell_number": d.cell_number,
        "issuing_date": str(d.issuing_date) if d.issuing_date else None,
        "expiry_date": str(d.expiry_date) if d.expiry_date else None,
        "crate_balance": flt(d.custom_invoice_crate_balance),
        "email": user,
        "image": user_doc.user_image if user_doc else None,
    }


@frappe.whitelist()
def get_driver_pending_deliveries(vml=None):
    _require("driver")
    driver = get_logged_in_driver()

    filters = {"driver": driver, "docstatus": 0}
    if vml:
        filters["vehicle_movement_log"] = vml

    return frappe.db.get_list(
        "Crate Delivery",
        filters=filters,
        fields=["name", "date", "sales_invoice", "customer", "vehicle_movement_log",
                "crates_delivered", "crates_returned", "invoice_crate_qty"],
        order_by="creation desc"
    )


# =========================================================
# DRIVER — CREATE CRATE DELIVERY
# =========================================================

@frappe.whitelist()
def create_crate_delivery(vml, sales_invoice=None, stock_entry=None, crates_delivered=0, crates_returned=0,
                          latitude=None, longitude=None):
    _require("driver")
    driver = get_logged_in_driver()

    if not sales_invoice and not stock_entry:
        frappe.throw("Either sales_invoice or stock_entry is required.")

    # GPS is required for mobile deliveries
    if latitude in (None, "", 0, "0") or longitude in (None, "", 0, "0"):
        frappe.throw("Location (GPS) is required to record a crate delivery. Please enable location and try again.")

    vml_state = frappe.db.get_value("Vehicle Movement Log", vml, "workflow_state")
    if vml_state != "Submitted":
        frappe.throw(f"Crate Delivery can only be created after the trip is submitted. Current status: {vml_state}")

    if sales_invoice:
        existing = frappe.db.get_value("Crate Delivery", {"sales_invoice": sales_invoice, "docstatus": 1}, "name")
        if existing:
            frappe.throw(f"A Crate Delivery ({existing}) already exists for this invoice.")
        # Draft exists → return it so driver can re-open the OTP screen
        draft = frappe.db.get_value(
            "Crate Delivery",
            {"sales_invoice": sales_invoice, "docstatus": 0},
            ["name", "crates_delivered", "crates_returned", "actual_customer",
             "customer_phone", "otp_phone_override"],
            as_dict=True
        )
        if draft:
            # Refresh the captured GPS on the existing draft
            frappe.db.set_value("Crate Delivery", draft.name, {
                "location_source": "Mobile GPS",
                "delivery_latitude": flt(latitude),
                "delivery_longitude": flt(longitude),
                "location_captured_at": now_datetime(),
            })
            return {
                "status": "success",
                "crate_delivery": draft.name,
                "crates_delivered": flt(draft.crates_delivered),
                "crates_returned": flt(draft.crates_returned),
                "customer_phone": draft.otp_phone_override or draft.customer_phone,
                "customer": draft.actual_customer
            }
    else:
        existing = frappe.db.get_value("Crate Delivery", {"stock_entry": stock_entry, "docstatus": 1}, "name")
        if existing:
            frappe.throw(f"A Crate Delivery ({existing}) already exists for this stock entry.")
        draft = frappe.db.get_value("Crate Delivery", {"stock_entry": stock_entry, "docstatus": 0}, "name")
        if draft:
            frappe.throw(f"A draft Crate Delivery ({draft}) already exists for this stock entry.")

    cd = frappe.new_doc("Crate Delivery")
    cd.vehicle_movement_log = vml
    if sales_invoice:
        cd.sales_invoice = sales_invoice
    if stock_entry:
        cd.stock_entry = stock_entry
    cd.crates_delivered = flt(crates_delivered)
    cd.crates_returned = flt(crates_returned)
    cd.location_source = "Mobile GPS"
    cd.delivery_latitude = flt(latitude)
    cd.delivery_longitude = flt(longitude)
    cd.location_captured_at = now_datetime()
    cd.insert(ignore_permissions=True)

    # Stock entries have no customer to confirm; submit immediately.
    # Invoice deliveries stay as draft until customer OTP is verified.
    if stock_entry:
        cd.submit()

    return {
        "status": "success",
        "crate_delivery": cd.name,
        "crates_delivered": cd.crates_delivered,
        "crates_returned": cd.crates_returned,
        "customer_phone": (cd.otp_phone_override or cd.customer_phone) if sales_invoice else None,
        "customer": cd.actual_customer if sales_invoice else None
    }


@frappe.whitelist()
def confirm_customer_otp(crate_delivery):
    _require("driver")

    if not frappe.db.exists("Crate Delivery", crate_delivery):
        frappe.throw("Crate Delivery not found")

    doc = frappe.get_doc("Crate Delivery", crate_delivery)

    if doc.docstatus != 1:
        frappe.throw("Crate Delivery must be submitted before confirming OTP.")

    if doc.customer_confirmed:
        return {"status": "already_confirmed", "crate_delivery": crate_delivery}

    frappe.db.set_value("Crate Delivery", crate_delivery, "customer_confirmed", 1)

    return {"status": "confirmed", "crate_delivery": crate_delivery}


# =========================================================
# DISPATCH ENDPOINTS
# =========================================================

@frappe.whitelist()
def get_dispatch_vmls(date=None):
    _require("dispatch")
    target_date = date or today()

    return frappe.db.get_list(
        "Vehicle Movement Log",
        filters={
            "date_and_time": ["between", [f"{target_date} 00:00:00", f"{target_date} 23:59:59"]],
            "workflow_state": ["!=", "Cancelled"]
        },
        fields=["name", "date_and_time", "driver", "vehicle", "route", "workflow_state",
                "custom_invoice_crate_balance"],
        order_by="creation desc"
    )


@frappe.whitelist()
def get_dispatch_driver_balances():
    _require("dispatch")

    return frappe.db.get_list(
        "Driver",
        filters={"status": "Active"},
        fields=["name", "full_name", "custom_invoice_crate_balance"]
    )


# =========================================================
# CUSTOMER CRATE ENDPOINTS
# =========================================================

@frappe.whitelist()
def get_customer_crate_balance():
    customer_id = get_logged_in_customer()

    balance = flt(frappe.db.get_value("Customer", customer_id, "custom_current_crate_balance"))
    return {"customer_id": customer_id, "crate_balance": balance}


@frappe.whitelist()
def get_customer_crate_ledger(filter_type="Last 7 Days", start_date=None, end_date=None):
    customer_id = get_logged_in_customer()
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    return frappe.get_all(
        "Customer Crate Ledger",
        filters={
            "customer": customer_id,
            "posting_date": ["between", [from_date, to_date]]
        },
        fields=["name", "posting_date", "creation", "entry_type", "crate_category",
                "crates_out", "crates_in", "balance_crates", "crate_type",
                "sales_invoice", "vehicle_movement_log", "crate_delivery",
                "crate_balance_adjustment"],
        order_by="creation desc",
        ignore_permissions=True
    )


@frappe.whitelist()
def get_driver_crate_ledger(filter_type="Last 30 Days", start_date=None, end_date=None):
    """
    Full crate chain from the driver's perspective:
      - Assigned from plant   (ledger_type=Driver, OUT)
      - Given to customer     (ledger_type=Customer, OUT, driver set)
      - Returned by customer  (ledger_type=Customer, IN,  driver set)
    """
    _require("driver")
    driver = get_logged_in_driver()
    from_date, to_date = get_date_range(filter_type, start_date, end_date)

    rows = frappe.get_all(
        "Customer Crate Ledger",
        filters={
            "driver": driver,
            "posting_date": ["between", [from_date, to_date]]
        },
        fields=["name", "posting_date", "creation", "ledger_type", "entry_type",
                "crate_category", "crates_out", "crates_in", "balance_crates",
                "crate_type", "customer", "sales_invoice", "vehicle_movement_log",
                "crate_delivery"],
        order_by="creation desc",
        ignore_permissions=True
    )

    # Resolve customer names for display
    customer_names = {}
    for r in rows:
        cust = r.get("customer")
        if cust and cust not in customer_names:
            customer_names[cust] = frappe.db.get_value("Customer", cust, "customer_name") or cust
        r["customer_name"] = customer_names.get(cust)

        # Classify the movement for the app
        if r.get("ledger_type") == "Driver":
            r["movement"] = "assigned"       # plant -> driver
        elif r.get("entry_type") == "OUT":
            r["movement"] = "to_customer"    # driver -> customer
        else:
            r["movement"] = "from_customer"  # customer -> driver

    return rows


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
