/** @odoo-module */
/**
 * Hide the "Print" dropdown (the reports bound to stock.move.line — "Final
 * Adjustment Form" and "Location Update Form") from the Pallet Breakdown ONLY.
 *
 * The Pallet Breakdown list is the sole user of multiple_relocation's
 * `magic_wizard_list_view` controller (js_class set on the detailed-operation
 * tree). Patching that controller's `actionMenuItems` getter to drop the
 * `print` group removes those reports from this list's action bar while leaving
 * them bound and available on every other stock.move.line view. Nothing in the
 * base module changes — this is an additive patch, in keeping with the module's
 * plug-and-play design.
 */
import { patch } from "@web/core/utils/patch";
import { MagicWizardListController } from "@multiple_relocation/js/magic_wizard_list_controller";

patch(MagicWizardListController.prototype, {
    get actionMenuItems() {
        const items = super.actionMenuItems;
        return { ...items, print: [] };
    },
});
