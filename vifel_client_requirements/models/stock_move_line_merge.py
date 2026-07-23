# -*- coding: utf-8 -*-
"""Merge entry points on the Pallet Breakdown line (Client-Specific Req. Enh).

The ``is_pallet_merge`` FIELD lives in multiple_relocation (ledger evidence);
this file adds only the interaction around it — when the Merge / Un-merge
button shows, and what the two buttons do. Nothing here stores merge state, so
uninstalling drops the buttons and leaves every historical flag intact.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockMoveLineMergeEntry(models.Model):
    _inherit = 'stock.move.line'

    vifel_show_merge_button = fields.Boolean(
        compute='_compute_vifel_show_merge_button')

    @api.depends('picking_id.partner_id', 'picking_id.state',
                 'picking_id.picking_type_id')
    def _compute_vifel_show_merge_button(self):
        """Merge is a receiving-time tool for merge-enabled clients:
        incoming, non blast freeze, not a return, not validated."""
        for line in self:
            picking = line.picking_id
            line.vifel_show_merge_button = bool(
                picking
                and picking.picking_type_code == 'incoming'
                and picking.state != 'done'
                and not picking.return_id
                and not getattr(picking, 'is_void_return', False)
                and not picking.x_studio_is_a_blast_freezer
                and picking.partner_id.vifel_can_merge_pallets)

    def write(self, vals):
        """Guard merged lines, and detect an un-merge.

        Both used to live inside ``multiple_relocation``'s own write override.
        They wrap it from here instead, so core carries none of this feature:
        the guard runs before core's write, and the flag is cleared after it,
        once core's restore machinery has put the line's own series back.
        """
        self._vifel_guard_merged_line_edit(vals)

        # UN-MERGE: a merged line whose pallet is changed away outside the
        # merge wizard becomes a plain line again. Conditions mirror core's
        # own early returns, so this fires exactly where core would have.
        ctx = self.env.context
        unmerged = self.browse()
        if ('result_package_id' in vals
                and not ctx.get('skip_pallet_series_sync')
                and not ctx.get('vifel_pallet_merge')):
            unmerged = self.filtered(
                lambda r: r.is_pallet_merge and r.picking_id
                and r.picking_id.picking_type_code == 'incoming'
                and r.product_id and not r.picking_id.return_id)

        res = super().write(vals)

        if unmerged:
            # bypass this override: only the flag changes, and core's write
            # returns early for a vals without result_package_id anyway. The
            # adopted PSI is NOT recycled — push_unused_pallet's stocked-guard
            # refuses a series that is live on the floor.
            super(StockMoveLineMergeEntry, unmerged).write(
                {'is_pallet_merge': False})
        return res

    def _vifel_guard_merged_line_edit(self, vals):
        """Refuse a silent edit of a merged line's location or series.

        Exempt when the merge wizard itself is writing (vifel_pallet_merge),
        when the flag is being cleared in the same write (an un-merge), and
        for validation/void machinery that carries skip_pallet_series_sync.
        """
        ctx = self.env.context
        if ctx.get('vifel_pallet_merge') or ctx.get('skip_pallet_series_sync'):
            return
        if vals.get('is_pallet_merge') is False:
            return                      # un-merging: the pin is being removed
        watched = {
            'location_dest_id': _('Location'),
            'x_studio_pallet_series_id': _('Pallet Series ID'),
        }
        touched = [label for key, label in watched.items() if key in vals]
        if not touched:
            return
        for line in self:
            if not line.is_pallet_merge:
                continue
            # Mid-un-merge: the pallet has already been cleared and the
            # restore machinery is putting the original series back (it
            # re-enters write through base_automation's wrapper). A merged
            # line with no pallet has nothing left to stay consistent with.
            if not line.result_package_id:
                continue
            raise UserError(_(
                "Line #%(num)s is merged onto pallet %(pallet)s "
                "(%(psi)s), so its %(fields)s cannot be changed here — the "
                "line has to stay where that pallet is.\n\n"
                "Press Un-merge on the line first if it should go somewhere "
                "else."
            ) % {'num': line.x_studio_ or '',
                 'pallet': line.result_package_id.name or '?',
                 'psi': line.x_studio_pallet_series_id or '?',
                 'fields': ' / '.join(touched)})

    def action_open_pallet_merge_wizard(self):
        self.ensure_one()
        wizard = self.env['pallet.merge.wizard'].create(
            {'move_line_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Merge Pallet — %s') % (
                self.product_id.display_name or _('line #%s') % (
                    self.x_studio_ or '')),
            'res_model': 'pallet.merge.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _vifel_restore_premerge_state(self, captured, pre_series, pre_location):
        """Put the line back exactly as the merge found it.

        Only corrects what the generic restore cannot know:

        * a line that had NO series before merging keeps the adopted one,
          because that restore is gated on original_pallet_series_id and a
          line with no original never enters it — so the series is cleared
          here;
        * a line that had no x_studio_initial_location is sent to a hardcoded
          fallback location — so the real pre-merge location is written back
          here.

        A line that did have its own series is left to the existing, tested
        machinery (which also settles the recycling pool); this only fills the
        gaps rather than overriding it.
        """
        self.ensure_one()
        if not captured:
            return
        vals = {}
        if not pre_series and self.x_studio_pallet_series_id:
            vals['x_studio_pallet_series_id'] = False
        if pre_location and self.location_dest_id != pre_location:
            vals['location_dest_id'] = pre_location.id
        vals.update({'vifel_premerge_captured': False,
                     'vifel_premerge_series': False,
                     'vifel_premerge_location_id': False})
        self.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)

        # x_studio_pallet_series_display is a STORED Studio computed field
        # whose compute only assigns when the source has a value:
        #
        #     if record.x_studio_pallet_series_id:
        #         record['x_studio_pallet_series_display'] = ...
        #
        # so clearing the series leaves the display holding the old one. The
        # real fix is an else-branch in that Studio compute — see
        # ai_context/studio_psi_display_clear_FIX.py — but the field is
        # cleared here too, in its own write after the recompute has run, so
        # un-merge is correct even before that paste reaches a database.
        if 'x_studio_pallet_series_display' in self._fields \
                and vals.get('x_studio_pallet_series_id', True) is False:
            self.with_context(skip_pallet_series_sync=True,
                              vifel_pallet_merge=True).write(
                {'x_studio_pallet_series_display': False})

    def action_unmerge_pallet_line(self):
        """Reverse a merge: the line leaves the stocked target and becomes a
        plain line needing its own pallet again.

        Clearing the pallet routes through the stock_move write override,
        which detects the flagged line as an un-merge (clears the flag) and
        runs the standard restore-original machinery. The adopted Pallet
        Series belongs to the target's live stock, so the restore's recycle
        attempt is refused by push_unused_pallet's stocked-guard — it is
        never returned to the pool.
        """
        self.ensure_one()
        if not self.is_pallet_merge:
            raise UserError(_('This line is not a merged pallet.'))
        target_name = self.result_package_id.name
        captured = self.vifel_premerge_captured
        pre_series = self.vifel_premerge_series
        pre_location = self.vifel_premerge_location_id
        self.write({'result_package_id': False})
        self._vifel_restore_premerge_state(captured, pre_series, pre_location)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pallet un-merged'),
                'message': _(
                    'Line #%(num)s no longer merges onto %(pallet)s — assign '
                    'it its own pallet.') % {
                        'num': self.x_studio_ or '', 'pallet': target_name},
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
