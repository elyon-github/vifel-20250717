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


class FastEncodeLineMergeFields(models.TransientModel):
    """The merge-related columns of a Magic Wizard row.

    These lived in ``multiple_relocation`` until 2026-07-23. They are ordinary
    ``_inherit`` additions, so they belong with the feature.
    """
    _inherit = 'stock.move.line.fast_encode_rr.line'

    client_lot_no = fields.Char(string='Lot No.')
    is_pallet_merge = fields.Boolean(string='Merged Pallet', readonly=True)

    # Same user-facing marker as on stock.move.line: checked whenever a row is
    # part of a merged pallet, INCLUDING two rows of this transfer that simply
    # share one pallet (is_pallet_merge alone stays false there). Drives the row
    # tint so the floor sees every consolidated pallet, not only the +0 ones.
    vifel_on_merged_pallet = fields.Boolean(
        compute='_compute_vifel_on_merged_pallet')

    @api.depends('result_package_id', 'is_pallet_merge',
                 'wizard_id.line_ids.result_package_id')
    def _compute_vifel_on_merged_pallet(self):
        for line in self:
            pkg = line.result_package_id
            shares = bool(pkg) and len(line.wizard_id.line_ids.filtered(
                lambda l: l.result_package_id == pkg)) > 1
            line.vifel_on_merged_pallet = bool(line.is_pallet_merge) or shares

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
            vals.setdefault('is_pallet_merge', move_line.is_pallet_merge)
        return super().create(vals_list)


class FastEncodeWizardMergeHooks(models.TransientModel):
    """Answers the three extension hooks core's Magic Wizard exposes."""
    _inherit = 'stock.move.line.fast_encode_rr'

    def _vifel_line_is_merge_locked(self, line):
        """A merged row keeps its adopted pallet, series and location: it is
        skipped by pallet-availability validation (it points at an occupied
        pallet on purpose) and never competes in the winner grouping."""
        if line.is_pallet_merge:
            return True
        return super()._vifel_line_is_merge_locked(line)

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
            'x_studio_production_date': line.production_date,
            'x_studio_expiration_date': line.expiration_date,
            'x_studio_quantity_uom':
                line.quantity_uom.id if line.quantity_uom else False,
            'x_studio_min_quantity_uom':
                line.packs_uom.id if line.packs_uom else False,
        })
        return True

    def _vifel_line_write_vals(self, line):
        """Carry the client Lot No. through on the normal path."""
        vals = super()._vifel_line_write_vals(line)
        vals['client_lot_no'] = line.client_lot_no or False
        return vals


class StockMoveLineFastEncodeContext(models.Model):
    _inherit = 'stock.move.line'

    def action_open_fast_encode_wizard(self):
        """Tell the Magic Wizard whether this client shows a Lot No. column."""
        res = super().action_open_fast_encode_wizard()
        if isinstance(res, dict) and isinstance(res.get('context'), dict) \
                and self:
            res['context'] = dict(
                res['context'],
                show_client_lot_no=bool(self[0].picking_id.show_client_lot_no))
        return res
