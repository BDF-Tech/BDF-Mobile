frappe.pages['sales-analytics-dash'].on_page_load = function(wrapper) {

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Sales Analytics Dashboard',
        single_column: true
    });

    // ======================
    // LOADER (PROFESSIONAL VERSION)
    // ======================

    let loader = $(`
    <div id="dashboard-loader" style="
        position:fixed;
        top:0;
        left:0;
        width:100%;
        height:100%;
        background: rgba(255, 255, 255, 0.7);
        backdrop-filter: blur(4px);
        display:none;
        align-items:center;
        justify-content:center;
        z-index:10001;
        transition: all 0.3s ease;
    ">
        <div class="loader-container" style="text-align:center;">
            <div class="modern-spinner">
                <div></div><div></div><div></div><div></div>
            </div>
            <div style="margin-top:15px; font-weight:500; color:#1f2937; letter-spacing:0.5px; font-size:13px;">
                FETCHING ANALYTICS...
            </div>
        </div>
    </div>
`).appendTo('body');

// Inject Professional Spinner CSS
$(`<style>
.modern-spinner {
  display: inline-block;
  position: relative;
  width: 64px;
  height: 64px;
}
.modern-spinner div {
  box-sizing: border-box;
  display: block;
  position: absolute;
  width: 51px;
  height: 51px;
  margin: 6px;
  border: 4px solid #3b82f6;
  border-radius: 50%;
  animation: modern-spinner 1.2s cubic-bezier(0.5, 0, 0.5, 1) infinite;
  border-color: #3b82f6 transparent transparent transparent;
}
.modern-spinner div:nth-child(1) { animation-delay: -0.45s; }
.modern-spinner div:nth-child(2) { animation-delay: -0.3s; }
.modern-spinner div:nth-child(3) { animation-delay: -0.15s; }

@keyframes modern-spinner {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>`).appendTo('head');

    function show_loader() {
        $("#dashboard-loader").css('display', 'flex').hide().fadeIn(200);
    }

    function hide_loader() {
        $("#dashboard-loader").fadeOut(200);
    }

    // ======================
    // FILTERS
    // ======================

    let period = page.add_field({
        label: 'Period',
        fieldtype: 'Select',
        options: ['Today','Weekly','Monthly','Quarterly','Yearly','Custom'],
        default: 'Monthly',
        change() {
            set_dates();
        }
    });

    let from_date = page.add_field({
        label: 'From Date',
        fieldtype: 'Date'
    });

    let to_date = page.add_field({
        label: 'To Date',
        fieldtype: 'Date'
    });

    let view_by = page.add_field({
        label: 'View By',
        fieldtype: 'Select',
        options: ['Top Customers', 'Territory Wise'],
        default: 'Top Customers'
    });

    function set_dates() {
        let today = frappe.datetime.get_today();
        let p = period.get_value();

        if (p === 'Today') {
            from_date.set_value(today);
            to_date.set_value(today);
        } else if (p === 'Weekly') {
            from_date.set_value(frappe.datetime.add_days(today, -7));
            to_date.set_value(today);
        } else if (p === 'Monthly') {
            from_date.set_value(frappe.datetime.add_months(today, -1));
            to_date.set_value(today);
        } else if (p === 'Quarterly') {
            from_date.set_value(frappe.datetime.add_months(today, -3));
            to_date.set_value(today);
        } else if (p === 'Yearly') {
            from_date.set_value(frappe.datetime.add_years(today, -1));
            to_date.set_value(today);
        }
    }

    set_dates();

    page.set_primary_action('Load Data', () => {

        show_loader();   // ✅ START LOADER

        if (view_by.get_value() === "Top Customers") {
            load_top_customers();
        } else {
            load_territory_sales();
        }

    });

    // ======================
    // TOP SECTION
    // ======================

    let top_section = $(`
        <div style="margin-top:20px;">
            <h3>Analytics</h3>
            <div id="top-customers" style="display:flex;flex-wrap:wrap;gap:15px;"></div>
        </div>
    `).appendTo(page.body);

    // ======================
    // TOP CUSTOMERS
    // ======================

    function load_top_customers() {
        frappe.call({
            method: 'mobile.mobile.page.sales_analytics_dash.sales_analytics_dash.get_top_customers',
            args: {
                from_date: from_date.get_value(),
                to_date: to_date.get_value()
            },
            callback: function(r) {

                let container = $("#top-customers");
                container.empty();

                if (!r.message || r.message.length === 0) {
                    container.html("<p>No Data Found</p>");
                    hide_loader();   // ✅ STOP LOADER
                    return;
                }

                r.message.forEach((cust, index) => {

                    let highlight = index < 3 ? 'border:2px solid #16a34a;' : '';

                    let card = $(`
                        <div style="
                            width:260px;
                            padding:16px;
                            border-radius:12px;
                            background:#fff;
                            border:1px solid #e5e7eb;
                            box-shadow:0 2px 6px rgba(0,0,0,0.05);
                            cursor:pointer;
                            ${highlight}
                        ">
                            <div style="font-size:12px;color:#999;">#${index+1}</div>
                            <div style="font-weight:600;font-size:15px;">
                                ${cust.customer_name || cust.customer}
                            </div>
                            <div style="font-size:12px;color:#666;">
                                ${cust.customer}
                            </div>
                            <div style="margin-top:10px;font-size:18px;font-weight:700;color:#16a34a;">
                                ${format_currency(cust.total)}
                            </div>
                        </div>
                    `);

                    card.on("click", () => {
                        frappe.set_route("Form", "Customer", cust.customer);
                    });

                    container.append(card);
                });

                hide_loader();   // ✅ STOP LOADER
            }
        });
    }

    // ======================
    // TERRITORY SALES
    // ======================

    function load_territory_sales() {
        frappe.call({
            method: 'mobile.mobile.page.sales_analytics_dash.sales_analytics_dash.get_territory_sales',
            args: {
                from_date: from_date.get_value(),
                to_date: to_date.get_value()
            },
            callback: function(r) {

                let container = $("#top-customers");
                container.empty();

                if (!r.message || r.message.length === 0) {
                    container.html("<p>No Data Found</p>");
                    hide_loader();   // ✅ STOP LOADER
                    return;
                }

                r.message.forEach((row, index) => {

                    let growth_color = row.growth >= 0 ? "#16a34a" : "#dc2626";
                    let arrow = row.growth >= 0 ? "▲" : "▼";

                    let card = $(`
                        <div style="
                            width:260px;
                            padding:16px;
                            border-radius:12px;
                            background:#fff;
                            border:1px solid #e5e7eb;
                            box-shadow:0 2px 6px rgba(0,0,0,0.05);
                        ">
                            <div style="font-size:12px;color:#999;">#${index+1}</div>

                            <div style="font-weight:600;font-size:15px;">
                                ${row.territory || "No Territory"}
                            </div>

                            <div style="margin-top:8px;font-size:18px;font-weight:700;color:#2563eb;">
                                ${format_currency(row.total)}
                            </div>

                            <div style="margin-top:6px;font-size:13px;color:${growth_color};font-weight:600;">
                                ${arrow} ${Math.abs(row.growth)}%
                            </div>
                        </div>
                    `);

                    container.append(card);
                });

                hide_loader();   // ✅ STOP LOADER
            }
        });
    }

};