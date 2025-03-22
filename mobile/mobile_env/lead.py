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
            "Lead",
                fields=[
                    "lead_name"
                ],
                filters={"company": company},
            )
        list=remove_duplicates(list,lambda item: item['lead_name'])
        gen_response(200,"List get successfully", list)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def after_save(name):
    try:
        doc=frappe.get_doc("Lead",name)
        request_type = doc.request_type
        if request_type:
            # Define your logic to determine the condition and generate the link
            
            link = ""
            # Example logic, replace this with your actual logic
            if request_type == "Enquiry for retailer":
                link = "http://devsamruddhi.erpdata.in/retailer-distribution/new"
            elif request_type == "Enquiry as a distributor":
                link = "http://devsamruddhi.erpdata.in/distributor-registration/new"
            elif request_type == "Enquiry as supplier":
                link = "http://devsamruddhi.erpdata.in/supplier-registration/new"


            # Send email with the link
            recipient_email = doc.email_id
            subject = "Link for Request"
            message = f"Dear {doc.lead_name},\n\nFill the below form to connect with us: <a href='{link}'>{link}</a>"


            # Send email using Frappe's email API
            frappe.sendmail(recipients=[recipient_email], subject=subject, message=message, as_markdown=True)

        if request_type == "Customer Complaint":
            frappe.get_doc(dict(
                doctype = 'Issue',
                subject = doc.custom_sub_complaint_type,
                customer=doc.custom_complaint_customer,
                custom_complaint_type=doc.custom_complaint_type,
                custom_sub_complaint_type=doc.custom_sub_complaint_type,
                custom_department=doc.custom_department,
                custom_complaint_status=doc.custom_complaint_status
            )).insert()
        
        gen_response(200, "Mail sent successfully")
    except Exception as e:
        return exception_handel(e)