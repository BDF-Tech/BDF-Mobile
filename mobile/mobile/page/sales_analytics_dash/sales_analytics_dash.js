frappe.pages['sales-analytics-dash'].on_page_load = function(wrapper) {

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Sales Analytics Dashboard',
        single_column: true
    });

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

        if (view_by.get_value() === "Top Customers") {
            load_top_customers();
        } else {
            load_territory_sales();
        }

        load_chart();
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
            }
        });
    }

    // ======================
    // TERRITORY SALES (WITH GROWTH)
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
            }
        });
    }

    // ======================
    // CHART
    // ======================

    let chart_section = $(`
        <div style="margin-top:40px;">
            <h3>Sales Trend</h3>
            <div id="chart"></div>
        </div>
    `).appendTo(page.body);

    let chart;

    function load_chart() {
        frappe.call({
            method: 'mobile.mobile.page.sales_analytics_dash.sales_analytics_dash.get_sales_trend',
            args: {
                from_date: from_date.get_value(),
                to_date: to_date.get_value(),
                period: period.get_value()
            },
            callback: function(r) {

                if (!r.message || r.message.length === 0) {
                    $("#chart").html("<p>No Data Found</p>");
                    return;
                }

                let labels = r.message.map(d => d.label);
                let values = r.message.map(d => d.total);

                let percent_change = values.map((val, i) => {
                    if (i === 0) return 0;
                    let prev = values[i - 1] || 1;
                    return (((val - prev) / prev) * 100).toFixed(1);
                });

                if (chart) chart.destroy();

                chart = new frappe.Chart("#chart", {
                    title: "Sales Trend",
                    data: {
                        labels: labels,
                        datasets: [
                            { name: "Sales", values: values },
                            { name: "% Growth", values: percent_change }
                        ]
                    },
                    type: 'axis-mixed',
                    height: 320,
                    lineOptions: {
                        spline: true
                    },
                    tooltipOptions: {
                        formatTooltipY: d => format_currency(d)
                    }
                });
            }
        });
    }

};