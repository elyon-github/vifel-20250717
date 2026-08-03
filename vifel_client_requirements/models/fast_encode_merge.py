# -*- coding: utf-8 -*-
"""Merge initiation from inside the Magic Wizard (Client-Specific Req. Enh.).

FastEncodeRR (the Magic Wizard) already CONSUMES merges made in the Pallet
Breakdown — it loads them flagged, relaxes its guards for them, locks their
pallet/PSI, and preserves them through its deferred-write action_confirm
(verified end-to-end). This adds the ability to START a merge from inside it.

The Magic Wizard is deferred-write, so the safe design is: apply the merge to
the REAL move line immediately (reusing the Pallet Breakdown wizard's verified
_apply_merge), then sync the transient row and reopen the list. That way the
merge rides the SAME consumer path already proven for the Pallet-Breakdown-
then-Magic-Wizard round-trip — no second, divergent apply path at confirm.

All of this lives in the new module: core's FastEncodeRR stays a pure
consumer, unaware of the merge wizard. Only create-special is withheld here
(it stays a Pallet Breakdown action) — the Magic Wizard offers merge-onto-
stocked only, which is the encoder's actual need.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FastEncodeLineMerge(models.TransientModel):
    _inherit = 'stock.move.line.fast_encode_rr.line'

    show_merge_button = fields.Boolean(compute='_compute_show_merge_button')

    @api.depends('stock_move_line')
    def _compute_show_merge_button(self):
        MoveLine = self.env['stock.move.line']
        for tline in self:
            ml = MoveLine.browse(tline.stock_move_line) \
                if tline.stock_move_line else MoveLine
            tline.show_merge_button = bool(
                ml.exists() and ml.vifel_show_merge_button)

    def _real_line(self):
        self.ensure_one()
        ml = self.env['stock.move.line'].browse(self.stock_move_line)
        if not ml.exists():
            raise UserError(_(
                'This line is no longer available to merge — reopen the '
                'Magic Wizard.'))
        return ml

    def action_merge_from_fast_encode(self):
        """Open the merge wizard for this row's real line, tagged so confirm
        syncs this transient row and reloads."""
        self.ensure_one()
        if self.vifel_pending_unmerge:
            # The row shows "Merge" only because an un-merge is STAGED but not
            # yet committed — the real line was never touched. Treat the click
            # as "cancel that staged un-merge" rather than opening a merge onto
            # a line that is, in truth, still merged.
            self.write({'vifel_pending_unmerge': False})
            return self._reopen_fast_encode_list()
        return self._vifel_open_merge_from_fast_encode(
            self, _('Merge Pallet — %s') % (
                self._real_line().product_id.display_name or ''))

    def action_merge_selected_from_fast_encode(self):
        """Selection-bar 'Merge Selected' inside the Magic Wizard."""
        rows = self or self.browse(self.env.context.get('active_ids', []))
        mergeable = rows.filtered(
            lambda r: r.show_merge_button and not r.is_pallet_merge)
        if not mergeable:
            raise UserError(_(
                'None of the selected rows can be merged — they must be '
                'unmerged lines of a merge-enabled client.'))
        return self._vifel_open_merge_from_fast_encode(
            mergeable, _('Merge %d Selected Lines') % len(mergeable))

    def _vifel_open_merge_from_fast_encode(self, rows, name):
        real = self.env['stock.move.line']
        for row in rows:
            ml = self.env['stock.move.line'].browse(row.stock_move_line)
            if ml.exists():
                real |= ml
        if not real:
            raise UserError(_(
                'These lines are no longer available — reopen the Magic '
                'Wizard.'))
        wizard = self.env['pallet.merge.wizard'].create({
            'move_line_id': real[:1].id,
            'move_line_ids': [(6, 0, real.ids)],
            'from_fast_encode': True,
            'fast_encode_line_id': rows[:1].id,
            'fast_encode_line_ids': [(6, 0, rows.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'pallet.merge.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'fast_encode_line_id': rows[:1].id,
                        'default_from_fast_encode': True},
        }

    def action_unmerge_from_fast_encode(self):
        """STAGE an un-merge: flip the row to un-merged now, but leave the real
        move line untouched until the wizard's Confirm applies it.

        Guards on the same "on a merged/shared pallet" marker the Pallet
        Breakdown uses, so a +0 merge AND a same-receipt share (host or joiner)
        can both be peeled off from the Magic Wizard. The real detach — with its
        original-Pallet-Series restore — runs in FastEncodeRR.action_confirm via
        _vifel_apply_staged_unmerge, so nothing in the Pallet Breakdown moves
        before the encoder commits (matching how Merge defers its write-back)."""
        if self.vifel_pending_merge:
            # The row shows Merged only because a merge is STAGED but not yet
            # committed — the real line was never touched. Treat Un-merge as
            # "cancel that staged merge": clear the markers and restore the row's
            # own identity from the real line. The drawn create-special series (if
            # any) is left as a harmless gap — same accepted trade-off.
            self._vifel_cancel_staged_merge()
            return self._reopen_fast_encode_list()
        ml = self._real_line()
        if not ml.vifel_on_merged_pallet:
            raise UserError(_('This line is not a merged pallet.'))
        # Mark only the transient row. Its pallet / series are LEFT in place, so
        # the wizard's confirm passes treat it exactly like a still-merged row
        # (merge-locked → a no-op through the series-recycle passes); the compute
        # keys off vifel_pending_unmerge to show it un-merged, and the confirm's
        # staged-unmerge hook applies the real detach.
        self.write({'vifel_pending_unmerge': True})
        return self._reopen_fast_encode_list()

    def _vifel_cancel_staged_merge(self):
        """Undo a staged (not-yet-committed) merge on this row: clear the pending
        markers and restore the row's display from the untouched real line."""
        self.ensure_one()
        ml = self._real_line()
        series = ml.x_studio_pallet_series_id or ''
        self.write({'result_package_id': ml.result_package_id.id})
        self.write({
            'pallet_series_id': series,
            'pre_wizard_pallet_series_id': series,
            'location_dest_id': ml.location_dest_id.id,
            'is_pallet_merge': ml.is_pallet_merge,
            'vifel_premerge_captured': ml.vifel_premerge_captured,
            'vifel_pending_merge': False,
            'vifel_pending_merge_kind': False,
            'vifel_pending_merge_psi_type_id': False,
            # keep the line's existing series if it has one (do NOT let Confirm
            # draw a fresh number); only a truly series-less line needs a new one.
            'needs_new_pallet_series': not bool(series),
        })

    def _vifel_sync_from_move_line(self, move_line, reset_original=False):
        """Copy the real line's pallet identity onto this transient row.

        Written in TWO steps on purpose. This model's own write override
        (FastEncodeRR.py) intercepts any write containing result_package_id
        and RE-DERIVES the series from pallet-group logic — winner election,
        sibling sync, restore-original. That is right for a user retyping a
        Pallet #, but wrong for a merge: it would discard the adopted series
        and put the line's original one back.

        So: write the package first and let the override resolve whatever it
        wants, then write the merge identity in a second write with NO
        result_package_id key, which the override passes straight through.
        The real move line is the source of truth; the transient row just
        mirrors it.
        """
        self.ensure_one()
        series = move_line.x_studio_pallet_series_id or ''
        self.write({'result_package_id': move_line.result_package_id.id})
        vals = {
            'is_pallet_merge': move_line.is_pallet_merge,
            'vifel_premerge_captured': move_line.vifel_premerge_captured,
            # the row now mirrors a freshly (un)merged real line — any earlier
            # staged un-merge on it is stale
            'vifel_pending_unmerge': False,
            'pallet_series_id': series,
            'location_dest_id': move_line.location_dest_id.id,
            'pre_wizard_pallet_series_id': series,
        }
        if reset_original:
            # Starting a new special pallet DRAWS a series and hands the one
            # the line arrived with back to the pool. Leaving the old value in
            # original_pallet_series_id would let the wizard's restore path
            # put a number back that another line may already have taken.
            vals['original_pallet_series_id'] = series
        self.write(vals)

    def _vifel_stage_merge(self, decision):
        """Record a resolved merge decision on THIS transient row for display,
        WITHOUT touching the real move line — the merge is applied at the Magic
        Wizard's Confirm (_vifel_apply_staged_merge).

        Same TWO-STEP write as _vifel_sync_from_move_line: write the package
        first (the row's own override re-derives series/location — discarded),
        then the merge identity in a second write with NO result_package_id so
        the override passes it straight through.

        decision = {'kind', 'target', 'adopted', 'location', 'psi_type'}.
        Markers mirror the real apply: only a +0 'merge' flags is_pallet_merge;
        every kind captures so the row shows Merged + Un-merge and can revert.
        For 'first_stock' the merge sets no location (empty), so the row KEEPS
        its current one."""
        self.ensure_one()
        kind = decision['kind']
        adopted = decision['adopted'] or ''
        location = decision['location']
        psi_type = decision.get('psi_type')
        keep_location = self.location_dest_id
        self.write({'result_package_id': decision['target'].id})
        self.write({
            'pallet_series_id': adopted,
            'pre_wizard_pallet_series_id': adopted,
            'location_dest_id': location.id if location else keep_location.id,
            'is_pallet_merge': (kind == 'merge'),
            'vifel_premerge_captured': (kind != 'merge'),
            'vifel_pending_unmerge': False,
            'vifel_pending_merge': True,
            'vifel_pending_merge_kind': kind,
            'vifel_pending_merge_psi_type_id': psi_type.id if psi_type else False,
            # step 1 (a fresh target pallet) may have flagged needs_new — clear
            # it so Confirm's "resolve NEW series" pass does not overwrite the
            # staged series before _vifel_apply_staged_merge runs.
            'needs_new_pallet_series': False,
        })

    def _reopen_fast_encode_list(self):
        """Rebuild the Magic Wizard list action for this row's wizard, so the
        dialog refreshes with the merge/un-merge applied."""
        self.ensure_one()
        view_id = self.env.ref(
            'multiple_relocation.view_fast_encode_rr_line_list').id
        picking = self.env['stock.picking'].browse(self.wizard_id.transfer_id)
        return {
            'name': _('Fast Encode RR Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line.fast_encode_rr.line',
            'view_mode': 'list',
            'views': [(view_id, 'list')],
            'target': 'new',
            'domain': [('wizard_id', '=', self.wizard_id.id)],
            'context': {
                'default_wizard_id': self.wizard_id.id,
                'default_transfer_id': self.wizard_id.transfer_id,
                'is_blast_freeze': picking.x_studio_is_a_blast_freezer,
                'show_client_lot_no': getattr(
                    picking, 'show_client_lot_no', False),
                'show_batch_no': getattr(
                    picking, 'show_batch_no', False),
                # gates the header "Merge Selected" button for a non-merge client
                'vifel_can_merge': bool(
                    picking.partner_id.vifel_can_merge_pallets),
            },
        }


class FastEncodeLineMergeFields(models.TransientModel):
    """The merge-related columns of a Magic Wizard row.

    These lived in ``multiple_relocation`` until 2026-07-23. They are ordinary
    ``_inherit`` additions, so they belong with the feature.
    """
    _inherit = 'stock.move.line.fast_encode_rr.line'

    client_lot_no = fields.Char(string='Lot No.')
    batch_no = fields.Char(string='Batch #')
    is_pallet_merge = fields.Boolean(string='Merged Pallet', readonly=True)

    # Mirrors stock.move.line.vifel_premerge_captured — a same-receipt JOINER
    # carries it (the +0 host does not). Seeded from the real line at create so
    # the Magic Wizard tells a genuine merge from ordinary multi-line encoding
    # exactly as the Pallet Breakdown does.
    vifel_premerge_captured = fields.Boolean(
        string='Pre-merge State Recorded', readonly=True)

    # Set when the encoder presses Un-merge INSIDE the Magic Wizard. The row
    # shows as un-merged at once, but the real move line is left untouched — the
    # detach is applied only on the wizard's Confirm (see
    # _vifel_apply_staged_unmerge), so nothing in the Pallet Breakdown moves
    # before the encoder commits.
    vifel_pending_unmerge = fields.Boolean(
        string='Pending Un-merge', default=False)

    # Set when the encoder confirms a Merge INSIDE the Magic Wizard. The row
    # shows the merged pallet/series at once, but the real move line is left
    # untouched — the merge is applied only on the wizard's Confirm (see
    # _vifel_apply_staged_merge), so nothing in the Pallet Breakdown moves before
    # the encoder commits, mirroring the staged un-merge. The row's own
    # result_package_id / pallet_series_id / location_dest_id already carry the
    # decision's target / series / location; these three record HOW to re-apply.
    vifel_pending_merge = fields.Boolean(
        string='Pending Merge', default=False)
    vifel_pending_merge_kind = fields.Selection(
        [('merge', 'Merge onto stocked (+0)'),
         ('same_receipt', 'Join a same-receipt pallet'),
         ('first_stock', 'First stock on the pinned pallet'),
         ('create_special', 'Start a new special pallet')],
        string='Pending Merge Kind')
    vifel_pending_merge_psi_type_id = fields.Many2one(
        'vifel.psi.type', string='Pending Merge PSI Type')

    # Same user-facing marker as on stock.move.line: checked whenever a row is
    # part of a merged pallet, INCLUDING the HOST of a same-receipt merge (its
    # own is_pallet_merge / vifel_premerge_captured stay false, but a joiner
    # sibling carries the marker). Drives the row tint so the floor sees every
    # consolidated pallet, not only the +0 ones.
    vifel_on_merged_pallet = fields.Boolean(
        compute='_compute_vifel_on_merged_pallet')

    @api.depends('result_package_id', 'is_pallet_merge',
                 'vifel_premerge_captured', 'vifel_pending_unmerge',
                 'wizard_id.line_ids.result_package_id',
                 'wizard_id.line_ids.is_pallet_merge',
                 'wizard_id.line_ids.vifel_premerge_captured')
    def _compute_vifel_on_merged_pallet(self):
        for line in self:
            # A staged un-merge shows the row as un-merged immediately, even
            # though the real line is only detached on Confirm.
            if line.vifel_pending_unmerge:
                line.vifel_on_merged_pallet = False
                continue
            # OWN marker: a +0 merge OR an explicit merge-button placement
            # (captured — same-receipt join or first-stock birth). Shows Merged +
            # Un-merge so it can be reverted, even as the sole row on the pallet.
            if line.is_pallet_merge or line.vifel_premerge_captured:
                line.vifel_on_merged_pallet = True
                continue
            # HOST symmetry: an unmarked row that shares its pallet with a marked
            # sibling. Sharing with an UNMARKED row is NOT a merge (ordinary
            # multi-line encoding).
            pkg = line.result_package_id
            if not pkg:
                line.vifel_on_merged_pallet = False
                continue
            line.vifel_on_merged_pallet = any(
                (sib.is_pallet_merge or sib.vifel_premerge_captured)
                for sib in (line.wizard_id.line_ids - line)
                if sib.result_package_id == pkg)

    # Pallets another line of this transfer has MERGED onto. They must not be
    # offered in the RR Pallet # dropdown: a merge target is reached through
    # the Merge button, which sets the flag, the series and the location
    # together. Typing the same pallet here instead would put a second,
    # unflagged line on it — counting it as a received pallet and leaving the
    # two lines free to disagree about the series.
    vifel_merge_locked_package_ids = fields.Many2many(
        'stock.quant.package', string='Merge-locked Pallets',
        compute='_compute_vifel_merge_locked_package_ids')

    @api.depends('transfer_id')
    def _compute_vifel_merge_locked_package_ids(self):
        MoveLine = self.env['stock.move.line']
        # Pallets pinned as some client's Fixed Merge Pallet are dedicated and
        # never offered as a free empty pallet — not even to their own client,
        # and not even while empty. They are reached only via Merge.
        pinned = self.env['res.partner']._vifel_fixed_merge_packages()
        for record in self:
            packages = pinned
            if record.transfer_id:
                packages |= MoveLine.search([
                    ('picking_id', '=', record.transfer_id),
                    ('is_pallet_merge', '=', True),
                ]).mapped('result_package_id')
            record.vifel_merge_locked_package_ids = packages

    @api.model_create_multi
    def create(self, vals_list):
        """Seed the merge columns from the real move line.

        Core builds these rows inside ``action_open_fast_encode_wizard`` (86
        lines). Rather than duplicate that method to add two keys, the values
        are backfilled here from the ``stock_move_line`` the row already
        points at — same result, no duplication.
        """
        MoveLine = self.env['stock.move.line']
        for vals in vals_list:
            move_line = MoveLine.browse(vals.get('stock_move_line') or 0)
            if not move_line.exists():
                continue
            vals.setdefault('client_lot_no', move_line.client_lot_no or '')
            vals.setdefault('batch_no', move_line.batch_no or '')
            vals.setdefault('is_pallet_merge', move_line.is_pallet_merge)
            vals.setdefault('vifel_premerge_captured',
                            move_line.vifel_premerge_captured)
        return super().create(vals_list)


class FastEncodeWizardMergeHooks(models.TransientModel):
    """Answers the three extension hooks core's Magic Wizard exposes."""
    _inherit = 'stock.move.line.fast_encode_rr'

    def _vifel_line_is_merge_locked(self, line):
        """A merged row keeps its adopted pallet, series and location: it is
        skipped by pallet-availability validation (it points at an occupied
        pallet on purpose) and never competes in the winner grouping.

        A row with a STAGED un-merge is kept out of the same passes: its real
        detach happens in the staged-unmerge pass, so the recycle machinery must
        treat it as a no-op (and, for a joiner leaving a shared pallet, exclude
        it from the remaining siblings' winner election).

        A STAGED merge (vifel_pending_merge) is locked too: its real apply runs in
        the staged-merge pass, so it must stay out of the winner-grouping /
        series-recycle passes — otherwise a staged birth / same-receipt /
        create-special row (whose own is_pallet_merge is False) could perturb
        another pallet's series election before its merge is applied."""
        if (line.is_pallet_merge or line.vifel_pending_unmerge
                or line.vifel_pending_merge):
            return True
        return super()._vifel_line_is_merge_locked(line)

    def _vifel_apply_staged_unmerge(self, line, move_line):
        """A row the encoder un-merged inside the Magic Wizard: apply the real
        detach NOW, at Confirm (it was deferred so the Pallet Breakdown did not
        change mid-session). action_unmerge_pallet_line runs the full restore —
        including putting the original Pallet Series back when it is still free —
        and we skip the standard write for this row (return True)."""
        if not line.vifel_pending_unmerge:
            return super()._vifel_apply_staged_unmerge(line, move_line)
        if move_line.exists() and move_line.vifel_on_merged_pallet:
            move_line.action_unmerge_pallet_line()
        return True

    def _vifel_apply_staged_merge(self, line, move_line):
        """A row the encoder merged inside the Magic Wizard: apply the REAL merge
        NOW, at Confirm (it was deferred so the Pallet Breakdown did not change
        mid-session). Re-runs the SAME low-level apply the Pallet Breakdown uses,
        dispatched on the staged kind, then writes the row's cargo. Returns True
        so the standard write is skipped for this row."""
        if not line.vifel_pending_merge:
            return super()._vifel_apply_staged_merge(line, move_line)
        if not (move_line.exists() and line.result_package_id):
            return True
        Wizard = self.env['pallet.merge.wizard']
        wiz = Wizard.with_context(vifel_skip_candidates=True).create({
            'move_line_id': move_line.id,
            'move_line_ids': [(6, 0, [move_line.id])],
        })
        target = line.result_package_id
        adopted = line.pallet_series_id or ''
        location = line.location_dest_id
        kind = line.vifel_pending_merge_kind
        if kind == 'create_special':
            wiz.psi_type_id = line.vifel_pending_merge_psi_type_id
            wiz.new_package_id = target
            wiz.new_location_id = location
            wiz._apply_create_special(preassigned_series=adopted)
        elif kind == 'same_receipt':
            wiz._apply_same_receipt_one(move_line, target, adopted, location)
        else:
            # 'merge' / 'first_stock' both land on a stocked-or-pinned pallet.
            # Re-run the FULL _apply_merge with the target forced, so it
            # re-resolves +0-vs-first-stock (with the pinned-pallet lock) exactly
            # as the Pallet Breakdown does — robust to a concurrent birth between
            # stage and Confirm. Its returned notification action is ignored here.
            wiz.manual_package_id = target
            wiz._apply_merge()
        # cargo (weight / qty / container / dates / lot / batch) onto the real
        # line — the merge apply only set pallet / series / location / flags.
        move_line.with_context(skip_pallet_series_sync=True).write({
            'bf_pallet_char': line.bf_pallet_char,
            'x_studio_2nd_uom': line.quantity,
            'x_studio_total_units': line.min_uom_unit,
            'quantity': line.kilogram,
            'x_studio_container_number': line.container_number or '',
            'client_lot_no': line.client_lot_no or False,
            'batch_no': line.batch_no or False,
            'x_studio_production_date': line.production_date,
            'x_studio_expiration_date': line.expiration_date,
            'x_studio_quantity_uom':
                line.quantity_uom.id if line.quantity_uom else False,
            'x_studio_min_quantity_uom':
                line.packs_uom.id if line.packs_uom else False,
        })
        return True

    def _vifel_apply_merge_locked_line(self, line, move_line):
        """Cargo-only write for a merged row.

        Its pallet / series / location belong to the stock already standing
        there, and the stocked target must never be stamped as reserved.
        """
        if not line.is_pallet_merge:
            return super()._vifel_apply_merge_locked_line(line, move_line)
        move_line.with_context(skip_pallet_series_sync=True).write({
            'bf_pallet_char': line.bf_pallet_char,
            'x_studio_2nd_uom': line.quantity,
            'x_studio_total_units': line.min_uom_unit,
            'quantity': line.kilogram,
            'x_studio_container_number': line.container_number or '',
            'client_lot_no': line.client_lot_no or False,
            'batch_no': line.batch_no or False,
            'x_studio_production_date': line.production_date,
            'x_studio_expiration_date': line.expiration_date,
            'x_studio_quantity_uom':
                line.quantity_uom.id if line.quantity_uom else False,
            'x_studio_min_quantity_uom':
                line.packs_uom.id if line.packs_uom else False,
        })
        return True

    def _vifel_line_write_vals(self, line):
        """Carry the client Lot No. and Batch # through on the normal path —
        this is the Confirm write-back onto the real move line."""
        vals = super()._vifel_line_write_vals(line)
        vals['client_lot_no'] = line.client_lot_no or False
        vals['batch_no'] = line.batch_no or False
        return vals


class StockMoveLineFastEncodeContext(models.Model):
    _inherit = 'stock.move.line'

    def action_open_fast_encode_wizard(self):
        """Tell the Magic Wizard which client columns to show — Lot No. and
        Batch #."""
        res = super().action_open_fast_encode_wizard()
        if isinstance(res, dict) and isinstance(res.get('context'), dict) \
                and self:
            picking = self[0].picking_id
            res['context'] = dict(
                res['context'],
                show_client_lot_no=bool(picking.show_client_lot_no),
                show_batch_no=bool(picking.show_batch_no),
                vifel_can_merge=bool(picking.partner_id.vifel_can_merge_pallets))
        return res
