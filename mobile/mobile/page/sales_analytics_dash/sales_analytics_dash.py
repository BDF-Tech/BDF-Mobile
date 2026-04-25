import frappe
from datetime import datetime, timedelta

def _get_filter_query(customer_group, item_group):
    conditions = ["si.docstatus = 1"]
    values = {}
    join_clause = ""
    amount_field = "si.base_grand_total"

    if customer_group:
        conditions.append("si.customer_group = %(customer_group)s")
        values["customer_group"] = customer_group

    if item_group:
        join_clause = "JOIN `tabSales Invoice Item` sii ON sii.parent = si.name"
        amount_field = "sii.base_amount"
        conditions.append("sii.item_group = %(item_group)s")
        values["item_group"] = item_group

    return " AND ".join(conditions), values, join_clause, amount_field


def get_top_customers(from_date=None, to_date=None, customer_group=None, item_group=None, ranking="Top 10"):
    base_where, values, join_clause, amount_field = _get_filter_query(customer_group, item_group)
    
    values["from_date"] = from_date
    values["to_date"] = to_date
    where_clause = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    
    order_by = "ASC" if ranking == "Lowest 10" else "DESC"
    limit_clause = "" if ranking == "All" else "LIMIT 10"

    return frappe.db.sql(f"""
        SELECT 
            si.customer,
            si.customer_name,
            SUM({amount_field}) as total
        FROM `tabSales Invoice` si
        {join_clause}
        WHERE {where_clause}
        GROUP BY si.customer, si.customer_name
        ORDER BY total {order_by}
        {limit_clause}
    """, values, as_dict=True)


def get_top_items(from_date=None, to_date=None, customer_group=None, item_group=None, ranking="Top 10"):
    base_where, values, join_clause, _ = _get_filter_query(customer_group, item_group)
    
    if not join_clause:
        join_clause = "JOIN `tabSales Invoice Item` sii ON sii.parent = si.name"
    
    join_clause += " JOIN `tabItem` i ON i.name = sii.item_code"
    base_where += " AND i.is_sales_item = 1"
    
    amount_field = "sii.base_amount"
    values["from_date"] = from_date
    values["to_date"] = to_date
    where_clause = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    
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
        ORDER BY total {order_by}
        {limit_clause}
    """, values, as_dict=True)


def get_territory_sales(from_date=None, to_date=None, customer_group=None, item_group=None, ranking="Top 10"):
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    diff = (to_dt - from_dt).days

    prev_from = (from_dt - timedelta(days=diff)).strftime("%Y-%m-%d")
    prev_to = (to_dt - timedelta(days=diff)).strftime("%Y-%m-%d")

    base_where, values_base, join_clause, amount_field = _get_filter_query(customer_group, item_group)

    values_current = values_base.copy()
    values_current["from_date"] = from_date
    values_current["to_date"] = to_date
    curr_where = f"{base_where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    
    current = frappe.db.sql(f"""
        SELECT si.territory, SUM({amount_field}) as total
        FROM `tabSales Invoice` si {join_clause}
        WHERE {curr_where} GROUP BY si.territory
    """, values_current, as_dict=True)

    values_prev = values_base.copy()
    values_prev["prev_from"] = prev_from
    values_prev["prev_to"] = prev_to
    prev_where = f"{base_where} AND si.posting_date BETWEEN %(prev_from)s AND %(prev_to)s"
    
    previous = frappe.db.sql(f"""
        SELECT si.territory, SUM({amount_field}) as total
        FROM `tabSales Invoice` si {join_clause}
        WHERE {prev_where} GROUP BY si.territory
    """, values_prev, as_dict=True)

    prev_map = {d.territory: d.total for d in previous}
    result = []

    for row in current:
        prev_total = prev_map.get(row.territory, 0)
        growth = ((row.total - prev_total) / prev_total) * 100 if prev_total else (100 if row.total else 0)

        result.append({
            "territory": row.territory,
            "total": row.total,
            "growth": round(growth, 2)
        })

    reverse_sort = False if ranking == "Lowest 10" else True
    result.sort(key=lambda x: x["total"], reverse=reverse_sort)

    if ranking == "All":
        return result
    return result[:10]


@frappe.whitelist()
def get_dashboard_data(from_date, to_date, ranking, customer_group=None, item_group=None, fetch_customers=0, fetch_items=0, fetch_territories=0):
    data = {}

    if int(fetch_customers):
        data["customers"] = get_top_customers(from_date, to_date, customer_group, item_group, ranking)
    
    if int(fetch_items):
        data["items"] = get_top_items(from_date, to_date, customer_group, item_group, ranking)
    
    if int(fetch_territories):
        data["territories"] = get_territory_sales(from_date, to_date, customer_group, item_group, ranking)

    return data