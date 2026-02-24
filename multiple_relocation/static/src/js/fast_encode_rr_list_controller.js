/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from '@web/core/registry';
import { listView } from '@web/views/list/list_view';
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onMounted, onWillUnmount } from "@odoo/owl";

export class FastEncodeRRListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.notification = useService("notification");
        this.action = useService("action");

        // Close-confirmation state
        this._isClosing = false;
        this._confirmOpen = false;

        // Bind handlers once so we can remove them later
        this._boundKeyDown = this._onKeyDown.bind(this);
        this._boundCloseClick = this._onCloseButtonClick.bind(this);

        onMounted(() => {
            // Intercept Escape key in capture phase (fires before Odoo's dialog handler)
            document.addEventListener("keydown", this._boundKeyDown, true);

            // Find the parent dialog's X/close button and intercept it
            this._attachCloseBtnListener();
        });

        onWillUnmount(() => {
            document.removeEventListener("keydown", this._boundKeyDown, true);
            if (this._closeBtn) {
                this._closeBtn.removeEventListener("click", this._boundCloseClick, true);
            }
        });
    }

    /**
     * Find the dialog's close button (the X) and attach our interceptor.
     * Uses a short delay because the dialog DOM may render slightly after mount.
     */
    _attachCloseBtnListener() {
        const tryAttach = () => {
            // The wizard dialog is the last .o_dialog in the DOM
            const dialogs = document.querySelectorAll(".o_dialog");
            const dialogEl = dialogs[dialogs.length - 1];
            if (dialogEl) {
                const closeBtn = dialogEl.querySelector(".btn-close");
                if (closeBtn) {
                    this._closeBtn = closeBtn;
                    closeBtn.addEventListener("click", this._boundCloseClick, true);
                    return true;
                }
            }
            return false;
        };

        if (!tryAttach()) {
            // Retry once after a tick if DOM wasn't ready yet
            setTimeout(() => tryAttach(), 150);
        }
    }

    /**
     * Capture-phase keydown: intercept Escape only when our confirm dialog isn't open.
     */
    _onKeyDown(ev) {
        if (ev.key === "Escape" && !this._isClosing && !this._confirmOpen) {
            ev.stopImmediatePropagation();
            ev.preventDefault();
            this._askCloseConfirmation();
        }
    }

    /**
     * Capture-phase click on the dialog's X button.
     */
    _onCloseButtonClick(ev) {
        if (!this._isClosing) {
            ev.stopImmediatePropagation();
            ev.preventDefault();
            this._askCloseConfirmation();
        }
    }

    /**
     * Show a confirmation dialog before discarding wizard progress.
     */
    _askCloseConfirmation() {
        if (this._confirmOpen) return;
        this._confirmOpen = true;

        this.dialogService.add(ConfirmationDialog, {
            title: "Close Wizard?",
            body: "Are you sure you want to close? All unsaved progress will be lost.",
            confirmLabel: "Yes, Close",
            cancelLabel: "Continue Editing",
            confirm: () => {
                this._isClosing = true;
                this.action.doAction({ type: "ir.actions.act_window_close" });
            },
            cancel: () => {},
        }, {
            onClose: () => {
                this._confirmOpen = false;
            },
        });
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