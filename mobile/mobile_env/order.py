import json
import frappe
from frappe import _
from erpnext.utilities.product import get_price
from erpnext.stock.get_item_details import get_item_price,get_item_details
from erpnext.accounts.utils import getdate
from mobile.mobile_env.app_utils import (
    gen_response,
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
            fields=["name", "customer_name", "workflow_state", "default_price_list"],
            filters={"workflow_state": "Approved"},
        )
        for customer in customer_list:
            routes = frappe.get_value(
                "Dynamic Link",
                {
                    "link_doctype": "Route Master",
                    "parenttype": "Customer",
                    "parent": customer.name,
                },
                "link_name",
            )
            customer["routes"] = routes
            route_warehouse = frappe.get_value(
                "Route Master", routes, "source_warehouse"
            )
            customer["route_warehouse"] = route_warehouse

        gen_response(200, "Customer list fetched successfully", customer_list)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_route_master():
    try:
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        route_list = frappe.get_list(
            "Route Master",
            fields=["name", "company", "route_type"],
            filters={"route_type": "Milk Marketing", "company": company},
        )
        gen_response(200, "Route list get successfully", route_list)
    except Exception as e:
        return exception_handel(e)


"""get item list for mobile app to make order"""


@frappe.whitelist()
def get_warehouselist():
    global_defaults = get_global_defaults()
    company = global_defaults.get("default_company")
    try:
        warehouselist = frappe.get_list(
            "Warehouse",
            # fields=["name", "company"],
            filters={"company": company},
        )

        gen_response(200, "warehouse list successfully", warehouselist)
    except Exception as e:
        exception_handel(e)

@frappe.whitelist()
def get_rates_for_uoms(item_code, price_list):
    uom_rates = []
    
    # Fetch rates from Item Price doctype
    item_rates = get_item_rates_from_price_list(item_code, price_list)
    
    for uom, rate in item_rates.items():
        uom_rates.append({
            "uom": uom,
            "rate": rate
        })

    return uom_rates

def get_item_rates_from_price_list(item_code, price_list, uom=None):
    # Fetch item prices for the specific item and price list
    item_price_conditions = {
        "item_code": item_code,
        "price_list": price_list
    }
    
    if uom:
        item_price_conditions["uom"] = uom
    
    # Fetch the item price records
    item_prices = frappe.get_all(
        "Item Price",
        filters=item_price_conditions,
        fields=["uom", "price_list_rate"]
    )
    
    rates = {}
    for price in item_prices:
        rates[price.uom] = price.price_list_rate
    
    return rates




@frappe.whitelist()
def get_item_list(warehouse=None, price_list=None, customer=None):
    current_user = frappe.session.user

    # Check if the current user is present in the 'custom_user' field of the specified customer
    is_customer = frappe.db.exists('Customer', {'custom_user': current_user})

    # Set default warehouse and price list if not provided
    if not warehouse:
        warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
        
    if not price_list:
        price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")

    try:
        # Fetching the party specific items
        party_item_list = frappe.get_all(
            "Party Specific Item",
            filters={
                "party_type": "Customer",
                "party": customer,
                "restrict_based_on": "Item"
            },
            pluck="based_on_value"
        )
        
        frappe.msgprint(f"Party Item List: {party_item_list}")

        # If no party-specific items are found, get all items
        if not party_item_list:
            frappe.msgprint("No party-specific items found, retrieving all items.")
            item_filters = {
                "is_sales_item": 1,
                "has_variants": 0,
                "disabled": 0
            }
        else:
            item_filters = {
                "is_sales_item": 1,
                "has_variants": 0,
                "disabled": 0,
                "name": ["in", party_item_list]
            }

        # Fetching item details
        item_list = frappe.get_list(
            "Item",
            fields=[
               "*"
            ],
            filters=item_filters
        )

        items=[]
        
        # Getting additional item data
        items = get_items_data(item_list, warehouse, price_list, customer)
        
        # Adding is_customer flag to each item
        for item in items:
            item['is_customer'] = bool(is_customer)

            # Fetching UOM list and conversion factors for each item
            uom_data = frappe.get_all(
                "UOM Conversion Detail",
                filters={"parent": item["item_code"]},
                fields=["uom", "conversion_factor"]
            )
            item['uoms'] = uom_data
            item['rate']= item["price_list_rate"]
            item['conversion_rate']= get_item_price_list_rate(item["item_code"],price_list,customer)
            item['custom_restrict_the_uom_to_change']=frappe.get_value("Item",item["item_code"],"custom_restrict_the_uom_to_change")
        frappe.msgprint(f"Final Items: {items}")
        # Generating response
        gen_response(200, "Item list retrieved successfully", items)
    except Exception as e:
        frappe.log_error(message=str(e), title="Error in get_item_list")
        exception_handel(e)


@frappe.whitelist()
def get_items_data(items, warehouse, price_list, customer):
    items_data = []
    company = get_global_defaults().get("default_company")
    
    if not items:
        frappe.throw("No items found to process.")

    for item in items:
        # if not all(field in item for field in ["item_code", "name"]):
        #     frappe.throw(f"Missing required fields in item: {item}")

        args = {
            "item_code": item.get("item_code"),
            "set_warehouse": warehouse,
            "warehouse": warehouse,
            "customer": customer,
            "selling_price_list": price_list,
            "doctype": "Sales Order",
            "company": company,
            "currency": "INR",
        }
        
        item_data = get_item_details(args)
        
        # Filter item_data to include only the desired keys
        filtered_item_data = filter_item_data(item_data)
        
        items_data.append(filtered_item_data)

    return items_data



def filter_item_data(item_data):
    # Define the keys you want to keep
    keys_to_keep = [
        "item_code", "item_name", "description", "image",
        "uom", "stock_uom", "qty", "stock_qty",
        "price_list_rate", "base_price_list_rate", "rate", "base_rate",
        "amount", "base_amount", "net_rate", "net_amount",
        "discount_percentage", "discount_amount", "bom_no",
        "weight_per_unit", "weight_uom", "grant_commission",
        "conversion_factor", "item_group", "actual_qty"
    ]
    
    # Filter the dictionary to only include these keys
    filtered_item_data = {key: item_data.get(key) for key in keys_to_keep}
    
    return filtered_item_data


def get_actual_qty(item_code, warehouse):
    bin_data = frappe.get_all(
        "Bin",
        filters={"item_code": item_code, "warehouse": warehouse},
        fields=["actual_qty", "warehouse"],
    )
    if bin_data:
        return bin_data[0].get("actual_qty", 0)
    else:
        return 0


def get_item_rate(item_code, price_list, customer):
    # Retrieve the customer group from the customer record
    customer_group = frappe.get_value("Customer", customer, "customer_group")
    
    global_defaults = get_global_defaults()
    company = global_defaults.get("default_company")
    item_price = get_price(item_code=item_code, price_list=price_list, customer_group=customer_group, company=company)
    if item_price and "formatted_price_sales_uom" in item_price:
        formatted_price = item_price["formatted_price_sales_uom"].replace('₹', '').replace(',', '').strip()
        return float(formatted_price)
    else:
        return 0.0
    
def get_item_price_list_rate(item_code, price_list, customer):
    # Retrieve the customer group from the customer record
    customer_group = frappe.get_value("Customer", customer, "customer_group")
    
    global_defaults = get_global_defaults()
    company = global_defaults.get("default_company")
    
    # Get the item price using customer group and company
    item_price = get_price(item_code=item_code, price_list=price_list, customer_group=customer_group, company=company)
    
    # Check if the price list rate is available
    if item_price and "price_list_rate" in item_price:
        return float(item_price["price_list_rate"])
    else:
        return 0.0   


@frappe.whitelist()
def item_price_on_uom(itemCode,price_list,customer,uom):
    item_price_args = {
		"item_code": itemCode,
		"price_list": price_list,
		"customer": customer,
		"uom": uom,
	}
    
    price=get_item_price(item_price_args,item_code=itemCode)
    gen_response(200, "Generate Price", price)
    return price

# Continue with your code as needed
@frappe.whitelist()
def get_rate_for_uom(item_code, price_list, uom):

    if not price_list:
        price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    # Fetch the rate for the specific item, price list, and UOM
    item_price = frappe.get_value(
        "Item Price", 
        {"item_code": item_code, "price_list": price_list, "uom": uom},
        "price_list_rate"
    )
    
    if item_price:
        return float(item_price)
    else:
        return 0.0  
    
@frappe.whitelist()
def grtratesWithUOM(item_code, price_list):
    uom_rates = []

    # Fetch all UOMs and their conversion factors for the item
    uom_conversion_factors = frappe.get_all(
        "UOM Conversion Factor",
        filters={"from_uom": item_code},
        fields=["to_uom", "value"]
    )

    # Fetch base UOM rates
    base_uom_rates = get_item_rates_from_price_list(item_code, price_list)

    for uom_conversion in uom_conversion_factors:
        uom = uom_conversion.to_uom
        conversion_factor = uom_conversion.value

        # Get the rate for the base UOM
        base_rate = base_uom_rates.get(item_code, 0.0)
        
        # Calculate rate for the UOM
        rate = base_rate * conversion_factor

        uom_rates.append({
            "uom": uom,
            "rate": rate
        })

    return uom_rates


@frappe.whitelist()
def prepare_order_totals(**kwargs):
    try:
        data = kwargs
        if not data.get("customer"):
            return gen_response(500, "Customer is required.")
        # ess_settings = get_ess_settings()
        # default_warehouse = ess_settings.get("default_warehouse")
        delivery_date = data.get("delivery_date")
        for item in data.get("items"):
            item["delivery_date"] = delivery_date
            item["warehouse"] = data.get("set_warehouse")
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        sales_order_doc = frappe.get_doc(dict(doctype="Sales Order", company=company))
        sales_order_doc.update(data)
        sales_order_doc.run_method("set_missing_values")
        sales_order_doc.run_method("calculate_taxes_and_totals")
        order_data = (
            prepare_json_data(
                [
                    "taxes_and_charges",
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
def get_order_list():
    try:
        order_list = frappe.get_list(
            "Sales Order",
            fields=[
                "name",
                "customer_name",
                "DATE_FORMAT(transaction_date, '%d-%m-%Y') as transaction_date",
                "grand_total",
                "status",
                "total_qty",
            ],
            order_by="creation desc",
        )
        gen_response(200, "Order list get successfully", order_list)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def create_order(**kwargs):
    try:
        data = kwargs
        if not data.get("customer"):
            return gen_response(500, "Customer is required.")
        if not data.get("items") or len(data.get("items")) == 0:
            return gen_response(500, "Please select items to proceed.")
        if not data.get("delivery_date"):
            return gen_response(500, "Please select delivery date to proceed.")

        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        # ess_settings = get_ess_settings()
        # default_warehouse = ess_settings.get("default_warehouse")

        if data.get("name"):
            if not frappe.db.exists("Sales Order", data.get("name"), cache=True):
                return gen_response(500, "Invalid order id.")
            sales_order_doc = frappe.get_doc("Sales Order", data.get("name"))
            delivery_date = data.get("delivery_date")
            # for item in data.get("items"):
            #     item["delivery_date"] = delivery_date
            #     item["warehouse"] = default_warehouse
            sales_order_doc.update(data)
            sales_order_doc.run_method("set_missing_values")
            sales_order_doc.run_method("calculate_taxes_and_totals")
            sales_order_doc.save()
            gen_response(200, "Order updated successfully.", sales_order_doc)

        else:
            sales_order_doc = frappe.get_doc(
                dict(doctype="Sales Order", company=company)
            )
            delivery_date = data.get("delivery_date")
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
                            "attached_to_doctype": "Sales Order",
                            "attached_to_name": sales_order_doc.name,
                        }
                    )
                    file_doc.insert(ignore_permissions=True)
            gen_response(200, "Order created successfully.", sales_order_doc)

    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def getting_item_for_customer(code,price_list,warehouse,customer):
    global_defaults = get_global_defaults()
    company = global_defaults.get("default_company")
    args = {
        "item_code": code,
       "set_warehouse":warehouse,
       "warehouse":warehouse,
        "customer": customer,
        "selling_price_list": price_list,
        "doctype": "Sales Order",
        "company":company,
        "currency":"INR",
        "order_type":"Sales",
            }
    data=get_item_details(args)
    # data = get_price(item_code=code,price_list=pricelist,customer_group=group,company=company)

    return data


@frappe.whitelist()
def get_units():
    units_types = frappe.get_all('UOM', fields=['name'])
    return units_types
