/** @odoo-module */
/**
 * Adds the "Generate Report" button to VIFEL stock.quant list views.
 *
 * The controller is attached to the shared quant list view, so the button
 * only renders when the action asks for it (context.show_pkr_report) —
 * standard Odoo quant screens (Physical Inventory, ...) stay untouched.
 *
 * When the list is already scoped to one client (the Contact smart
 * buttons pass vifel_client_id), the wizard opens with that client
 * pre-selected.
 */
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";

// Widest a single column may become when we stop Odoo squeezing them. Long
// product names would otherwise stretch the table to absurd widths.
const VIFEL_MAX_COL_WIDTH = 320;

export class VifelQuantListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    get showVifelReportButton() {
        return Boolean(this.props.context && this.props.context.show_pkr_report);
    }

    async onGenerateReportClick() {
        const ctx = this.props.context || {};
        const wizardContext = {};
        const clientId = ctx.vifel_client_id;
        if (clientId) {
            wizardContext.default_partner_ids = [[6, 0, [clientId]]];
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Generate Report",
            res_model: "pallet_kilos_record_model.report.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: wizardContext,
        });
    }
}

VifelQuantListController.template = "multiple_relocation.VifelQuantListView";

/**
 * Stop the Stock Inquiry columns being squeezed into unreadable stubs.
 *
 * Odoo fits a list to the viewport: computeColumnWidthsFromContent() shrinks
 * the widest columns until the table fits, flooring each at 92px, and never
 * scrolls horizontally. That is fine for a 6-column list, but the VIFEL quant
 * screens carry ~30 columns, so every header collapses to "Productio...",
 * "Expiratio..." or a single letter and the list becomes unreadable.
 *
 * Here the natural widths are kept (capped, so one long product name cannot
 * stretch the table without limit) and the table is allowed to overflow, which
 * gives a horizontal scrollbar instead — the trade the encoders want: every
 * column readable, scrolling is acceptable.
 *
 * Gated on the same context flag as the report button, so standard quant
 * screens (Physical Inventory, ...) keep Odoo's fit-to-width behaviour.
 */
export class VifelQuantListRenderer extends ListRenderer {
    get vifelWideColumns() {
        // props.list.context is the datapoint context (datapoint.js "get
        // context"); the searchModel is a fallback so a context that never
        // reaches the datapoint cannot turn this into a silent no-op.
        const listCtx = (this.props.list && this.props.list.context) || {};
        const searchCtx = (this.env.searchModel && this.env.searchModel.context) || {};
        return Boolean(listCtx.show_pkr_report || searchCtx.show_pkr_report);
    }

    freezeColumnWidths() {
        super.freezeColumnWidths();
        if (!this.vifelWideColumns || !this.tableRef || !this.tableRef.el) {
            return;
        }
        // The table is now wider than its container by design, so the
        // container has to scroll rather than clip. Set here rather than in
        // SCSS: no selector reaches this list alone, and a global rule would
        // change every other list in the database.
        const container = this.tableRef.el.parentNode;
        if (container) {
            container.style.overflowX = "auto";
        }
    }

    computeColumnWidthsFromContent() {
        const table = this.tableRef && this.tableRef.el;
        if (!this.vifelWideColumns || !table) {
            return super.computeColumnWidthsFromContent();
        }
        let widths;
        try {
            // Same guard Odoo uses: measure unwrapped so the width reflects
            // the real content rather than a mid-word break. try/finally so a
            // throw mid-measure cannot leave the helper class on the table.
            table.classList.add("o_list_computing_widths");
            try {
                widths = [...table.querySelectorAll("thead th")].map((th) =>
                    Math.min(th.getBoundingClientRect().width, VIFEL_MAX_COL_WIDTH)
                );
            } finally {
                table.classList.remove("o_list_computing_widths");
            }
            if (!widths.length) {
                return super.computeColumnWidthsFromContent();
            }
            // Only take over when the columns genuinely do not fit. If they
            // already do, Odoo's own sizing spreads them across the full
            // width — keeping ours would leave a gap down the right-hand side.
            const total = widths.reduce((sum, w) => sum + w, 0);
            const available = table.parentNode
                ? table.parentNode.getBoundingClientRect().width
                : 0;
            if (!available || total <= available) {
                return super.computeColumnWidthsFromContent();
            }
        } catch (_err) {
            // Never let a sizing tweak break the list: fall back to stock Odoo.
            return super.computeColumnWidthsFromContent();
        }
        return widths;
    }
}

export const vifelQuantListView = {
    ...listView,
    Controller: VifelQuantListController,
    Renderer: VifelQuantListRenderer,
};

registry.category("views").add("vifel_quant_report_list", vifelQuantListView);
