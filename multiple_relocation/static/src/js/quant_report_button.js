/** @odoo-module */
/**
 * Adds the "Generate Report" button to VIFEL stock.quant list views.
 *
 * The controller is attached to the shared quant list view, so the button
 * only renders when the action asks for it (context.show_pkr_report) —
 * standard Odoo quant screens (Physical Inventory, ...) stay untouched.
 *
 * When the list is already scoped to one client (the Contact smart
 * buttons pass vifel_client_id), the wizard opens with that client
 * pre-selected.
 */
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";

export class VifelQuantListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    get showVifelReportButton() {
        return Boolean(this.props.context && this.props.context.show_pkr_report);
    }

    async onGenerateReportClick() {
        const ctx = this.props.context || {};
        const wizardContext = {};
        const clientId = ctx.vifel_client_id;
        if (clientId) {
            wizardContext.default_partner_ids = [[6, 0, [clientId]]];
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Generate Report",
            res_model: "pallet_kilos_record_model.report.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: wizardContext,
        });
    }
}

VifelQuantListController.template = "multiple_relocation.VifelQuantListView";

export const vifelQuantListView = {
    ...listView,
    Controller: VifelQuantListController,
};

registry.category("views").add("vifel_quant_report_list", vifelQuantListView);
