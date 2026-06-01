import frappe
import json
from datetime import datetime, date


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _wo_conditions(company, from_date, to_date, date_field="wo.planned_start_date"):
    conditions = ["wo.docstatus = 1"]
    values = {"from_date": from_date, "to_date": to_date}
    if company:
        conditions.append("wo.company = %(company)s")
        values["company"] = company
    conditions.append(f"{date_field} BETWEEN %(from_date)s AND %(to_date)s")
    return " AND ".join(conditions), values


# ─────────────────────────────────────────────
# 1. PRODUCTION OVERVIEW  (default view)
# ─────────────────────────────────────────────

def get_production_overview(from_date, to_date, company=None):
    where, values = _wo_conditions(company, from_date, to_date)

    status_data = frappe.db.sql(f"""
        SELECT
            wo.status,
            COUNT(wo.name)          AS count,
            SUM(wo.qty)             AS planned_qty,
            SUM(wo.produced_qty)    AS produced_qty
        FROM `tabWork Order` wo
        WHERE {where}
        GROUP BY wo.status
    """, values, as_dict=True)

    item_data = frappe.db.sql(f"""
        SELECT
            wo.production_item  AS item_code,
            wo.item_name,
            SUM(wo.qty)         AS planned_qty,
            SUM(wo.produced_qty) AS produced_qty
        FROM `tabWork Order` wo
        WHERE {where}
        GROUP BY wo.production_item, wo.item_name
        ORDER BY produced_qty DESC
        LIMIT 10
    """, values, as_dict=True)

    return {"status_summary": status_data, "items": item_data}


# ─────────────────────────────────────────────
# 2. ITEM-WISE PRODUCTION
# ─────────────────────────────────────────────

def get_item_production(from_date, to_date, company=None, item_group=None):
    where, values = _wo_conditions(company, from_date, to_date)
    join = ""
    if item_group:
        join = "JOIN `tabItem` i ON i.name = wo.production_item"
        where += " AND i.item_group = %(item_group)s"
        values["item_group"] = item_group

    return frappe.db.sql(f"""
        SELECT
            wo.production_item      AS item_code,
            wo.item_name,
            SUM(wo.qty)             AS planned_qty,
            SUM(wo.produced_qty)    AS produced_qty,
            COUNT(wo.name)          AS wo_count,
            MIN(wo.planned_start_date) AS start_date,
            MAX(wo.planned_end_date)   AS end_date
        FROM `tabWork Order` wo
        {join}
        WHERE {where}
        GROUP BY wo.production_item, wo.item_name
        ORDER BY planned_qty DESC
    """, values, as_dict=True)


# ─────────────────────────────────────────────
# 3. SO vs PRODUCTION
# ─────────────────────────────────────────────

def get_so_vs_production(from_date, to_date, company=None):
    where, values = _wo_conditions(company, from_date, to_date)
    where += " AND wo.sales_order IS NOT NULL AND wo.sales_order != ''"

    rows = frappe.db.sql(f"""
        SELECT
            wo.production_item  AS item_code,
            wo.item_name,
            wo.sales_order,
            SUM(wo.qty)             AS planned_qty,
            SUM(wo.produced_qty)    AS produced_qty,
            COALESCE((
                SELECT SUM(soi.qty)
                FROM `tabSales Order Item` soi
                WHERE soi.parent = wo.sales_order
                  AND soi.item_code = wo.production_item
            ), 0) AS so_demand,
            COALESCE((
                SELECT SUM(b.actual_qty)
                FROM `tabBin` b
                WHERE b.item_code = wo.production_item
            ), 0) AS current_stock
        FROM `tabWork Order` wo
        WHERE {where}
        GROUP BY wo.production_item, wo.sales_order
        ORDER BY wo.sales_order, wo.production_item
    """, values, as_dict=True)

    result = []
    for row in rows:
        so_demand         = float(row.so_demand or 0)
        opening_stock     = float(row.current_stock or 0)
        produced          = float(row.produced_qty or 0)
        planned           = float(row.planned_qty or 0)
        need_to_mfg       = max(0.0, so_demand - opening_stock)
        closing_stock     = opening_stock + produced - so_demand

        if so_demand <= opening_stock:
            status = "Stock Sufficient"
        elif produced == 0 and planned > 0:
            status = "Not Started"
        elif produced >= need_to_mfg:
            status = "Fulfilled"
        elif produced > 0:
            status = "Partial"
        else:
            status = "Not Started"

        result.append({
            "item_code":          row.item_code,
            "item_name":          row.item_name,
            "sales_order":        row.sales_order,
            "so_demand":          so_demand,
            "opening_stock":      opening_stock,
            "need_to_manufacture":need_to_mfg,
            "planned_qty":        planned,
            "produced_qty":       produced,
            "closing_stock":      round(closing_stock, 3),
            "shortfall":          round(max(0, need_to_mfg - produced), 3),
            "status":             status,
        })

    return result


# ─────────────────────────────────────────────
# 4. RAW MATERIAL CONSUMPTION
# ─────────────────────────────────────────────

def get_raw_materials(from_date, to_date, company=None):
    conditions = ["wo.docstatus = 1"]
    values = {"from_date": from_date, "to_date": to_date}
    if company:
        conditions.append("wo.company = %(company)s")
        values["company"] = company
    conditions.append("wo.planned_start_date BETWEEN %(from_date)s AND %(to_date)s")
    where = " AND ".join(conditions)

    return frappe.db.sql(f"""
        SELECT
            woi.item_code,
            woi.item_name,
            woi.stock_uom               AS uom,
            SUM(woi.required_qty)       AS required_qty,
            SUM(woi.consumed_qty)       AS consumed_qty,
            COALESCE((
                SELECT SUM(b.actual_qty)
                FROM `tabBin` b
                WHERE b.item_code = woi.item_code
            ), 0) AS current_stock
        FROM `tabWork Order Item` woi
        JOIN `tabWork Order` wo ON wo.name = woi.parent
        WHERE {where}
        GROUP BY woi.item_code, woi.item_name, woi.stock_uom
        ORDER BY required_qty DESC
    """, values, as_dict=True)


# ─────────────────────────────────────────────
# 5. WORK ORDER STATUS
# ─────────────────────────────────────────────

def get_work_orders(from_date, to_date, company=None, wo_status=None):
    conditions = ["wo.docstatus = 1"]
    values = {"from_date": from_date, "to_date": to_date}
    if company:
        conditions.append("wo.company = %(company)s")
        values["company"] = company
    if wo_status:
        conditions.append("wo.status = %(wo_status)s")
        values["wo_status"] = wo_status
    conditions.append("wo.planned_start_date BETWEEN %(from_date)s AND %(to_date)s")
    where = " AND ".join(conditions)

    return frappe.db.sql(f"""
        SELECT
            wo.name,
            wo.production_item  AS item_code,
            wo.item_name,
            wo.qty              AS planned_qty,
            wo.produced_qty,
            wo.status,
            wo.planned_start_date,
            wo.planned_end_date,
            wo.actual_start_date,
            wo.actual_end_date,
            wo.sales_order,
            wo.company
        FROM `tabWork Order` wo
        WHERE {where}
        ORDER BY
            FIELD(wo.status, 'In Process', 'Not Started', 'Completed', 'Stopped') ASC,
            wo.planned_end_date ASC
    """, values, as_dict=True)


# ─────────────────────────────────────────────
# 6. SALES ORDER DELIVERY
# ─────────────────────────────────────────────

def get_so_delivery(from_date, to_date, company=None):
    conditions = [
        "so.docstatus = 1",
        "so.status NOT IN ('Cancelled', 'Closed')",
        "so.delivery_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    values = {"from_date": from_date, "to_date": to_date}
    if company:
        conditions.append("so.company = %(company)s")
        values["company"] = company
    where = " AND ".join(conditions)

    rows = frappe.db.sql(f"""
        SELECT
            so.name,
            so.customer,
            so.customer_name,
            so.delivery_date,
            so.status,
            SUM(soi.qty)                         AS ordered_qty,
            SUM(soi.delivered_qty)               AS delivered_qty,
            SUM(soi.qty - soi.delivered_qty)     AS pending_qty
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        WHERE {where}
        GROUP BY so.name, so.customer, so.customer_name, so.delivery_date, so.status
        ORDER BY so.delivery_date ASC
    """, values, as_dict=True)

    today_str = str(date.today())
    for row in rows:
        row["is_overdue"] = (
            str(row.get("delivery_date") or "") < today_str
            and float(row.get("pending_qty") or 0) > 0
        )

    return rows


# ─────────────────────────────────────────────
# MASTER ENDPOINT
# ─────────────────────────────────────────────

@frappe.whitelist()
def get_production_data(
    from_date, to_date, company=None,
    fetch_overview=0, fetch_items=0, fetch_so_vs_production=0,
    fetch_raw_materials=0, fetch_work_orders=0, fetch_so_delivery=0,
    item_group=None, wo_status=None,
):
    data = {}

    if int(fetch_overview):
        data["overview"] = get_production_overview(from_date, to_date, company)

    if int(fetch_items):
        data["items"] = get_item_production(from_date, to_date, company, item_group)

    if int(fetch_so_vs_production):
        data["so_vs_production"] = get_so_vs_production(from_date, to_date, company)

    if int(fetch_raw_materials):
        data["raw_materials"] = get_raw_materials(from_date, to_date, company)

    if int(fetch_work_orders):
        data["work_orders"] = get_work_orders(from_date, to_date, company, wo_status)

    if int(fetch_so_delivery):
        data["so_delivery"] = get_so_delivery(from_date, to_date, company)

    return data
