frappe.pages['production-analytics'].on_page_load = function(wrapper) {

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Production Analytics Dashboard',
        single_column: true
    });

    // ── LOADER ──────────────────────────────────────────────────────────────
    let loader = $(`
        <div id="prod-loader" style="
            position:fixed; top:0; left:0; width:100%; height:100%;
            background:rgba(255,255,255,0.7); backdrop-filter:blur(4px);
            display:none; align-items:center; justify-content:center; z-index:10001;">
            <div class="prod-spinner">
                <div></div><div></div><div></div><div></div>
            </div>
        </div>
    `).appendTo('body');

    if ($('#prod-dash-styles').length === 0) {
        $(`<style id="prod-dash-styles">
        .prod-spinner{display:inline-block;position:relative;width:64px;height:64px;}
        .prod-spinner div{box-sizing:border-box;display:block;position:absolute;width:51px;height:51px;margin:6px;border:4px solid #7c3aed;border-radius:50%;animation:prod-spin 1.2s linear infinite;border-color:#7c3aed transparent transparent transparent;}
        .prod-spinner div:nth-child(1){animation-delay:-0.45s;}
        .prod-spinner div:nth-child(2){animation-delay:-0.3s;}
        .prod-spinner div:nth-child(3){animation-delay:-0.15s;}
        @keyframes prod-spin{0%{transform:rotate(0deg);}100%{transform:rotate(360deg);}}
        .prod-progress-bar{height:8px;border-radius:4px;background:#e5e7eb;overflow:hidden;margin-top:8px;}
        .prod-progress-fill{height:100%;border-radius:4px;transition:width 0.4s ease;}
        .prod-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;}
        .prod-flow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px;}
        .prod-flow-box{text-align:center;padding:8px 12px;border-radius:8px;min-width:90px;}
        .prod-flow-arrow{color:#9ca3af;font-size:18px;font-weight:bold;}
        </style>`).appendTo('head');
    }

    function show_loader() { $("#prod-loader").css('display','flex'); if(page.btn_primary) page.btn_primary.prop('disabled',true); }
    function hide_loader() { $("#prod-loader").hide(); if(page.btn_primary) page.btn_primary.prop('disabled',false); }

    function fmt_num(v, decimals=2) { return parseFloat((Number(v)||0).toFixed(decimals)); }
    function fmt_date(d) { return d ? frappe.datetime.str_to_user(d) : '—'; }

    // ── FILTERS ─────────────────────────────────────────────────────────────
    let company_filter = page.add_field({
        label: 'Company', fieldtype: 'Link', options: 'Company',
        default: frappe.defaults.get_user_default("Company")
    });

    let filter_type = page.add_field({
        label: 'View',
        fieldtype: 'Select',
        options: ['', 'Item-wise Production', 'SO vs Production', 'Raw Materials', 'Work Orders', 'SO Delivery'],
        change() { on_filter_change(); }
    });

    let item_group_filter = page.add_field({ label: 'Item Group', fieldtype: 'Link', options: 'Item Group' });
    let wo_status_filter  = page.add_field({ label: 'WO Status', fieldtype: 'Select', options: ['', 'Not Started', 'In Process', 'Completed', 'Stopped'] });
    $(item_group_filter.wrapper).hide();
    $(wo_status_filter.wrapper).hide();

    let period = page.add_field({
        label: 'Period', fieldtype: 'Select',
        options: ['Today','Weekly','Monthly','Quarterly','Yearly','Custom'],
        default: 'Monthly',
        change() { set_dates(); }
    });

    let from_date = page.add_field({ label: 'From Date', fieldtype: 'Date' });
    let to_date   = page.add_field({ label: 'To Date',   fieldtype: 'Date' });

    function set_dates() {
        let today = frappe.datetime.get_today(), p = period.get_value();
        if      (p==='Today')     { from_date.set_value(today); to_date.set_value(today); }
        else if (p==='Weekly')    { from_date.set_value(frappe.datetime.add_days(today,-7));  to_date.set_value(today); }
        else if (p==='Monthly')   { from_date.set_value(frappe.datetime.add_months(today,-1)); to_date.set_value(today); }
        else if (p==='Quarterly') { from_date.set_value(frappe.datetime.add_months(today,-3)); to_date.set_value(today); }
        else if (p==='Yearly')    { from_date.set_value(frappe.datetime.add_years(today,-1)); to_date.set_value(today); }
    }
    set_dates();

    function on_filter_change() {
        let type = filter_type.get_value();
        $(item_group_filter.wrapper).hide();
        $(wo_status_filter.wrapper).hide();
        item_group_filter.set_value('');
        wo_status_filter.set_value('');
        if (type === 'Item-wise Production') $(item_group_filter.wrapper).show();
        if (type === 'Work Orders')          $(wo_status_filter.wrapper).show();
    }

    // ── SECTIONS ────────────────────────────────────────────────────────────
    let overview_section = $(`
        <div id="prod-overview-section" style="margin-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Production Overview</h3>
                <div id="prod-overview-summary"></div>
            </div>
            <div id="prod-status-cards" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:25px;"></div>
            <div id="prod-overview-chart"></div>
        </div>
    `).appendTo(page.body);

    let item_section = $(`
        <div id="prod-item-section" style="margin-top:20px; border-top:1px solid #e5e7eb; padding-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Item-wise Production</h3>
                <div id="prod-item-summary"></div>
            </div>
            <div id="prod-item-cards" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="prod-item-chart"></div>
        </div>
    `).appendTo(page.body);

    let so_vs_prod_section = $(`
        <div id="prod-so-section" style="margin-top:20px; border-top:1px solid #e5e7eb; padding-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Sales Order vs Production</h3>
                <div id="prod-so-summary"></div>
            </div>
            <div id="prod-so-cards" style="display:flex;flex-direction:column;gap:15px;"></div>
        </div>
    `).appendTo(page.body);

    let raw_mat_section = $(`
        <div id="prod-raw-section" style="margin-top:20px; border-top:1px solid #e5e7eb; padding-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Raw Material Consumption</h3>
                <div id="prod-raw-summary"></div>
            </div>
            <div id="prod-raw-cards" style="display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px;"></div>
            <div id="prod-raw-chart"></div>
        </div>
    `).appendTo(page.body);

    let wo_section = $(`
        <div id="prod-wo-section" style="margin-top:20px; border-top:1px solid #e5e7eb; padding-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Work Orders</h3>
                <div id="prod-wo-summary"></div>
            </div>
            <div id="prod-wo-cards" style="display:flex;flex-wrap:wrap;gap:15px;"></div>
        </div>
    `).appendTo(page.body);

    let delivery_section = $(`
        <div id="prod-delivery-section" style="margin-top:20px; border-top:1px solid #e5e7eb; padding-top:20px; display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">SO Delivery Status</h3>
                <div id="prod-delivery-summary"></div>
            </div>
            <div id="prod-delivery-cards" style="display:flex;flex-wrap:wrap;gap:15px;"></div>
        </div>
    `).appendTo(page.body);

    let overview_chart = null, item_chart = null, raw_chart = null;

    // ── LOAD ────────────────────────────────────────────────────────────────
    page.set_primary_action('Load Data', () => {
        let type = filter_type.get_value();

        let fetch_overview        = (!type) ? 1 : 0;
        let fetch_items           = (type === 'Item-wise Production') ? 1 : 0;
        let fetch_so_vs_production = (type === 'SO vs Production') ? 1 : 0;
        let fetch_raw_materials   = (type === 'Raw Materials') ? 1 : 0;
        let fetch_work_orders     = (type === 'Work Orders') ? 1 : 0;
        let fetch_so_delivery     = (type === 'SO Delivery') ? 1 : 0;

        // Show/hide sections
        fetch_overview         ? overview_section.show()    : overview_section.hide();
        fetch_items            ? item_section.show()        : item_section.hide();
        fetch_so_vs_production ? so_vs_prod_section.show()  : so_vs_prod_section.hide();
        fetch_raw_materials    ? raw_mat_section.show()     : raw_mat_section.hide();
        fetch_work_orders      ? wo_section.show()          : wo_section.hide();
        fetch_so_delivery      ? delivery_section.show()    : delivery_section.hide();

        show_loader();

        frappe.call({
            method: 'mobile.mobile.page.production_analytics.production_analytics.get_production_data',
            args: {
                from_date:             from_date.get_value(),
                to_date:               to_date.get_value(),
                company:               company_filter.get_value(),
                fetch_overview:        fetch_overview,
                fetch_items:           fetch_items,
                fetch_so_vs_production: fetch_so_vs_production,
                fetch_raw_materials:   fetch_raw_materials,
                fetch_work_orders:     fetch_work_orders,
                fetch_so_delivery:     fetch_so_delivery,
                item_group:            item_group_filter.get_value(),
                wo_status:             wo_status_filter.get_value(),
            },
            callback: function(r) {
                if (r.message) {
                    let d = r.message;
                    if (fetch_overview)         render_overview(d.overview);
                    if (fetch_items)            render_items(d.items);
                    if (fetch_so_vs_production) render_so_vs_production(d.so_vs_production);
                    if (fetch_raw_materials)    render_raw_materials(d.raw_materials);
                    if (fetch_work_orders)      render_work_orders(d.work_orders);
                    if (fetch_so_delivery)      render_so_delivery(d.so_delivery);
                }
                hide_loader();
            }
        });
    });


    // ── RENDER: OVERVIEW ────────────────────────────────────────────────────
    function render_overview(data) {
        if (!data) return;
        let status_list = data.status_summary || [];
        let items       = data.items || [];

        // KPI summary banner
        let total_wo       = status_list.reduce((s, r) => s + (Number(r.count)||0), 0);
        let total_planned  = status_list.reduce((s, r) => s + (Number(r.planned_qty)||0), 0);
        let total_produced = status_list.reduce((s, r) => s + (Number(r.produced_qty)||0), 0);
        let efficiency     = total_planned > 0 ? ((total_produced / total_planned) * 100).toFixed(1) : 0;

        $('#prod-overview-summary').html(`
            <div style="display:flex;gap:20px;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total WOs</div>
                    <div style="font-size:16px;font-weight:700;color:#7c3aed;">${total_wo}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Planned Qty</div>
                    <div style="font-size:16px;font-weight:700;color:#0ea5e9;">${fmt_num(total_planned, 0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Produced Qty</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fmt_num(total_produced, 0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Efficiency</div>
                    <div style="font-size:16px;font-weight:700;color:${efficiency >= 90 ? '#16a34a' : efficiency >= 60 ? '#f59e0b' : '#dc2626'};">${efficiency}%</div>
                </div>
            </div>
        `);

        // Status cards
        let status_colors = {
            'Completed':   { bg:'#dcfce7', color:'#16a34a', icon:'✅' },
            'In Process':  { bg:'#dbeafe', color:'#2563eb', icon:'🔄' },
            'Not Started': { bg:'#fef9c3', color:'#ca8a04', icon:'⏳' },
            'Stopped':     { bg:'#fee2e2', color:'#dc2626', icon:'🛑' },
        };
        let status_html = '';
        status_list.forEach(row => {
            let cfg = status_colors[row.status] || { bg:'#f3f4f6', color:'#374151', icon:'📋' };
            status_html += `
                <div style="flex:1;min-width:160px;padding:20px;border-radius:12px;background:${cfg.bg};border:1px solid ${cfg.color}22;">
                    <div style="font-size:24px;margin-bottom:8px;">${cfg.icon}</div>
                    <div style="font-weight:700;color:${cfg.color};font-size:15px;">${row.status}</div>
                    <div style="font-size:28px;font-weight:800;color:${cfg.color};margin:4px 0;">${row.count}</div>
                    <div style="font-size:12px;color:${cfg.color}99;">Planned: ${fmt_num(row.planned_qty,0)}</div>
                    <div style="font-size:12px;color:${cfg.color}99;">Produced: ${fmt_num(row.produced_qty,0)}</div>
                </div>
            `;
        });
        $('#prod-status-cards').html(status_html || '<p class="text-muted">No work orders found.</p>');

        // Bar chart
        if (items.length) {
            let labels = items.map(i => (i.item_name||i.item_code).substring(0,15));
            let chart_data = {
                labels,
                datasets: [
                    { name: 'Planned',  values: items.map(i => Number(i.planned_qty)||0)  },
                    { name: 'Produced', values: items.map(i => Number(i.produced_qty)||0) },
                ]
            };
            if (overview_chart) { $("#prod-overview-chart").empty(); overview_chart = null; }
            overview_chart = new frappe.Chart("#prod-overview-chart", {
                title: 'Top Items: Planned vs Produced', data: chart_data, type: 'bar', height: 320,
                colors: ['#0ea5e9', '#16a34a'],
                axisOptions: { xAxisMode:'tick', xIsSeries:false, shortenYAxisNumbers:1 },
                barOptions: { spaceRatio: 0.3 },
            });
        }
    }


    // ── RENDER: ITEM-WISE PRODUCTION ─────────────────────────────────────────
    function render_items(data) {
        let container = $('#prod-item-cards');
        let summary   = $('#prod-item-summary');
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No data found.</p>"); summary.empty(); return;
        }

        let total_planned  = data.reduce((s,r) => s + (Number(r.planned_qty)||0), 0);
        let total_produced = data.reduce((s,r) => s + (Number(r.produced_qty)||0), 0);
        summary.html(`
            <div style="display:flex;gap:20px;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Planned</div>
                    <div style="font-size:16px;font-weight:700;color:#0ea5e9;">${fmt_num(total_planned,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Produced</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fmt_num(total_produced,0)}</div>
                </div>
            </div>
        `);

        let html = '';
        let labels = [], planned_vals = [], produced_vals = [];

        data.forEach((row, i) => {
            let planned  = Number(row.planned_qty)||0;
            let produced = Number(row.produced_qty)||0;
            let pct      = planned > 0 ? Math.min(100, (produced/planned)*100) : 0;
            let bar_color = pct >= 100 ? '#16a34a' : pct >= 60 ? '#f59e0b' : '#dc2626';
            let shortfall = Math.max(0, planned - produced);
            let name = row.item_name || row.item_code;

            labels.push(name.length > 15 ? name.substring(0,15)+'...' : name);
            planned_vals.push(planned);
            produced_vals.push(produced);

            html += `
                <div style="width:280px;padding:18px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;">
                    <div style="color:#6b7280;font-size:12px;">#${i+1} · ${row.wo_count} WO${row.wo_count>1?'s':''}</div>
                    <div style="font-weight:700;font-size:15px;margin:4px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
                    <div style="font-size:12px;color:#9ca3af;">${row.item_code}</div>
                    <div class="prod-progress-bar">
                        <div class="prod-progress-fill" style="width:${pct}%;background:${bar_color};"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:13px;">
                        <span>Planned: <b>${fmt_num(planned,0)}</b></span>
                        <span style="color:${bar_color};font-weight:700;">${pct.toFixed(1)}%</span>
                    </div>
                    <div style="font-size:13px;margin-top:3px;color:#16a34a;font-weight:600;">Produced: ${fmt_num(produced,0)}</div>
                    ${shortfall > 0 ? `<div style="font-size:12px;color:#dc2626;margin-top:3px;">⚠️ Shortfall: ${fmt_num(shortfall,0)}</div>` : `<div style="font-size:12px;color:#16a34a;margin-top:3px;">✅ On Track</div>`}
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels, datasets: [{ name:'Planned', values:planned_vals }, { name:'Produced', values:produced_vals }] };
        if (item_chart) { $("#prod-item-chart").empty(); item_chart = null; }
        item_chart = new frappe.Chart("#prod-item-chart", {
            title: 'Planned vs Produced by Item', data: chart_data, type: 'bar', height: 320,
            colors: ['#0ea5e9', '#16a34a'],
            axisOptions: { xAxisMode:'tick', xIsSeries:false, shortenYAxisNumbers:1 },
            barOptions: { spaceRatio: 0.3 },
        });
    }


    // ── RENDER: SO vs PRODUCTION ─────────────────────────────────────────────
    function render_so_vs_production(data) {
        let container = $('#prod-so-cards');
        let summary   = $('#prod-so-summary');
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No Sales Orders with linked Work Orders found.</p>");
            summary.empty(); return;
        }

        let total_demand   = data.reduce((s,r) => s + (Number(r.so_demand)||0), 0);
        let total_produced = data.reduce((s,r) => s + (Number(r.produced_qty)||0), 0);
        let total_shortfall= data.reduce((s,r) => s + (Number(r.shortfall)||0), 0);
        let fulfilled      = data.filter(r => r.status === 'Fulfilled' || r.status === 'Stock Sufficient').length;

        summary.html(`
            <div style="display:flex;gap:20px;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">SO Demand</div>
                    <div style="font-size:16px;font-weight:700;color:#7c3aed;">${fmt_num(total_demand,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Produced</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fmt_num(total_produced,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Shortfall</div>
                    <div style="font-size:16px;font-weight:700;color:${total_shortfall > 0 ? '#dc2626' : '#16a34a'};">${fmt_num(total_shortfall,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Fulfilled</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fulfilled} / ${data.length}</div>
                </div>
            </div>
        `);

        let status_cfg = {
            'Fulfilled':        { color:'#16a34a', bg:'#dcfce7', icon:'✅' },
            'Stock Sufficient': { color:'#0ea5e9', bg:'#dbeafe', icon:'📦' },
            'Partial':          { color:'#f59e0b', bg:'#fef9c3', icon:'⚠️' },
            'Not Started':      { color:'#dc2626', bg:'#fee2e2', icon:'🔴' },
        };

        let html = '';
        data.forEach(row => {
            let cfg = status_cfg[row.status] || { color:'#374151', bg:'#f3f4f6', icon:'📋' };
            let so_demand      = fmt_num(row.so_demand, 0);
            let opening        = fmt_num(row.opening_stock, 0);
            let need_to_mfg    = fmt_num(row.need_to_manufacture, 0);
            let produced       = fmt_num(row.produced_qty, 0);
            let closing        = fmt_num(row.closing_stock, 0);
            let closing_color  = row.closing_stock >= 0 ? '#16a34a' : '#dc2626';
            let name           = row.item_name || row.item_code;

            html += `
                <div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid ${cfg.color};border-radius:12px;padding:20px;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                        <div>
                            <div style="font-weight:700;font-size:16px;">${name}</div>
                            <div style="font-size:12px;color:#9ca3af;margin-top:2px;">${row.item_code} · SO: <b>${row.sales_order}</b></div>
                        </div>
                        <span class="prod-badge" style="background:${cfg.bg};color:${cfg.color};">${cfg.icon} ${row.status}</span>
                    </div>

                    <div class="prod-flow">
                        <div class="prod-flow-box" style="background:#ede9fe;border:1px solid #7c3aed22;">
                            <div style="font-size:11px;color:#7c3aed;font-weight:600;">SO DEMAND</div>
                            <div style="font-size:20px;font-weight:800;color:#7c3aed;">${so_demand}</div>
                            <div style="font-size:10px;color:#9ca3af;">nos</div>
                        </div>
                        <div class="prod-flow-arrow">→</div>
                        <div class="prod-flow-box" style="background:#dbeafe;border:1px solid #2563eb22;">
                            <div style="font-size:11px;color:#2563eb;font-weight:600;">OPENING STOCK</div>
                            <div style="font-size:20px;font-weight:800;color:#2563eb;">${opening}</div>
                            <div style="font-size:10px;color:#9ca3af;">nos</div>
                        </div>
                        <div class="prod-flow-arrow">→</div>
                        <div class="prod-flow-box" style="background:#fef9c3;border:1px solid #ca8a0422;">
                            <div style="font-size:11px;color:#ca8a04;font-weight:600;">TO MANUFACTURE</div>
                            <div style="font-size:20px;font-weight:800;color:#ca8a04;">${need_to_mfg}</div>
                            <div style="font-size:10px;color:#9ca3af;">nos</div>
                        </div>
                        <div class="prod-flow-arrow">→</div>
                        <div class="prod-flow-box" style="background:#dcfce7;border:1px solid #16a34a22;">
                            <div style="font-size:11px;color:#16a34a;font-weight:600;">PRODUCED</div>
                            <div style="font-size:20px;font-weight:800;color:#16a34a;">${produced}</div>
                            <div style="font-size:10px;color:#9ca3af;">nos</div>
                        </div>
                        <div class="prod-flow-arrow">→</div>
                        <div class="prod-flow-box" style="background:#f3f4f6;border:1px solid ${closing_color}44;">
                            <div style="font-size:11px;color:${closing_color};font-weight:600;">CLOSING STOCK</div>
                            <div style="font-size:20px;font-weight:800;color:${closing_color};">${closing}</div>
                            <div style="font-size:10px;color:#9ca3af;">nos</div>
                        </div>
                    </div>

                    ${row.shortfall > 0 ? `<div style="margin-top:10px;padding:8px 12px;background:#fee2e2;border-radius:6px;font-size:13px;color:#dc2626;font-weight:600;">⚠️ Shortfall: ${fmt_num(row.shortfall,0)} nos still pending production</div>` : ''}
                </div>
            `;
        });

        container.html(html);
    }


    // ── RENDER: RAW MATERIALS ────────────────────────────────────────────────
    function render_raw_materials(data) {
        let container = $('#prod-raw-cards');
        let summary   = $('#prod-raw-summary');
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No raw material data found.</p>"); summary.empty(); return;
        }

        let total_req  = data.reduce((s,r) => s + (Number(r.required_qty)||0), 0);
        let total_cons = data.reduce((s,r) => s + (Number(r.consumed_qty)||0), 0);
        let shortfall_count = data.filter(r => Number(r.consumed_qty) < Number(r.required_qty)).length;

        summary.html(`
            <div style="display:flex;gap:20px;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Required</div>
                    <div style="font-size:16px;font-weight:700;color:#f59e0b;">${fmt_num(total_req,2)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Consumed</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fmt_num(total_cons,2)}</div>
                </div>
                ${shortfall_count > 0 ? `
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Short Items</div>
                    <div style="font-size:16px;font-weight:700;color:#dc2626;">${shortfall_count}</div>
                </div>` : ''}
            </div>
        `);

        let html = '';
        let labels = [], req_vals = [], cons_vals = [];

        data.forEach(row => {
            let required  = Number(row.required_qty)||0;
            let consumed  = Number(row.consumed_qty)||0;
            let stock     = Number(row.current_stock)||0;
            let pct       = required > 0 ? Math.min(100, (consumed/required)*100) : 100;
            let bar_color = pct >= 100 ? '#16a34a' : pct >= 50 ? '#f59e0b' : '#dc2626';
            let name      = row.item_name || row.item_code;

            labels.push(name.length > 15 ? name.substring(0,15)+'...' : name);
            req_vals.push(required);
            cons_vals.push(consumed);

            html += `
                <div style="width:270px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;">
                    <div style="font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
                    <div style="font-size:12px;color:#9ca3af;">${row.item_code} · ${row.uom||''}</div>
                    <div class="prod-progress-bar">
                        <div class="prod-progress-fill" style="width:${pct}%;background:${bar_color};"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:13px;">
                        <span>Required: <b>${fmt_num(required,2)}</b></span>
                        <span style="color:${bar_color};font-weight:700;">${pct.toFixed(1)}%</span>
                    </div>
                    <div style="font-size:13px;margin-top:3px;color:#16a34a;">Consumed: <b>${fmt_num(consumed,2)}</b></div>
                    <div style="font-size:12px;margin-top:3px;color:#0ea5e9;">Current Stock: <b>${fmt_num(stock,2)}</b></div>
                    ${consumed < required ? `<div style="font-size:12px;color:#dc2626;margin-top:4px;">⚠️ Under-consumed: ${fmt_num(required-consumed,2)}</div>` : ''}
                </div>
            `;
        });

        container.html(html);

        let chart_data = { labels, datasets: [{ name:'Required', values:req_vals }, { name:'Consumed', values:cons_vals }] };
        if (raw_chart) { $("#prod-raw-chart").empty(); raw_chart = null; }
        raw_chart = new frappe.Chart("#prod-raw-chart", {
            title: 'Raw Material: Required vs Consumed', data: chart_data, type: 'bar', height: 320,
            colors: ['#f59e0b', '#16a34a'],
            axisOptions: { xAxisMode:'tick', xIsSeries:false, shortenYAxisNumbers:1 },
            barOptions: { spaceRatio: 0.3 },
        });
    }


    // ── RENDER: WORK ORDERS ──────────────────────────────────────────────────
    function render_work_orders(data) {
        let container = $('#prod-wo-cards');
        let summary   = $('#prod-wo-summary');
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No work orders found.</p>"); summary.empty(); return;
        }

        let by_status = {};
        data.forEach(r => { by_status[r.status] = (by_status[r.status]||0) + 1; });
        let summary_pills = Object.entries(by_status).map(([s,c]) => {
            let colors = { 'Completed':'#16a34a', 'In Process':'#2563eb', 'Not Started':'#ca8a04', 'Stopped':'#dc2626' };
            return `<span class="prod-badge" style="background:${colors[s]||'#e5e7eb'}22;color:${colors[s]||'#374151'};">${s}: ${c}</span>`;
        }).join(' ');
        summary.html(`<div style="display:flex;gap:8px;flex-wrap:wrap;">${summary_pills}</div>`);

        let status_colors = {
            'Completed':   { border:'#16a34a', bg:'#f0fdf4' },
            'In Process':  { border:'#2563eb', bg:'#eff6ff' },
            'Not Started': { border:'#ca8a04', bg:'#fefce8' },
            'Stopped':     { border:'#dc2626', bg:'#fff1f2' },
        };

        let html = '';
        data.forEach(row => {
            let cfg = status_colors[row.status] || { border:'#9ca3af', bg:'#f9fafb' };
            let produced = Number(row.produced_qty)||0;
            let planned  = Number(row.planned_qty)||0;
            let pct      = planned > 0 ? Math.min(100, (produced/planned)*100) : 0;
            let name     = row.item_name || row.item_code;

            html += `
                <div style="width:270px;padding:16px;border-radius:12px;background:${cfg.bg};border:1px solid ${cfg.border}44;border-top:3px solid ${cfg.border};">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <div style="font-size:12px;color:#6b7280;font-weight:600;">${row.name}</div>
                        <span class="prod-badge" style="background:${cfg.border}22;color:${cfg.border};">${row.status}</span>
                    </div>
                    <div style="font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
                    ${row.sales_order ? `<div style="font-size:12px;color:#7c3aed;margin-top:2px;">SO: ${row.sales_order}</div>` : ''}
                    <div class="prod-progress-bar" style="margin-top:10px;">
                        <div class="prod-progress-fill" style="width:${pct}%;background:${cfg.border};"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:13px;">
                        <span>Planned: <b>${fmt_num(planned,0)}</b></span>
                        <span style="color:${cfg.border};font-weight:700;">${pct.toFixed(0)}%</span>
                    </div>
                    <div style="font-size:13px;color:#16a34a;margin-top:2px;">Produced: <b>${fmt_num(produced,0)}</b></div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:6px;">
                        Start: ${fmt_date(row.planned_start_date)} · End: ${fmt_date(row.planned_end_date)}
                    </div>
                </div>
            `;
        });

        container.html(html);
    }


    // ── RENDER: SO DELIVERY ──────────────────────────────────────────────────
    function render_so_delivery(data) {
        let container = $('#prod-delivery-cards');
        let summary   = $('#prod-delivery-summary');
        if (!data || data.length === 0) {
            container.html("<p class='text-muted'>No sales orders due in this period.</p>"); summary.empty(); return;
        }

        let total_ordered    = data.reduce((s,r) => s + (Number(r.ordered_qty)||0), 0);
        let total_delivered  = data.reduce((s,r) => s + (Number(r.delivered_qty)||0), 0);
        let total_pending    = data.reduce((s,r) => s + (Number(r.pending_qty)||0), 0);
        let overdue_count    = data.filter(r => r.is_overdue).length;

        summary.html(`
            <div style="display:flex;gap:20px;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Ordered</div>
                    <div style="font-size:16px;font-weight:700;color:#7c3aed;">${fmt_num(total_ordered,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Delivered</div>
                    <div style="font-size:16px;font-weight:700;color:#16a34a;">${fmt_num(total_delivered,0)}</div>
                </div>
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Pending</div>
                    <div style="font-size:16px;font-weight:700;color:#f59e0b;">${fmt_num(total_pending,0)}</div>
                </div>
                ${overdue_count > 0 ? `
                <div style="width:1px;background:#cbd5e1;"></div>
                <div>
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Overdue</div>
                    <div style="font-size:16px;font-weight:700;color:#dc2626;">${overdue_count}</div>
                </div>` : ''}
            </div>
        `);

        let html = '';
        data.forEach(row => {
            let ordered   = Number(row.ordered_qty)||0;
            let delivered = Number(row.delivered_qty)||0;
            let pending   = Number(row.pending_qty)||0;
            let pct       = ordered > 0 ? Math.min(100, (delivered/ordered)*100) : 0;
            let is_overdue= row.is_overdue;
            let border    = is_overdue ? '#dc2626' : pct >= 100 ? '#16a34a' : '#f59e0b';

            html += `
                <div style="width:270px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e5e7eb;border-top:3px solid ${border};">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="font-size:12px;color:#6b7280;font-weight:600;">${row.name}</div>
                        ${is_overdue ? `<span class="prod-badge" style="background:#fee2e2;color:#dc2626;">🔴 OVERDUE</span>` : `<span class="prod-badge" style="background:#fef9c3;color:#ca8a04;">${row.status}</span>`}
                    </div>
                    <div style="font-weight:700;font-size:15px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${row.customer_name||row.customer}</div>
                    <div style="font-size:12px;color:#9ca3af;">Due: ${fmt_date(row.delivery_date)}</div>
                    <div class="prod-progress-bar" style="margin-top:10px;">
                        <div class="prod-progress-fill" style="width:${pct}%;background:${border};"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:13px;">
                        <span>Ordered: <b>${fmt_num(ordered,0)}</b></span>
                        <span style="color:${border};font-weight:700;">${pct.toFixed(0)}%</span>
                    </div>
                    <div style="font-size:13px;color:#16a34a;margin-top:2px;">Delivered: <b>${fmt_num(delivered,0)}</b></div>
                    <div style="font-size:13px;color:#f59e0b;margin-top:2px;">Pending: <b>${fmt_num(pending,0)}</b></div>
                </div>
            `;
        });

        container.html(html);
    }


    // Auto-load on page open
    setTimeout(() => { if (page.btn_primary) page.btn_primary.trigger('click'); }, 100);
};
