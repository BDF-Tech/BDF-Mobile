// Copyright (c) 2023, Qunatbit and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Location', {
	   onload: function(frm) {
        frm.call({
            method:'calculate_distance',//function name defined in python
            doc: frm.doc, //current document
        });

    
    }
});
