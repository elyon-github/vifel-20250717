/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from '@web/core/registry';
import { listView } from '@web/views/list/list_view';
import { useService } from "@web/core/utils/hooks";

export class MagicWizardListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
    }

    get isIncoming() {
        const ctx = this.props.context || {};
        return ctx.picking_type_code === 'incoming' || ctx.picking_code === 'incoming';
    }

    get isDone() {
        const ctx = this.props.context || {};
        return ctx.state === 'done';
    }

    get showMagicWizardButton() {
        return this.isIncoming && !this.isDone;
    }

    async onMagicWizardClick() {
        // Get all record IDs from the list (all move lines for this picking)
        const records = this.model.root.records;

        if (!records || records.length === 0) {
            this.notification.add("No move lines found.", { type: "warning" });
            return;
        }

        // Collect all record IDs
        const allIds = records.map(r => r.resId).filter(id => id);

        if (allIds.length === 0) {
            this.notification.add("No valid move lines found.", { type: "warning" });
            return;
        }

        try {
            // Call action_open_fast_encode_wizard on all move line records
            const result = await this.orm.call(
                'stock.move.line',
                'action_open_fast_encode_wizard',
                [allIds]
            );

            if (result) {
                await this.action.doAction(result, {
                    onClose: async () => {
                        // Reload the list view after wizard closes
                        await this.model.root.load();
                        this.render(true);
                    },
                });
            }
        } catch (error) {
            this.notification.add(
                error.data?.message || error.message || "An error occurred while opening the wizard.",
                { type: "danger" }
            );
        }
    }
}

MagicWizardListController.template = "multiple_relocation.MagicWizardListView";

export const magicWizardListView = {
    ...listView,
    Controller: MagicWizardListController,
};

registry.category("views").add("magic_wizard_list_view", magicWizardListView);
