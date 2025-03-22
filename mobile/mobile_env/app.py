import json
import os
import calendar
import frappe
from frappe import _
from hrms.hr.doctype.leave_application.leave_application import (
            get_leave_balance_on,
        )
from bs4 import BeautifulSoup
from frappe.utils import cstr, now, today
from frappe.auth import LoginManager
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
)
from mobile.mobile_env.customer import (
    run_customer_report,
    
)

from erpnext.accounts.utils import get_fiscal_year



@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    try:
        login_manager = LoginManager()
        login_manager.authenticate(usr, pwd)
        login_manager.post_login()
        if frappe.response["message"] == "Logged In":
            frappe.response["user"] = login_manager.user
            frappe.response["key_details"] = generate_key(login_manager.user)
        gen_response(200, frappe.response["message"])
    except frappe.AuthenticationError:
        gen_response(500, frappe.response["message"])
    except Exception as e:
        return exception_handel(e)


def validate_employee(user):
    if not frappe.db.exists("Employee", dict(user_id=user)):
        frappe.response["message"] = "Please link Employee with this user"
        raise frappe.AuthenticationError(frappe.response["message"])


@frappe.whitelist()
def get_user_document():
    user_doc = frappe.get_doc("User", frappe.session.user)
    return user_doc

@frappe.whitelist()
def user_has_permission():
    permission_list=[]
    doclist=["sales Invoice","Sales Order","Customer","Payment Entry","Report"]
    for i in doclist:
        permission=has_permission(i)
        if permission:
            permission_list.append(i)
    return permission_list


@frappe.whitelist()
def add_comment(reference_doctype=None, reference_name=None, content=None):
    try:
        from frappe.desk.form.utils import add_comment

        comment_by = frappe.db.get_value(
            "User", frappe.session.user, "full_name", as_dict=1
        )

        add_comment(
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            content=content,
            comment_email=frappe.session.user,
            comment_by=comment_by.get("full_name"),
        )
        return gen_response(200, "Comment Added Successfully")

    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_comments(reference_doctype=None, reference_name=None):
    """
    reference_doctype: doctype
    reference_name: docname
    """
    try:
        current_site=frappe.local.site
        filters = [
            ["Comment", "reference_doctype", "=", f"{reference_doctype}"],
            ["Comment", "reference_name", "=", f"{reference_name}"],
            ["Comment", "comment_type", "=", "Comment"],
        ]
        comments = frappe.get_all(
            "Comment",
            filters=filters,
            fields=[
                "content as comment",
                "comment_by",
                "creation",
                "comment_email",
            ],
        )

        for comment in comments:
            user_image = frappe.get_value(
                "User", comment.comment_email, "user_image", cache=True
            )
            
       
            if user_image is not None:
                comment["user_image"] = frappe.utils.get_url()+ user_image
            else:
                comment["user_image"] = None
            comment["commented"] = pretty_date(comment["creation"])
            comment["creation"] = comment["creation"].strftime('%Y-%m-%d %H:%M %p')

        return gen_response(200, "Comment Getting Successfully", comments)

    except Exception as e:
        return exception_handel(e)



@frappe.whitelist()
def get_dashboard():
    try:
        emp_data = get_employee_by_user(frappe.session.user, fields=["name", "company","employee_name"])
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        attendance_details = get_attendance_details(emp_data)
        log_details = get_last_log_details(emp_data.get("name"))
        a,b=get_leave_balance_dashboard()
        current_site=frappe.local.site
        permissionlist=user_has_permission()
        customer=frappe.get_value("Customer",{"custom_user":frappe.session.user},"name")
        is_customer = frappe.db.exists('Customer', {'custom_user': frappe.session.user})
        if customer:
            customer_report=run_customer_report(customer)
        dashboard_data = {
           "leave_balance": b,
            # "latest_leave": {},
            # "latest_expense": {},
            # "latest_salary_slip": {},
            "is_customer_login":bool(is_customer),
            "permission_list":permissionlist,
            "last_log_type": log_details.get("log_type"),
           "attendance_details":attendance_details,
           "credit_limit":customer_report.get("credit_limit"),
            "outstanding_amt":customer_report.get("outstanding_amt"),
            "credit_balance":customer_report.get("credit_balance"),
            "emp_name":emp_data.get("employee_name"),
            "email":frappe.session.user,
            "company": emp_data.get("company") or "Employee Dashboard",
            "last_log_time": log_details.get("time").strftime("%I:%M%p")
            if log_details.get("time")
            else "",
        }
        str1=frappe.get_cached_value(
            "Employee", emp_data.get("name"), "image"
        )
       
        if str1 is not None:
            dashboard_data["employee_image"] = frappe.utils.get_url() + str1
        else:
            dashboard_data["employee_image"] = None
            
        get_last_log_type(dashboard_data, emp_data.get("name"))
        return gen_response(200, "Dashboard data get successfully", dashboard_data)

    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_emp_name():
    try:
        emp_data = frappe.get_doc("User",frappe.session.user)
        global_defaults = get_global_defaults()
        company = global_defaults.get("default_company")
        customer=frappe.get_value("Customer",{"custom_user":frappe.session.user},"name")
        is_customer = frappe.db.exists('Customer', {'custom_user': frappe.session.user})

        customer_report=run_customer_report(customer)
        dashboard_data = {
            "customer":customer,
            "is_customer_login":bool(is_customer),
            "credit_limit":customer_report.get("credit_limit") if customer_report else None,
            "outstanding_amt":customer_report.get("outstanding_amt") if customer_report else None,
            "credit_balance":customer_report.get("credit_balance") if customer_report else None,
            "emp_name":emp_data.full_name,
            "email":emp_data.email,
            "company": company if company else None,
        }
        str1=frappe.get_cached_value(
            "User",frappe.session.user, "user_image",
        )
       
        if str1 is not None:
            dashboard_data["employee_image"] = frappe.utils.get_url()+ str1
        else:
            dashboard_data["employee_image"] = None
        return gen_response(200, "Dashboard data get successfully", dashboard_data)

    except Exception as e:
        return exception_handel(e)

def get_last_log_details(employee):
    log_details = frappe.db.sql(
        """select log_type,time from `tabEmployee Checkin` where employee=%s and DATE(time)=%s order by time desc""",
        (employee, today()),
        as_dict=1,
    )

    if log_details:
        return log_details[0]
    else:
        return {"log_type": "OUT", "time": None}


@frappe.whitelist()
def change_password(**kwargs):
    try:
        from frappe.utils.password import check_password, update_password
        data=kwargs
        user = frappe.session.user
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        check_password(user, current_password)
        update_password(user, new_password)
        return gen_response(200, "Password updated")
    except frappe.AuthenticationError:
        return gen_response(500, "Incorrect current password")
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def get_profile():
    try:
        
        employee_details = frappe.get_cached_value(
            "User",
           frappe.session.user,
            [
                "username",
                "full_name",
                "email",
                "name",
            "time_zone",
                "birth_date",
                "gender",
                "mobile_no"
            ],
            as_dict=True,
        )
        
        image=frappe.get_cached_value(
            "User",frappe.session.user, "user_image",
        )
        if image is not None:
            employee_details["user_image"] = frappe.utils.get_url()+ image
        else:
            employee_details["user_image"] = None
        

        return gen_response(200, "My Profile", employee_details)
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def change_status(doc_name,type):
    try:
        frappe.db.set_value('Lead', doc_name, 'custom_call_status', type, update_modified=True)
        return gen_response(200,'Status Changed')
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def add_note_in_lead(doc_name, note):
    try:
        doc=frappe.get_doc("Lead",{'name':doc_name},['notes'])
        doc.append("notes", {"note": note, "added_by": frappe.session.user, "added_on": now()})
        doc.save()
        return gen_response(200, "Note Added Successfully")
    
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def update_profile_picture():
    try:
       
        from frappe.handler import upload_file

        employee_profile_picture = upload_file()
       
        if employee_profile_picture:
            frappe.db.set_value(
                "User",
                frappe.session.user,
                "user_image",
                employee_profile_picture.file_url,
            )
        return gen_response(200, "Profile picture updated successfully")
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def edit_note_in_lead(doc_name, note, row_id):
    doc=frappe.get_doc("Lead",{'name':doc_name},['notes'])
    for d in doc.notes:
        if cstr(d.name) == row_id:
            d.note = note
            d.db_update()

@frappe.whitelist()
def delete_note_in_lead(doc_name, row_id):
    try:
        doc=frappe.get_doc("Lead",{'name':doc_name},['notes'])
        for d in doc.notes:
            if cstr(d.name) == row_id:
                doc.remove(d)
                break
        doc.save()
        return gen_response(200, "Comment Delete Successfully")
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_data_from_notes(doc_name):
    emp_data = get_employee_by_user(frappe.session.user, fields=["name", "company", "employee_name"])
    if isinstance(emp_data, str):
            return gen_response(400,emp_data)
    doc = frappe.get_doc("Lead", {'name': doc_name}, ['notes'])
    note_li = []
    current_site = frappe.local.site
   
   
    for i in doc.notes:
        note_dict = {}
        
        # Use BeautifulSoup to extract text from HTML string
        soup = BeautifulSoup(i.note, 'html.parser')

        # Find all <p> tags and extract the text
        paragraphs = soup.find_all('p')

        # Extracted text from <p> tags
        text_list = [p.get_text(strip=True) for p in paragraphs]

        # Remove empty strings from the list
        text_list = list(filter(None, text_list))
        
        # Add formatted message to the note_dict
        note_dict["name"] = int(i.name)
        note_dict["note"] = str(i.note)
        note_dict["commented"] = str(i.added_by)
        
        # Check if added_on is not None before formatting
        note_dict["added_on"] = i.added_on.strftime("%I:%M %p") if i.added_on else None
        str1 = frappe.get_value(
                "User", i.added_by, "user_image", cache=True
            )
        frappe.msgprint(str1)
        if str1 is not None:
            note_dict['image'] = frappe.utils.get_url()+ str1
        else:
            note_dict['image'] = None
        
        note_li.append(note_dict)

    return gen_response(200, "Notes get successfully", note_li)




@frappe.whitelist()
def create_employee_log(log_type, location=None):
    try:
        emp_data = get_employee_by_user(
            frappe.session.user, fields=["name", "default_shift"]
        )
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        log_doc = frappe.get_doc(
            dict(
                doctype="Employee Checkin",
                employee=emp_data.get("name"),
                log_type=log_type,
                time=now_datetime().__str__()[:-7],
                custom_location=location,
               
            )
        ).insert(ignore_permissions=True)
        update_shift_last_sync(emp_data)
        return gen_response(200, "Employee Log Added")
    except Exception as e:
        return exception_handel(e)



def update_shift_last_sync(emp_data):
    if emp_data.get("default_shift"):
        frappe.db.set_value(
            "Shift Type",
            emp_data.get("default_shift"),
            "last_sync_of_checkin",
            now_datetime(),
        )


@frappe.whitelist()
def get_holiday_list(year):
    try:
        if not year:
            return gen_response(500, "year is required")
        emp_data = get_employee_by_user(frappe.session.user)
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        from erpnext.setup.doctype.employee.employee import (
            get_holiday_list_for_employee,
        )

        holiday_list = get_holiday_list_for_employee(
            emp_data.name, raise_exception=False
        )

        if not holiday_list:
            return gen_response(200, "Holiday list get successfully", [])

        holidays = frappe.get_all(
            "Holiday",
            filters={
                "parent": holiday_list,
                "holiday_date": ("between", [f"{year}-01-01", f"{year}-12-31"]),
            },
            fields=["description", "holiday_date"],
        )

        if len(holidays) == 0:
            return gen_response(500, f"No holidays found for year {year}")

        holiday_list = []

        for holiday in holidays:
            holiday_date = frappe.utils.data.getdate(holiday.holiday_date)

            # Check if the day of the week is not Sunday (6 represents Sunday in Python)
            if holiday_date.weekday() != 6:
                holiday_list.append(
                    {
                        "year": holiday_date.strftime("%Y"),
                        "date": holiday_date.strftime("%d %b"),
                        "day": holiday_date.strftime("%A"),
                        "description": holiday.description,
                    }
                )

        return gen_response(200, "Holiday List", holiday_list)
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def get_leave_balance_dashboard():
    try:
        emp_data = get_employee_by_user(frappe.session.user, fields=["name", "company"])
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        fiscal_year = get_fiscal_year(nowdate())[0]
        dashboard_data = {"leave_balance": []}
        if fiscal_year:
            res = get_leave_balance_report(
                emp_data.get("name"), emp_data.get("company"), fiscal_year
            )
            dashboard_data["leave_balance"] = res["result"]
        return gen_response(200, "Leave Balance data get successfully") , res["result"]
    except Exception as e:
        return exception_handel(e)



def get_last_log_type(dashboard_data, employee):
    logs = frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee},
        fields=["log_type"],
        order_by="time desc",
    )

    if len(logs) >= 1:
        dashboard_data["last_log_type"] = logs[0].log_type



@frappe.whitelist()
def make_leave_application(**kwargs):
    try:
        from hrms.hr.doctype.leave_application.leave_application import (
            get_leave_approver,
        )

        emp_data = get_employee_by_user(frappe.session.user)
        if not len(emp_data) >= 1:
            return gen_response(500, "Employee does not exists")
        validate_employee_data(emp_data)
        leave_application_doc = frappe.get_doc(
            dict(
                doctype="Leave Application",
                employee=emp_data.get("name"),
                company=emp_data.company,
                leave_approver=get_leave_approver(emp_data.name),
            )
        )
        leave_application_doc.update(kwargs)
        res = leave_application_doc.insert()
        gen_response(200, "Leave Application Successfully Added",res)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_leave_type(from_date=None, to_date=None):
    try:
        emp_data = get_employee_by_user(frappe.session.user)
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        leave_types = frappe.get_all(
            "Leave Type", filters={}, fields=["name", "'0' as balance"]
        )
        for leave_type in leave_types:
            leave_type["balance"] = get_leave_balance_on(
                emp_data.get("name"),
                leave_type.get("name"),
                from_date,
                consider_all_leaves_in_the_allocation_period=True,
            )
        return gen_response(200, "Leave Type Get Successfully", leave_types)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def get_expense_list(month=None, year=None):
    try:
        emp_data = get_employee_by_user(frappe.session.user)
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        if not len(emp_data) >= 1:
            return gen_response(500, "Employee does not exist")
        validate_employee_data(emp_data)

        filters = {"employee": emp_data.get("name")}

        # Add filters for month and year if provided
        if month and year:
            start_date = frappe.utils.getdate(f"{year}-{month}-01")
            end_date = frappe.utils.get_last_day(start_date)
            filters["posting_date"] = ["between", [start_date, end_date]]

        expense_list = frappe.get_all(
            "Expense Claim",
            filters=filters,
            fields=["*"],
        )

        expense_data = []
        for expense in expense_list:
            (
                expense["expense_type"],
                expense["expense_description"],
                expense["expense_date"],
            ) = frappe.get_value(
                "Expense Claim Detail",
                {"parent": expense.name},
                ["expense_type", "description", "expense_date"],
            )
            expense["expense_date"] = expense["expense_date"].strftime("%d-%m-%Y")
            expense["posting_date"] = expense["posting_date"].strftime("%d-%m-%Y")
            expense["attachments"] = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Expense Claim",
                    "attached_to_name": expense.name,
                    "is_folder": 0,
                },
                fields=["file_url"],
            )

            expense_data.append(expense)

        return gen_response(200, "Expense Date Get Successfully", expense_data)

    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def get_attendance_list(year=None, month=None):
    try:
        if not year or not month:
            return gen_response(500, "year and month is required", [])
        emp_data = get_employee_by_user(frappe.session.user)
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        present_count = 0
        absent_count = 0
        late_count = 0
        halfday_count=0
        onleave_count=0
        

        employee_attendance_list = frappe.get_all(
            "Attendance",
            filters={
                "employee": emp_data.get("name"),
                "attendance_date": [
                    "between",
                    [
                        f"{int(year)}-{int(month)}-01",
                        f"{int(year)}-{int(month)}-{calendar.monthrange(int(year), int(month))[1]}",
                    ],
                ],
            },
            fields=[
                "name",
                "attendance_date",
                "status",
                "working_hours",
                "time_format(in_time, '%h:%i%p') as in_time",
                "time_format(out_time, '%h:%i%p') as out_time",
                "late_entry",
            ],
        )

        if not employee_attendance_list:
            return gen_response(500, "No attendance found for this year and month", [])

        for attendance in employee_attendance_list:
            employee_checkin_details = frappe.get_all(
                "Employee Checkin",
                filters={"attendance": attendance.get("name")},
                fields=["log_type", "time_format(time, '%h:%i%p') as time"],
            )

            attendance["employee_checkin_detail"] = employee_checkin_details

            if attendance["status"] == "Present":
                present_count += 1

                if attendance["late_entry"] == 1:
                    late_count += 1

            elif attendance["status"] == "Absent":
                absent_count += 1
            
            elif attendance["status"] == "Half Day":
                halfday_count += 1
            
            elif attendance["status"] == "On Leave":
                onleave_count += 1

            del attendance["name"]
            # del attendance["status"]
            del attendance["late_entry"]

        attendance_details = {
            "days_in_month": calendar.monthrange(int(year), int(month))[1],
            "present": present_count,
            "absent": absent_count,
            "late": late_count,
            "half day":halfday_count,
            "on leave":onleave_count
        }
        attendance_data = {
            "attendance_details": attendance_details,
            "attendance_list": employee_attendance_list,
        }
        return gen_response(
            200, "Attendance data getting Successfully", attendance_data
        )

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
                    "company_name"
                ],
                filters={"company": company},
            )
        list=remove_duplicates(list,lambda item: item['company_name'])
        gen_response(200,"List get successfully", list)
    except Exception as e:
        return exception_handel(e)


@frappe.whitelist()
def apply_expense():
    try:
        emp_data = get_employee_by_user(
            frappe.session.user, fields=["name", "company", "expense_approver"]
        )
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        if not len(emp_data) >= 1:
            return gen_response(500, "Employee does not exists")
        validate_employee_data(emp_data)

        payable_account = get_payable_account(emp_data.get("company"))
        expense_doc = frappe.get_doc(
            dict(
                doctype="Expense Claim",
                employee=emp_data.name,
                expense_approver=emp_data.expense_approver,
                expenses=[
                    {
                        "expense_date": frappe.form_dict.expense_date,
                        "expense_type": frappe.form_dict.expense_type,
                        "description": frappe.form_dict.description,
                        "amount": frappe.form_dict.amount,
                    }
                ],
                posting_date=today(),
                company=emp_data.get("company"),
                payable_account=payable_account,
            )
        ).insert()

        from frappe.handler import upload_file

        if "file" in frappe.request.files:
            file = upload_file()
            file.attached_to_doctype = "Expense Claim"
            file.attached_to_name = expense_doc.name
            file.save(ignore_permissions=True)

        return gen_response(200, "Expense applied Successfully", frappe.request.files)
    except Exception as e:
        return exception_handel(e)

@frappe.whitelist()
def get_leave_application_list():
    try:
        emp_data = get_employee_by_user(frappe.session.user)
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        validate_employee_data(emp_data)
        leave_application_fields = [
            "name",
            "leave_type",
            "DATE_FORMAT(from_date, '%d-%m-%Y') as from_date",
            "DATE_FORMAT(to_date, '%d-%m-%Y') as to_date",
            "total_leave_days",
            "description",
            "status",
            "posting_date",
        ]
        upcoming_leaves = frappe.get_all(
            "Leave Application",
            filters={"from_date": [">", today()], "employee": emp_data.get("name")},
            fields=leave_application_fields,
        )

        taken_leaves = frappe.get_all(
            "Leave Application",
            fields=leave_application_fields,
            filters={"from_date": ["<=", today()], "employee": emp_data.get("name")},
        )
        fiscal_year = get_fiscal_year(nowdate())[0]
        if not fiscal_year:
            return gen_response(500, "Fiscal year not set")
        res = get_leave_balance_report(
            emp_data.get("name"), emp_data.get("company"), fiscal_year
        )
        leave_applications = {
            "upcoming": upcoming_leaves,
            "taken": taken_leaves,
            "balance": res["result"],
        }
        return gen_response(200, "leave data getting successfully", leave_applications)
    except Exception as e:
        return exception_handel(e)


def get_leave_balance_report(employee, company, fiscal_year):
    fiscal_year = get_fiscal_year(fiscal_year=fiscal_year, as_dict=True)
    year_start_date = get_date_str(fiscal_year.get("year_start_date"))
    year_end_date = get_date_str(fiscal_year.get("year_end_date"))
    filters_leave_balance = {
        "from_date": year_start_date,
        "to_date": year_end_date,
        "company": company,
        "employee": employee,
    }
    from frappe.desk.query_report import run

    return run("Employee Leave Balance", filters=filters_leave_balance)




@frappe.whitelist()
def book_expense(**kwargs):
    try:
        emp_data = get_employee_by_user(
            frappe.session.user, fields=["name", "company", "expense_approver"]
        )
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        if not len(emp_data) >= 1:
            return gen_response(500, "Employee does not exists")
        validate_employee_data(emp_data)
        data = kwargs
        
        payable_account = get_payable_account(emp_data.get("company"))
        expense_doc = frappe.get_doc(
            dict(
                doctype="Expense Claim",
                employee=emp_data.name,
                expense_approver=emp_data.expense_approver,
                expenses=[
                    {
                        "expense_date": data.get("expense_date"),
                        "expense_type": data.get("expense_type"),
                        "description": data.get("expense_description"),
                        "amount": data.get("amount"),
                        
                    }
                ],
                grand_total=data.get("amount"),
                posting_date=today(),
                company=emp_data.get("company"),
                payable_account=payable_account,
            )
        ).insert()
        
        # expense_doc.submit()
        if not data.get("attachments") == None:
            for file in data.get("attachments"):
                frappe.db.set_value(
                    "File", file.get("name"), "attached_to_doctype", "Expense Claim"
                )
                frappe.db.set_value(
                    "File", file.get("name"), "attached_to_name", expense_doc.name
                )
        return gen_response(200, "Expense applied Successfully", expense_doc)
    except Exception as e:
        return exception_handel(e)




# @frappe.whitelist()
def get_payable_account(company):
    try:
        default_payable_account = frappe.db.get_value(
                "Company", company, "default_payable_account"
            )
        return default_payable_account
    except Exception as e:
           return exception_handel(e)


@frappe.whitelist()
def get_attendance_details_dashboard():
    try:
        emp_data = get_employee_by_user(frappe.session.user, fields=["name", "company"])
        if isinstance(emp_data, str):
            return gen_response(400,emp_data)
        attendance_details = get_attendance_details(emp_data)
        return gen_response(
            200, "Attendance data get successfully", attendance_details
        )
    except Exception as e:
        return exception_handel(e)


def get_attendance_details(emp_data):
    last_date = get_last_day(today())
    first_date = get_first_day(today())
    total_days = date_diff(last_date, first_date)
    till_date_days = date_diff(today(), first_date)
    days_off = 0
    absent = 0
    total_present = 0
    attendance_report = run_attendance_report(
        emp_data.get("name"), emp_data.get("company")
    )
    if attendance_report:
        days_off = flt(attendance_report.get("total_leaves")) + flt(
            attendance_report.get("total_holidays")
        )
        absent = till_date_days - (
            flt(days_off) + flt(attendance_report.get("total_present"))
        )
        total_present = attendance_report.get("total_present")
    attendance_details = {
        "month_title": f"{frappe.utils.getdate().strftime('%B')} Details",
        "till_days":till_date_days,
        "total_days":total_days,
        "day off":float(days_off),
        "present":float(total_present),
        "absent":abs(float(absent))
        # "data": [
        #     {
        #         "type": "Total Days",
        #         "data": [
        #             till_date_days,
        #             total_days,
        #         ],
        #     },
        #     {
        #         "type": "Presents",
        #         "data": [
        #             total_present,
        #             till_date_days,
        #         ],
        #     },
        #     {
        #         "type": "Absents",
        #         "data": [
        #             absent,
        #             till_date_days,
        #         ],
        #     },
        #     {
        #         "type": "Days off",
        #         "data": [
        #             days_off,
        #             till_date_days,
        #         ],
        #     },
        # ],
    }
    return attendance_details

@frappe.whitelist()
def run_attendance_report(employee, company):
    filters = {
        "month": cstr(frappe.utils.getdate().month),
        "year": cstr(frappe.utils.getdate().year),
        "company": company,
        "employee": employee,
        "summarized_view": 1,
    }
    from frappe.desk.query_report import run

    attendance_report = run("Monthly Attendance Sheet", filters=filters)
    if attendance_report.get("result"):
        return attendance_report.get("result")[0]

