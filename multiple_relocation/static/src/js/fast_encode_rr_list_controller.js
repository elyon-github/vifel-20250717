/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from '@web/core/registry';
import { listView } from '@web/views/list/list_view';
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

export class FastEncodeRRListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.notification = useService("notification");
        this.action = useService("action");
    }
    
    async onConfirmClick() {
        const records = this.model.root.records;
        
        if (!records || records.length === 0) {
            this.notification.add("No lines to confirm.", { type: "warning" });
            return;
        }
        
        let wizardId = null;
        
        // Try to get wizard_id from the first record
        const firstRecord = records[0];
        if (firstRecord.data.wizard_id) {
            wizardId = Array.isArray(firstRecord.data.wizard_id) 
                ? firstRecord.data.wizard_id[0] 
                : firstRecord.data.wizard_id;
        }
        
        // If still not found, search for the wizard record that has these lines
        if (!wizardId) {
            try {
                const lineIds = records.map(r => r.resId);
                const wizards = await this.orm.searchRead(
                    'stock.move.line.fast_encode_rr',
                    [['line_ids', 'in', lineIds]],
                    ['id'],
                    { limit: 1 }
                );
                if (wizards.length > 0) {
                    wizardId = wizards[0].id;
                }
            } catch (e) {
                console.error("Error finding wizard:", e);
            }
        }
        
        if (!wizardId) {
            this.notification.add("Could not find wizard. Please try again.", { type: "warning" });
            return;
        }
        
        // Show confirmation dialog
        this.dialogService.add(ConfirmationDialog, {
            title: "Confirm Action",
            body: "Are you sure you want to apply these changes?",
            confirmLabel: "Yes",
            cancelLabel: "No",
            confirm: async () => {
                try {
                    await this.orm.call(
                        'stock.move.line.fast_encode_rr',
                        'action_confirm',
                        [[wizardId]]
                    );
                    
                    this.notification.add("Changes applied successfully!", { type: "success" });
                    this.action.doAction({ type: 'ir.actions.act_window_close' });
                } catch (error) {
                    this.notification.add(error.message || "Error occurred", { type: "danger" });
                }
            },
            cancel: () => {
                // User clicked No, do nothing
            }
        });
    }
}

FastEncodeRRListController.template = "stock.move.line.fast_encode_rr.ListView.Buttons";

export const customFastEncodeRRListController = {
    ...listView,
    Controller: FastEncodeRRListController,
};

registry.category("views").add("fast_encode_rr_list_button", customFastEncodeRRListController);