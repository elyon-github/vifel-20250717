/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { registry } from '@web/core/registry';
import { listView } from '@web/views/list/list_view';
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onMounted, onWillUnmount, markup } from "@odoo/owl";

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
        this._resyncDialogOpen = false;

        // Bind handlers once so we can remove them later
        this._boundKeyDown = this._onKeyDown.bind(this);
        this._boundCloseClick = this._onCloseButtonClick.bind(this);

        onMounted(() => {
            // Intercept Escape key in capture phase (fires before Odoo's dialog handler)
            document.addEventListener("keydown", this._boundKeyDown, true);

            // Find the parent dialog's X/close button and intercept it
            this._attachCloseBtnListener();

            // Poll for pending resync flags on records
            this._resyncInterval = setInterval(() => this._checkPendingResync(), 500);
        });

        onWillUnmount(() => {
            document.removeEventListener("keydown", this._boundKeyDown, true);
            if (this._closeBtn) {
                this._closeBtn.removeEventListener("click", this._boundCloseClick, true);
            }
            if (this._resyncInterval) {
                clearInterval(this._resyncInterval);
            }
        });
    }

    /**
     * Check if any record has a pending_resync_pallet_id set and show confirmation.
     */
    async _checkPendingResync() {
        if (this._resyncDialogOpen || this._confirmOpen || this._checkingResync) return;
        this._checkingResync = true;
        try {
            await this._doCheckPendingResync();
        } finally {
            this._checkingResync = false;
        }
    }

    async _doCheckPendingResync() {

        // Check local pending fields for dialogs to show.
        // Cascade detected by write() and flagged immediately; no need to re-poll server every 2s.
        const records = this.model.root.records || [];
        const pendingLines = [];
        for (const rec of records) {
            const pendingPallet = rec.data.pending_resync_pallet_id;
            if (pendingPallet && pendingPallet[0]) {
                pendingLines.push({
                    lineId: rec.resId,
                    palletId: pendingPallet[0],
                    oldSeries: rec.data.pending_resync_old_series || "?",
                    newSeries: rec.data.pending_resync_new_series || "?",
                    resyncType: rec.data.pending_resync_type || "resync",
                });
            }
        }
        if (pendingLines.length === 0) return;
        this._resyncDialogOpen = true;

        // Separate cascade vs resync lines
        const cascadeLines = pendingLines.filter(l => l.resyncType === "cascade");
        const resyncLines = pendingLines.filter(l => l.resyncType !== "cascade");

        // Build a rich HTML body listing all affected lines
        const esc = (s) => {
            const d = document.createElement("div");
            d.textContent = s;
            return d.innerHTML;
        };

        let html = "";
        let title = "";
        let confirmLabel = "";

        if (cascadeLines.length > 0 && resyncLines.length === 0) {
            // Pure cascade
            title = "Pallet Group Series Update";
            confirmLabel = "Yes, Update Series";
            const oldS = esc(cascadeLines[0].oldSeries);
            const newS = esc(cascadeLines[0].newSeries);
            html += `<p>The line with series <strong style='color:#d9534f;'>${oldS}</strong> was also used as the pallet series for other lines on this pallet. Since it has been removed, the lines that depend on it will be re-adjusted.</p>`;
            html += `<p style='margin:8px 0;'>Series will change from <strong style='color:#d9534f;'>${oldS}</strong> &rarr; <strong style='color:#5cb85c;'>${newS}</strong></p>`;
            if (cascadeLines.length > 1) {
                html += `<p><strong>${cascadeLines.length} lines</strong> will be affected.</p>`;
            }
        } else if (resyncLines.length > 0 && cascadeLines.length === 0) {
            // Pure resync
            title = "Pallet Series Will Be Re-Synced";
            confirmLabel = "Yes, Re-Sync";
            html += "<p><strong>This pallet is already in use.</strong> The following pallet series will be recycled back to the pool and can be used for future pallets:</p>";
            html += "<ul style='margin:8px 0;padding-left:20px;color:#666;'>";
            for (const line of resyncLines) {
                html += `<li><strong style='color:#d9534f;'>${esc(line.oldSeries)}</strong> will be recycled (originally assigned to this line)</li>`;
            }
            html += "</ul>";
            const newSeries = resyncLines[0].newSeries;
            html += `<p style='margin:8px 0;'>Current lines will be assigned to series <strong style='color:#5cb85c;'>${esc(newSeries)}</strong>.</p>`;
            html += "<p style='color:#666;font-size:0.95em;'><em>\uD83D\uDCA1 If you clear the pallet or revert this line to a unique pallet later, the original series will be restored.</em></p>";
            if (resyncLines.length > 1) {
                html += `<p style='margin-top:12px;'><strong>${resyncLines.length} lines</strong> will be affected by this change.</p>`;
            }
        } else {
            // Mixed — show both
            title = "Pallet Series Changes Required";
            confirmLabel = "Yes, Apply Changes";
            html += "<p>Multiple pallet series changes are needed:</p>";
            if (resyncLines.length > 0) {
                html += `<p><strong>Re-sync (${resyncLines.length} line${resyncLines.length > 1 ? 's' : ''}):</strong> Series will be recycled.</p>`;
            }
            if (cascadeLines.length > 0) {
                const oldS = esc(cascadeLines[0].oldSeries);
                const newS = esc(cascadeLines[0].newSeries);
                html += `<p><strong>Cascade (${cascadeLines.length} line${cascadeLines.length > 1 ? 's' : ''}):</strong> ${oldS} &rarr; ${newS}</p>`;
            }
        }

        this.dialogService.add(ConfirmationDialog, {
            title: title,
            body: markup(html),
            confirmLabel: confirmLabel,
            cancelLabel: "No, Cancel",
            confirm: async () => {
                for (const { lineId, palletId } of pendingLines) {
                    await this.orm.call(
                        "stock.move.line.fast_encode_rr.line",
                        "action_apply_resync",
                        [[lineId], palletId]
                    );
                }
                await this.model.root.load();
                this.render(true);
            },
            cancel: async () => {
                const lineIds = pendingLines.map(p => p.lineId);
                await this.orm.call(
                    "stock.move.line.fast_encode_rr.line",
                    "action_cancel_resync",
                    [lineIds]
                );
                await this.model.root.load();
                this.render(true);
            },
        }, {
            onClose: () => {
                this._resyncDialogOpen = false;
            },
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
                    // Server-side UserError messages live at error.data.message;
                    // error.message is the generic "Odoo Server Error" wrapper.
                    const msg = error.data?.message || error.message || "Error occurred";
                    this.notification.add(msg, { type: "danger", sticky: true });
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