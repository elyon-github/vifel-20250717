/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";

export class StockQuantHistorySnapshotListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    async onOccupancyReportClick() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Occupancy Report",
            res_model: "stock.quant.history.occupancy.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }
}

StockQuantHistorySnapshotListController.template =
    "stock_quant_history.StockQuantHistorySnapshotListView";

export const stockQuantHistorySnapshotListView = {
    ...listView,
    Controller: StockQuantHistorySnapshotListController,
};

registry
    .category("views")
    .add("stock_quant_history_snapshot_list_button", stockQuantHistorySnapshotListView);
