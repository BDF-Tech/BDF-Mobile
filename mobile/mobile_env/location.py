import frappe
from frappe import _
from mobile.mobile_env.app_utils import (
    gen_response,
    ess_validate,
    get_employee_by_user,
    exception_handel,
)
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

"""save user location"""

"""{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [72.855663, 19.080709],
          [72.871113, 19.09531],
          [72.873344, 19.078438],
          [72.86459, 19.067731],
          [72.848454, 19.073084],
          [72.854633, 19.081521],
          [72.840214, 19.105204]
        ]
      }
    }
  ]
}
"""


@frappe.whitelist()
def user_location(longitude, latitude,device_id):
    try:
       
        data =  {
        "device_id":device_id,
        "location_table": [
            {
                "longitude": longitude,
                "latitude": latitude 
            }
        ]
    }

        if not data.get("location_table"):
            return gen_response(500, "location is required.")
        # current_employee = get_employee_by_user(frappe.session.user)
        if not frappe.db.exists(
            "Employee Location",
            {"user":frappe.session.user, 
             "date": today()},
            cache=True,
        ):
            location_doc = frappe.get_doc(
                dict(
                    doctype="Employee Location",
                    user=frappe.session.user,
                    date=today(),
                )
            )
            location_doc.update(data)
            location_doc.insert()
        else:
            location_doc = frappe.get_doc(
                "Employee Location",
                {
                   "user":frappe.session.user,
                    "date": today(),
                },
            )
            for location in data.get("location_table"):
                location_doc.append("location_table", location)

            # Load the formatted JSON string back into a Python object (dictionary)
            # parsed_json = json.loads(
            # )
            # Convert the Python object back to a compact JSON string
            compact_json = """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [72.855663, 19.080709],
          [72.871113, 19.09531],
          [72.873344, 19.078438],
          [72.86459, 19.067731],
          [72.848454, 19.073084],
          [72.854633, 19.081521]
        ]
      }
    }
  ]
}
"""
            # frappe.log_error(title="ESS Mobile App debug", message=compact_json)
            location_doc.location_map = compact_json
            location_doc.save()

        gen_response(200, "Location updated successfully.",location_doc)

    except Exception as e:
        return exception_handel(e)
    
    


@frappe.whitelist()
def getLocation():
  try:
    doc_name=frappe.get_value("Employee Location",{"user":frappe.session.user,"date":today()},"name")
    if(doc_name):
      doc = frappe.get_doc("Employee Location",doc_name)
      gen_response(200, "Location get successfully.",doc)

  except Exception as e:
        return exception_handel(e)