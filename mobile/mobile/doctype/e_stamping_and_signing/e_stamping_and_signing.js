frappe.ui.form.on("E stamping and signing", {
  refresh: function (frm) {

    const allowed_users = [ "sanskar@bastardairyfarm.com"];
    const current_user = frappe.session.user;

    // 2. Hide the entire Tab if the user is not allowed
    if (!allowed_users.includes(current_user)) {
      // Replace 'api_debug_tab' with the actual fieldname of your Tab Break
      frm.set_df_property("api_call_back_tab", "hidden", 1);
      
      // Also hide any other specific fields that might be outside that tab
      frm.set_df_property("full_response", "hidden", 1);
    }

    const scroll_fields = [
      "only_content",
      "request_content",
      "request_body",
      "response_body",
      "request_body_stamping",
      "response_body_stamping",
      "full_response",
    ];

    scroll_fields.forEach((fieldname) => {
      let field = frm.get_field(fieldname);
      if (field && field.wrapper) {
        $(field.wrapper).find(".ace_editor").css("height", "300px");
        frm.set_df_property(fieldname, "options", "Copy");
      }
    });

    // ✅ Apply UI mode (tabs + buttons)
    frm.events.apply_mode(frm);
  },

  // 🔥 TRIGGER ON FIELD CHANGE (INSTANT)
  choose_actio: function (frm) {
    frm.events.apply_mode(frm);
  },

  // 🔥 MAIN CONTROLLER (TABS + BUTTONS)
  apply_mode: function (frm) {
    // -------------------------
    // ✅ TAB LOGIC (STABLE)
    // -------------------------
    setTimeout(() => {
      let stamping_tab = frm.$wrapper
        .find('[data-fieldname="stamping_details_tab"]')
        .closest(".tab-pane");
      let stamping_btn = frm.$wrapper.find(
        '.nav-link[data-fieldname="stamping_details_tab"]',
      );

      // RESET FIRST (IMPORTANT)
      stamping_tab.show();
      stamping_btn.show();

      if (frm.doc.choose_actio === "signing") {
        stamping_tab.hide();
        stamping_btn.hide();

        // 👉 move to signing tab
        frm.set_active_tab("e_sign_details_tab");
      }
    }, 100);

    // -------------------------
    // ✅ BUTTON LOGIC
    // -------------------------
    frm.events.setup_buttons(frm);
  },

  // 🔥 BUTTON CONTROLLER
  setup_buttons: function (frm) {
    frm.clear_custom_buttons();

    if (frm.doc.docstatus !== 0) return;

    if (frm.doc.signing_status === "Success") {
        return; 
    }

    // ✅ ONLY SIGNING MODE
    if (frm.doc.choose_actio === "signing") {
      frm
        .add_custom_button(
          __("Call E-Sign API"),
          function () {
            frm.trigger("execute_esign");
          },
          __("Actions"),
        )
        .addClass("btn-primary");

      return;
    }

    // ✅ STAMPING + SIGNING MODE (YOUR ORIGINAL LOGIC PRESERVED)
    if (frm.doc.request_content && !frm.doc.only_content) {
      frm.add_custom_button(
        __("Call Stamping API"),
        function () {
          frm.trigger("execute_stamping");
        },
        __("Actions"),
      );
    }

    if (frm.doc.only_content) {
      frm
        .add_custom_button(
          __("Call E-Sign API"),
          function () {
            frm.trigger("execute_esign");
          },
          __("Actions"),
        )
        .addClass("btn-primary");
    }
  },

  convert_pdf: function (frm) {
    if (!frm.doc.content)
      return frappe.msgprint(__("Please upload a PDF first."));
    frappe.call({
      doc: frm.doc,
      method: "convert_pdf_to_base64",
      freeze: true,
      callback: () => {
        frm.reload_doc();
        frappe.show_alert({
          message: __("PDF Converted Successfully"),
          indicator: "green",
        });
      },
    });
  },

  execute_stamping: function (frm) {
    frappe.call({
      doc: frm.doc,
      method: "call_stamping_api",
      freeze: true,
      callback: (r) => {
        if (r.message) {
          frm.set_value("request_body_stamping", r.message.request);
          frm.set_value("response_body_stamping", r.message.response);

          if (r.message.status === "success") {
            frappe.msgprint({
              title: __("Success"),
              indicator: "green",
              message: __("Stamping done proceed for esign"),
            });

            // 🔥 Refresh buttons after stamping
            frm.events.setup_buttons(frm);
          } else {
            frappe.msgprint({
              title: __("Stamping Failed"),
              indicator: "red",
              message: __(r.message.error || "Unknown Error"),
            });
          }
        }
      },
    });
  },

  execute_esign: function (frm) {
    if (!frm.doc.signer_info_table || frm.doc.signer_info_table.length === 0) {
      frappe.throw(__("Please add at least one signer to the table."));
    }

    frappe.confirm(__("Trigger E-Sign for all signers?"), function () {
      frappe.call({
        doc: frm.doc,
        method: "call_esign_api",
        freeze: true,
        callback: function (r) {
          if (r.message) {
            frm.set_value("request_body", r.message.request);
            frm.set_value("response_body", r.message.response);

            if (r.message.status === "success") {
              frappe.msgprint({
                title: __("Success"),
                indicator: "green",
                message: __("Signing is Done Successfully"),
              });
            } else {
              frappe.msgprint({
                title: __("Signing Failed"),
                indicator: "red",
                message: r.message.error || "Request Failed",
              });
            }
          }
        },
      });
    });
  },
});

frappe.ui.form.on("Signers Info", {
  signer_info_table_add: function (frm, cdt, cdn) {
    if (frm.doc.reference_doc_id) {
      frappe.model.set_value(
        cdt,
        cdn,
        "document_to_be_signed",
        frm.doc.reference_doc_id,
      );
    }
  },
});

frappe.ui.form.on("E stamping and signing", {
  category_of_agreement: function (frm) {
    // Triggered whenever 'category_of_agreement' is changed
    if (frm.doc.category_of_agreement) {
      frm.set_value("document_category", frm.doc.category_of_agreement);

      frm.set_value("document_title", frm.doc.category_of_agreement);

      frm.refresh_field("document_category");
      frm.refresh_field("document_title");
    }
  },
});

frappe.ui.form.on('E stamping and signing', {

    refresh: function(frm) {

        // ✅ Auto add rows (only once)
        if (frm.is_new() && (!frm.doc.signer_info_table || frm.doc.signer_info_table.length === 0)) {

            const default_rows = [
                { type_of_signer: "First Party", signer_ref_id: "S1", sequence: 1 },
                { type_of_signer: "Second Party", signer_ref_id: "S2", sequence: 2 },
                { type_of_signer: "Witness 1", signer_ref_id: "S3", sequence: 3 },
                { type_of_signer: "Witness 2", signer_ref_id: "S4", sequence: 4 }
            ];

            default_rows.forEach(row => {
                let child = frm.add_child('signer_info_table');
                Object.assign(child, row);
            });

            frm.refresh_field('signer_info_table');
        }

        let grid = frm.get_field('signer_info_table').grid;

        // ❌ Disable buttons
        grid.cannot_add_rows = true;

        // ❌ Hide Add Row button (IMPORTANT)
        $(frm.wrapper).find('.grid-add-row').hide();
    }

});