import frappe
from datetime import datetime, timedelta


# =========================
# SALES TREND (UNCHANGED)
# =========================
@frappe.whitelist()
def get_sales_trend(from_date=None, to_date=None, period=None):

    if period == "Weekly":
        group_by = "YEARWEEK(posting_date)"
        label = "YEARWEEK(posting_date)"

    elif period == "Monthly":
        group_by = "DATE_FORMAT(posting_date, '%%Y-%%m')"
        label = "DATE_FORMAT(posting_date, '%%b %%Y')"

    elif period == "Quarterly":
        group_by = "QUARTER(posting_date)"
        label = "CONCAT('Q', QUARTER(posting_date))"

    elif period == "Yearly":
        group_by = "YEAR(posting_date)"
        label = "YEAR(posting_date)"

    else:
        group_by = "DATE(posting_date)"
        label = "DATE(posting_date)"

    return frappe.db.sql(f"""
        SELECT 
            {label} as label,
            SUM(base_grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND posting_date BETWEEN %s AND %s
        GROUP BY {group_by}
        ORDER BY posting_date
    """, (from_date, to_date), as_dict=True)


# =========================
# TOP CUSTOMERS (UNCHANGED)
# =========================
@frappe.whitelist()
def get_top_customers(from_date=None, to_date=None):
    return frappe.db.sql("""
        SELECT 
            customer,
            customer_name,
            SUM(base_grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND posting_date BETWEEN %s AND %s
        GROUP BY customer, customer_name
        ORDER BY total DESC
        LIMIT 10
    """, (from_date, to_date), as_dict=True)


# =========================
# TERRITORY WITH GROWTH (NEW LOGIC)
# =========================
@frappe.whitelist()
def get_territory_sales(from_date=None, to_date=None):

    # convert to date
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    # calculate previous period
    diff = (to_dt - from_dt).days

    prev_from = from_dt - timedelta(days=diff)
    prev_to = to_dt - timedelta(days=diff)

    # current period
    current = frappe.db.sql("""
        SELECT 
            territory,
            SUM(base_grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND posting_date BETWEEN %s AND %s
        GROUP BY territory
    """, (from_date, to_date), as_dict=True)

    # previous period
    previous = frappe.db.sql("""
        SELECT 
            territory,
            SUM(base_grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND posting_date BETWEEN %s AND %s
        GROUP BY territory
    """, (prev_from, prev_to), as_dict=True)

    # map previous
    prev_map = {d.territory: d.total for d in previous}

    result = []

    for row in current:
        prev_total = prev_map.get(row.territory, 0)

        if prev_total:
            growth = ((row.total - prev_total) / prev_total) * 100
        else:
            growth = 100 if row.total else 0

        result.append({
            "territory": row.territory,
            "total": row.total,
            "growth": round(growth, 2)
        })

    # sort by total
    result.sort(key=lambda x: x["total"], reverse=True)

    return result