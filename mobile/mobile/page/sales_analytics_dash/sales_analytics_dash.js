frappe.pages['sales-analytics-dash'].on_page_load = function(wrapper) {

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Sales Analytics Dashboard',
        single_column: true
    });

    // ======================
    // LOADER & CSS GUARD
    // ======================
    let loader = $(`
        <div id="dashboard-loader" style="
            position:fixed; top:0; left:0; width:100%; height:100%;
            background: rgba(255,255,255,0.7); backdrop-filter: blur(4px);
            display:none; align-items:center; justify-content:center; z-index:10001;
        ">
            <div class="modern-spinner">
                <div></div><div></div><div></div><div></div>
            </div>
        </div>
    `).appendTo('body');

    // OPTIMIZATION: Prevent duplicate CSS injection on hot reloads
    if ($('#sales-dash-styles').length === 0) {
        $(`<style id="sales-dash-styles">
        .modern-spinner { display: inline-block; position: relative; width: 64px; height: 64px; }
        .modern-spinner div { box-sizing: border-box; display: block; position: absolute; width: 51px; height: 51px; margin: 6px; border: 4px solid #3b82f6; border-radius: 50%; animation: modern-spinner 1.2s linear infinite; border-color: #3b82f6 transparent transparent transparent; }
        .modern-spinner div:nth-child(1) { animation-delay: -0.45s; }
        .modern-spinner div:nth-child(2) { animation-delay: -0.3s; }
        .modern-spinner div:nth-child(3) { animation-delay: -0.15s; }
        @keyframes modern-spinner { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        </style>`).appendTo('head');
    }

    // OPTIMIZATION: Throttle button to prevent database spamming
    function show_loader() { 
        $("#dashboard-loader").css('display','flex'); 
        if (page.btn_primary) page.btn_primary.prop('disabled', true);
    }
    function hide_loader() { 
        $("#dashboard-loader").hide(); 
        if (page.btn_primary) page.btn_primary.prop('disabled', false);
    }

    // ======================
    // DYNAMIC FILTERS
    // ======================
    
    // Added Company Filter
    let company_filter = page.add_field({
        label: 'Company',
        fieldtype: 'Link',
        options: 'Company',
        default: frappe.defaults.get_user_default("Company")
    });

    let filter_type = page.add_field({
        label: 'Filter By',
        fieldtype: 'Select',
        options: ['', 'Customer', 'Territory', 'Item'],
        change() {
            let type = filter_type.get_value();
            filter_group.set_value('');

            if (type === 'Customer') {
                filter_group.df.options = 'Customer Group';
                filter_group.df.label = 'Customer Group';
                $(filter_group.wrapper).show();
            } else if (type === 'Item') {
                filter_group.df.options = 'Item Group';
                filter_group.df.label = 'Item Group';
                $(filter_group.wrapper).show();
            } else {
                $(filter_group.wrapper).hide();
            }
            filter_group.refresh();
        }
    });

    let filter_group = page.add_field({ label: 'Group', fieldtype: 'Link', options: 'Customer Group' });
    $(filter_group.wrapper).hide();

    let period = page.add_field({
        label: 'Period',
        fieldtype: 'Select',
        options: ['Today','Weekly','Monthly','Quarterly','Yearly','Custom'],
        default: 'Monthly',
        change() { set_dates(); }
    });

    let from_date = page.add_field({ label: 'From Date', fieldtype: 'Date' });
    let to_date = page.add_field({ label: 'To Date', fieldtype: 'Date' });
    
    let ranking_filter = page.add_field({ label: 'Ranking', fieldtype: 'Select', options: ['Top 10', 'Lowest 10', 'All'], default: 'Top 10' });

    function set_dates() {
        let today = frappe.datetime.get_today();
        let p = period.get_value();
        if (p === 'Today') { from_date.set_value(today); to_date.set_value(today); } 
        else if (p === 'Weekly') { from_date.set_value(frappe.datetime.add_days(today, -7)); to_date.set_value(today); } 
        else if (p === 'Monthly') { from_date.set_value(frappe.datetime.add_months(today, -1)); to_date.set_value(today); } 
        else if (p === 'Quarterly') { from_date.set_value(frappe.datetime.add_months(today, -3)); to_date.set_value(today); } 
        else if (p === 'Yearly') { from_date.set_value(frappe.datetime.add_years(today, -1)); to_date.set_value(today); }
    }
    set_dates();

    // ======================
    // LAYOUT SECTIONS 
    // ======================
    let customer_section = $(`
        <div id="customer-section" style="margin-top:20px; display:none;">
            <h3>Customer Sales</h3>
            <div id="top-customers-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="customer-chart"></div>
        </div>
    `).appendTo(page.body);

    let item_section = $(`
        <div id="item-section" style="margin-top:30px; border-top: 1px solid #e5e7eb; padding-top: 20px; display:none;">
            <h3>Item Sales</h3>
            <div id="top-items-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="item-chart"></div>
        </div>
    `).appendTo(page.body);

    let territory_section = $(`
        <div id="territory-section" style="margin-top:30px; border-top: 1px solid #e5e7eb; padding-top: 20px; display:none;">
            <h3>Territory Sales</h3>
            <div id="territory-cards-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="territory-chart"></div>
        </div>
    `).appendTo(page.body);

    let customer_chart = null, item_chart = null, territory_chart = null;

    // ======================
    // MASTER LOAD FUNCTION
    // ======================
    page.set_primary_action('Load Data', () => {
        let type = filter_type.get_value();
        
        let fetch_customers = (type === 'Customer' || !type) ? 1 : 0;
        let fetch_items = (type === 'Item' || !type) ? 1 : 0;
        let fetch_territories = (type === 'Territory' || !type) ? 1 : 0;

        if (fetch_customers + fetch_items + fetch_territories === 0) return;
        
        show_loader();

        // 1. Toggle UI Sections Instantly
        fetch_customers ? customer_section.show() : customer_section.hide();
        fetch_items ? item_section.show() : item_section.hide();
        fetch_territories ? territory_section.show() : territory_section.hide();

        // 2. Build Single API Payload
        let args = {
            company: company_filter.get_value(), // Added company parameter
            from_date: from_date.get_value(),
            to_date: to_date.get_value(),
            ranking: ranking_filter.get_value(),
            customer_group: type === 'Customer' ? filter_group.get_value() : null,
            item_group: type === 'Item' ? filter_group.get_value() : null,
            fetch_customers: fetch_customers,
            fetch_items: fetch_items,
            fetch_territories: fetch_territories
        };

        // 3. One Call to Rule Them All
        frappe.call({
            method: 'mobile.mobile.page.sales_analytics_dash.sales_analytics_dash.get_dashboard_data',
            args: args,
            callback: function(r) {
                if (r.message) {
                    if (fetch_customers) render_customers(r.message.customers);
                    if (fetch_items) render_items(r.message.items);
                    if (fetch_territories) render_territories(r.message.territories);
                }
                hide_loader();
            }
        });
    });

    // ======================
    // DOM RENDERING METHODS (BATCHED & RECYCLED)
    // ======================
    function render_customers(data) {
        let container = $("#top-customers-container");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Customer Data Found.</p>");
            if (customer_chart) { customer_chart.destroy(); customer_chart = null; }
            return;
        }

        let html = ""; 
        let labels = [];
        let values = [];
        let ranking = ranking_filter.get_value();

        data.forEach((cust, index) => {
            let highlight = index < 3 && (ranking === 'Top 10' || ranking === 'All') ? 'border:2px solid #16a34a;' : '';
            let name = cust.customer_name || cust.customer;
            
            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(Number(cust.total) || 0);

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;${highlight}">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="font-size: 12px; color: #4b5563;">${cust.customer}</div>
                    <div style="color:#16a34a;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${format_currency(cust.total)}
                    </div>
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: "Sales", values: values }] };

        // OPTIMIZATION: Recycle existing chart if it exists
        if (customer_chart) {
            customer_chart.update(chart_data);
        } else {
            customer_chart = new frappe.Chart("#customer-chart", {
                title: "Sales by Customer",
                data: chart_data,
                type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 },
                tooltipOptions: { formatTooltipY: d => format_currency(d) }
            });
        }
    }

    function render_items(data) {
        let container = $("#top-items-container");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Item Data Found.</p>");
            if (item_chart) { item_chart.destroy(); item_chart = null; }
            return;
        }

        let html = "";
        let labels = [];
        let values = [];
        let ranking = ranking_filter.get_value();

        data.forEach((itm, index) => {
            let highlight = index < 3 && (ranking === 'Top 10' || ranking === 'All') ? 'border:2px solid #16a34a;' : '';
            let name = itm.item_name || itm.item_code;
            let qty = Number(itm.total_qty) || 0;
            
            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(Number(itm.total) || 0);

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;${highlight}">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="font-size: 12px; color: #4b5563;">${itm.item_code}</div>
                    <div style="color:#2563eb;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${format_currency(itm.total)}
                    </div>
                    <div style="color:#6b7280; font-size: 13px; font-weight: 500; margin-top: 4px;">
                        <span style="color:#0ea5e9; font-weight: 600;">${qty}</span> Units Sold
                    </div>
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: "Sales", values: values }] };

        // OPTIMIZATION: Recycle existing chart if it exists
        if (item_chart) {
            item_chart.update(chart_data);
        } else {
            item_chart = new frappe.Chart("#item-chart", {
                title: "Sales by Item",
                data: chart_data,
                type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 },
                tooltipOptions: { formatTooltipY: d => format_currency(d) }
            });
        }
    }

    function render_territories(data) {
        let container = $("#territory-cards-container");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Territory Data Found.</p>");
            if (territory_chart) { territory_chart.destroy(); territory_chart = null; }
            return;
        }

        let html = "";
        let labels = [];
        let values = [];

        data.forEach((row, index) => {
            let growth_color = row.growth >= 0 ? "#16a34a" : "#dc2626";
            let arrow = row.growth >= 0 ? "▲" : "▼";
            let name = row.territory || "No Territory";

            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(Number(row.total) || 0);

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="color:#2563eb;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${format_currency(row.total)}
                    </div>
                    <div style="color:${growth_color}; font-size: 13px; margin-top: 4px;">
                        ${arrow} ${Math.abs(row.growth)}% vs Prev Period
                    </div>
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: "Sales", values: values }] };

        // OPTIMIZATION: Recycle existing chart if it exists
        if (territory_chart) {
            territory_chart.update(chart_data);
        } else {
            territory_chart = new frappe.Chart("#territory-chart", {
                title: "Sales by Territory",
                data: chart_data,
                type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 },
                tooltipOptions: { formatTooltipY: d => format_currency(d) }
            });
        }
    }

    // OPTIMIZATION: Auto-load data once filters are rendered
    setTimeout(() => {
        if (page.btn_primary) page.btn_primary.trigger('click');
    }, 100);
};