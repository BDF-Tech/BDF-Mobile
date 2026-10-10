import frappe
from frappe.utils import getdate, add_days, today, get_first_day, get_last_day, add_months

@frappe.whitelist()
def get_customer_details(customer=None, customer_group=None, status_filter=None, start=0, page_len=20):

    filters = {}
    if customer:
        filters["name"] = customer
    if customer_group:
        filters["customer_group"] = customer_group

    customers = frappe.get_all(
        "Customer",
        filters=filters,
        fields=[
            "name", "customer_name", "lead_name", "default_price_list",
            "custom_starting_date_of_the_contract", "food_license_number",
            "food_license_validity", "customer_group", "territory"
        ],
        order_by="creation desc"
    )

    current_date = getdate(today())
    expiry_limit = add_days(current_date, 30)

    processed = []

    for c in customers:

        status = "Healthy"

        if not c.food_license_number or not c.food_license_validity:
            status = "No License"

        else:
            expiry = getdate(c.food_license_validity)

            if expiry < current_date:
                status = "Expired"

            elif expiry <= expiry_limit:
                status = "Expiring Soon"

        c.status = status

        if status_filter and status_filter != "All":
            if status != status_filter:
                continue

        files = frappe.get_all(
            "File",
            filters={
                "attached_to_name": c.name,
                "attached_to_doctype": "Customer"
            },
            fields=["file_url"]
        )

        c.attachments = [f.file_url for f in files]

        processed.append(c)


    total_count = len(processed)

    paged_customers = processed[int(start): int(start) + int(page_len)]


    summary = {"total": len(customers), "expired": 0, "expiring": 0, "healthy": 0, "missing": 0}

    for c in customers:

        if not c.food_license_number or not c.food_license_validity:
            summary["missing"] += 1
            continue

        expiry = getdate(c.food_license_validity)

        if expiry < current_date:
            summary["expired"] += 1

        elif expiry <= expiry_limit:
            summary["expiring"] += 1

        else:
            summary["healthy"] += 1


    total = summary["total"] or 1

    summary["healthy_pc"] = round((summary["healthy"] / total) * 100)
    summary["expiring_pc"] = round((summary["expiring"] / total) * 100)
    summary["expired_pc"] = round((summary["expired"] / total) * 100)
    summary["missing_pc"] = round((summary["missing"] / total) * 100)

    # -----------------------------
    # LAST MONTH SALES REVENUE
    # -----------------------------
    last_month = add_months(today(), -1)
    month_start = get_first_day(last_month)
    month_end = get_last_day(last_month)

    revenue = frappe.db.sql("""
        SELECT SUM(grand_total)
        FROM `tabSales Invoice`
        WHERE posting_date BETWEEN %s AND %s
        AND docstatus = 1
    """, (month_start, month_end))[0][0] or 0

    return {
        "customers": paged_customers,
        "summary": summary,
        "total_count": total_count,
        "last_month_revenue": revenue
    }