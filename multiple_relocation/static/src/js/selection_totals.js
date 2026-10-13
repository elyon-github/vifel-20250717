/** @odoo-module **/

// Totals of the TICKED rows (No. of Pallets / Quantity / Weight (KG) / Packs) shown in the
// "N selected" box of any list that carries these fields (the quant lists: pick pallets for a WR).
//
// Odoo 17 rendered this from ListController getters + an extension of web.ListView.Selection.
// Odoo 19 moved the "N selected" box into its own component (web.SelectionBox, props: root), so the
// getters live on that component now. "Select all" (domain selected) totals come from the server.

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useEffect, useState } from "@odoo/owl";
import { SelectionBox } from "@web/views/view_components/selection_box";

const QTY = "x_studio_2nd_uom";
const KG = "available_quantity";
const PACKS = "x_studio_total_units";
const PALLET = "package_id";

function fmt(number) {
    return parseFloat(number || 0).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

patch(SelectionBox.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.vifelTotals = useState({ domain: null });
        // Fetch server-side totals whenever "Select all" is switched on; drop them when it is off.
        useEffect(
            (isDomainSelected) => {
                if (isDomainSelected && this.vifelHasTotals) {
                    this.vifelFetchDomainTotals();
                } else {
                    this.vifelTotals.domain = null;
                }
            },
            () => [this.root.isDomainSelected]
        );
    },

    // Only lists that actually have the weight field get the box (same gate as on 17: KG > 0).
    get vifelHasTotals() {
        return KG in (this.root.fields || {});
    },

    async vifelFetchDomainTotals() {
        const fields = this.root.fields;
        const aggregates = [`${KG}:sum`];
        if (QTY in fields) aggregates.push(`${QTY}:sum`);
        if (PACKS in fields) aggregates.push(`${PACKS}:sum`);
        if (PALLET in fields) aggregates.push(`${PALLET}:count_distinct`);
        try {
            const [res] = await this.orm.formattedReadGroup(
                this.root.resModel, this.root.domain, [], aggregates, { context: this.root.context }
            );
            this.vifelTotals.domain = {
                kg: res?.[`${KG}:sum`] || 0,
                quantity: res?.[`${QTY}:sum`] || 0,
                packs: res?.[`${PACKS}:sum`] || 0,
                pallets: res?.[`${PALLET}:count_distinct`] || 0,
            };
        } catch (error) {
            console.error("Error fetching selection totals:", error);
        }
    },

    // Numeric totals of the current selection (or of the whole domain once fetched).
    get vifelTotalsNumeric() {
        if (this.root.isDomainSelected) {
            return this.vifelTotals.domain;   // null while loading
        }
        const pallets = new Set();
        let quantity = 0, kg = 0, packs = 0;
        for (const record of this.selectedRecords) {
            const d = record.data;
            quantity += parseFloat(d[QTY]) || 0;
            kg += parseFloat(d[KG]) || 0;
            packs += parseFloat(d[PACKS]) || 0;
            const pallet = d[PALLET];
            const palletId = pallet && (pallet.id ?? (Array.isArray(pallet) ? pallet[0] : pallet));
            if (palletId) {
                pallets.add(palletId);
            }
        }
        return { quantity, kg, packs, pallets: pallets.size };
    },

    get vifelSelectionTotals() {
        if (!this.vifelHasTotals || !this.nbSelected && !this.root.isDomainSelected) {
            return null;
        }
        const t = this.vifelTotalsNumeric;
        if (!t) {
            return { loading: true };
        }
        if (!(t.kg > 0)) {
            return null;
        }
        return {
            pallets: t.pallets,
            quantity: t.quantity > 0 ? fmt(t.quantity) : null,
            kg: fmt(t.kg),
            packs: t.packs > 0 ? fmt(t.packs) : null,
        };
    },
});
