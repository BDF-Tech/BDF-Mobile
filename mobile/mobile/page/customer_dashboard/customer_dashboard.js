frappe.pages["customer-dashboard"].on_page_load = function (wrapper) {
  var page = frappe.ui.make_app_page({
    parent: wrapper,
    title: "Customer Dashboard",
    single_column: true,
  });

  // ==========================
  // FILTER
  // ==========================

  page.customer_f = page.add_field({
    fieldname: "customer",
    label: "Customer",
    fieldtype: "Link",
    options: "Customer",
    change: () => refresh_data(page),
  });

  page.set_primary_action(__("Refresh"), () => refresh_data(page));

  // ==========================
  // CSS
  // ==========================

  $(`
    <style>

    .stats-grid{
        display:grid;
        grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:15px;
        margin:20px 0;
    }

    .stat-card{
        background:var(--card-bg);
        border:1px solid var(--border-color);
        border-radius:var(--border-radius-md);
        padding:16px;
    }

    .stat-title{
        font-size:12px;
        color:var(--text-muted);
    }

    .stat-value{
        font-size:24px;
        font-weight:600;
        margin-top:5px;
    }

    .grid-container{
        display:grid;
        grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
        gap:16px;
        margin-top:15px;
    }

    .customer-card{
        background:var(--card-bg);
        border:1px solid var(--border-color);
        border-radius:var(--border-radius-md);
        padding:16px;
        cursor:pointer;
        transition:0.2s;
    }

    .customer-card:hover{
        box-shadow:var(--shadow-md);
        transform:translateY(-2px);
    }

    .customer-header{
        display:flex;
        align-items:center;
        gap:10px;
        margin-bottom:10px;
    }

    .avatar{
        width:36px;
        height:36px;
        border-radius:50%;
        background:var(--primary);
        color:white;
        display:flex;
        align-items:center;
        justify-content:center;
        font-weight:600;
    }

    .customer-info{
        display:flex;
        justify-content:space-between;
        font-size:12px;
        margin-top:6px;
        color:var(--text-muted);
    }

    .customer-info b{
        color:var(--text-color);
    }

    .license-warning{
        margin-top:8px;
        font-size:11px;
        font-weight:500;
    }

    .expiring{
        color:var(--orange-600);
    }

    .expired{
        color:var(--red-600);
    }

    .empty-state{
        padding:40px;
        text-align:center;
        color:var(--text-muted);
    }

    </style>
    `).appendTo(page.main);

  // ==========================
  // HTML
  // ==========================

  $(`
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-title">Total Customers</div>
            <div class="stat-value" id="total-customers">0</div>
        </div>
    </div>

    <div id="customer-cards-container" class="grid-container"></div>
    `).appendTo(page.main);

  refresh_data(page);
};

// ==========================
// DATA REFRESH
// ==========================

function refresh_data(page) {
  $("#customer-cards-container").html(
    "<div class='empty-state'>Loading customers...</div>",
  );

  frappe.call({
    method:
      "mobile.mobile.page.customer_dashboard.customer_dashboard.get_customer_details",
    args: {
      customer: page.customer_f.get_value(),
    },
    callback: function (r) {
      render_customers(r.message || []);
    },
  });
}

// ==========================
// RENDER
// ==========================

function render_customers(data) {
  if (!data.length) {
    $("#customer-cards-container").html(
      "<div class='empty-state'>No customers found.</div>",
    );
    return;
  }

  $("#total-customers").text(data.length);

  let html = data
    .map((c) => {
      let letter = c.customer_name
        ? c.customer_name.charAt(0).toUpperCase()
        : "C";

      let expiry_html = "";

      if (c.food_license_validity) {
        let today = frappe.datetime.get_today();
        let diff = frappe.datetime.get_diff(c.food_license_validity, today);

        if (diff <= 30 && diff >= 0) {
          expiry_html = `<div class="license-warning expiring">
                    ⚠ License expiring in ${diff} days
                </div>`;
        }

        if (diff < 0) {
          expiry_html = `<div class="license-warning expired">
                    ❌ License expired
                </div>`;
        }
      }

      return `
        <div class="customer-card"
             onclick="frappe.set_route('Form','Customer','${c.name}')">

            <div class="customer-header">
                <div class="avatar">${letter}</div>
                <div><b>${c.customer_name}</b></div>
            </div>

            <div class="customer-info">
                <span>Start Date</span>
                <b>${c.custom_starting_date_of_the_contract || "-"}</b>
            </div>

            <div class="customer-info">
                <span>Price List</span>
                <b>${c.default_price_list || "-"}</b>
            </div>

            <div class="customer-info">
                <span>Food License</span>
                <b>${c.food_license_number || "-"}</b>
            </div>

            <div class="customer-info">
                <span>License Validity</span>
                <b>${c.food_license_validity || "-"}</b>
            </div>

            ${expiry_html}

        </div>
        `;
    })
    .join("");

  $("#customer-cards-container").html(html);
}
