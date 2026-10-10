frappe.pages["customer-dashboard"].on_page_load = function (wrapper) {
  var page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Customer Insights Pro"),
    single_column: true,
  });

  page.start = 0;
  page.page_len = 20;

  page.customer_f = page.add_field({
    fieldname: "customer", label: "Customer",
    fieldtype: "Link", options: "Customer",
    change: () => { page.start = 0; refresh_data(page); },
  });

  page.customer_group_f = page.add_field({
    fieldname: "customer_group", label: "Group",
    fieldtype: "Link", options: "Customer Group",
    change: () => { page.start = 0; refresh_data(page); },
  });

  page.status_filter_f = page.add_field({
    fieldname: "status_filter",
    label: "License Status",
    fieldtype: "Select",
    options: ["All", "Healthy", "Expiring Soon", "Expired", "No License"],
    default: "All",
    change: () => { page.start = 0; refresh_data(page); }  // FIXED pagination issue
  });

  page.page_len_f = page.add_field({
    fieldname: "page_len",
    label: "Display",
    fieldtype: "Select",
    options: ["20", "100", "500", "2500"],
    default: "20",
    change: () => {
      page.page_len = page.page_len_f.get_value();
      page.start = 0;
      refresh_data(page);
    }
  });

  page.search_f = page.add_field({
    fieldname: "search",
    label: "Global Search",
    fieldtype: "Data",
    onchange: () => filter_cards_locally(page)
  });

  page.set_primary_action(__("Refresh Data"), () => refresh_data(page), "refresh");

  $(`
    <style>
    .dashboard-container { padding: 20px; background-color: var(--bg-color); }
    .top-layout { display: grid; grid-template-columns: 1fr 2fr; gap: 24px; margin-bottom: 30px; }
    .chart-box { background: var(--card-bg); border-radius: 16px; border: 1px solid var(--border-color); padding: 20px; box-shadow: var(--shadow-sm); }

    .health-analysis { background: var(--card-bg); border-radius: 16px; border: 1px solid var(--border-color); padding: 20px; display: flex; flex-direction: column; justify-content: center; }

    .health-row { margin-bottom: 15px; }

    .health-meta {
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--text-color);
    }

    .health-bar-container {
      height: 8px;
      background: var(--border-color);
      border-radius: 4px;
      overflow: hidden;
    }

    .health-bar-fill {
      height: 100%;
      transition: width 1.2s ease;
    }

    .customer-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 24px;
    }

    .modern-card {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 20px;
        padding: 24px;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        position: relative;
        cursor: pointer;
    }

    .modern-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 24px rgba(0,0,0,0.08);
        border-color: var(--primary);
    }

    .m-card-head { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 20px; }

    .m-avatar {
        width: 50px;
        height: 50px;
        border-radius: 14px;
        background: linear-gradient(135deg, var(--primary) 0%, #6366f1 100%);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 22px;
    }

    .m-name { font-size: 16px; font-weight: 700; color: var(--text-color); margin-bottom: 4px; }

    .m-badge { padding: 4px 12px; border-radius: 8px; font-size: 10px; font-weight: 700; text-transform: uppercase; }

    .m-safe { background: rgba(34,197,94,0.1); color:#22c55e; border:1px solid rgba(34,197,94,0.2); }
    .m-warn { background: rgba(249,115,22,0.1); color:#f97316; border:1px solid rgba(249,115,22,0.2); }
    .m-alert { background: rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.2); }

    .m-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }

    .m-label {
      font-size: 10px;
      color: var(--text-muted);
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 4px;
      text-transform: uppercase;
    }

    .m-val { font-size: 13px; font-weight: 600; color: var(--text-color); }

    .m-footer {
      background: var(--control-bg);
      border-radius: 12px;
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border: 1px solid var(--border-color);
    }

    .license-no{
      font-size:16px;
      font-weight:800;
      color:white;
    }

    .m-attach {
      font-size: 11px;
      font-weight: 700;
      color: var(--primary);
      cursor: pointer;
    }

    .p-nav {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 40px 0;
      border-top: 1px solid var(--border-color);
    }
    </style>
  `).appendTo(page.main);

  $(`
    <div class="dashboard-container">
        <div class="top-layout">
            <div id="m-chart" class="chart-box"></div>
            <div class="health-analysis" id="health-overview"></div>
        </div>
        <div id="m-grid" class="customer-grid"></div>
        <div id="m-pagination" class="p-nav"></div>
    </div>
  `).appendTo(page.main);

  refresh_data(page);
};

function refresh_data(page) {
  frappe.call({
    method: "mobile.mobile.page.customer_dashboard.customer_dashboard.get_customer_details",
    args: {
      customer: page.customer_f.get_value(),
      customer_group: page.customer_group_f.get_value(),
      status_filter: page.status_filter_f.get_value(), // FIXED pagination filtering
      start: page.start,
      page_len: page.page_len
    },
    callback: function (r) {
      if(r.message) {
          render_health_overview(r.message.summary);
          render_chart(r.message.summary);
          render_customers(r.message.customers);
          render_pagination(page, r.message.total_count);
      }
    },
  });
}

function render_health_overview(summary){
let html = `
<b style="font-size:16px">License Health Breakdown</b>

<div class="health-row">
<div class="health-meta"><span>Healthy (${summary.healthy})</span><span>${summary.healthy_pc}%</span></div>
<div class="health-bar-container"><div class="health-bar-fill" style="width:${summary.healthy_pc}%;background:#22c55e"></div></div>
</div>

<div class="health-row">
<div class="health-meta"><span>Expiring Soon (${summary.expiring})</span><span>${summary.expiring_pc}%</span></div>
<div class="health-bar-container"><div class="health-bar-fill" style="width:${summary.expiring_pc}%;background:#f97316"></div></div>
</div>

<div class="health-row">
<div class="health-meta"><span>Expired (${summary.expired})</span><span>${summary.expired_pc}%</span></div>
<div class="health-bar-container"><div class="health-bar-fill" style="width:${summary.expired_pc}%;background:#ef4444"></div></div>
</div>

<div class="health-row">
<div class="health-meta"><span>No License (${summary.missing})</span><span>${summary.missing_pc}%</span></div>
<div class="health-bar-container"><div class="health-bar-fill" style="width:${summary.missing_pc}%;background:#64748b"></div></div>
</div>

<div style="margin-top:10px;font-size:11px;font-weight:600">
TOTAL PORTFOLIO: ${summary.total}
</div>
`;
$("#health-overview").html(html)
}

function render_chart(summary){
let data = {
labels:["Healthy","Expiring","Expired","No License"],
datasets:[{values:[summary.healthy,summary.expiring,summary.expired,summary.missing]}]
}
new frappe.Chart("#m-chart",{title:"Status Distribution",data:data,type:'donut',height:200,colors:['#22c55e','#f97316','#ef4444','#64748b'],donutRadius:45})
}

function filter_cards_locally(page){
let search=(page.search_f.get_value()||"").toLowerCase()
let status=page.status_filter_f.get_value()

$(".modern-card").each(function(){
let text=$(this).text().toLowerCase()
let c_status=$(this).attr("data-license")
let m_search=text.includes(search)
let m_status=(status==="All"||c_status===status)
$(this).toggle(m_search&&m_status)
})
}

function show_files(files){   // NEW: show all attachments
let html=""
files.forEach(f=>{
html+=`<div style="padding:8px"><a href="${f}" target="_blank">${f}</a></div>`
})
let d=new frappe.ui.Dialog({title:"Attachments",fields:[{fieldtype:"HTML",fieldname:"files"}]})
d.fields_dict.files.$wrapper.html(html)
d.show()
}

function render_customers(data){

let container=$("#m-grid").empty()

if(!data.length){
container.html("<div style='grid-column:1/-1;text-align:center;padding:60px'>No results</div>")
return
}

let html=data.map(c=>{

let b_class="m-safe"
let b_text="Healthy"
let b_key="Healthy"

if(!c.food_license_number||!c.food_license_validity){
b_class="m-alert"
b_text="No License"
b_key="No License"
}
else{

let diff=frappe.datetime.get_diff(c.food_license_validity,frappe.datetime.get_today())

if(diff<0){
b_class="m-alert"
b_text="Expired"
b_key="Expired"
}

else if(diff<=30){
b_class="m-warn"
b_text=`${diff} Days Left`
b_key="Expiring Soon"
}

}

let attach="No Doc"
if(c.attachments && c.attachments.length){
attach=`<div class="m-attach" onclick='event.stopPropagation();show_files(${JSON.stringify(c.attachments)})'><i class="fa fa-paperclip"></i> View (${c.attachments.length})</div>`
}

return `
<div class="modern-card" data-license="${b_key}" onclick="frappe.set_route('Form','Customer','${c.name}')">

<div class="m-card-head">

<div class="m-avatar">${c.customer_name[0]}</div>

<div style="flex:1">
<div class="m-name">${c.customer_name}</div>
<div style="font-size:12px;color:var(--text-muted)">${c.territory||"Global"}</div>
</div>

<div class="m-badge ${b_class}">${b_text}</div>

</div>

<div class="m-body">

<div><span class="m-label">Lead</span><span class="m-val">${c.lead_name||"-"}</span></div>

<div><span class="m-label">Group</span><span class="m-val">${c.customer_group||"-"}</span></div>

<div><span class="m-label">Price List</span><span class="m-val">${c.default_price_list||"-"}</span></div>

<div><span class="m-label">Start Date</span><span class="m-val">${c.custom_starting_date_of_the_contract||"-"}</span></div>

</div>

<div class="m-footer">

<div>
<div class="license-no">${c.food_license_number||"N/A"}</div>
<div style="font-size:11px">${c.food_license_validity||"N/A"}</div>
</div>

${attach}

</div>

</div>
`

}).join("")

container.html(html)

}

function render_pagination(page,total){

let area=$("#m-pagination").empty()

let end=Math.min(page.start+parseInt(page.page_len),total)

area.append(`<span style="font-size:12px">Results ${page.start+1}-${end} / ${total}</span>`)

let wrap=$('<div class="btn-group"></div>').appendTo(area)

let p_btn=$(`<button class="btn btn-default btn-sm">Previous</button>`).appendTo(wrap)

let n_btn=$(`<button class="btn btn-default btn-sm">Next</button>`).appendTo(wrap)

if(page.start<=0)p_btn.attr("disabled",true)
if(end>=total)n_btn.attr("disabled",true)

p_btn.click(()=>{page.start-=parseInt(page.page_len);refresh_data(page)})
n_btn.click(()=>{page.start+=parseInt(page.page_len);refresh_data(page)})

}