# -*- coding: utf-8 -*-
"""Carry the withdrawn stock's Lot No. / Batch # onto a return.

A partial-withdrawal (or full) return re-receives stock, but the base return
builder copied everything EXCEPT the client Lot No. / Batch # (on a withdrawal
those live on the QUANT, not the move line), so the re-received stock lost them
and its Prodcode. These overrides fill the two neutral hooks the base return
wizard exposes, so the values ride the wizard line to the return move line and
are re-stamped onto the quant at validation (regenerating the Prodcode).

Plug-and-play: the base module (multiple_relocation) only carries empty hooks;
all of the Lot No. / Batch # logic lives here.
"""
from odoo import models, fields


class ReturnPackageWizardLineLotBatch(models.TransientModel):
    _inherit = 'return.package.wizard.line'

    client_lot_no = fields.Char(string='Lot No.')
    batch_no = fields.Char(string='Batch #')


class ReturnPackageWizardLotBatch(models.TransientModel):
    _inherit = 'return.package.wizard'

    def _vifel_return_wizard_line_vals(self, move_line):
        """The withdrawn stock's Lot No. / Batch # were entered on the ORIGINAL
        receiving line (and stamped to stock there). The source quant is often
        already depleted by the time the return is built, so read them back from
        that incoming, non-return line, matched by product + lot (the lot is
        receipt-specific, so it identifies the original line)."""
        vals = super()._vifel_return_wizard_line_vals(move_line)
        src = self.env['stock.move.line'].search([
            ('product_id', '=', move_line.product_id.id),
            ('lot_id', '=', move_line.lot_id.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.return_id', '=', False),
            ('client_lot_no', '!=', False)], limit=1)
        vals.update({'client_lot_no': src.client_lot_no or False,
                     'batch_no': src.batch_no or False})
        return vals

    def _vifel_return_move_line_vals(self, package):
        """Copy the Lot No. / Batch # from the wizard line onto the return move
        line, so validation re-stamps them and regenerates the Prodcode."""
        vals = super()._vifel_return_move_line_vals(package)
        vals.update({'client_lot_no': package.client_lot_no or False,
                     'batch_no': package.batch_no or False})
        return vals
