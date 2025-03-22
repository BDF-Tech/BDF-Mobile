import functools
import json
import os
import calendar
import frappe
from frappe import _
from bs4 import BeautifulSoup
from frappe.utils import cstr, now, today
from frappe.permissions import has_permission
from frappe.utils import (
    cstr,
    get_date_str,
    today,
    nowdate,
    getdate,
    now_datetime,
    get_first_day,
    get_last_day,
    date_diff,
    flt,
    pretty_date,
    fmt_money,
)
from frappe.utils.data import nowtime
from mobile.mobile_env.app_utils import (
    gen_response,
    generate_key,
    role_profile,
    ess_validate,
    get_employee_by_user,
    validate_employee_data,
    get_global_defaults,
    exception_handel,
    get_actions,
    check_workflow_exists,
)


@frappe.whitelist()
def create_customer(**kwargs):
    try:
        data = kwargs
        
        if not data.get("email_id"):
            return gen_response(500, "Email Id is required.")
        if not data.get("mobile_no"):
            return gen_response(500, "Mobile is required.")
        # if not data.get("billing"):
        #     return gen_response(500, "Please enter the Address")
        # if not data.get("shipping"):
            return gen_response(500, "Please enter the Address")
        
        if data.get("name"):
            if not frappe.db.exists("Customer", data.get("name"), cache=True):
                return gen_response(500, "Invalid customer id.")
            Customer_doc = frappe.get_doc("Customer", data.get("name"))
            Customer_doc.update(data)
            Customer_doc.save()
            make_billing_address(Customer_doc)
            make_shipping_address(Customer_doc)
            make_contact(Customer_doc)
            gen_response(200, "Customer updated successfully.", Customer_doc.name)
           
        else:
            Customer_doc = frappe.get_doc(dict(doctype="Customer",))
            Customer_doc.update(data)
            Customer_doc.insert()
            make_billing_address(Customer_doc)
            make_shipping_address(Customer_doc)
            make_contact(Customer_doc)
            gen_response(200, "Customer created successfully.", Customer_doc.name)

    except Exception as e:
        return exception_handel(e)
    

@frappe.whitelist()
def filter_customer_list():
    try:
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        list = frappe.get_list(
            "Customer",
                fields=[
                    "name"
                ],
                # filters={"company": company},
            )
        list=remove_duplicates(list,lambda item: item['name'])
        gen_response(200,"List get successfully", list)
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
def get_customer(name):
    from frappe.contacts.doctype.address.address import get_address_display, get_condensed_address
    try:
        contact = frappe.get_value("Dynamic Link", {"link_doctype": "Customer", "parenttype": "Contact", "link_name": name}, 'parent')
        billing_add = None
        shipping_add = None
        contact_doc = None
        
        if contact:
            contact_doc = frappe.get_doc('Contact', contact)

        cust = frappe.get_doc('Customer', name)
        filters = [
		["Dynamic Link", "link_doctype", "=", cust.doctype],
		["Dynamic Link", "link_name", "=", cust.name],
		["Dynamic Link", "parenttype", "=", "Address"],
        ]
        address_list = frappe.get_list("Address", filters=filters, fields=["*"], order_by="creation asc")
        address_list = [a.update({"display": get_address_display(a)}) for a in address_list]
        
        customer_report=run_customer_report(cust.name)
        address_list = sorted(
            address_list,
            key=functools.cmp_to_key(
                lambda a, b: (int(a.is_primary_address - b.is_primary_address))
                or (1 if a.modified - b.modified else 0)
            ),
            reverse=True,
        )
        for a in address_list:
            if a.address_type=="Billing":
               billing_add=a
            elif a.address_type=="Shipping":
                 shipping_add=a                                  
        result = {
            "name": cust.name,
            "docstatus":cust.docstatus,
            "disabled":cust.disabled,
            "workflow_state":cust.workflow_state,
            "doctype":cust.doctype,
            "customer_name": cust.customer_name,
            "customer_type": cust.customer_type,
            "customer_group": cust.customer_group,
            "territory": cust.territory,
            "credit_limit":customer_report.get("credit_limit") if customer_report else None,
            "outstanding_amt":customer_report.get("outstanding_amt") if customer_report else None,
            "credit_balance":customer_report.get("credit_balance") if customer_report else None,
            "gst_category": cust.gst_category,
            "gstin": cust.gstin,
            "email_id": contact_doc.email_id if contact_doc else None,
            "mobile_no": contact_doc.mobile_no if contact_doc else None,
            "contact_id":contact_doc.name if contact_doc else None,
            "billing": {
                "billing_id":billing_add.name if billing_add else None,
                "address_line1": billing_add.address_line1 if billing_add else None,
                "address_line2": billing_add.address_line2 if billing_add else None,
                "city": billing_add.city if billing_add else None,
                "state": billing_add.state if billing_add else None,
                "pincode": billing_add.pincode if billing_add else None,
                "country": billing_add.country if billing_add else None
            } if billing_add else None,
            "shipping": {
                "shipping_id":shipping_add.name if shipping_add else None,
                "address_line1": shipping_add.address_line1 if shipping_add else None,
                "address_line2": shipping_add.address_line2 if shipping_add else None,
                "city": shipping_add.city if shipping_add else None,
                "state": shipping_add.state if shipping_add else None,
                "pincode": shipping_add.pincode if shipping_add else None,
                "country": shipping_add.country if shipping_add else None
            } if shipping_add else None
        }
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_name": ["like", "%{0}%".format(result.get("name"))],
                "comment_type": "Comment",
            },
            fields=[
                "content as comment",
                "comment_by",
                "reference_name",
                "creation",
                "comment_email",
            ],
        )
        ordertodeliver = frappe.get_list(
            "Sales Order",
            filters={
                "customer": result.get("name"),
                "status":["in", ["To Deliver and Bill","To Deliver"]],
            },
            fields=[
                "name",
            ],order_by="creation desc"
        )
        orders = frappe.get_list(
            "Sales Order",
            filters={
                "customer": result.get("name"),
            },
            fields=[
                "name","delivery_date","rounded_total"
            ],order_by="creation desc"
        )
        for comment in comments:
            comment["commented"] = pretty_date(comment["creation"])
            comment["creation"] = comment["creation"].strftime("%I:%M %p")
            comment["user_image"] = frappe.get_value(
                "User", comment.comment_email, "user_image", cache=True
            ) 
        result["orders"]=orders
        result["comments"] = comments
        result["order_deliver"]=len(ordertodeliver)
        result["next_action"] = get_actions(result, result)
        result["allow_edit"] = (
            True if result.get("docstatus") == 0 else False
        )
        gen_response(200, "Customer data get successfully.", result)
    except Exception as e:
        return exception_handel(e)



def make_contact(args, is_primary_contact=1):
    try:

        if args.get("contact_id"):
            contact = frappe.get_doc("Contact", args.get("contact_id"))
    

            for email in contact.email_ids:
                if email.email_id == contact.email_id:
                    email.email_id = args.get("email_id")
                    contact.save()
            for mobile in contact.phone_nos:
                if mobile.phone == contact.mobile_no:
                    mobile.phone = args.get("mobile_no")
                    contact.save()
        else:
            contact = frappe.get_doc(
                {
                    "doctype": "Contact",
                    "first_name": args.get("name"),
                    "is_primary_contact": is_primary_contact,
                    "links": [{"link_doctype": args.get("doctype"), "link_name": args.get("name")}],
                }
            )
            if args.get("email_id"):
                contact.add_email(args.get("email_id"), is_primary=True)
            if args.get("mobile_no"):
                contact.add_phone(args.get("mobile_no"), is_primary_mobile_no=True)
            contact.insert()

        return contact
    except Exception as e:
        return exception_handel(e)


def make_billing_address(args):
    try:
        billing_address=args.get("billing")
        if billing_address.get("billing_id"):
            address = frappe.get_doc(
                                        "Address",
                                            billing_address.get("billing_id")
                                        )
            address.update(billing_address)
            address.save()
        else:
            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": args.get("name"),
                    "address_type":"Billing",
                    "address_line1": billing_address.get("address_line1"),
                    "address_line2": billing_address.get("address_line2"),
                    "city": billing_address.get("city"),
                    "state": billing_address.get("state"),
                    "pincode": billing_address.get("pincode"),
                    "country": billing_address.get("country"),
                    "links": [{"link_doctype": args.get("doctype"), "link_name": args.get("name")}],
                }
            ).insert()

        return address
    except Exception as e:
        return exception_handel(e)

def make_shipping_address(args):
    try:
        shipping_address=args.get("shipping")
        if shipping_address.get("shipping_id"):
            address = frappe.get_doc(
                                        "Address",
                                            shipping_address.get("shipping_id")
                                        )
            address.update(shipping_address)
            address.save()
        else:
            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": args.get("name"),
                    "address_type":"Shipping",
                    "address_line1": shipping_address.get("address_line1"),
                    "address_line2": shipping_address.get("address_line2"),
                    "city": shipping_address.get("city"),
                    "state": shipping_address.get("state"),
                    "pincode": shipping_address.get("pincode"),
                    "country": shipping_address.get("country"),
                    "links": [{"link_doctype": args.get("doctype"), "link_name": args.get("name")}],
                }
            ).insert()

        return address
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def run_customer_report(customer):
    global_defaults = get_global_defaults()
    company = global_defaults.get("default_company")
    filters = {
        "customer":customer,
        "company": company,
        "summarized_view": 1,
    }
    from frappe.desk.query_report import run

    customercreditlimit_report = run("Customer Credit limit Report", filters=filters)
    if customercreditlimit_report.get("result"):
        return customercreditlimit_report.get("result")[0]