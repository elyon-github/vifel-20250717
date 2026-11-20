/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { Domain } from "@web/core/domain";
// Retrieve the SMLX2ManyField class from the registry
const SMLX2ManyField = registry.category("fields").get("sml_x2_many")?.component;

// Odoo 19 Many2one values are {id, display_name} (Odoo 17: [id, name]).
const m2oId = (value) => (Array.isArray(value) ? value[0] : value?.id);

if (SMLX2ManyField) {
    patch(SMLX2ManyField.prototype, {
    // Odoo 19's own onAdd (stock_move_line_x2_many_field.js) plus VIFEL's
    // one addition: only quants owned by the transfer's client are offered.
    async onAdd({ context, editable } = {}) {
        if (!this.props.record.data.show_quant) {
            return super.onAdd(...arguments);
        }
        // Compute the quant offset from move lines quantity changes that were not saved yet.
        // Hence, did not yet affect quant's quantity in DB.
        await this.updateDirtyQuantsData();
        context = {
            ...context,
            single_product: true,
            list_view_ref: "stock.view_stock_quant_tree_simple",
        };
        const productName = this.props.record.data.product_id?.display_name;
        const title = _t("Add line: %s", productName);
        let domain = [
            ["product_id", "=", m2oId(this.props.record.data.product_id)],
            ["location_id", "child_of", this.props.context.default_location_id],
            ["quantity", ">", 0.0],
        ];
        const ownerId = m2oId(this.props.record.data.partner_id);
        if (ownerId) {
            domain.push(["owner_id", "=", ownerId]);
        }
        if (this.quantListViewShowOnHandOnly) {
            domain.push(["on_hand", "=", true]);
        }
        if (this.dirtyQuantsData.size) {
            const notFullyUsed = [];
            const fullyUsed = [];
            for (const [quantId, quantData] of this.dirtyQuantsData.entries()) {
                if (quantData.available_quantity > 0) {
                    notFullyUsed.push(quantId);
                } else {
                    fullyUsed.push(quantId);
                }
            }
            if (fullyUsed.length) {
                domain = Domain.and([domain, [["id", "not in", fullyUsed]]]).toList();
            }
            if (notFullyUsed.length) {
                domain = Domain.or([domain, [["id", "in", notFullyUsed]]]).toList();
            }
        }
        return this.selectCreate({ domain, context, title });
    }
    });
} else {
    console.error("SMLX2ManyField is undefined. Ensure the base module is loaded.");
}
