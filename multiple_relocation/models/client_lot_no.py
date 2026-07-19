# -*- coding: utf-8 -*-
"""Client Lot No. (Client-Specific Requirement Enhancement).

Some clients track their own lot numbers next to VIFEL's internal ones.
The column only appears for clients whose profile has "Show Lot No." on
(picking compute `show_client_lot_no` gates the views), is encoded on
the move line, and is stamped onto the matching quants when the transfer
validates so stock inquiries show it too.

copy=False everywhere: void mirrors and returns start blank.
"""
from odoo import api, fields, models


class StockMoveLineClientLotNo(models.Model):
    _inherit = 'stock.move.line'

    client_lot_no = fields.Char(
        string='Lot No.', copy=False,
        help="The client's own lot number for this pallet line.")


class StockQuantClientLotNo(models.Model):
    _inherit = 'stock.quant'

    client_lot_no = fields.Char(
        string='Lot No.', copy=False,
        help="The client's own lot number, stamped from the receiving "
             "line at validation. When several lines land on one quant, "
             "the last stamped value wins.")


class StockPickingClientLotNo(models.Model):
    _inherit = 'stock.picking'

    show_client_lot_no = fields.Boolean(
        string='Show Client Lot No.',
        compute='_compute_show_client_lot_no',
        help="This client's profile has Show Lot No. enabled.")

    @api.depends('partner_id', 'partner_id.vifel_show_lot_no')
    def _compute_show_client_lot_no(self):
        for picking in self:
            picking.show_client_lot_no = bool(
                picking.partner_id.vifel_show_lot_no)

    def button_validate(self):
        res = super().button_validate()
        self._vifel_stamp_client_lot_no()
        return res

    def _vifel_stamp_client_lot_no(self):
        """Copy each line's Lot No. onto the quants it landed on.

        Matched on the quant identity (product / destination location /
        lot / package / owner). Several lines with different Lot Nos can
        land on one quant — last write wins, by design.
        """
        Quant = self.env['stock.quant']
        for picking in self:
            if picking.state != 'done':
                continue
            for line in picking.move_line_ids:
                lot_no = (line.client_lot_no or '').strip()
                if not lot_no:
                    continue
                quants = Quant.search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.location_dest_id.id),
                    ('lot_id', '=', line.lot_id.id),
                    ('package_id', '=', line.result_package_id.id),
                    ('owner_id', '=',
                     line.owner_id.id or picking.partner_id.id),
                ])
                if quants:
                    quants.write({'client_lot_no': lot_no})
