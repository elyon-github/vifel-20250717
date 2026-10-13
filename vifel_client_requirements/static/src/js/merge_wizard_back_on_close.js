/** @odoo-module */
/**
 * When the Pallet Merge wizard was opened FROM the Magic Wizard, closing it with
 * the dialog's X (or Escape) must land the user back in the Magic Wizard — not
 * drop them out entirely.
 *
 * Why this is needed: the Magic Wizard and the merge wizard are both
 * target='new' actions, and a second target='new' REPLACES the first. So
 * opening the merge wizard already tore the Magic Wizard down; the "Back to
 * Magic Wizard" and Confirm buttons rebuild it via a returned action, but the
 * dialog's X is a pure client-side close that runs no server code, so it left
 * the encoder with nothing. This controller intercepts that X/Escape and, when
 * from_fast_encode is set, calls the wizard's own action_back_to_fast_encode
 * (the same reopen the Back button uses) instead of a bare close.
 *
 * Mirrors multiple_relocation's FastEncodeRRListController, which already guards
 * the Magic Wizard's own X the same way. Additive js_class — no base change.
 */
import { FormController } from "@web/views/form/form_controller";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

export class MergeWizardFormController extends FormController {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
        this._reopening = false;
        this._boundCloseClick = this._onCloseButtonClick.bind(this);
        this._boundKeyDown = this._onKeyDown.bind(this);

        onMounted(() => {
            document.addEventListener("keydown", this._boundKeyDown, true);
            this._attachCloseBtnListener();
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._boundKeyDown, true);
            if (this._closeBtn) {
                this._closeBtn.removeEventListener("click", this._boundCloseClick, true);
            }
        });
    }

    get _fromFastEncode() {
        const root = this.model && this.model.root;
        return !!(root && root.data && root.data.from_fast_encode);
    }

    _attachCloseBtnListener() {
        const tryAttach = () => {
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
            setTimeout(tryAttach, 150);
        }
    }

    _onKeyDown(ev) {
        if (ev.key === "Escape" && this._fromFastEncode && !this._reopening) {
            ev.stopImmediatePropagation();
            ev.preventDefault();
            this._backToMagicWizard();
        }
    }

    _onCloseButtonClick(ev) {
        if (this._fromFastEncode && !this._reopening) {
            ev.stopImmediatePropagation();
            ev.preventDefault();
            this._backToMagicWizard();
        }
    }

    async _backToMagicWizard() {
        if (this._reopening) {
            return;
        }
        this._reopening = true;
        try {
            const resId = this.model.root.resId;
            const action = await this.orm.call(
                "pallet.merge.wizard", "action_back_to_fast_encode", [[resId]]);
            await this.action.doAction(action);
        } catch (e) {
            // never trap the user: fall back to a plain close on any error
            this.action.doAction({ type: "ir.actions.act_window_close" });
        }
    }
}

export const mergeWizardFormView = {
    ...formView,
    Controller: MergeWizardFormController,
};

registry.category("views").add("pallet_merge_wizard_form", mergeWizardFormView);
