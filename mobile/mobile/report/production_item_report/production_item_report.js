// Copyright (c) 2026, Qunatbit and contributors
// For license information, please see license.txt

frappe.query_reports["Production Item Report"] = {
	tree : true,
	"filters": [
			{
				"fieldname": "from_date",
				"label": __("From Date"),
				"fieldtype": "Date",
				"reqd": 1,
			},
			{
				"fieldname": "to_date",
				"label": __("To Date"),
				"fieldtype": "Date",
				"reqd": 1,
				"default": frappe.datetime.get_today()
			},
			{
				"fieldname": "item_code",
				"label": __("Item Code"),
				"fieldtype": "Link",
				"options": "Item",
			},
	]
};
