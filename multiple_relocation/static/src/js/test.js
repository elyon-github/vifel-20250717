/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
// Retrieve the SMLX2ManyField class from the registry
const SMLX2ManyField = registry.category("fields").get("sml_x2_many")?.component;

if (SMLX2ManyField) {
    patch(SMLX2ManyField.prototype, {
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
            tree_view_ref: "stock.view_stock_quant_tree_simple",
            search_default_on_hand: true,
            search_default_in_stock: true,
        };
        console.log('haha')
        console.log(this.props.record.data.partner_id[0])
        
        const productName = this.props.record.data.product_id[1];
        const title = _t("Add line: %s", productName);
        let domain = [
            ["product_id", "=", this.props.record.data.product_id[0]],
            ["location_id", "child_of", this.props.context.default_location_id],
            ["owner_id", "=", this.props.record.data.partner_id[0]],
        ];
        if (this.props.domain) {
            domain = [...domain, ...this.props.domain()];
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
