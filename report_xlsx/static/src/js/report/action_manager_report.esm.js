/** @odoo-module **/

import {download} from "@web/core/network/download";
import {registry} from "@web/core/registry";

registry
    .category("ir.actions.report handlers")
    .add("xlsx_handler", async function (action, options, env) {
        if (action.report_type === "xlsx") {
            const type = action.report_type;
            let url = `/report/${type}/${action.report_name}`;
            const actionContext = action.context || {};
            // VIFEL: also pass the list's domain. "Select all" only sends the
            // first active_ids_limit (20,000) ids, so a report can use
            // active_domain to cover the rest. report_download reads the
            // context posted below (not the one in the url) for id reports.
            const reportContext = {...env.services.user.context};
            if (actionContext.active_domain) {
                reportContext.active_domain = actionContext.active_domain;
            }
            if (action.data && JSON.stringify(action.data) !== "{}") {
                // Build a query string with `action.data` (it's the place where reports
                // using a wizard to customize the output traditionally put their options)
                const action_options = encodeURIComponent(JSON.stringify(action.data));
                const context = encodeURIComponent(JSON.stringify(actionContext));
                url += `?options=${action_options}&context=${context}`;
            } else {
                if (actionContext.active_ids) {
                    url += `/${actionContext.active_ids.join(",")}`;
                }
                if (type === "xlsx") {
                    const context = encodeURIComponent(
                        JSON.stringify(reportContext)
                    );
                    url += `?context=${context}`;
                }
            }
            env.services.ui.block();
            try {
                await download({
                    url: "/report/download",
                    data: {
                        data: JSON.stringify([url, action.report_type]),
                        context: JSON.stringify(reportContext),
                    },
                });
            } finally {
                env.services.ui.unblock();
            }
            const onClose = options.onClose;
            if (action.close_on_report_download) {
                return env.services.action.doAction(
                    {type: "ir.actions.act_window_close"},
                    {onClose}
                );
            } else if (onClose) {
                onClose();
            }
            return Promise.resolve(true);
        }
        return Promise.resolve(false);
    });
