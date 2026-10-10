import frappe
from frappe import _

@frappe.whitelist()
def get_stock_data(warehouse=None, item_code=None, item_group=None, stock_status="All", sort_order="asc"):
    # Security Check
    if not frappe.has_permission("Bin", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # 1. Handle Item Group Hierarchy (Optimization: use nested set)
    lft, rgt = None, None
    if item_group:
        group_info = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
        if group_info:
            lft, rgt = group_info.lft, group_info.rgt

    # 2. Optimized Query Construction
    # We use a subquery for Reorder Levels to avoid "Many-to-Many" duplication during SUM(qty)
    query = """
        SELECT 
            i.name as item_code,
            i.item_name,
            i.stock_uom,
            i.custom_no_of_days,
            COALESCE(sub_bin.warehouse, %(wh)s) as warehouse,
            COALESCE(sub_bin.actual_qty, 0) as actual_qty,
            COALESCE(r.warehouse_reorder_level, 0) as reorder_level
        FROM `tabItem` i
        LEFT JOIN (
            SELECT item_code, warehouse, SUM(actual_qty) as actual_qty 
            FROM `tabBin` 
            {bin_where}
            GROUP BY item_code, warehouse
        ) sub_bin ON i.name = sub_bin.item_code
        LEFT JOIN `tabItem Reorder` r ON r.parent = i.name 
            AND (r.warehouse = sub_bin.warehouse OR r.warehouse = %(wh)s)
        WHERE i.disabled = 0 AND i.is_stock_item = 1
    """

    bin_where = ""
    conditions = []
    values = {"wh": warehouse}

    if warehouse:
        bin_where = "WHERE warehouse = %(wh)s"
        conditions.append("(sub_bin.warehouse = %(wh)s OR sub_bin.warehouse IS NULL)")
    
    if item_code:
        conditions.append("i.name = %(item_code)s")
        values["item_code"] = item_code

    if lft and rgt:
        conditions.append("i.item_group IN (SELECT name FROM `tabItem Group` WHERE lft >= %(lft)s AND rgt <= %(rgt)s)")
        values.update({"lft": lft, "rgt": rgt})

    final_query = query.format(bin_where=bin_where)
    if conditions:
        final_query += " AND " + " AND ".join(conditions)

    # 3. Status Filtering (Optimized HAVING)
    if stock_status == "Critical":
        final_query += " HAVING actual_qty <= reorder_level AND (actual_qty > 0 OR reorder_level > 0)"
    elif stock_status == "Healthy":
        final_query += " HAVING actual_qty > reorder_level"
    else:
        # Don't show items that have 0 stock AND no reorder level (Reduces bloat)
        final_query += " HAVING (actual_qty != 0 OR reorder_level > 0)"

    final_query += f" ORDER BY actual_qty {sort_order}"

    return frappe.db.sql(final_query, values, as_dict=True)