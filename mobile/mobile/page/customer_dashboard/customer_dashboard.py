import frappe


@frappe.whitelist()
def get_customer_details(customer=None):

    filters = {}

    if customer:
        filters["name"] = customer

    customers = frappe.get_all(
        "Customer",
        filters=filters,
        fields=[
            "name",
            "customer_name",
            "default_price_list",
            "custom_starting_date_of_the_contract",
            "food_license_number",
            "food_license_validity"
        ]
    )

    return customers