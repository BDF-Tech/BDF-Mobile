frappe.pages['stock-dashboard'].on_page_load = function(wrapper) {

    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Production Inventory Hub',
        single_column: true
    });

    // ==========================
    // FRAPPE-NATIVE CSS
    // ==========================

    $(`
    <style>

    .stats-wrapper {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px,1fr));
        gap: 15px;
        margin: 20px 0;
    }

    .stat-card {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: var(--border-radius-md);
        padding: 16px;
        transition: 0.2s ease;
    }

    .stat-card:hover {
        box-shadow: var(--shadow-sm);
    }

    .stat-title {
        font-size: 12px;
        color: var(--text-muted);
        text-transform: uppercase;
    }

    .stat-value {
        font-size: 22px;
        font-weight: 600;
        margin-top: 5px;
        color: var(--text-color);
    }

    .dashboard-container {
        margin-top: 10px;
    }

    .grid-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px,1fr));
        gap: 16px;
    }

    .stock-card {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: var(--border-radius-md);
        padding: 16px;
        transition: 0.2s ease;
        cursor: pointer;
    }

    .stock-card:hover {
        box-shadow: var(--shadow-md);
        transform: translateY(-2px);
    }

    .stock-card.safe {
        border-left: 4px solid var(--green-500);
    }

    .stock-card.critical {
        border-left: 4px solid var(--red-500);
    }

    .item-name {
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 10px;
        color: var(--text-color);
    }

    .metric-row {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        margin-top: 6px;
        color: var(--text-muted);
    }

    .metric-row b {
        font-weight: 600;
        color: var(--text-color);
    }

    .status-badge {
        font-size: 11px;
        padding: 3px 8px;
        border-radius: var(--border-radius-sm);
        font-weight: 500;
    }

    .badge-critical {
        background: var(--red-100);
        color: var(--red-700);
    }

    .badge-healthy {
        background: var(--green-100);
        color: var(--green-700);
    }

    .mini-stats {
        display: grid;
        grid-template-columns: repeat(3,1fr);
        gap: 6px;
        margin-top: 12px;
        padding-top: 10px;
        border-top: 1px solid var(--border-color);
        font-size: 11px;
        text-align: center;
    }

    .mini-stats div {
        background: var(--bg-light);
        padding: 6px;
        border-radius: var(--border-radius-sm);
    }

    .mini-stats strong {
        display: block;
        font-size: 13px;
        color: var(--text-color);
    }

    .empty-state {
        padding: 40px;
        text-align: center;
        color: var(--text-muted);
    }

    </style>
    `).appendTo(page.main);

    // ==========================
    // FILTERS
    // ==========================

    page.wh_f = page.add_field({
        fieldname:'warehouse',
        label:__('Warehouse'),
        fieldtype:'Link',
        options:'Warehouse',
        change:()=>refresh_data(page)
    });

    // Explicitly adding Item Code filter here
    page.item_f = page.add_field({
        fieldname:'item_code',
        label:__('Item Code'),
        fieldtype:'Link',
        options:'Item',
        change:()=>refresh_data(page)
    });

    page.group_f = page.add_field({
        fieldname:'item_group',
        label:__('Item Group'),
        fieldtype:'Link',
        options:'Item Group',
        change:()=>refresh_data(page)
    });

    page.status_f = page.add_field({
        fieldname:'stock_status',
        label:'Stock Status',
        fieldtype:'Select',
        options:['All','Critical','Healthy'],
        default:'All',
        change:()=>refresh_data(page)
    });

    page.sort_f = page.add_field({
        fieldname:'sort_order',
        label:'Sort',
        fieldtype:'Select',
        options:['asc','desc'],
        default:'asc',
        change:()=>refresh_data(page)
    });

    page.set_primary_action(__('Refresh'), ()=>refresh_data(page));

    // ==========================
    // HTML
    // ==========================

    $(`
    <div class="stats-wrapper">
        <div class="stat-card">
            <div class="stat-title">Total Items</div>
            <div class="stat-value" id="total-items">0</div>
        </div>
        <div class="stat-card">
            <div class="stat-title">Reorder Required</div>
            <div class="stat-value" id="critical-items">0</div>
        </div>
        <div class="stat-card">
            <div class="stat-title">Healthy Items</div>
            <div class="stat-value" id="healthy-items">0</div>
        </div>
        <div class="stat-card">
            <div class="stat-title">Avg Days</div>
            <div class="stat-value" id="avg-days">0</div>
        </div>
    </div>

    <div class="dashboard-container">
        <div id="stock-cards-container" class="grid-container"></div>
    </div>
    `).appendTo(page.main);

    refresh_data(page);
};


// ==========================
// DATA REFRESH
// ==========================

function refresh_data(page){

    $("#stock-cards-container").html(
        "<div class='empty-state'>Loading inventory data...</div>"
    );

    frappe.call({
        method:"dairy.dairy.page.stock_dashboard.stock_dashboard.get_stock_data",
        args:{
            warehouse:page.wh_f.get_value(),
            item_code:page.item_f.get_value(), // Passing the item filter value
            item_group:page.group_f.get_value(),
            stock_status:page.status_f.get_value(),
            sort_order:page.sort_f.get_value()
        },
        callback:function(r){
            render_data(r.message || []);
        }
    });
}


// ==========================
// RENDER
// ==========================

function render_data(data){

    if(!data.length){
        $("#stock-cards-container").html(
            "<div class='empty-state'>No stock found.</div>"
        );
        return;
    }

    let total = data.length;
    let critical = 0;
    let healthy = 0;
    let total_days = 0;
    let valid_day_items = 0;

    data.forEach(i=>{
        if(i.actual_qty <= i.reorder_level){
            critical++;
        } else {
            healthy++;
        }

        if(i.custom_no_of_days && i.custom_no_of_days > 0){
            total_days += (i.actual_qty / i.custom_no_of_days);
            valid_day_items++;
        }
    });

    let avg_days = valid_day_items ? (total_days / valid_day_items).toFixed(1) : 0;

    $("#total-items").text(total);
    $("#critical-items").text(critical);
    $("#healthy-items").text(healthy);
    $("#avg-days").text(avg_days);

    let html = data.map(i=>{

        let days_remaining = 0;
        if(i.custom_no_of_days && i.custom_no_of_days > 0){
            days_remaining = (i.actual_qty / i.custom_no_of_days).toFixed(1);
        }

        let isCritical = i.actual_qty <= i.reorder_level;

        return `
        <div class="stock-card ${isCritical ? 'critical' : 'safe'}"
             onclick="frappe.set_route('Form','Item','${i.item_code}')">

            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="item-name">${i.item_name}</div>
                <div class="status-badge ${isCritical ? 'badge-critical' : 'badge-healthy'}">
                    ${isCritical ? 'Critical' : 'Healthy'}
                </div>
            </div>

            <div class="mini-stats">
                <div>
                    <strong>${Math.round(i.actual_qty)}</strong>
                    Qty
                </div>
                <div>
                    <strong>${i.reorder_level}</strong>
                    Reorder
                </div>
                <div>
                    <strong>${days_remaining}</strong>
                    Days
                </div>
            </div>

            <div class="metric-row">
                <span>Warehouse</span>
                <b>${i.warehouse || 'Multiple'}</b>
            </div>

        </div>
        `;
    }).join("");

    $("#stock-cards-container").html(html);
}