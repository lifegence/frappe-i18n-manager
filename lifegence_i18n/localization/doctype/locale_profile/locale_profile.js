frappe.ui.form.on("Locale Profile", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Run Scan"), () => {
			frm.call("run_scan").then((r) => {
				if (!r.message) return;
				frappe.show_alert({
					message: __("Started scan {0}", [r.message]),
					indicator: "blue",
				});
				frappe.set_route("Form", "Translation Scan", r.message);
			});
		}).addClass("btn-primary");

		frm.add_custom_button(__("Verify Delivery"), () => {
			frm.call("verify_delivery").then((r) => {
				if (!r.message) return;
				const d = r.message;
				const rows = [
					[__("Live on this site"), d.live],
					[__("Not deployed"), d.not_deployed],
					[__("Cache stale"), d.stale],
					[__("Overridden"), d.overridden],
				];
				let advice = "";
				if (d.stale) {
					advice = __("The files carry these translations but this site is serving an older copy. Run bench clear-cache.");
				} else if (d.not_deployed) {
					advice = __("These translations have not reached the application files yet — not exported, not merged, or not deployed.");
				} else if (d.overridden) {
					advice = __("Something later in the merge order resolves these strings to a different value.");
				}
				frappe.msgprint({
					title: __("Delivery: {0}", [__(d.state)]),
					message:
						`<table class="table table-bordered"><tbody>` +
						rows.map(([label, n]) => `<tr><td>${label}</td><td class="text-right">${n}</td></tr>`).join("") +
						`</tbody></table>` +
						(advice ? `<p>${advice}</p>` : ""),
					indicator: d.state === "Live" ? "green" : "orange",
				});
				frm.reload_doc();
			});
		});

		frm.add_custom_button(__("Translation Ledger"), () => {
			frappe.set_route("List", "Translation Entry", { locale: frm.doc.name });
		}, __("Go To"));

		frm.add_custom_button(__("Issues"), () => {
			frappe.set_route("List", "Translation Issue", {
				locale: frm.doc.name,
				status: "Open",
			});
		}, __("Go To"));

		frm.add_custom_button(__("Glossary"), () => {
			frappe.set_route("List", "Glossary Term", { locale: frm.doc.name });
		}, __("Go To"));

		frm.add_custom_button(__("Review Sheet (CSV)"), () => {
			open_url_post(
				"/api/method/lifegence_i18n.api.export_review_sheet",
				{ locale: frm.doc.name },
				true
			);
		}, __("Export"));

		frm.add_custom_button(__("App Translation CSV"), () => {
			const apps = (frm.doc.target_apps || []).map((row) => row.app_name);
			frappe.prompt(
				[
					{
						fieldname: "app",
						label: __("App"),
						fieldtype: "Select",
						options: apps.join("\n"),
						reqd: 1,
					},
					{
						fieldname: "write_to_app",
						label: __("Also write into the app's translations folder on this bench"),
						fieldtype: "Check",
						description: __(
							"Writes <app>/translations/<lang>.csv where the app is checked out on this server, ready to commit. Not available on Frappe Cloud."
						),
					},
				],
				(values) => {
					open_url_post(
						"/api/method/lifegence_i18n.api.export_app_translations",
						{ locale: frm.doc.name, app: values.app, write_to_app: values.write_to_app ? 1 : 0 },
						true
					);
				},
				__("Export App Translation CSV")
			);
		}, __("Export"));

		frm.add_custom_button(__("Review Sheet (CSV)"), () => import_review(frm), __("Import File"));

		frm.add_custom_button(__("Bulk Term Change"), () => term_replace(frm), __("Actions"));

		frm.add_custom_button(__("Approve Drafts"), () => {
			frm.call("draft_count").then((r) => {
				const count = r.message || 0;
				if (!count) {
					frappe.show_alert({ message: __("No drafts to approve"), indicator: "blue" });
					return;
				}
				frappe.confirm(
					__("Approve {0} draft translations so they can be applied to the site?", [count]),
					() => {
						frm.call("approve_drafts").then((res) => {
							frappe.show_alert({
								message: __("Approved {0}", [res.message.approved]),
								indicator: "green",
							});
						});
					}
				);
			});
		}, __("Actions"));

		frm.add_custom_button(__("Apply to Site"), () => {
			frappe.confirm(
				__("Apply the approved translations to the site as Translation records. Continue?"),
				() => {
					frm.call("apply_to_site").then((r) => {
						if (!r.message) return;
						let message = __("{0} created / {1} updated", [
							r.message.created,
							r.message.updated,
						]);
						if (r.message.formats === false) {
							message +=
								"<br><br>" +
								__(
									"Display formats were not applied: this Frappe version holds no per-language formats. Set them in System Settings or per user."
								);
						}
						if (r.message.drafts) {
							message +=
								"<br><br>" +
								__(
									"{0} translations are still Draft and were not applied. Use Actions → Approve Drafts.",
									[r.message.drafts]
								);
						}
						frappe.msgprint({
							title: __("Applied to the site"),
							indicator: r.message.drafts ? "orange" : "green",
							message: message,
						});
					});
				}
			);
		}, __("Actions"));

		render_summary(frm);
	},
});

function render_summary(frm) {
	if (!frm.doc.total_strings) return;
	const rows = (frm.doc.target_apps || [])
		.slice()
		.sort((a, b) => b.untranslated_strings - a.untranslated_strings)
		.slice(0, 10);

	const body = rows
		.map(
			(row) => `<tr>
				<td>${frappe.utils.escape_html(row.app_name || "")}</td>
				<td class="text-right">${row.total_strings}</td>
				<td class="text-right">${row.untranslated_strings}</td>
				<td class="text-right">${(row.coverage || 0).toFixed(1)}%</td>
			</tr>`
		)
		.join("");

	frm.dashboard.add_section(
		`<table class="table table-bordered" style="margin:0">
			<thead><tr>
				<th>${__("App")}</th>
				<th class="text-right">${__("Total")}</th>
				<th class="text-right">${__("Untranslated")}</th>
				<th class="text-right">${__("Coverage")}</th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>`,
		__("Apps with the Most Untranslated Strings")
	);
}

function import_review(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Import Review Sheet"),
		fields: [
			{
				fieldname: "file_url",
				label: __("Completed Review Sheet"),
				fieldtype: "Attach",
				reqd: 1,
				description: __("Only rows with an entry in the proposal column are imported. Blank rows are left unchanged."),
			},
		],
		primary_action_label: __("Import File"),
		primary_action(values) {
			frappe.call({
				method: "lifegence_i18n.api.import_review_sheet",
				args: { locale: frm.doc.name, file_url: values.file_url },
				freeze: true,
				freeze_message: __("Importing..."),
				callback(r) {
					dialog.hide();
					frappe.msgprint({
						title: __("Import Complete"),
						indicator: r.message.skipped ? "orange" : "green",
						message: __("Applied {0} / skipped {1}", [
							r.message.applied,
							r.message.skipped,
						]),
					});
				},
			});
		},
	});
	dialog.show();
}

function term_replace(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Term Change"),
		fields: [
			{ fieldname: "find", label: __("Current Translation"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "replace", label: __("After Change"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "preview", fieldtype: "HTML" },
		],
		primary_action_label: __("Check Impact"),
		primary_action(values) {
			frappe.call({
				method: "lifegence_i18n.api.replace_term",
				args: { locale: frm.doc.name, ...values, dry_run: 1 },
				callback(r) {
					const data = r.message;
					const body = data.rows
						.map(
							(row) => `<tr>
								<td>${frappe.utils.escape_html(row.source_text)}</td>
								<td>${frappe.utils.escape_html(row.before)}</td>
								<td>${frappe.utils.escape_html(row.after)}</td>
							</tr>`
						)
						.join("");
					dialog.fields_dict.preview.$wrapper.html(
						`<p>${__("{0} rows affected (first 200 shown)", [data.count])}</p>
						<div style="max-height:280px;overflow:auto">
						<table class="table table-bordered">
							<thead><tr><th>${__("Source Text")}</th><th>${__("Current Translation")}</th><th>${__("After Change")}</th></tr></thead>
							<tbody>${body}</tbody>
						</table></div>`
					);
					dialog.set_primary_action(__("Run Replacement"), () => {
						frappe.call({
							method: "lifegence_i18n.api.replace_term",
							args: { locale: frm.doc.name, ...values, dry_run: 0 },
							callback(res) {
								frappe.show_alert({
									message: __("Changed {0} rows", [res.message.count]),
									indicator: "green",
								});
								dialog.hide();
							},
						});
					});
				},
			});
		},
	});
	dialog.show();
}
