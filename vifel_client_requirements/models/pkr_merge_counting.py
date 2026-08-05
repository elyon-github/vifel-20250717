# -*- coding: utf-8 -*-
"""PKR counting: a merged line originates no pallet.

The billing invariant (BUSINESS_CONTEXT_AND_LEARNINGS.md §4): a merged line
contributes **+0 pallets** but its full Weight / Quantity / Packs. It joined a
pallet already standing on the floor, whose arrival an earlier receipt already
counted.

This fills the two extension hooks ``pallet_kilos_record_model`` exposes. The
counting itself lives inside ``_populate_operations_data`` (~150 lines) and
``action_resync_pallet_counts`` (~990 lines); re-implementing either here to
change three lines would guarantee drift from core, so core asks and this
module answers.
"""
from odoo import models


class PkrMergeCounting(models.Model):
    _inherit = 'pallet_kilos_record_model.pallet_kilos_record_model'

    def _vifel_line_originates_pallet(self, move_line):
        """A merged line joined an existing pallet — it brings none in.

        NOTE the asymmetry with the amounts: kilos, quantity and packs are
        summed unconditionally by the caller. Only the pallet count is spared,
        and only for a line that genuinely landed on stock already held.
        """
        if getattr(move_line, 'is_pallet_merge', False):
            return False
        return super()._vifel_line_originates_pallet(move_line)

    def _vifel_merge_free_domain(self):
        """Exclude merged lines wherever received-counts are rebuilt.

        Verified to be a NO-OP on unflagged data (suite C): the clause matches
        exactly the same rows as no clause at all until something is actually
        flagged, which is what makes it safe to apply to a live ledger.
        """
        MoveLine = self.env['stock.move.line']
        if 'is_pallet_merge' not in MoveLine._fields:
            return super()._vifel_merge_free_domain()
        return super()._vifel_merge_free_domain() + [
            ('is_pallet_merge', '!=', True)]


class StockPickingMergeCounting(models.Model):
    """The SAME +0-merge rule for the printed RR/WR pallet count and the
    on-picking Transacted Pallet Count.

    Core's report counters (``get_pallet_count_for_page`` /
    ``preprocess_stock_move_data``) and ``_compute_transacted_pallet_count`` ask
    ``stock.picking._vifel_line_originates_pallet(line)`` per line. Without this
    override the printout counted a merged pallet as received (+1), disagreeing
    with the PKR ledger (e.g. M/RR/05298 printed 4 vs ledger 3). Here a merged
    line answers False, so the printout and Transacted count match the ledger.
    """
    _inherit = 'stock.picking'

    def _vifel_line_originates_pallet(self, line):
        if getattr(line, 'is_pallet_merge', False):
            return False
        return super()._vifel_line_originates_pallet(line)
