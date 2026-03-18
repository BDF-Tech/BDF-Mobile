frappe.ui.form.on('E stamping and signing', {
    refresh: function(frm) {
        const scroll_fields = [
            'only_content', 'request_content', 'request_body', 
            'response_body', 'request_body_stamping', 
            'response_body_stamping', 'full_response'
        ];
        
        scroll_fields.forEach(fieldname => {
            let field = frm.get_field(fieldname);
            if (field && field.wrapper) {
                $(field.wrapper).find('.ace_editor').css('height', '300px');
                frm.set_df_property(fieldname, 'options', 'Copy');
            }
        });

        frm.clear_custom_buttons();

        if (frm.doc.request_content && !frm.doc.only_content && frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Call Stamping API'), function() {
                frm.trigger('execute_stamping');
            }, __("Actions"));
        }

        if (frm.doc.only_content && frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Call E-Sign API'), function() {
                frm.trigger('execute_esign');
            }, __("Actions")).addClass('btn-primary');
        }
    },

    convert_pdf: function(frm) {
        if (!frm.doc.content) return frappe.msgprint(__('Please upload a PDF first.'));
        frappe.call({
            doc: frm.doc,
            method: "convert_pdf_to_base64",
            freeze: true,
            callback: () => {
                frm.reload_doc();
                frappe.show_alert({message: __('PDF Converted Successfully'), indicator: 'green'});
            }
        });
    },

    execute_stamping: function(frm) {
        frappe.call({
            doc: frm.doc,
            method: "call_stamping_api",
            freeze: true,
            callback: (r) => {
                if (r.message) {
                    // Update UI fields directly
                    frm.set_value('request_body_stamping', r.message.request);
                    frm.set_value('response_body_stamping', r.message.response);

                    if (r.message.status === "success") {
                        frappe.msgprint({
                            title: __('Success'),
                            indicator: 'green',
                            message: __('Stamping done proceed for esign')
                        });
                    } else {
                        frappe.msgprint({
                            title: __('Stamping Failed'),
                            indicator: 'red',
                            message: __(r.message.error || "Unknown Error")
                        });
                    }
                    // Do NOT reload_doc here to keep the field values visible
                }
            }
        });
    },

    execute_esign: function(frm) {
        if (!frm.doc.signer_info_table || frm.doc.signer_info_table.length === 0) {
            frappe.throw(__("Please add at least one signer to the table."));
        }

        frappe.confirm(__('Trigger E-Sign for all signers?'), function() {
            frappe.call({
                doc: frm.doc,
                method: "call_esign_api",
                freeze: true,
                callback: function(r) {
                    if (r.message) {
                        // Set values so they appear in the text areas
                        frm.set_value('request_body', r.message.request);
                        frm.set_value('response_body', r.message.response);
                        
                        if (r.message.status === "success") {
                            frappe.msgprint({
                                title: __('Success'),
                                indicator: 'green',
                                message: __('Signing is Done Successfully')
                            });
                        } else {
                            frappe.msgprint({
                                title: __('Signing Failed'),
                                indicator: 'red',
                                message: r.message.error || "Request Failed"
                            });
                        }
                    }
                }
            });
        });
    }
});

frappe.ui.form.on('Signers Info', {
    signer_info_table_add: function(frm, cdt, cdn) {
        if (frm.doc.reference_doc_id) {
            frappe.model.set_value(cdt, cdn, 'document_to_be_signed', frm.doc.reference_doc_id);
        }
    }
});