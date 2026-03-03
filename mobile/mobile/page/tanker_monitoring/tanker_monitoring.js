frappe.pages['tanker-monitoring'].on_page_load = function(wrapper) {
	var page = frappe.make_page(wrapper);
	$(wrapper).find('.layout-main-section').html('<h1>JS IS WORKING</h1>');
}