/** @odoo-module **/
/*
 * VIFEL (19): give selection fields their empty first line back.
 *
 * On Odoo 17 every selection dropdown that is not required started with an
 * empty line, which users pick to leave a field (e.g. Record Remarks) blank.
 * Odoo 19's searchable dropdown (SelectMenu) has no such line. This adds it
 * again for plain selection fields that are not required. Picking it stores
 * False, the same as the empty line on 17.
 */
import { patch } from "@web/core/utils/patch";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { SelectionField } from "@web/views/fields/selection/selection_field";

// A non-breaking space: the line keeps its height and does not print "false".
const BLANK_LABEL = " ";

patch(SelectionField.prototype, {
    get choices() {
        const choices = super.choices;
        if (this.type === "selection" && !this.props.required && !this.props.readonly) {
            return [{ value: false, label: BLANK_LABEL }, ...choices];
        }
        return choices;
    },
});

// With the blank line picked, the field itself stays empty (not a space).
patch(SelectMenu.prototype, {
    get displayValue() {
        const value = super.displayValue;
        return value === BLANK_LABEL ? "" : value;
    },
    // An empty field "matches" the blank line, so Odoo would think there is
    // something to clear. Clicking an option first blurs the (empty) input,
    // which then cleared the field and closed the list before the click
    // landed - the option was never set (e.g. Truck Type on a new RR/WR).
    // Nothing to clear when the field is already empty.
    get canDeselect() {
        if (!this.props.multiSelect && this.selectedChoice?.value === false) {
            return false;
        }
        return super.canDeselect;
    },
});
