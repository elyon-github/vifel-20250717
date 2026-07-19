# -*- coding: utf-8 -*-
"""Pallet merge flag + entry point (Client-Specific Requirement Enh.).

A merged line stores its cargo on a pallet that is ALREADY stocked on
the floor: the line adopts the target pallet's PSI and location, and the
PKR ledger must not count it as a new pallet (is_pallet_merge).

copy=False: void mirrors and returns are plain lines again.
"""
from odoo import api, fields, models


class StockMoveLineMerge(models.Model):
    _inherit = 'stock.move.line'

    is_pallet_merge = fields.Boolean(
        string='Merged Pallet', copy=False,
        help='This line was merged onto an already stocked pallet — it '
             'adopted that pallet\'s PSI and location, and does not count '
             'as a received pallet in the ledger.')
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

    def action_open_pallet_merge_wizard(self):
        self.ensure_one()
        wizard = self.env['pallet.merge.wizard'].create(
            {'move_line_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Merge Pallet — line #%s' % (self.x_studio_ or ''),
            'res_model': 'pallet.merge.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }
