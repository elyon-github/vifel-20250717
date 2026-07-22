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
        """Open the merge wizard for this row's real line, in merge-only
        mode, tagged so confirm syncs this transient row and reloads."""
        ml = self._real_line()
        wizard = self.env['pallet.merge.wizard'].create({
            'move_line_id': ml.id,
            'from_fast_encode': True,
            'fast_encode_line_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Merge Pallet — %s') % (ml.product_id.display_name or ''),
            'res_model': 'pallet.merge.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'fast_encode_line_id': self.id,
                        'default_from_fast_encode': True},
        }

    def action_unmerge_from_fast_encode(self):
        """Un-merge this row's real line, sync the transient, reopen."""
        ml = self._real_line()
        if not ml.is_pallet_merge:
            raise UserError(_('This line is not a merged pallet.'))
        ml.action_unmerge_pallet_line()
        self._vifel_sync_from_move_line(ml)
        return self._reopen_fast_encode_list()

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
            },
        }
