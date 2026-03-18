import frappe


def execute(filters=None):

    columns = [
        {"label": "Stock Entry", "fieldname": "stock_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 200},
        {"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 120},
        {"label": "Time", "fieldname": "posting_time", "fieldtype": "Time", "width": 100},
        {"label": "Finished Good", "fieldname": "fg_item", "fieldtype": "Data", "width": 180},
        {"label": "Raw Material", "fieldname": "rm_item", "fieldtype": "Data", "width": 210},
        {"label": "UOM", "fieldname": "uom", "fieldtype": "Data", "width": 80},
        {"label": "Qty", "fieldname": "qty", "fieldtype": "Float", "width": 120},
        {"label": "Handling Loss Qty", "fieldname": "custom_handling_loss_qty", "fieldtype": "Float", "width": 150},
    ]

    data = []

    # Warehouses for stages
    SFG_WH = "Production Cold Room - BDF"
    FG_WH = "Dispatch Cold Room - BDF"

    stock_entries = frappe.get_all(
        "Stock Entry",
        filters={
            "docstatus": 1,
            "stock_entry_type": "Manufacture",
            "posting_date": ["between", [filters.get("from_date"), filters.get("to_date")]]
        },
        fields=["name", "posting_date", "posting_time"]
    )

    stock_entry_names = [d.name for d in stock_entries]

    items = frappe.get_all(
        "Stock Entry Detail",
        filters={"parent": ["in", stock_entry_names]},
        fields=[
            "parent",
            "item_code",
            "item_name",
            "qty",
            "t_warehouse",
            "s_warehouse",
            "custom_handling_loss_qty",
            "uom"
        ]
    )

    # Group items by Stock Entry
    items_by_entry = {}

    for item in items:
        items_by_entry.setdefault(item.parent, []).append(item)

    for entry in stock_entries:

        entry_items = items_by_entry.get(entry.name, [])

        fg_row_name = None

        for item in entry_items:

            if item.t_warehouse:

                stage = filters.get("product_stage")

                if stage == "Semi Finished" and item.t_warehouse != SFG_WH:
                    continue

                if stage == "Finished" and item.t_warehouse != FG_WH:
                    continue

                fg_row_name = f"{item.item_code} / {item.item_name}"

                row = {
                    "date": entry.posting_date,
                    "posting_time": entry.posting_time,
                    "stock_entry": entry.name,
                    "fg_item": fg_row_name,
                    "qty": item.qty,
                    "custom_handling_loss_qty": item.custom_handling_loss_qty,
                    "uom": item.uom,
                    "indent": 0,
                    "parent": None
                }

                data.append(row)

        # Add raw materials under FG
        if fg_row_name:

            for item in entry_items:

                if item.s_warehouse:

                    row_rm = {
                        "date": entry.posting_date,
                        "posting_time": entry.posting_time,
                        "rm_item": f"{item.item_code} / {item.item_name}",
                        "qty": item.qty,
                        "custom_handling_loss_qty": item.custom_handling_loss_qty,
                        "uom": item.uom,
                        "indent": 1,
                        "parent": fg_row_name
                    }

                    data.append(row_rm)

    return columns, data