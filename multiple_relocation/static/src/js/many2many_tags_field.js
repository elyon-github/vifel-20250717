/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Many2ManyTagsFieldColorEditable } from "@web/views/fields/many2many_tags/many2many_tags_field";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";

patch(Many2ManyTagsFieldColorEditable.prototype, {
    setup() {
        super.setup();
        this.action = useService("action");
        this.dialog = useService("dialog");
    },
    
    onBadgeClick(ev, record) {
        ev.preventDefault();
        ev.stopPropagation();
        
        this.dialog.add(ConfirmationDialog, {
            body: _t("If you want to open form view click 'Open Form View'."),
            confirmClass: "btn-primary",
            confirmLabel: _t("Open Form View"),
            confirm: () => {
                this.action.doAction({
                    type: 'ir.actions.act_window',
                    res_model: this.relation,
                    res_id: record.resId,
                    views: [[false, 'form']],
                    target: 'current',
                });
            },
            cancelLabel: _t("Cancel"),
            cancel: () => {},
        });
    }
});