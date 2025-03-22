import json
import frappe
from frappe import _

from erpnext.accounts.utils import getdate
from mobile.mobile_env.app_utils import (
    gen_response,
    ess_validate,
    prepare_json_data,
    get_global_defaults,
    exception_handel,
)
from erpnext.accounts.party import get_dashboard_info



@frappe.whitelist()
def get_customer_list():
    try:
        customer_list = frappe.get_list(
            "Customer",
            fields=["name", "customer_name"],
        )
        gen_response(200, "Customer list get successfully", customer_list)
    except Exception as e:
        return exception_handel(e)


"""get item list for mobile app to make Quotation"""



@frappe.whitelist()
def get_item_list():
    try:
        item_list = frappe.get_list(
            "Item",
            fields=["name", "item_name", "item_code", "image"],
        )
        items = get_items_data(item_list)
        gen_response(200, "Item list get successfully", items)
    except Exception as e:
        exception_handel(e)


def get_items_data(items):
    items_data = []
    for item in items:
        item_data = {
            "name": item.name,
            "item_name": item.item_name,
            "item_code": item.item_code,
            "image": item.image,
            "actual_qty": float(get_actual_qty(item.item_code)),
            "rate": get_item_rate(item.item_code)  # Fetch rate
        }
        items_data.append(item_data)
    return items_data


def get_actual_qty(item_code):
    warehouse=frappe.db.get_single_value("Stock Settings","default_warehouse")
    bin_data = frappe.get_all(
        "Bin",
        filters={"item_code": item_code,"warehouse":warehouse},
        fields=["actual_qty"]
    )
    if bin_data:
        return bin_data[0].get("actual_qty", 0)
    else:
        return 0


def get_item_rate(item_code):
    item_price = frappe.get_all(
        "Item Price",
        filters={"item_code": item_code},
        fields=["price_list_rate"],
        order_by="creation desc",  # Add this to get the latest price
        limit=1  # Add this to get only the latest price
    )
    if item_price:
        return item_price[0].get("price_list_rate", 0)
    else:
        return 0.0


def set_customer_name(party_name, quotation_to):
    customer_name = None

    if party_name and quotation_to == "Customer":
        customer_name = frappe.db.get_value("Customer", party_name, "customer_name")
    elif party_name and quotation_to == "Lead":
        lead_name, company_name = frappe.db.get_value(
            "Lead", party_name, ["lead_name", "company_name"]
        )
        customer_name = company_name or lead_name

    return customer_name

def get_tax_template(partyname, company):
    tax_template = None
    # frappe.msgprint(partyname)
    # frappe.msgprint(company)
    state_name = frappe.get_value("Lead", {'name': partyname}, ["state"])
    state_name = state_name.split("-")[1].lower()
    frappe.msgprint(state_name)

    if str(state_name) == "maharashtra":
        tax_template = frappe.get_value("Sales Taxes and Charges Template", {'company': company, "tax_category": "In-State"}, ["name"])
        frappe.msgprint('in-state')
        frappe.msgprint(tax_template)
    else:
        tax_template = frappe.get_value("Sales Taxes and Charges Template", {'company': company, "tax_category": "Out-State"}, ["name"])
        frappe.msgprint('out-state')
        frappe.msgprint(tax_template)

    return tax_template



# Continue with your code as needed
@frappe.whitelist()
def prepare_quotation_detail(**kwargs):
    try:
        data = kwargs
        partyname=data.get('party_name')
        quotation_to=data.get('quotation_to')
        data["customer_name"] = set_customer_name(partyname,quotation_to)
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        state_name = frappe.get_value("Lead", {'name': partyname}, ["state"])
        data["company"]=company
        data["currency"]= "INR"
        if(quotation_to=="Lead"):
            data["place_of_supply"]=state_name
            data["taxes_and_charges"]=get_tax_template(partyname,company)
        sales_order_doc = frappe.get_doc(dict(doctype="Quotation",company=company))
        frappe.msgprint(str(sales_order_doc))        
        sales_order_doc.update(data)
        sales_order_doc.run_method("set_missing_values")
        sales_order_doc.run_method("calculate_taxes_and_totals")
        order_data = (
            prepare_json_data(
                [   "taxes_and_charges",
                    "total_taxes_and_charges",
                    "net_total",
                    "discount_amount",
                    "grand_total",
                ],
                json.loads(sales_order_doc.as_json()),
            ),
        )
        gen_response(200, "Order details get successfully", order_data)
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def get_customer_list(doctype):
    try:
        list = frappe.get_all(
            str(doctype),
            fields=[
                "name",
            ],
        )
        gen_response(200,"list get successfully", list)
    except Exception as e:
        return exception_handel(e)

def remove_duplicates(input_list, key_extractor):
    unique_keys = set()
    unique_list = []

    for item in input_list:
        key = key_extractor(item)
        if key not in unique_keys:
            unique_keys.add(key)
            unique_list.append(item)

    return unique_list

@frappe.whitelist()
def filter_customer_list():
    try:
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        list = frappe.get_all(
            "Quotation",
                fields=[
                    "customer_name"
                ],
                filters={"company": company},
            )
        list=remove_duplicates(list,lambda item: item['customer_name'])
        gen_response(200,"list get successfully", list)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def create_order(**kwargs):
    try:
        data = kwargs
        # if not data.get("customer"):
        #     return gen_response(500, "Customer is required.")
        if not data.get("items") or len(data.get("items")) == 0:
            return gen_response(500, "Please select items to proceed.")
        if not data.get("valid_till"):
            return gen_response(500, "Please select valid till to proceed.")
        
        partyname=data.get('party_name')
        quotation_to=data.get('quotation_to')
        data["customer_name"] = set_customer_name(partyname,quotation_to)
        state_name = frappe.get_value("Lead", {'name': partyname}, ["state"])
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        data["company"]=company
        data["currency"]= "INR"
        if(quotation_to=="Lead"):
            data["place_of_supply"]=state_name
            data["taxes_and_charges"]=get_tax_template(partyname,company)
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        # ess_settings = get_ess_settings()
        # default_warehouse = ess_settings.get("default_warehouse")

        if data.get("name"):
            if not frappe.db.exists("Quotation", data.get("name"), cache=True):
                return gen_response(500, "Invalid order id.")
            data.get("taxes").clear()
            sales_order_doc = frappe.get_doc("Quotation", data.get("name"))
            # valid_till = data.get("valid_till")
            sales_order_doc.items = data.get("items")
            sales_order_doc.update(data)
            sales_order_doc.run_method("set_missing_values")
            sales_order_doc.run_method("calculate_taxes_and_totals")
            sales_order_doc.save()
            gen_response(200, "Quotation updated successfully.", sales_order_doc)
        else:
            sales_order_doc = frappe.get_doc(
                dict(doctype="Quotation", company=company)
            )
            # delivery_date = data.get("valid_till")
            # for item in data.get("items"):
            #     item["delivery_date"] = delivery_date
            #     item["warehouse"] = default_warehouse
            sales_order_doc.update(data)
            sales_order_doc.run_method("set_missing_values")
            sales_order_doc.run_method("calculate_taxes_and_totals")
            sales_order_doc.insert()

            if data.get("attachments") is not None:
                for file in data.get("attachments"):
                    file_doc = frappe.get_doc(
                        {
                            "doctype": "File",
                            "file_url": file.get("file_url"),
                            "attached_to_doctype": "Quotation",
                            "attached_to_name": sales_order_doc.name,
                        }
                    )
                    file_doc.insert(ignore_permissions=True)

            gen_response(200, "Quotation created successfully.", sales_order_doc)

    except Exception as e:
        return exception_handel(e)