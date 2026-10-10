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

    function fmt_currency(v) {
        return format_currency(parseFloat((Number(v) || 0).toFixed(2)));
    }

    function fmt_qty(v) {
        return parseFloat((Number(v) || 0).toFixed(2));
    }

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
    let ranking_filter; 
    let sort_by_filter; 

    let company_filter = page.add_field({
        label: 'Company',
        fieldtype: 'Link',
        options: 'Company',
        default: frappe.defaults.get_user_default("Company")
    });

    let filter_type = page.add_field({
        label: 'Filter By',
        fieldtype: 'Select',
        options: ['', 'Customer', 'Route', 'Item', 'Warehouse', 'Customer Comparison'],
        change() {
            let type = filter_type.get_value();
            
            filter_group.set_value('');
            compare_cust_1.set_value('');
            compare_cust_2.set_value('');
            compare_item.set_value(''); // Clear item when changing views

            // Hide EVERYTHING dependent by default
            $(filter_group.wrapper).hide();
            $(compare_cust_1.wrapper).hide();
            $(compare_cust_2.wrapper).hide();
            $(compare_item.wrapper).hide(); // <-- Hide compare item
            $(bifurcation.wrapper).hide();
            
            if (ranking_filter && ranking_filter.wrapper) {
                $(ranking_filter.wrapper).show();
            }
            if (sort_by_filter && sort_by_filter.wrapper) {
                $(sort_by_filter.wrapper).show();
            }

            if (type === 'Customer') {
                filter_group.df.options = 'Customer Group';
                filter_group.df.label = 'Customer Group';
                $(filter_group.wrapper).show();
            } else if (type === 'Item') {
                filter_group.df.options = 'Item Group';
                filter_group.df.label = 'Item Group';
                $(filter_group.wrapper).show();
            } else if (type === 'Customer Comparison') { 
                $(compare_cust_1.wrapper).show();
                $(compare_cust_2.wrapper).show();
                $(compare_item.wrapper).show(); // <-- Show compare item here
                $(bifurcation.wrapper).show();
                
                if (ranking_filter && ranking_filter.wrapper) {
                    $(ranking_filter.wrapper).hide();
                }
                if (sort_by_filter && sort_by_filter.wrapper) {
                    $(sort_by_filter.wrapper).hide(); 
                }
                $(filter_group.wrapper).hide();
            }
            filter_group.refresh();
        }
    });

    let filter_group = page.add_field({ label: 'Group', fieldtype: 'Link', options: 'Customer Group' });
    $(filter_group.wrapper).hide();

    let compare_cust_1 = page.add_field({ label: 'Customer A', fieldtype: 'Link', options: 'Customer' });
    let compare_cust_2 = page.add_field({ label: 'Customer B', fieldtype: 'Link', options: 'Customer' });
    
    // <-- NEW: Item filter specific to comparison
    let compare_item = page.add_field({ label: 'Specific Item (Opt)', fieldtype: 'Link', options: 'Item' });
    let bifurcation = page.add_field({ label: 'Bifurcation', fieldtype: 'Select', options: ['Daily', 'Weekly', 'Monthly'], default: 'Daily' });
    
    $(compare_cust_1.wrapper).hide();
    $(compare_cust_2.wrapper).hide();
    $(compare_item.wrapper).hide(); // <-- Hide on init
    $(bifurcation.wrapper).hide();

    let period = page.add_field({
        label: 'Period',
        fieldtype: 'Select',
        options: ['Today','Weekly','Monthly','Quarterly','Yearly','Custom'],
        default: 'Monthly',
        change() { set_dates(); }
    });

    let from_date = page.add_field({ label: 'From Date', fieldtype: 'Date' });
    let to_date = page.add_field({ label: 'To Date', fieldtype: 'Date' });
    
    ranking_filter = page.add_field({ label: 'Ranking', fieldtype: 'Select', options: ['Top 10', 'Lowest 10', 'All'], default: 'Top 10' });
    sort_by_filter = page.add_field({ label: 'Sort By', fieldtype: 'Select', options: ['Value', 'Quantity'], default: 'Value' });

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
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0;">Customer Sales</h3>
                <div id="customer-summary"></div>
            </div>
            <div id="top-customers-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="customer-chart"></div>
        </div>
    `).appendTo(page.body);

    let item_section = $(`
        <div id="item-section" style="margin-top:30px; border-top: 1px solid #e5e7eb; padding-top: 20px; display:none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0;">Item Sales</h3>
                <div id="item-summary"></div>
            </div>
            <div id="top-items-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="item-chart"></div>
        </div>
    `).appendTo(page.body);

    let territory_section = $(`
        <div id="territory-section" style="margin-top:30px; border-top: 1px solid #e5e7eb; padding-top: 20px; display:none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0;">Route Sales</h3>
                <div id="territory-summary"></div>
            </div>
            <div id="territory-cards-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="territory-chart"></div>
        </div>
    `).appendTo(page.body);

    let warehouse_section = $(`
        <div id="warehouse-section" style="margin-top:30px; border-top: 1px solid #e5e7eb; padding-top: 20px; display:none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0;">Warehouse Sales</h3>
                <div id="warehouse-summary"></div> <!-- NEW SUMMARY CONTAINER -->
            </div>
            <div id="top-warehouses-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="warehouse-chart"></div>
        </div>
    `).appendTo(page.body);

    let comparison_section = $(`
        <div id="comparison-section" style="margin-top:20px; display:none;">
            <h3>Time Series Comparison</h3>
            <div id="comparison-cards-container" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div style="display:flex; flex-direction:column; gap: 30px;">
                <div id="comparison-value-chart" style="width:100%;"></div>
                <div id="comparison-qty-chart" style="width:100%;"></div>
            </div>
        </div>
    `).appendTo(page.body);

    let customer_chart = null, item_chart = null, territory_chart = null, warehouse_chart = null, comp_value_chart = null, comp_qty_chart = null;

    // ======================
    // MASTER LOAD FUNCTION
    // ======================
    page.set_primary_action('Load Data', () => {
        let type = filter_type.get_value();
        
        let fetch_customers = (type === 'Customer' || !type) ? 1 : 0;
        let fetch_items = (type === 'Item' || !type) ? 1 : 0;
        let fetch_territories = (type === 'Route' || !type) ? 1 : 0;
        let fetch_warehouses = (type === 'Warehouse' || !type) ? 1 : 0;
        let fetch_comparison = (type === 'Customer Comparison') ? 1 : 0;
        
        if (fetch_comparison) {
            fetch_customers = 0; fetch_items = 0; fetch_territories = 0; fetch_warehouses = 0;
        }

        if (fetch_customers + fetch_items + fetch_territories + fetch_warehouses + fetch_comparison === 0) return;
        
        show_loader();

        fetch_customers ? customer_section.show() : customer_section.hide();
        fetch_items ? item_section.show() : item_section.hide();
        fetch_territories ? territory_section.show() : territory_section.hide();
        fetch_warehouses ? warehouse_section.show() : warehouse_section.hide();
        fetch_comparison ? comparison_section.show() : comparison_section.hide();

        let compare_array = [compare_cust_1.get_value(), compare_cust_2.get_value()].filter(Boolean);

        let args = {
            company: company_filter.get_value(),
            from_date: from_date.get_value(),
            to_date: to_date.get_value(),
            ranking: ranking_filter.get_value(),
            sort_by: sort_by_filter.get_value(),
            customer_group: type === 'Customer' ? filter_group.get_value() : null,
            item_group: type === 'Item' ? filter_group.get_value() : null,
            fetch_customers: fetch_customers,
            fetch_items: fetch_items,
            fetch_territories: fetch_territories,
            fetch_warehouses: fetch_warehouses,
            fetch_comparison: fetch_comparison,
            compare_customers: JSON.stringify(compare_array),
            compare_item: compare_item.get_value(), // <-- Pass item argument to backend
            bifurcation: bifurcation.get_value()
        };

        frappe.call({
            method: 'mobile.mobile.page.sales_analytics_dash.sales_analytics_dash.get_dashboard_data',
            args: args,
            callback: function(r) {
                if (r.message) {
                    if (fetch_customers) render_customers(r.message.customers);
                    if (fetch_items) render_items(r.message.items);
                    if (fetch_territories) render_territories(r.message.territories);
                    if (fetch_warehouses) render_warehouses(r.message.warehouses);
                    if (fetch_comparison) render_comparison(r.message.comparison);
                }
                hide_loader();
            }
        });
    });

    // ======================
    // DOM RENDERING METHODS 
    // ======================
    function render_customers(data) {
        let container = $("#top-customers-container");
        let summary_container = $("#customer-summary");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Customer Data Found.</p>");
            summary_container.empty();
            if (customer_chart) { customer_chart.destroy(); customer_chart = null; }
            return;
        }

        let grand_total_val = data.reduce((sum, row) => sum + (Number(row.total) || 0), 0);
        let grand_total_qty = data.reduce((sum, row) => sum + (Number(row.total_qty) || 0), 0);
        summary_container.html(`
            <div style="display:flex; gap: 20px; padding: 8px 16px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Value</div>
                    <div style="font-size: 16px; font-weight: 700; color: #16a34a;">${fmt_currency(grand_total_val)}</div>
                </div>
                <div style="width: 1px; background: #cbd5e1;"></div>
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Qty</div>
                    <div style="font-size: 16px; font-weight: 700; color: #f59e0b;">${fmt_qty(grand_total_qty)}</div>
                </div>
            </div>
        `);

        let html = "";
        let labels = [];
        let values = [];
        let ranking = ranking_filter.get_value();
        let sort_by = sort_by_filter.get_value();

        data.forEach((cust, index) => {
            let highlight = index < 3 && (ranking === 'Top 10' || ranking === 'All') ? 'border:2px solid #16a34a;' : '';
            let name = cust.customer_name || cust.customer;
            let qty = Number(cust.total_qty) || 0;
            
            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(sort_by === 'Quantity' ? qty : (Number(cust.total) || 0));

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;${highlight}">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="font-size: 12px; color: #4b5563;">${cust.customer}</div>
                    <div style="color:#16a34a;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${fmt_currency(cust.total)}
                    </div>
                    
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: sort_by === 'Quantity' ? "Units Sold" : "Sales", values: values }] };
        if (customer_chart) { customer_chart.update(chart_data); } 
        else {
            customer_chart = new frappe.Chart("#customer-chart", {
                title: `Sales by Customer (${sort_by})`, data: chart_data, type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 }, 
                tooltipOptions: { formatTooltipY: d => sort_by === 'Quantity' ? d : fmt_currency(d) }
            });
        }
    }

    function render_items(data) {
        let container = $("#top-items-container");
        let summary_container = $("#item-summary");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Item Data Found.</p>");
            summary_container.empty();
            if (item_chart) { item_chart.destroy(); item_chart = null; }
            return;
        }

        let grand_total_val = data.reduce((sum, row) => sum + (Number(row.total) || 0), 0);
        let grand_total_qty = data.reduce((sum, row) => sum + (Number(row.total_qty) || 0), 0);
        // Sum total_kg_sold only for rows where it is not null
        let grand_total_kg = data.reduce((sum, row) => sum + (row.total_kg_sold != null ? Number(row.total_kg_sold) : 0), 0);
        let show_kg_summary = data.some(row => row.total_kg_sold != null);

        summary_container.html(`
            <div style="display:flex; gap: 20px; padding: 8px 16px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Value</div>
                    <div style="font-size: 16px; font-weight: 700; color: #2563eb;">${fmt_currency(grand_total_val)}</div>
                </div>
                <div style="width: 1px; background: #cbd5e1;"></div>
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Qty</div>
                    <div style="font-size: 16px; font-weight: 700; color: #f59e0b;">${fmt_qty(grand_total_qty)}</div>
                </div>
                ${show_kg_summary ? `
                <div style="width: 1px; background: #cbd5e1;"></div>
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total KG Sold</div>
                    <div style="font-size: 16px; font-weight: 700; color: #8b5cf6;">${parseFloat(grand_total_kg.toFixed(3))} kg</div>
                </div>` : ''}
            </div>
        `);

        let html = ""; let labels = []; let values = [];
        let ranking = ranking_filter.get_value();
        let sort_by = sort_by_filter.get_value();

        data.forEach((itm, index) => {
            let highlight = index < 3 && (ranking === 'Top 10' || ranking === 'All') ? 'border:2px solid #16a34a;' : '';
            let name = itm.item_name || itm.item_code;
            let qty = Number(itm.total_qty) || 0;
            let kg_sold = itm.total_kg_sold;
            let kg_line = kg_sold != null
                ? `<div style="color:#6b7280; font-size: 13px; font-weight: 500; margin-top: 3px;">
                       <span style="color:#8b5cf6; font-weight: 700;">${parseFloat(Number(kg_sold).toFixed(3))} kg</span> Sold (weight)
                   </div>`
                : '';

            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(sort_by === 'Quantity' ? qty : (Number(itm.total) || 0));

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;${highlight}">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="font-size: 12px; color: #4b5563;">${itm.item_code}</div>
                    <div style="color:#2563eb;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${fmt_currency(itm.total)}
                    </div>
                    <div style="color:#6b7280; font-size: 13px; font-weight: 500; margin-top: 4px;">
                        <span style="color:#0ea5e9; font-weight: 600;">${fmt_qty(qty)}</span> Units Sold
                    </div>
                    ${kg_line}
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: sort_by === 'Quantity' ? "Units Sold" : "Sales", values: values }] };
        if (item_chart) { item_chart.update(chart_data); } 
        else {
            item_chart = new frappe.Chart("#item-chart", {
                title: `Sales by Item (${sort_by})`, data: chart_data, type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 }, 
                tooltipOptions: { formatTooltipY: d => sort_by === 'Quantity' ? d : fmt_currency(d) }
            });
        }
    }

    function render_territories(data) {
        let container = $("#territory-cards-container");
        let summary_container = $("#territory-summary");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Territory Data Found.</p>");
            summary_container.empty();
            if (territory_chart) { territory_chart.destroy(); territory_chart = null; }
            return;
        }

        let grand_total_val = data.reduce((sum, row) => sum + (Number(row.total) || 0), 0);
        let grand_total_qty = data.reduce((sum, row) => sum + (Number(row.total_qty) || 0), 0);
        summary_container.html(`
            <div style="display:flex; gap: 20px; padding: 8px 16px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Value</div>
                    <div style="font-size: 16px; font-weight: 700; color: #2563eb;">${fmt_currency(grand_total_val)}</div>
                </div>
                <div style="width: 1px; background: #cbd5e1;"></div>
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Qty</div>
                    <div style="font-size: 16px; font-weight: 700; color: #f59e0b;">${fmt_qty(grand_total_qty)}</div>
                </div>
            </div>
        `);

        let html = ""; let labels = []; let values = [];
        let sort_by = sort_by_filter.get_value();

        data.forEach((row, index) => {
            let growth_color = row.growth >= 0 ? "#16a34a" : "#dc2626";
            let arrow = row.growth >= 0 ? "▲" : "▼";
            let name = row.route || "No Route";
            let qty = Number(row.total_qty) || 0;

            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(sort_by === 'Quantity' ? qty : (Number(row.total) || 0));

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="color:#2563eb;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${fmt_currency(row.total)}
                    </div>
                    <div style="color:#6b7280; font-size: 13px; font-weight: 500; margin-top: 4px;">
                        <span style="color:#0ea5e9; font-weight: 600;">${fmt_qty(qty)}</span> Units Sold
                    </div>
                    <div style="color:${growth_color}; font-size: 13px; margin-top: 4px;">
                        ${arrow} ${Math.abs(row.growth)}% vs Prev Period
                    </div>
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: sort_by === 'Quantity' ? "Units Sold" : "Sales", values: values }] };
        if (territory_chart) { territory_chart.update(chart_data); } 
        else {
            territory_chart = new frappe.Chart("#territory-chart", {
                title: `Sales by Route (${sort_by})`, data: chart_data, type: 'bar', height: 320,
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 }, 
                tooltipOptions: { formatTooltipY: d => sort_by === 'Quantity' ? d : fmt_currency(d) }
            });
        }
    }

    function render_warehouses(data) {
        let container = $("#top-warehouses-container");
        let summary_container = $("#warehouse-summary"); // Target summary container
        
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Warehouse Data Found.</p>");
            summary_container.empty(); // Clear summary if no data
            if (warehouse_chart) { warehouse_chart.destroy(); warehouse_chart = null; }
            return;
        }

        // --- NEW: Calculate Totals ---
        let grand_total_val = data.reduce((sum, row) => sum + (Number(row.total) || 0), 0);
        let grand_total_qty = data.reduce((sum, row) => sum + (Number(row.total_qty) || 0), 0);

        // --- NEW: Render Summary Banner ---
        summary_container.html(`
            <div style="display:flex; gap: 20px; padding: 8px 16px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Value</div>
                    <div style="font-size: 16px; font-weight: 700; color: #10b981;">${fmt_currency(grand_total_val)}</div>
                </div>
                <div style="width: 1px; background: #cbd5e1;"></div>
                <div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600;">Total Qty</div>
                    <div style="font-size: 16px; font-weight: 700; color: #f59e0b;">${fmt_qty(grand_total_qty)}</div>
                </div>
            </div>
        `);

        let html = ""; let labels = []; let values = [];
        let ranking = ranking_filter.get_value();
        let sort_by = sort_by_filter.get_value();

        data.forEach((row, index) => {
            let highlight = index < 3 && (ranking === 'Top 10' || ranking === 'All') ? 'border:2px solid #10b981;' : '';
            let name = row.warehouse || "Unknown Warehouse";
            let qty = Number(row.total_qty) || 0;

            labels.push(name.length > 15 ? name.substring(0, 15) + "..." : name);
            values.push(sort_by === 'Quantity' ? qty : (Number(row.total) || 0));

            html += `
                <div style="width:260px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;${highlight}">
                    <div style="color:#6b7280; font-size: 12px;">#${index+1}</div>
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${name}</div>
                    <div style="color:#10b981;font-weight:bold; margin-top: 8px; font-size: 16px;">
                        ${fmt_currency(row.total)}
                    </div>
                    <div style="color:#6b7280; font-size: 13px; font-weight: 500; margin-top: 4px;">
                        <span style="color:#f59e0b; font-weight: 600;">${fmt_qty(qty)}</span> Units Sold
                    </div>
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels: labels, datasets: [{ name: sort_by === 'Quantity' ? "Units Sold" : "Sales", values: values }] };
        if (warehouse_chart) { warehouse_chart.update(chart_data); } 
        else {
            warehouse_chart = new frappe.Chart("#warehouse-chart", {
                title: `Sales by Warehouse (${sort_by})`, data: chart_data, type: 'bar', height: 320,
                colors: ['#10b981'], 
                axisOptions: { xAxisMode: 'tick', xIsSeries: false, shortenYAxisNumbers: 1 }, 
                barOptions: { spaceRatio: 0.3 }, 
                tooltipOptions: { formatTooltipY: d => sort_by === 'Quantity' ? d : fmt_currency(d) }
            });
        }
    }

    function render_comparison(data) {
        let container = $("#comparison-cards-container");
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No data found for these customers/items in the selected range.</p>");
            if (comp_value_chart) { comp_value_chart.destroy(); comp_value_chart = null; }
            if (comp_qty_chart) { comp_qty_chart.destroy(); comp_qty_chart = null; }
            return;
        }

        let unique_periods = [...new Set(data.map(d => d.period))];
        let unique_customers = [...new Set(data.map(d => d.customer_name || d.customer))];
        let selected_item = compare_item.get_value() ? `<br><span style="font-size:12px; color:#6b7280;">Item: ${compare_item.get_value()}</span>` : '';

        let html = "";
        unique_customers.forEach(cust => {
            let total_val = data.filter(d => (d.customer_name || d.customer) === cust).reduce((sum, row) => sum + Number(row.total_value), 0);
            let total_qty = data.filter(d => (d.customer_name || d.customer) === cust).reduce((sum, row) => sum + Number(row.total_qty), 0);

            html += `
                <div style="flex:1; min-width: 200px; padding:20px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0; text-align:center;">
                    <div style="font-weight: 700; font-size: 16px; margin-bottom: 12px; color:#1e293b;">${cust}${selected_item}</div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-size:12px; color:#64748b; text-transform:uppercase;">Overall Value</span><br>
                        <span style="color:#16a34a; font-weight:bold; font-size: 20px;">${fmt_currency(total_val)}</span>
                    </div>
                    <div>
                        <span style="font-size:12px; color:#64748b; text-transform:uppercase;">Overall Items Sold</span><br>
                        <span style="color:#0ea5e9; font-weight:bold; font-size: 20px;">${fmt_qty(total_qty)}</span>
                    </div>
                </div>
            `;
        });
        container.html(html);

        let datasets_value = unique_customers.map(cust => {
            return {
                name: cust,
                values: unique_periods.map(p => {
                    let match = data.find(d => d.period === p && (d.customer_name || d.customer) === cust);
                    return match ? Number(match.total_value) : 0;
                })
            };
        });

        let datasets_qty = unique_customers.map(cust => {
            return {
                name: cust,
                values: unique_periods.map(p => {
                    let match = data.find(d => d.period === p && (d.customer_name || d.customer) === cust);
                    return match ? Number(match.total_qty) : 0;
                })
            };
        });

        let line_colors = ['#16a34a', '#0ea5e9']; 

        let chart_data_val = { labels: unique_periods, datasets: datasets_value };
        
        // FIX: Clear the container and recreate the chart from scratch to force legend update
        if (comp_value_chart) {
            $("#comparison-value-chart").empty(); 
            comp_value_chart = null;
        } 
        
        comp_value_chart = new frappe.Chart("#comparison-value-chart", {
            title: `Value Comparison (${bifurcation.get_value()})`,
            data: chart_data_val, type: 'line', height: 280, colors: line_colors,
            axisOptions: { xAxisMode: 'tick', xIsSeries: true, shortenYAxisNumbers: 1 },
            tooltipOptions: { formatTooltipY: d => fmt_currency(d) },
            lineOptions: { regionFill: 1, hideDots: 0 }
        });

        let chart_data_qty = { labels: unique_periods, datasets: datasets_qty };
        
        // FIX: Clear the container and recreate the chart from scratch to force legend update
        if (comp_qty_chart) {
            $("#comparison-qty-chart").empty();
            comp_qty_chart = null;
        } 
        
        comp_qty_chart = new frappe.Chart("#comparison-qty-chart", {
            title: `Quantity Comparison (${bifurcation.get_value()})`,
            data: chart_data_qty, type: 'line', height: 280, colors: line_colors,
            axisOptions: { xAxisMode: 'tick', xIsSeries: true, shortenYAxisNumbers: 1 },
            lineOptions: { regionFill: 1, hideDots: 0 }
        });
    }
    

    setTimeout(() => { if (page.btn_primary) page.btn_primary.trigger('click'); }, 100);
};