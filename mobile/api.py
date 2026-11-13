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
SECURITY_ROLES = {"Security Read Only", "Security Entry"}

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


# Which app home screen(s) a user gets = which "App ..." roles they have. The roles are given to users
# in the ERP (User > Roles); this table only says which screen each role opens.
APP_DASHBOARD_ROLES = {
    "App Admin": "master",
    "App Customer": "customer",
    "App Driver": "driver",
    "App Dispatch": "dispatch",
    "App Production": "production",
    "App Security": "security",
    "App Employee": "employee",
}
APP_DASHBOARD_LABELS = {
    "master": "System Admin", "customer": "Customer", "driver": "Driver", "dispatch": "Dispatch",
    "production": "Production", "security": "Security", "employee": "Employee",
}


def _legacy_dashboard(user):
    """OLD email rule (sanskar.driver@ -> driver ...). Used ONLY for users who have no "App ..." role yet,
    so nobody is locked out during the switch. Remove once every app user has an App role."""
    user_type = DEPARTMENT_MAP.get(_get_department(user), "customer")
    if user_type == "customer" and SECURITY_ROLES.intersection(frappe.get_roles(user)):
        user_type = "security"
    if user_type == "customer":
        try:
            customer_id = get_logged_in_customer()
        except Exception:
            customer_id = None
        if not customer_id and frappe.db.exists("Employee", {"user_id": user, "status": "Active"}):
            user_type = "employee"
    return user_type


def _app_dashboards(user=None):
    """(dashboards, from_roles): the user's app screens from their App roles, else the old email rule."""
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    dashboards = [d for r, d in APP_DASHBOARD_ROLES.items() if r in roles]
    if dashboards:
        return dashboards, True
    return [_legacy_dashboard(user)], False


def _is_master(user=None):
    return "master" in _app_dashboards(user)[0]


def _require(*departments):
    """Allow if the user's app dashboards (from App roles; old email rule as fallback) include one of these,
    or the user is System Admin."""
    if frappe.session.user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)
    dashboards = _app_dashboards()[0]
    if "master" in dashboards or set(departments) & set(dashboards):
        return
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
    """Which home screen(s) to open. `user_type` = the first one (kept for older app versions);
    `dashboards` = all of them: more than one -> the app shows a "Choose dashboard" screen."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)

    full_name = frappe.utils.get_fullname(user)
    dashboards, from_roles = _app_dashboards(user)
    out = {
        "user_type": dashboards[0],
        "dashboards": [{"type": d, "label": APP_DASHBOARD_LABELS.get(d, d.title())} for d in dashboards],
        "from_roles": from_roles,
        "full_name": full_name,
        "email": user,
    }

    if "driver" in dashboards:
        driver = frappe.db.get_value("Driver", {"custom_user": user}, ["name", "full_name"], as_dict=True)
        out["driver_id"] = driver.name if driver else None
        out["driver_name"] = driver.full_name if driver else full_name

    if "customer" in dashboards:
        try:
            out["customer_id"] = get_logged_in_customer()
        except Exception:
            out["customer_id"] = None

    if "employee" in dashboards:
        employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"},
                                       ["name", "employee_name", "department", "designation"], as_dict=True)
        if employee:
            out.update({
                "employee_id": employee.name,
                "department": employee.department,
                "designation": employee.designation,
            })
            if dashboards[0] == "employee":
                out["full_name"] = employee.employee_name or full_name

    return out


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

    # Drivers can only view their own VML (dispatch and System Admin see all)
    if not ({"dispatch", "master"} & set(_app_dashboards()[0])):
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


def _default_company():
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )


# =========================================================
# COMPLAINTS & FEEDBACK (Customer Complaint, dairy app)
# =========================================================
# Access comes ONLY from roles (Role Permission Manager on Customer Complaint): nothing here bypasses
# permissions. Remove the role from a user and the app's complaint screens stop working for them.
# On top of the role, results are narrowed to the caller's own complaints (never widened).

COMPLAINT_DT = "Customer Complaint"
COMPLAINT_PAGE = 20
COMPLAINT_MAX_UPLOAD_MB = 10  # one photo
COMPLAINT_MAX_VIDEO_MB = 20  # one video (the app records max 30 s, low quality)
COMPLAINT_MAX_PHOTOS = 5
COMPLAINT_MAX_VIDEOS = 1
COMPLAINT_MAX_ITEMS = 20
COMPLAINT_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "heic"}
COMPLAINT_VIDEO_EXT = {"mp4", "mov", "3gp"}
# What the raiser sees: approvals are internal, so they read as "In Progress".
COMPLAINT_STATUS_LABEL = {
    "Open": "Registered",
    "Assigned": "In Progress",
    "Pending Approval": "In Progress",
    "Accounts Approval": "In Progress",
    "Resolved": "Resolved",
    "Closed": "Closed",
    "Rejected": "Rejected",
}
COMPLAINT_OPEN_STATES = ("Open", "Assigned", "Pending Approval", "Accounts Approval")
COMPLAINT_CUSTOMER_TYPE = {"Franchise": "Franchise", "Sub Franchise": "Sub-Franchise", "Line Customer": "Line Customer"}


def _complaint_identity(as_=None):
    """Customer (Portal User) or Employee (Employee.user_id). as_ lets IT/MD test either side."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)
    # who-am-I takes 3-4 lookups and never changes mid-session: cache it for 10 minutes
    key = f"mobile_complaint_identity:{user}"
    links = frappe.cache.get_value(key, expires=True)
    if links is None:
        try:
            customer = get_logged_in_customer()
        except Exception:
            customer = None
        if customer and frappe.db.get_value("Customer", customer, "disabled"):
            customer = None  # a disabled customer link must not turn staff into a "customer"
        employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"},
                                       ["name", "employee_name"], as_dict=True)
        links = {"customer": customer, "employee": dict(employee) if employee else None}
        frappe.cache.set_value(key, links, expires_in_sec=600)
    customer = links["customer"]
    employee = frappe._dict(links["employee"]) if links["employee"] else None
    # the app sends as_ from the dashboard it was opened on (Customer dashboard -> Customer, staff dashboards -> Employee)
    kind = as_ if as_ in ("Customer", "Employee") else ("Customer" if customer else "Employee" if employee else None)
    if kind == "Customer" and not customer:
        frappe.throw("Your login is not linked to a customer. Please contact Bastar Dairy.", frappe.PermissionError)
    if kind == "Employee" and not employee:
        frappe.throw("Your login is not linked to an employee record. Please contact HR.", frappe.PermissionError)
    if not kind:
        frappe.throw("Your login is not linked to a customer or employee. Please contact support.", frappe.PermissionError)
    return frappe._dict(user=user, kind=kind, customer=customer,
                        employee=employee.name if employee else None,
                        employee_name=employee.employee_name if employee else None)


def _complaint_need(ptype, doc=None):
    if not frappe.has_permission(COMPLAINT_DT, ptype, doc=doc):
        frappe.throw("You don't have access to complaints. Please contact Bastar Dairy.", frappe.PermissionError)


def _complaint_own_filters(me):
    """A customer sees complaints about their customer; staff see the ones they raised."""
    if me.kind == "Customer":
        return {"complaint_from": "Customer", "customer_id": me.customer}
    return {"complaint_from": "Employee", "employee": me.employee}


def _complaint_get_own(name, me, fields, ptype="read"):
    _complaint_need("read")
    # get_list = the user's permissions apply; the own-filter only narrows it further
    rows = frappe.get_list(COMPLAINT_DT, filters=dict(_complaint_own_filters(me), name=name), fields=fields, limit_page_length=1)
    if not rows:
        frappe.throw("Complaint not found", frappe.DoesNotExistError)
    if ptype != "read":
        _complaint_need(ptype, doc=name)
    return rows[0]


def _complaint_options(fieldname):
    return [o for o in (frappe.get_meta(COMPLAINT_DT).get_field(fieldname).options or "").split("\n") if o]


def _complaint_departments():
    filters = {"is_group": 0, "disabled": 0}
    company = _default_company()
    if company:
        filters["company"] = company
    return frappe.get_all("Department", filters=filters, pluck="name", order_by="department_name")


@frappe.whitelist()
def get_complaint_options(as_=None):
    """Everything the 'New complaint' screen needs, in one call."""
    me = _complaint_identity(as_)
    _complaint_need("read")
    out = {
        "can_create": bool(frappe.has_permission(COMPLAINT_DT, "create")),
        "who": me.kind,
        "name": frappe.db.get_value("Customer", me.customer, "customer_name") if me.kind == "Customer" else me.employee_name,
        "entry_types": _complaint_options("entry_type"),
        "severities": ["Minor", "Major", "Critical"],
        "limits": {"photos": COMPLAINT_MAX_PHOTOS, "videos": COMPLAINT_MAX_VIDEOS, "video_mb": COMPLAINT_MAX_VIDEO_MB,
                   "video_seconds": 30, "items": COMPLAINT_MAX_ITEMS},
    }
    if me.kind == "Customer":
        out["complaint_types"] = _complaint_options("complaint_type")
        out["preferred_resolutions"] = _complaint_options("preferred_resolution")
    else:
        out["internal_types"] = _complaint_options("internal_type")
        # departments rarely change: cache for an hour instead of querying on every form open
        out["departments"] = _cached_departments()
    return out


def _cached_departments():
    key = "mobile_complaint_departments"
    rows = frappe.cache.get_value(key, expires=True)
    if rows is None:
        rows = _complaint_departments()
        frappe.cache.set_value(key, rows, expires_in_sec=3600)
    return rows


@frappe.whitelist()
def search_complaint_items(txt=""):
    """Product picker for the complaint form: item code + name only, 20 at a time."""
    _complaint_identity()
    _complaint_need("create")
    or_filters = None
    if txt:
        like = ["like", f"%{txt}%"]
        or_filters = {"item_name": like, "name": like}
    return frappe.get_all("Item", filters={"disabled": 0, "is_sales_item": 1, "has_variants": 0},
                          or_filters=or_filters, fields=["name as item_code", "item_name"],
                          order_by="item_name", limit_page_length=20)


def _complaint_short_address(address_name):
    if not address_name:
        return None
    a = frappe.db.get_value("Address", address_name, ["address_line1", "city"], as_dict=True)
    return ", ".join(filter(None, [a.address_line1, a.city]))[:140] if a else None


@frappe.whitelist(methods=["POST"])
def create_complaint(data, as_=None):
    me = _complaint_identity(as_)
    _complaint_need("create")
    data = frappe._dict(frappe.parse_json(data) or {})
    entry_type = data.entry_type if data.entry_type in _complaint_options("entry_type") else "Complaint"
    is_complaint = entry_type == "Complaint"

    def pick(key, field):
        return data.get(key) if data.get(key) in _complaint_options(field) else None

    doc = frappe.new_doc(COMPLAINT_DT)
    doc.update({
        "entry_type": entry_type,
        "complaint_from": me.kind,
        "source": "Mobile App",
        "date_of_complaint": today(),
        "description_of_issue": (data.description or "").strip()[:2000] or None,
        "severity_level": pick("severity", "severity_level") or ("Major" if is_complaint else None),
    })
    if entry_type == "Feedback" and data.get("rating") is not None:
        doc.rating = max(0.0, min(1.0, flt(data.rating) / 5.0))  # app sends 1-5 stars

    if me.kind == "Customer":
        c = frappe.db.get_value("Customer", me.customer, [
            "customer_name", "customer_group", "mobile_no", "custom_route_master", "territory", "customer_primary_address",
        ], as_dict=True)
        doc.update({
            "customer_id": me.customer,
            "name_of_a_customer": c.customer_name,
            "type_of_customer": COMPLAINT_CUSTOMER_TYPE.get(c.customer_group, "Other"),
            "route": c.custom_route_master,
            "contact_no": c.mobile_no or frappe.db.get_value("User", me.user, "mobile_no"),
            "address": _complaint_short_address(c.customer_primary_address) or c.territory,
        })
        if is_complaint:
            # items: [{item_code, qty, batch_no}]; older app versions send one item_code + batch_no
            raw = data.get("items") or ([{"item_code": data.item_code, "batch_no": data.batch_no}] if data.item_code else [])
            items, seen = [], set()
            for r in raw[:COMPLAINT_MAX_ITEMS]:
                r = frappe._dict(r or {})
                if not r.item_code or r.item_code in seen:
                    continue
                if not frappe.db.exists("Item", r.item_code):
                    frappe.throw(f"Product {r.item_code} not found")
                seen.add(r.item_code)
                items.append({
                    "item_code": r.item_code,
                    "qty": max(flt(r.qty) or 1, 0),
                    "batch_no": (r.batch_no or "").strip()[:140] or None,
                })
            if not items:
                frappe.throw("Please select the product")
            complaint_type = pick("complaint_type", "complaint_type")
            if not complaint_type:
                frappe.throw("Please select the problem type")
            doc.set("items", items)  # the doctype copies the first row to item_code / batch
            doc.update({
                "complaint_type": complaint_type,
                "preferred_resolution": pick("preferred_resolution", "preferred_resolution") or "Other",
                "purchase_date": getdate(data.purchase_date) if data.purchase_date else getdate(today()),
            })
    else:
        doc.update({
            "employee": me.employee,
            "confidential": frappe.utils.cint(data.confidential),
            "against_department": data.against_department
            if data.against_department and frappe.db.exists("Department", data.against_department) else None,
        })
        if is_complaint:
            internal_type = pick("internal_type", "internal_type")
            if not internal_type:
                frappe.throw("Please select the complaint type")
            doc.internal_type = internal_type

    if not is_complaint and not doc.description_of_issue:
        frappe.throw(f"Please write your {entry_type.lower()}")

    doc.insert()  # normal permission check: needs Create on Customer Complaint
    return {"status": "success", "name": doc.name, "status_label": COMPLAINT_STATUS_LABEL.get(doc.status, doc.status)}


@frappe.whitelist(methods=["POST"])
def upload_complaint_file(name, as_=None):
    """Multipart upload (field 'file') right after creating, one file per call.
    Up to 5 photos + 1 video. The first photo also goes in 'attachment', the video in 'attachment_video';
    the rest are normal attachments of the complaint."""
    me = _complaint_identity(as_)
    row = _complaint_get_own(name, me, ["name", "status", "owner"], ptype="write")
    if row.owner != me.user or row.status not in ("Open", "Assigned"):
        frappe.throw("You can add photos only to a new complaint you raised")
    f = frappe.request.files.get("file") if frappe.request and frappe.request.files else None
    if not f or not f.filename:
        frappe.throw("No file received")
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in COMPLAINT_IMAGE_EXT | COMPLAINT_VIDEO_EXT:
        frappe.throw("Only photos (jpg, png) or videos (mp4) can be attached")
    is_video = ext in COMPLAINT_VIDEO_EXT
    max_mb = COMPLAINT_MAX_VIDEO_MB if is_video else COMPLAINT_MAX_UPLOAD_MB
    limit = max_mb * 1024 * 1024
    content = f.stream.read(limit + 1)
    if len(content) > limit:
        frappe.throw(f"{'Video' if is_video else 'Photo'} is larger than {max_mb} MB")
    have = _complaint_media_counts([name]).get(name, {"photos": 0, "videos": 0})
    if is_video and have["videos"] >= COMPLAINT_MAX_VIDEOS:
        frappe.throw(f"Only {COMPLAINT_MAX_VIDEOS} video can be added")
    if not is_video and have["photos"] >= COMPLAINT_MAX_PHOTOS:
        frappe.throw(f"Only {COMPLAINT_MAX_PHOTOS} photos can be added")
    field = "attachment_video" if is_video else "attachment"
    first = (have["videos"] if is_video else have["photos"]) == 0
    try:
        file_doc = frappe.get_doc({
            "doctype": "File", "file_name": f.filename, "attached_to_doctype": COMPLAINT_DT,
            "attached_to_name": name, "attached_to_field": field if first else None, "is_private": 1, "content": content,
        }).insert()  # Frappe checks Write on the complaint it is attached to
    except Exception:
        # e.g. a corrupt photo (Frappe opens images to strip EXIF / location data)
        frappe.log_error("Complaint upload failed", reference_doctype=COMPLAINT_DT, reference_name=name)
        frappe.throw("This file could not be read. Please take the photo again.")
    if first:
        frappe.get_doc(COMPLAINT_DT, name).db_set(field, file_doc.file_url, update_modified=False)
    return {"status": "success", "field": field if first else None}


def _complaint_media_counts(names):
    """{complaint: {photos, videos}} from the files attached to these complaints (names already permission-checked)."""
    out = {n: {"photos": 0, "videos": 0} for n in names}
    if not names:
        return out
    rows = frappe.get_all("File", filters={"attached_to_doctype": COMPLAINT_DT, "attached_to_name": ["in", names]},
                          fields=["attached_to_name", "file_name"])
    for r in rows:
        ext = (r.file_name or "").rsplit(".", 1)[-1].lower()
        if ext in COMPLAINT_VIDEO_EXT:
            out[r.attached_to_name]["videos"] += 1
        elif ext in COMPLAINT_IMAGE_EXT:
            out[r.attached_to_name]["photos"] += 1
    return out


def _complaint_items(names):
    """{complaint: [{item_code, item_name, qty, batch_no}]} read through the complaint's own permissions."""
    out = {n: [] for n in names}
    if not names:
        return out
    rows = frappe.get_list(COMPLAINT_DT, filters={"name": ["in", names]}, fields=[
        "name", "`tabCustomer Complaint Item`.item_code as item_code", "`tabCustomer Complaint Item`.item_name as item_name",
        "`tabCustomer Complaint Item`.qty as qty", "`tabCustomer Complaint Item`.batch_no as batch_no",
        "`tabCustomer Complaint Item`.idx as idx",
    ], order_by="`tabCustomer Complaint Item`.idx asc", limit_page_length=0)
    for r in rows:
        if r.item_code:
            out[r.name].append({"item_code": r.item_code, "item_name": r.item_name, "qty": flt(r.qty), "batch_no": r.batch_no})
    return out


@frappe.whitelist()
def get_my_complaints(scope="open", start=0, as_=None):
    """scope: open | all. 20 per page, newest first."""
    me = _complaint_identity(as_)
    _complaint_need("read")
    filters = _complaint_own_filters(me)
    if scope == "open":
        filters["status"] = ["in", COMPLAINT_OPEN_STATES]
    rows = frappe.get_list(
        COMPLAINT_DT, filters=filters,
        fields=["name", "entry_type", "status", "date_of_complaint", "complaint_type", "internal_type", "item_name"],
        order_by="date_of_complaint desc, creation desc",
        start=frappe.utils.cint(start), page_length=COMPLAINT_PAGE,
    )
    items = _complaint_items([r.name for r in rows]) if me.kind == "Customer" else {}
    out = []
    for r in rows:
        extra = len(items.get(r.name) or []) - 1
        out.append({
            "name": r.name,
            "entry_type": r.entry_type,
            "title": r.internal_type if me.kind == "Employee" else (r.complaint_type or r.entry_type),
            "item_name": f"{r.item_name} +{extra} more" if r.item_name and extra > 0 else r.item_name,
            "status": r.status,
            "status_label": COMPLAINT_STATUS_LABEL.get(r.status, r.status),
            "date": str(r.date_of_complaint),
        })
    res = {"rows": out, "has_more": len(rows) == COMPLAINT_PAGE}
    if not frappe.utils.cint(start):
        # header counts, first page only: one grouped query, same permissions + own-filter
        by = frappe.get_list(COMPLAINT_DT, filters=_complaint_own_filters(me),
                             fields=["status", "count(name) as n"], group_by="status", order_by=None)
        n = {r.status: r.n for r in by}
        res["counts"] = {
            "open": sum(n.get(s, 0) for s in COMPLAINT_OPEN_STATES),
            "resolved": n.get("Resolved", 0) + n.get("Closed", 0),
            "total": sum(n.values()),
        }
    return res


@frappe.whitelist()
def get_my_complaint(name, as_=None):
    me = _complaint_identity(as_)
    d = _complaint_get_own(name, me, [
        "name", "entry_type", "status", "date_of_complaint", "creation", "complaint_type", "internal_type",
        "item_name", "data_kxgv", "purchase_date", "severity_level", "preferred_resolution", "description_of_issue",
        "against_department", "confidential", "rating", "attachment", "attachment_video", "assigned_on",
        "resolved_on", "approved_on", "closed_on", "action_taken", "resolution_type", "approver_remarks",
        "customer_satisfied", "closing_remarks",
    ])
    done = d.status in ("Resolved", "Closed")
    timeline = [{"label": "Registered", "on": str(d.creation)}]
    if d.assigned_on:
        timeline.append({"label": "In Progress", "on": str(d.assigned_on)})
    if done:
        timeline.append({"label": "Resolved", "on": str(d.approved_on or d.resolved_on or "")})
    if d.status == "Closed" and d.closed_on:
        timeline.append({"label": "Closed", "on": str(d.closed_on)})
    if d.status == "Rejected":
        timeline.append({"label": "Rejected", "on": str(d.closed_on or "")})
    return {
        "name": d.name, "entry_type": d.entry_type, "status": d.status,
        "status_label": COMPLAINT_STATUS_LABEL.get(d.status, d.status),
        "title": d.internal_type if me.kind == "Employee" else (d.complaint_type or d.entry_type),
        "date": str(d.date_of_complaint), "item_name": d.item_name, "batch_no": d.data_kxgv,
        "purchase_date": str(d.purchase_date) if d.purchase_date else None, "severity": d.severity_level,
        "preferred_resolution": d.preferred_resolution, "description": d.description_of_issue,
        "against_department": d.against_department, "confidential": frappe.utils.cint(d.confidential),
        "rating": round((d.rating or 0) * 5) if d.entry_type == "Feedback" else None,
        "has_photo": bool(d.attachment), "has_video": bool(d.attachment_video),
        "items": _complaint_items([d.name])[d.name] or (
            [{"item_code": None, "item_name": d.item_name, "qty": None, "batch_no": d.data_kxgv}] if d.item_name else []),
        "media": _complaint_media_counts([d.name])[d.name],
        "timeline": timeline,
        # the fix is shown once approved; internal approval notes never are
        "action_taken": d.action_taken if done else None,
        "resolution_type": d.resolution_type if done else None,
        "rejection_reason": d.approver_remarks if d.status == "Rejected" else None,
        "customer_satisfied": d.customer_satisfied, "closing_remarks": d.closing_remarks,
        "can_rate": done and d.entry_type == "Complaint" and not d.customer_satisfied,
    }


@frappe.whitelist(methods=["POST"])
def rate_complaint_resolution(name, satisfied, remarks=None, as_=None):
    """Raiser says whether the fix worked. Status/workflow untouched; the team sees it as a comment."""
    me = _complaint_identity(as_)
    d = _complaint_get_own(name, me, ["name", "status", "customer_satisfied"], ptype="write")
    if d.status not in ("Resolved", "Closed") or d.customer_satisfied:
        frappe.throw("This complaint can't be rated now")
    ok = str(satisfied).lower() in ("1", "yes", "true")
    remarks = (remarks or "").strip()[:500] or None
    values = {"customer_satisfied": "Yes" if ok else "No", "closing_remarks": remarks}
    if not ok:
        values["follow_up_required"] = 1
    doc = frappe.get_doc(COMPLAINT_DT, name)
    doc.db_set(values)
    doc.add_comment("Comment", ("Satisfied" if ok else "NOT satisfied") + " (via app)" + (f": {remarks}" if remarks else ""))
    if not ok and doc.assigned_user:
        doc.assign_user(doc.assigned_user, f"Customer not satisfied: {doc.title_text()}")
    from dairy.customer_service.doctype.customer_complaint.customer_complaint import notify_counters
    notify_counters()
    return {"status": "success"}


# =========================================================
# EMPLOYEE HOME: TODAY + ATTENDANCE (own records only)
# =========================================================
# Access comes from roles + the employee's User Permission on their own Employee record:
# frappe.get_list only returns what the user may read. A section the user may not read comes back
# with "access": False so the app can say "ask HR" instead of failing.

ATTENDANCE_STATUSES = ("Present", "Absent", "Half Day", "On Leave", "Work From Home")


def _my_employee():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Please login first", frappe.PermissionError)
    emp = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"},
                              ["name", "employee_name", "default_shift", "company"], as_dict=True)
    if not emp:
        frappe.throw("Your login is not linked to an employee record. Please contact HR.", frappe.PermissionError)
    return emp


def _hhmm(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}"


@frappe.whitelist()
def get_my_attendance(month=None):
    """month = 'YYYY-MM' (default: this month). Returns today's shift + punches and the month's attendance."""
    from frappe.utils import get_datetime, get_time, now_datetime, getdate as _gd
    emp = _my_employee()
    today_d = _gd(today())
    first = _gd(f"{month}-01") if month else today_d.replace(day=1)
    last = get_last_day(first)

    # --- today's shift: active Shift Assignment, else the employee's default shift
    shift_name = None
    if frappe.has_permission("Shift Assignment", "read"):
        sa = frappe.get_list("Shift Assignment", filters={
            "employee": emp.name, "docstatus": 1, "status": "Active", "start_date": ["<=", today_d],
        }, or_filters=[["end_date", "is", "not set"], ["end_date", ">=", today_d]],
            fields=["shift_type", "end_date"], order_by="start_date desc", limit_page_length=1)
        shift_name = sa[0].shift_type if sa else None
    shift_name = shift_name or emp.default_shift
    shift = None
    if shift_name and frappe.has_permission("Shift Type", "read"):
        st = frappe.get_list("Shift Type", filters={"name": shift_name}, fields=["name", "start_time", "end_time"], limit_page_length=1)
        if st:
            shift = {"name": st[0].name, "start": get_time(st[0].start_time).strftime("%H:%M"),
                     "end": get_time(st[0].end_time).strftime("%H:%M")}

    # --- today's punches
    can_checkin = bool(frappe.has_permission("Employee Checkin", "read"))
    punches = []
    if can_checkin:
        punches = frappe.get_list("Employee Checkin", filters={
            "employee": emp.name, "time": ["between", [f"{today_d} 00:00:00", f"{today_d} 23:59:59"]],
        }, fields=["time", "log_type"], order_by="time asc", limit_page_length=50)
    first_in = punches[0].time if punches else None
    last_out = punches[-1].time if len(punches) > 1 else None
    worked = None
    if first_in:
        end = last_out or (now_datetime() if today_d == _gd(today()) else None)
        if end:
            worked = _hhmm((get_datetime(end) - get_datetime(first_in)).total_seconds())

    # --- the month's attendance
    can_att = bool(frappe.has_permission("Attendance", "read"))
    days, counts, late, early = [], {s: 0 for s in ATTENDANCE_STATUSES}, 0, 0
    today_status = None
    if can_att:
        rows = frappe.get_list("Attendance", filters={
            "employee": emp.name, "docstatus": 1, "attendance_date": ["between", [first, last]],
        }, fields=["attendance_date", "status", "in_time", "out_time", "late_entry", "early_exit", "working_hours", "leave_type"],
            order_by="attendance_date asc", limit_page_length=0)
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
            late += 1 if r.late_entry else 0
            early += 1 if r.early_exit else 0
            if r.attendance_date == today_d:
                today_status = r.status
            days.append({
                "date": str(r.attendance_date), "status": r.status, "late": bool(r.late_entry), "early": bool(r.early_exit),
                "in": get_time(r.in_time).strftime("%H:%M") if r.in_time else None,
                "out": get_time(r.out_time).strftime("%H:%M") if r.out_time else None,
                "hours": round(r.working_hours or 0, 1), "leave_type": r.leave_type,
            })

    return {
        "employee": emp.name,
        "today": {
            "date": str(today_d),
            "shift": shift,
            "access": can_checkin,
            "first_in": get_datetime(first_in).strftime("%H:%M") if first_in else None,
            "last_out": get_datetime(last_out).strftime("%H:%M") if last_out else None,
            "punches": len(punches),
            "worked": worked,
            "status": today_status,
        },
        "month": {
            "month": first.strftime("%Y-%m"),
            "label": first.strftime("%B %Y"),
            "access": can_att,
            "counts": counts,
            "late": late,
            "early_exit": early,
            "marked_days": len(days),
            "days": days,
        },
    }


# =========================================================
# SYSTEM ADMIN DASHBOARD: TODAY AT A GLANCE
# =========================================================
# Only for users whose App roles include "App Admin". Every block is read with the admin's OWN permissions
# (frappe.get_list); a block they can't read comes back with "access": False, never bypassed.

def _admin_block(fn):
    try:
        return dict(fn(), access=True)
    except frappe.PermissionError:
        frappe.clear_last_message()
        return {"access": False}


@frappe.whitelist()
def get_admin_overview():
    _require()  # no department passes except System Admin (App Admin role)
    day = today()
    company = _default_company()
    co = {"company": company} if company else {}

    def sales_orders():
        r = frappe.get_list("Sales Order", filters=dict(co, docstatus=1, transaction_date=day),
                            fields=["count(name) as n", "sum(base_grand_total) as total"], limit_page_length=1)[0]
        return {"count": int(r.n or 0), "total": flt(r.total)}

    def sales_invoices():
        r = frappe.get_list("Sales Invoice", filters=dict(co, docstatus=1, posting_date=day, is_return=0),
                            fields=["count(name) as n", "sum(base_grand_total) as total"], limit_page_length=1)[0]
        return {"count": int(r.n or 0), "total": flt(r.total)}

    def attendance():
        rows = frappe.get_list("Attendance", filters=dict(co, docstatus=1, attendance_date=day),
                               fields=["status", "count(name) as n"], group_by="status", limit_page_length=0)
        by = {r.status: int(r.n) for r in rows}
        return {"present": by.get("Present", 0) + by.get("Work From Home", 0), "absent": by.get("Absent", 0),
                "half_day": by.get("Half Day", 0), "on_leave": by.get("On Leave", 0), "marked": sum(by.values())}

    def complaints():
        from dairy.customer_service.doctype.customer_complaint.customer_complaint import get_list_counters
        c = get_list_counters()
        out = {k: c.get(k, 0) for k in ("today", "open", "in_process", "approval", "overdue")}
        # pending (not yet resolved) by who raised it: Customer / Employee / Farmer / Vendor / Other
        rows = frappe.get_list("Customer Complaint", filters={"status": ["in", ADMIN_PENDING_STATES]},
                               fields=["complaint_from", "count(name) as n"], group_by="complaint_from", limit_page_length=0)
        out["by_group"] = {r.complaint_from or "Customer": int(r.n) for r in rows}
        return out

    return {
        "date": day,
        "company": company,
        "sales_orders": _admin_block(sales_orders),
        "sales_invoices": _admin_block(sales_invoices),
        "attendance": _admin_block(attendance),
        "complaints": _admin_block(complaints),
    }


# ---------------------------------------------------------- System Admin: complaints across all groups
# Read-only management view; actions (assign, approve, close) stay in the ERP. Admin's own permissions apply.
ADMIN_PENDING_STATES = ("Open", "Assigned", "Pending Approval", "Accounts Approval")
ADMIN_COMPLAINT_GROUPS = ("Customer", "Employee", "Farmer", "Vendor", "Other")
ADMIN_COMPLAINT_FIELDS = [
    "name", "complaint_from", "entry_type", "raised_by_name", "complaint_type", "internal_type", "issue_type",
    "status", "severity_level", "date_of_complaint", "due_date", "assigned_user", "department", "item_name",
    "description_of_issue", "source", "route", "dcs",
]


def _admin_complaint_row(r):
    today_d = getdate(today())
    issue = {"Employee": r.internal_type, "Customer": r.complaint_type}.get(r.complaint_from, r.issue_type)
    pending = r.status in ("Open", "Assigned")
    return {
        "name": r.name, "group": r.complaint_from or "Customer", "entry_type": r.entry_type,
        "raised_by": r.raised_by_name, "issue": issue or r.entry_type, "status": r.status,
        "severity": r.severity_level, "date": str(r.date_of_complaint) if r.date_of_complaint else None,
        "due": str(r.due_date) if r.due_date else None,
        "overdue": bool(pending and r.due_date and getdate(r.due_date) < today_d),
        "assigned": frappe.utils.get_fullname(r.assigned_user) if r.assigned_user else None,
        "department": r.department, "item": r.item_name, "source": r.source,
        "place": r.route or r.dcs,
        "description": (r.description_of_issue or "")[:160],
    }


@frappe.whitelist()
def get_admin_complaints(group=None, scope="open", search=None, start=0):
    """scope: open (not yet resolved) | overdue | all. 20 per page, overdue first then newest."""
    _require()
    filters = {}
    if group in ADMIN_COMPLAINT_GROUPS:
        filters["complaint_from"] = group
    if scope == "open":
        filters["status"] = ["in", ADMIN_PENDING_STATES]
    elif scope == "overdue":
        filters["status"] = ["in", ("Open", "Assigned")]
        filters["due_date"] = ["<", today()]
    or_filters = None
    if search:
        like = ["like", f"%{search.strip()}%"]
        or_filters = {"name": like, "raised_by_name": like, "complaint_id": like, "item_name": like, "description_of_issue": like}
    rows = frappe.get_list("Customer Complaint", filters=filters, or_filters=or_filters, fields=ADMIN_COMPLAINT_FIELDS,
                           order_by="date_of_complaint desc, creation desc", start=frappe.utils.cint(start), page_length=20)
    return {"rows": [_admin_complaint_row(r) for r in rows], "has_more": len(rows) == 20}


@frappe.whitelist()
def get_admin_complaint(name):
    _require()
    rows = frappe.get_list("Customer Complaint", filters={"name": name}, fields=ADMIN_COMPLAINT_FIELDS + [
        "contact_no", "complaint_id", "supplier_name", "employee_name", "against_department", "confidential",
        "creation", "assigned_on", "resolved_on", "approved_on", "closed_on", "action_taken", "resolution_type",
        "root_cause", "approver_remarks", "customer_satisfied", "closing_remarks", "escalated", "resolution_hours",
    ], limit_page_length=1)
    if not rows:
        frappe.throw("Complaint not found", frappe.DoesNotExistError)
    r = rows[0]
    out = _admin_complaint_row(r)
    out["description"] = r.description_of_issue
    timeline = [{"label": "Registered", "on": str(r.creation)}]
    for label, field in (("Assigned", "assigned_on"), ("Resolution submitted", "resolved_on"),
                         ("Approved", "approved_on"), ("Closed", "closed_on")):
        if r.get(field):
            timeline.append({"label": label, "on": str(r.get(field))})
    out.update({
        "contact": r.contact_no, "complaint_id": r.complaint_id, "confidential": frappe.utils.cint(r.confidential),
        "against_department": r.against_department, "escalated": frappe.utils.cint(r.escalated),
        "action_taken": r.action_taken, "resolution_type": r.resolution_type, "root_cause": r.root_cause,
        "approver_remarks": r.approver_remarks, "customer_satisfied": r.customer_satisfied,
        "closing_remarks": r.closing_remarks, "resolution_hours": r.resolution_hours, "timeline": timeline,
    })
    return out
