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

    // =====================================================================
    // Live Pallet Breakdown counter (No. of Pallets / Quantity / Weight KG)
    //
    // A read-only header tally that mirrors the PKR ledger and the generated
    // RR/WR reports, so the on-screen number never contradicts the paperwork
    // or the invoice. It recomputes reactively: `vifelCounts` reads
    // record.data.* during render, so Owl re-renders the chips whenever a line
    // is added, edited, merged or un-merged. Additive only — no write path.
    // =====================================================================

    /** 2-decimal en-US formatting, matching the Select Stocks counter. */
    _vifelFmt(n) {
        return (parseFloat(n) || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    /**
     * A line ORIGINATES a pallet unless it merged (+0) onto a pallet already
     * on the floor. `is_pallet_merge` is supplied by the client-requirements
     * Pallet Breakdown view; when that field is absent (feature not installed)
     * the read is undefined, so this defaults to true — exactly the neutral
     * "count everything" behaviour core already uses for pallet counting.
     */
    _vifelLineOriginatesPallet(record) {
        return !record.data.is_pallet_merge;
    }

    /**
     * Compute { pallets, quantity, weight } over all loaded lines, mirroring
     * pallet_kilos_record_model._populate_operations_data and the RR/WR report
     * pallet-count rules. quantity/weight sum EVERY line (a merge zeroes the
     * pallet count only, never the weight/qty); pallet count dedupes and
     * excludes merged lines on receipts.
     */
    get vifelCounts() {
        const ctx = this.props.context || {};
        const isBF = !!ctx.is_blast_freeze;
        const isOutgoing =
            ctx.picking_code === "outgoing" || ctx.picking_type_code === "outgoing";
        const records = (this.model.root && this.model.root.records) || [];
        const idOf = (v) => (Array.isArray(v) ? v[0] : v) || false;

        const seen = new Set();
        let pallets = 0;
        let quantity = 0;
        let weight = 0;

        for (const rec of records) {
            const d = rec.data;

            // Weight (KG): every line, both directions.
            weight += parseFloat(d.quantity) || 0;

            // Quantity (2nd UOM): every line, direction-specific field.
            quantity +=
                parseFloat(isOutgoing ? d.x_studio_affected_2nd_uom : d.x_studio_2nd_uom) ||
                0;

            // No. of Pallets: dedupe, mirror the ledger / report exactly.
            if (isBF) {
                const key = d.bf_pallet_char;
                if (key && !seen.has(key)) {
                    seen.add(key);
                    pallets += 1;
                }
            } else if (isOutgoing) {
                const pkg = idOf(d.package_id);
                if (!pkg) {
                    continue;
                }
                // _pdf_pallet_count_key identity: physical pallet + PSI.
                const key = "w:" + pkg + "|" + (idOf(d.x_studio_pallet_series_id) || "");
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);
                // A withdrawn pallet counts only when it leaves at 0 KG.
                // reserved_quantity_on_validation is stamped at validation; live
                // it reads 0 so every pallet counts (== a draft WR report), and a
                // validated WR uses the frozen snapshot to drop partial pallets.
                if ((parseFloat(d.reserved_quantity_on_validation) || 0) === 0) {
                    pallets += 1;
                }
            } else {
                // Incoming (RR): count per the server preview flag. On a pinned
                // Fixed pallet vifel_counts_in_preview counts EVERY receipt still
                // racing to birth it (pallet empty) and drops the losers once it
                // is stocked, matching validation order rather than merge order.
                // Falls back to the plain +0 rule when the flag is absent.
                const counts = ("vifel_counts_in_preview" in d)
                    ? !!d.vifel_counts_in_preview
                    : this._vifelLineOriginatesPallet(rec);
                if (!counts) {
                    continue;
                }
                const rpkg = idOf(d.result_package_id);
                if (!rpkg) {
                    continue;
                }
                const key = "r:" + rpkg;
                if (!seen.has(key)) {
                    seen.add(key);
                    pallets += 1;
                }
            }
        }

        return {
            pallets: pallets.toLocaleString("en-US"),
            quantity: this._vifelFmt(quantity),
            weight: this._vifelFmt(weight),
        };
    }

    /**
     * Show the multi-truck caveat only on an OPEN (not validated) withdrawal
     * whose pallet is being drawn by more than one transfer. is_package_multiple_withdraw
     * is a core computed flag: true when the same package sits on another active
     * (not done/cancel) picking. In that case a shared pallet only counts as
     * withdrawn on whichever transfer empties it last, so the live count is
     * provisional.
     */
    get vifelShowMultiWrNote() {
        const ctx = this.props.context || {};
        const isOutgoing =
            ctx.picking_code === "outgoing" || ctx.picking_type_code === "outgoing";
        const isDone = ctx.state === "done";
        if (!isOutgoing || isDone) {
            return false;
        }
        const records = (this.model.root && this.model.root.records) || [];
        return records.some((rec) => !!rec.data.is_package_multiple_withdraw);
    }

    /**
     * Show a "count is provisional" caveat on an OPEN (incoming, not done)
     * receipt that is birthing an empty pinned Fixed pallet: which receipt takes
     * the +1 is only settled at validation: whichever receipt validates onto
     * the empty pallet FIRST is the one that counts it. Reads the feature field
     * vifel_birth_provisional defensively (undefined when the merge add-on is
     * absent → falsy), exactly like vifelCounts reads is_pallet_merge.
     */
    get vifelShowProvisionalBirthNote() {
        const ctx = this.props.context || {};
        const isOutgoing =
            ctx.picking_code === "outgoing" || ctx.picking_type_code === "outgoing";
        const isDone = ctx.state === "done";
        if (isOutgoing || isDone) {
            return false;
        }
        const records = (this.model.root && this.model.root.records) || [];
        return records.some((rec) => !!rec.data.vifel_birth_provisional);
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
