/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";

export class PkrListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    async onGenerateReportClick() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Generate Report",
            res_model: "pallet_kilos_record_model.report.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }
}

PkrListController.template =
    "pallet_kilos_record_model.PkrListView";

export const pkrListView = {
    ...listView,
    Controller: PkrListController,
};

registry
    .category("views")
    .add("pkr_list_report_button", pkrListView);
