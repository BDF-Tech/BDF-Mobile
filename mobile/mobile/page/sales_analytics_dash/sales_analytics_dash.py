import frappe
import json
from datetime import datetime, timedelta

def _get_filter_query(company, customer_group, item_group, sort_by="Value"):
    conditions = ["si.docstatus = 1"]
    values = {}
    join_clause = ""
    amount_field = "si.base_grand_total"

    if company:
        conditions.append("si.company = %(company)s")
        values["company"] = company

    if customer_group:
        conditions.append("si.customer_group = %(customer_group)s")
        values["customer_group"] = customer_group

    if item_group or sort_by == "Quantity":
        join_clause = "JOIN `tabSales Invoice Item` sii ON sii.parent = si.name"
        amount_field = "sii.base_amount"
        if item_group:
            conditions.append("sii.item_group = %(item_group)s")
            values["item_group"] = item_group

    return " AND ".join(conditions), values, join_clause, amount_field


def get_top_customers(from_date=None, to_date=None, company=None, customer_group=None, item_group=None, ranking="Top 10", sort_by="Value"):
    base_where, values, join_clause, amount_field = _get_filter_query(company, customer_group, item_group, sort_by)
    
    values["from_date"] = from_date
    values["to_date"] = to_date
    where_clause = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    
    qty_select = "SUM(sii.stock_qty) as total_qty," if "sii" in join_clause else "0 as total_qty,"
    sort_field = "total_qty" if sort_by == "Quantity" else "total"
    
    order_by = "ASC" if ranking == "Lowest 10" else "DESC"
    limit_clause = "" if ranking == "All" else "LIMIT 10"

    return frappe.db.sql(f"""
        SELECT 
            si.customer,
            si.customer_name,
            {qty_select}
            SUM({amount_field}) as total
        FROM `tabSales Invoice` si
        {join_clause}
        WHERE {where_clause}
        GROUP BY si.customer, si.customer_name
        ORDER BY {sort_field} {order_by}
        {limit_clause}
    """, values, as_dict=True)


def get_top_items(from_date=None, to_date=None, company=None, customer_group=None, item_group=None, ranking="Top 10", sort_by="Value"):
    base_where, values, join_clause, _ = _get_filter_query(company, customer_group, item_group, sort_by)
    
    if not join_clause:
        join_clause = "JOIN `tabSales Invoice Item` sii ON sii.parent = si.name"
    
    join_clause += " JOIN `tabItem` i ON i.name = sii.item_code"
    base_where += " AND i.is_sales_item = 1"
    
    amount_field = "sii.base_amount"
    values["from_date"] = from_date
    values["to_date"] = to_date
    where_clause = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    
    sort_field = "total_qty" if sort_by == "Quantity" else "total"
    order_by = "ASC" if ranking == "Lowest 10" else "DESC"
    limit_clause = "" if ranking == "All" else "LIMIT 10"

    return frappe.db.sql(f"""
        SELECT 
            sii.item_code,
            sii.item_name,
            SUM(sii.stock_qty) as total_qty,
            SUM({amount_field}) as total
        FROM `tabSales Invoice` si
        {join_clause}
        WHERE {where_clause}
        GROUP BY sii.item_code, sii.item_name
        ORDER BY {sort_field} {order_by}
        {limit_clause}
    """, values, as_dict=True)


def get_territory_sales(from_date=None, to_date=None, company=None, customer_group=None, item_group=None, ranking="Top 10", sort_by="Value"):
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    diff = (to_dt - from_dt).days

    prev_from = (from_dt - timedelta(days=diff)).strftime("%Y-%m-%d")
    prev_to = (to_dt - timedelta(days=diff)).strftime("%Y-%m-%d")

    base_where, values_base, join_clause, amount_field = _get_filter_query(company, customer_group, item_group, sort_by)
    qty_select = "SUM(sii.stock_qty) as total_qty," if "sii" in join_clause else "0 as total_qty,"
    sort_field = "total_qty" if sort_by == "Quantity" else "total"

    values_current = values_base.copy()
    values_current["from_date"] = from_date
    values_current["to_date"] = to_date
    curr_where = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"

    current = frappe.db.sql(f"""
        SELECT si.route, {qty_select} SUM({amount_field}) as total
        FROM `tabSales Invoice` si {join_clause}
        WHERE {curr_where} GROUP BY si.route
    """, values_current, as_dict=True)

    values_prev = values_base.copy()
    values_prev["prev_from"] = prev_from
    values_prev["prev_to"] = prev_to
    prev_where = f"{base_where} AND si.posting_date BETWEEN %(prev_from)s AND %(prev_to)s"

    previous = frappe.db.sql(f"""
        SELECT si.route, {qty_select} SUM({amount_field}) as total
        FROM `tabSales Invoice` si {join_clause}
        WHERE {prev_where} GROUP BY si.route
    """, values_prev, as_dict=True)

    prev_map = {d.route: d.get(sort_field, 0) for d in previous}
    result = []

    for row in current:
        prev_val = prev_map.get(row.route, 0)
        curr_val = row.get(sort_field, 0)

        growth = ((curr_val - prev_val) / prev_val) * 100 if prev_val else (100 if curr_val else 0)

        result.append({
            "route": row.route,
            "total_qty": row.get("total_qty", 0),
            "total": row.total,
            "growth": round(growth, 2)
        })

    reverse_sort = False if ranking == "Lowest 10" else True
    result.sort(key=lambda x: x[sort_field], reverse=reverse_sort)

    if ranking == "All":
        return result
    return result[:10]


def get_warehouse_sales(from_date=None, to_date=None, company=None, customer_group=None, item_group=None, ranking="Top 10", sort_by="Value"):
    base_where, values, join_clause, _ = _get_filter_query(company, customer_group, item_group, sort_by)
    
    if not join_clause:
        join_clause = "JOIN `tabSales Invoice Item` sii ON sii.parent = si.name"
    
    amount_field = "sii.base_amount"
    values["from_date"] = from_date
    values["to_date"] = to_date
    where_clause = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s AND sii.warehouse IS NOT NULL AND sii.warehouse != ''"
    
    sort_field = "total_qty" if sort_by == "Quantity" else "total"
    order_by = "ASC" if ranking == "Lowest 10" else "DESC"
    limit_clause = "" if ranking == "All" else "LIMIT 10"

    return frappe.db.sql(f"""
        SELECT 
            sii.warehouse,
            SUM(sii.stock_qty) as total_qty,
            SUM({amount_field}) as total
        FROM `tabSales Invoice` si
        {join_clause}
        WHERE {where_clause}
        GROUP BY sii.warehouse
        ORDER BY {sort_field} {order_by}
        {limit_clause}
    """, values, as_dict=True)

# UPDATED: Added item_code parameter
def get_customer_comparison(from_date=None, to_date=None, company=None, customers=None, bifurcation="Daily", item_code=None):
    if not customers:
        return []
        
    conditions = ["si.docstatus = 1", "si.posting_date BETWEEN %(from_date)s AND %(to_date)s"]
    values = {"from_date": from_date, "to_date": to_date}
    
    if company:
        conditions.append("si.company = %(company)s")
        values["company"] = company

    # Apply Item Filter if selected
    if item_code:
        conditions.append("sii.item_code = %(item_code)s")
        values["item_code"] = item_code
        
    for i, cust in enumerate(customers):
        values[f"cust_{i}"] = cust
        
    in_clause = ', '.join([f"%(cust_{i})s" for i in range(len(customers))])
    conditions.append(f"si.customer IN ({in_clause})")
    
    where_clause = " AND ".join(conditions)
    
    if bifurcation == "Monthly":
        period_expr = "DATE_FORMAT(si.posting_date, '%%Y-%%b')"
    elif bifurcation == "Weekly":
        period_expr = "CONCAT(YEAR(si.posting_date), '-W', LPAD(WEEK(si.posting_date, 1), 2, '0'))"
    else:
        period_expr = "DATE_FORMAT(si.posting_date, '%%Y-%%m-%%d')"
    
    return frappe.db.sql(f"""
        SELECT 
            {period_expr} as period,
            si.customer,
            si.customer_name,
            SUM(sii.base_amount) as total_value,
            SUM(sii.stock_qty) as total_qty
        FROM `tabSales Invoice` si
        JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        WHERE {where_clause}
        GROUP BY period, si.customer, si.customer_name
        ORDER BY MIN(si.posting_date) ASC
    """, values, as_dict=True)


# =========================
# MASTER OPTIMIZED ENDPOINT
# =========================
@frappe.whitelist()
# UPDATED: Added compare_item parameter
def get_dashboard_data(from_date, to_date, ranking, sort_by="Value", company=None, customer_group=None, item_group=None, 
                       fetch_customers=0, fetch_items=0, fetch_territories=0, fetch_warehouses=0, fetch_comparison=0, 
                       compare_customers=None, compare_item=None, bifurcation="Daily"):
    
    data = {}

    if int(fetch_customers):
        data["customers"] = get_top_customers(from_date, to_date, company, customer_group, item_group, ranking, sort_by)
    
    if int(fetch_items):
        data["items"] = get_top_items(from_date, to_date, company, customer_group, item_group, ranking, sort_by)
    
    if int(fetch_territories):
        data["territories"] = get_territory_sales(from_date, to_date, company, customer_group, item_group, ranking, sort_by)

    if int(fetch_warehouses):
        data["warehouses"] = get_warehouse_sales(from_date, to_date, company, customer_group, item_group, ranking, sort_by)

    if int(fetch_comparison) and compare_customers:
        customers_list = json.loads(compare_customers)
        data["comparison"] = get_customer_comparison(from_date, to_date, company, customers_list, bifurcation, compare_item)

    return data