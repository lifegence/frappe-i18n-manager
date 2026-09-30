frappe.ui.form.on("Translation Scan", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (can_manage() && ["Queued", "Failed", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Run Scan"), () => {
				frm.call("enqueue_run").then(() => {
					frappe.show_alert({ message: __("Queued the scan"), indicator: "blue" });
					poll(frm);
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Running") {
			frm.dashboard.set_headline(__("Running. The page refreshes when it finishes."));
			poll(frm);
		}

		if (frm.doc.status === "Completed") {
			frm.add_custom_button(__("View Issues"), () => {
				frappe.set_route("List", "Translation Issue", { scan: frm.doc.name });
			});
		}
	},
});

function poll(frm) {
	setTimeout(() => {
		frappe.db.get_value("Translation Scan", frm.doc.name, "status").then((r) => {
			if (r.message && r.message.status !== frm.doc.status) {
				frm.reload_doc();
			} else if (r.message && r.message.status === "Running") {
				poll(frm);
			}
		});
	}, 4000);
}

// The server refuses the call in any case; hiding the button is so that nobody
// has to press it to find that out.
function can_manage() {
	return (
		frappe.user_roles.includes("Localization Manager") ||
		frappe.user_roles.includes("System Manager") ||
		frappe.user_roles.includes("Administrator")
	);
}
