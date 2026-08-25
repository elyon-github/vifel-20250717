/** @odoo-module */
/**
 * Inventory Overview, banded by Blast Freeze.
 *
 * Odoo's kanban groups exactly one level deep: kanban_controller.js sets
 * maxGroupByDepth to 1, dynamic_group_list.js reads groupBy[0], and the renderer
 * template iterates a group's RECORDS and never sub-groups. The Overview already
 * spends its one level on Warehouse - and does so through a saved favourite
 * (ir.filters "Overview", group_by warehouse_id) rather than through any view,
 * so that level cannot simply be reassigned either.
 *
 * So the second level is drawn rather than grouped: the records arrive already
 * sorted blast-freeze-first (default_order on the primary view), and this walks
 * them emitting a band heading wherever the flag changes. Two bands fall out of
 * the ordering; no extra query, no second read.
 *
 * Only views that opt in with js_class="vifel_overview_kanban" get this. Every
 * other kanban in the database, the Clients kanban included, is untouched.
 */
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { registry } from "@web/core/registry";

const BF_FIELD = "is_blast_freeze_operation";
const BAND_BLAST_FREEZE = "Blast Freeze";
const BAND_NORMAL = "Normal";

export class VifelOverviewKanbanRenderer extends KanbanRenderer {
    /**
     * Turn a flat record list into records interleaved with band headings.
     *
     * Returns entries of one of two shapes:
     *   { band: "Blast Freeze", key }   a heading to draw
     *   { record, key }                 a card to draw
     *
     * Degrades to the plain record list, with no headings at all, whenever
     * banding would be meaningless or wrong:
     *   - the field is missing from the datapoint (someone edited the arch and
     *     dropped the <field>), so the flag cannot be read;
     *   - every record falls in the same band, where a single heading over the
     *     whole set says nothing and only costs a row.
     * Either way the screen still renders as stock's does. It never throws: a
     * renderer that raises takes the whole view down with it.
     */
    vifelBandedItems(records) {
        const plain = (records || []).map((record) => ({ record, key: record.id }));
        try {
            if (!plain.length || !(BF_FIELD in (records[0].data || {}))) {
                return plain;
            }
            const isBf = (record) => Boolean(record.data[BF_FIELD]);
            const first = isBf(records[0]);
            if (records.every((record) => isBf(record) === first)) {
                return plain;
            }
            const items = [];
            let current = null;
            for (const record of records) {
                const band = isBf(record) ? BAND_BLAST_FREEZE : BAND_NORMAL;
                if (band !== current) {
                    items.push({ band, key: `vifel-band-${band}` });
                    current = band;
                }
                items.push({ record, key: record.id });
            }
            return items;
        } catch (_err) {
            return plain;
        }
    }
}

VifelOverviewKanbanRenderer.template = "vifel_encoder_ux.VifelOverviewKanbanRenderer";

export const vifelOverviewKanbanView = {
    ...kanbanView,
    Renderer: VifelOverviewKanbanRenderer,
};

registry.category("views").add("vifel_overview_kanban", vifelOverviewKanbanView);
