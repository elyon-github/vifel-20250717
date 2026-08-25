/** @odoo-module */
/**
 * Sort toggle for the Clients kanban, in the control panel next to "New".
 *
 * Two orderings, because encoders need both and for different reasons:
 *   A → Z            — how a client is found when a document names one
 *   Most Pending     — where the outstanding work actually is
 *
 * NOT "most transactions": that ranks by lifetime history, and in this data
 * MOMMY LOIDA (123 pending, 299 lifetime) would fall below FOODASIA
 * (4 pending, 466 lifetime) — the busiest client pushed off the first screen.
 *
 * The ranking itself is done server-side by res.partner._search, which
 * recognises the pending field in the order string. The button only asks for
 * that order and reloads.
 */
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";

const ORDER_NAME = "complete_name asc";
const ORDER_PENDING = "vifel_pending_transfer_count desc, complete_name asc";

// The view opens on Most Pending (default_order on the kanban in
// client_menu_views.xml). This has to agree with it: the button shows the sort
// that is ACTUALLY applied, so starting it on "name" would label a
// pending-sorted screen "A - Z" and the first click would appear to do nothing.
const DEFAULT_MODE = "pending";

export class VifelClientKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.vifelSort = useState({ mode: DEFAULT_MODE });
    }

    get vifelSortLabel() {
        return this.vifelSort.mode === "pending" ? "Most Pending" : "A → Z";
    }

    async onVifelSortToggle() {
        const mode = this.vifelSort.mode === "pending" ? "name" : "pending";
        const order = mode === "pending" ? ORDER_PENDING : ORDER_NAME;
        // load({orderBy}) is the supported path (dynamic_list.js): orderBy
        // itself is a read-only getter over config, so assigning to it throws
        // "proxy set handler returned false". load() also goes through the
        // model mutex, so a double-click cannot race two reloads.
        const orderBy = order.split(",").map((part) => {
            const [name, dir] = part.trim().split(/\s+/);
            return { name, asc: (dir || "asc").toLowerCase() === "asc" };
        });
        await this.model.root.load({ orderBy });
        this.vifelSort.mode = mode;   // only after the reload actually works
        this.render(true);
    }
}

VifelClientKanbanController.template = "vifel_encoder_ux.VifelClientKanbanView";

export const vifelClientKanbanView = {
    ...kanbanView,
    Controller: VifelClientKanbanController,
};

registry.category("views").add("vifel_client_kanban", vifelClientKanbanView);
