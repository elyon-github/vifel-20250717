# -*- coding: utf-8 -*-
"""Client Lot No. — gating and stamping (Client-Specific Requirement Enh.).

Some clients track their own lot numbers next to VIFEL's internal ones. This
module decides WHEN the column is shown (per the client's profile) and copies
the encoded value onto stock at validation.

The ``client_lot_no`` FIELDS themselves live in ``multiple_relocation``, not
here — see the manifest. They are evidence of what was received; uninstalling
this module must not erase them.
"""
from odoo import api, fields, models


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

        Matched on the quant identity (product / destination location / lot /
        package / owner). Several lines carrying different Lot Nos can land on
        one quant — last write wins, by design.
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
