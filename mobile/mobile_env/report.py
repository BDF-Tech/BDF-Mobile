import json
import os
import calendar
import frappe
from frappe import _

from frappe.utils import cstr, now, today
from frappe.auth import LoginManager
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
    get_global_defaults,
    exception_handel,
)



    
@frappe.whitelist()
def run_customer_ledger_report(from_date, to_date, customer, customer_group):
    try:
        processed_data = []
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        filters = {
            "from_date": from_date,
            "to_date": to_date,
            "company": company,
            "customer_group": customer_group if customer_group else None,
            "party": customer if customer else None
        }

        from frappe.desk.query_report import run

        attendance_report = run("Customer Ledger Summary",filters=filters,ignore_prepared_report=True)
        
        if attendance_report:
            for entry in attendance_report.get("result"):
                parsed_data = json.loads(data)

                # Access the 'result' key inside the parsed data (as a Python list)
                message_data = json.loads(parsed_data[0]["message"].replace("'", "\""))

                # Access the 'result' list and remove the first and last rows
                filtered_result = message_data['result'][1:-1]
                if isinstance(entry, dict): 
                    processed_entry = {
                        "party": entry.get("party")if entry.get("party") else '',
                        "party_name": entry.get("party_name")if entry.get("party") else '',
                        "opening_balance": float(entry.get("opening_balance", 0))if entry.get("opening_balance") else 0.0,
                        "invoiced_amount": float(entry.get("invoiced_amount", 0))if entry.get("invoiced_amount") else 0.0,
                        "bank_receipts": float(entry.get("bank_receipts", 0))if entry.get("bank_receipts") else 0.0,
                        "cash_receipts": float(entry.get("cash_receipts", 0))if entry.get("cash_receipts") else 0.0,
                        "closing_balance": float(entry.get("closing_balance", 0))if entry.get("closing_balance") else 0.0,
                    }
                    processed_data.append(processed_entry)
            return gen_response(200, "Customer Ledger get successfully", processed_data)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def run_payment_ledger_report(from_date, to_date,party_type=None):
    try:
        processed_data = []
        is_customer = frappe.db.exists('Customer', {'custom_user': frappe.session.user})
        if is_customer:
            customer_id=frappe.db.get_value("Customer",{"custom_user":frappe.session.user},"name")
            # frappe.msgprint(customer_id)
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        filters = {
            "from_date": from_date,
            "to_date": to_date,
            "company": company,
            # "party_type": "Customer" if is_customer else None,
            # "party":[(customer_id if is_customer else None)],
            "include_dimensions":1,
            "include_default_book_entries":1,
            "group_by":"Group by Voucher (Consolidated)",
        }
        if is_customer:
            filters = {
            "from_date": from_date,
            "to_date": to_date,
            "company": company,
            "party_type": "Customer" if is_customer else None,
            "party":[(customer_id if is_customer else None)],
            "include_dimensions":1,
            "include_default_book_entries":1,
            "group_by":"Group by Voucher (Consolidated)",
                     }
        
        
        from frappe.desk.query_report import run

        # Run the General Ledger report
        attendance_report = run("General Ledger", filters=filters, ignore_prepared_report=True)
        frappe.msgprint(f"{str(attendance_report)} and filters ={filters}")

        # Define the list of unwanted account names
        unwanted_accounts = ["'Closing (Opening + Total)'", "'Total'", "", "'Opening'"]

        if attendance_report and attendance_report.get("result"):
            for entry in attendance_report.get("result"):
                if isinstance(entry, dict):
                    account_name = entry.get("account", "")
                    
                    # Skip the unwanted account rows
                    if account_name in unwanted_accounts:
                        continue

                    # Process the remaining entries
                    processed_entry = {
                        "posting_date": entry.get("posting_date", ''),
                        "account": account_name,
                        "debit": entry.get("debit", 0.0),
                        "credit": entry.get("credit", 0.0),
                        "balance": round(entry.get("balance", 0.0),3),
                        "voucher_type": entry.get("voucher_type", ''),
                    }
                    processed_data.append(processed_entry)
            
            return gen_response(200, "General Ledger retrieved successfully", processed_data)
    except Exception as e:
        return exception_handel(e)



