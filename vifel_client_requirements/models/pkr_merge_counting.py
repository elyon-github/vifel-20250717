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

    # ------------------------------------------------------------------
    # Decide the merge-pallet count at VALIDATION, not at claim time.
    #
    # The +1 (birth) / +0 (merge) flag is set PROVISIONALLY when the merge
    # wizard runs - by claim order (``_pinned_pallet_already_claimed``). But the
    # receipt that actually lands the FIRST stock on an empty pinned pallet is
    # only known at validation. If we trust the claim-time flag, a receipt that
    # was stripped and re-merged after a sibling validated first can leave BOTH
    # receipts flagged +0, so the physical pallet is counted zero times (the
    # birth-race loophole). So at the moment a receipt goes done we re-read the
    # floor: a merge line whose target pallet is still EMPTY births it (+1); one
    # whose pallet already holds stock (from an earlier done receipt, or a
    # sibling receipt validated earlier in the same call) is a +0. The count is
    # then immune to claim order and to re-merges.
    # ------------------------------------------------------------------
    def _vifel_merge_count_scope(self):
        """Incoming, merge-enabled receipts whose pallet count follows the merge
        flag. Mirrors the counting scope; excludes returns, void returns and
        blast-freeze."""
        self.ensure_one()
        return bool(
            self.picking_type_code == 'incoming'
            and not self.return_id
            and not self.is_void_return
            and not self.x_studio_is_a_blast_freezer
            and self.partner_id.vifel_can_merge_pallets)

    def _vifel_merge_count_lines(self):
        """Lines whose +1/+0 identity is re-derived at validation: any line on a
        real pallet that took part in merging - flagged (+0), captured (a merge
        or a birth placed with the button), or landing on a durable merge
        pallet. Plain multi-line-on-one-pallet encoding is left untouched."""
        self.ensure_one()
        return self.move_line_ids.filtered(
            lambda l: l.result_package_id and (
                l.is_pallet_merge or l.vifel_premerge_captured
                or l.result_package_id.vifel_is_merge_pallet))

    def _vifel_rederive_merge_flags(self):
        """Set ``is_pallet_merge`` from the floor: a merge line whose target
        pallet is EMPTY now births it (+1); one whose pallet already holds stock
        (from an earlier done receipt, or a sibling receipt earlier in this same
        call) is a +0. Call this the instant BEFORE the receipts go done - this
        receipt's own stock is not on the pallet yet, so an empty pallet means
        THIS receipt is the first to stock it. ``birthed`` is updated only after
        each picking's line loop, so lines of the SAME receipt co-birthing one
        pallet all stay +1 (the ledger dedupes them), while a LATER receipt in
        the same call sees the pallet as already birthed and reads +0."""
        birthed = set()
        for picking in self:
            if not picking._vifel_merge_count_scope():
                continue
            this_births = set()
            for line in picking._vifel_merge_count_lines():
                pkg = line.result_package_id
                desired = pkg.vifel_holds_stock() or (pkg.id in birthed)
                if line.is_pallet_merge != desired:
                    line.with_context(
                        vifel_pallet_merge=True,
                        skip_pallet_series_sync=True,
                    ).write({'is_pallet_merge': desired})
                if not desired:
                    this_births.add(pkg.id)
            birthed |= this_births

    def _action_done(self):
        """Decide the merge-pallet count at VALIDATION. Re-derive the +1/+0 flag
        BEFORE super() so the done-transition ledger (BA#6 ->
        _populate_operations_data, which fires as state flips to done inside
        super()) reads the corrected flag."""
        self._vifel_rederive_merge_flags()
        return super()._action_done()
