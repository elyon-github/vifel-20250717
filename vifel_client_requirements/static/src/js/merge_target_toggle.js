/** @odoo-module */
/**
 * Single-select "Merge Here" toggle for the Pallet Merge wizard candidate list.
 *
 * The Python @api.onchange that clears the OTHER candidate rows is unreliable in
 * an editable list when a different row is the active/dirty one - the sibling
 * clear does not always reach the UI, so switching the target to an EARLIER row
 * appeared blocked unless the active row below was turned off first.
 *
 * This widget makes it a true radio, client-side: turning one row on turns every
 * OTHER candidate row off first, in a single click, whichever row is active. The
 * Python onchange is kept as the eligibility guard (the "not available" warning
 * for an ineligible row).
 */
import { BooleanToggleField, booleanToggleField } from "@web/views/fields/boolean_toggle/boolean_toggle_field";
import { registry } from "@web/core/registry";

export class MergeTargetToggleField extends BooleanToggleField {
    async onChange(newValue) {
        if (newValue) {
            const root = this.props.record.model.root;
            const list = root && root.data && root.data.candidate_line_ids;
            if (list && list.records) {
                for (const other of list.records) {
                    if (other.id !== this.props.record.id && other.data.is_target) {
                        await other.update({ is_target: false });
                    }
                }
            }
        }
        return super.onChange(newValue);
    }
}

export const mergeTargetToggleField = {
    ...booleanToggleField,
    component: MergeTargetToggleField,
};

registry.category("fields").add("merge_target_toggle", mergeTargetToggleField);
