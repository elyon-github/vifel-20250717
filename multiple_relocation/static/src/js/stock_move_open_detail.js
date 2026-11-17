/** @odoo-module **/
/*
 * RR / WR Operations tab: the list icon at the end of each line that opens
 * the line's "Move Detail" form (Number of Lines, Generate Lines, pallet
 * lines) - as on Odoo 17.
 *
 * Odoo 17's stock_move_one2many widget added this icon itself and let the
 * editable move list open its form subview. Odoo 19 dropped both (it shows a
 * "Details" button that opens the standard Detailed Operations popup, not
 * VIFEL's Move Detail form), so the line could no longer be opened.
 */
import { patch } from "@web/core/utils/patch";
import {
    MovesListRenderer,
    StockMoveX2ManyField,
} from "@stock/views/picking_form/stock_move_one2many";

patch(StockMoveX2ManyField.prototype, {
    setup() {
        super.setup(...arguments);
        // the list stays editable inline; this only lets the icon open the form
        this.canOpenRecord = true;
    },
});

patch(MovesListRenderer, {
    recordRowTemplate: "multiple_relocation.MovesListRenderer.RecordRow",
});

patch(MovesListRenderer.prototype, {
    processAllColumn(allColumns, list) {
        const cols = super.processAllColumn(...arguments);
        if (list.resModel === "stock.move") {
            cols.push({
                type: "vifel_open_move",
                id: `column_vifel_open_move_${cols.length}`,
                column_invisible: 'parent.state == "draft"',
            });
        }
        return cols;
    },
});
