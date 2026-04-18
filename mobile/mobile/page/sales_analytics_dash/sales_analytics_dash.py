import frappe


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


@frappe.whitelist()
def get_territory_sales(from_date=None, to_date=None):
    return frappe.db.sql("""
        SELECT 
            territory,
            SUM(base_grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND posting_date BETWEEN %s AND %s
        GROUP BY territory
        ORDER BY total DESC
        LIMIT 10
    """, (from_date, to_date), as_dict=True)