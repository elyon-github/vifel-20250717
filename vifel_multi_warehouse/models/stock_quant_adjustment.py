# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockQuantAdjustmentLine(models.Model):
    _inherit = 'stock.quant.adjustment.line'

    warehouse_id = fields.Many2one(
        related='quant_id.location_id.warehouse_id', store=True, index=True,
        string='Warehouse',
        help='Warehouse of the adjusted quant (multi-warehouse scoping).')


class StockQuantAdjustmentRequest(models.Model):
    _inherit = 'stock.quant.adjustment.request'

    warehouse_id = fields.Many2one(
        'stock.warehouse', compute='_compute_warehouse_id', store=True,
        index=True, string='Warehouse',
        help='Warehouse of the adjusted quants (from the request lines).')

    @api.depends('line_ids.warehouse_id')
    def _compute_warehouse_id(self):
        for request in self:
            request.warehouse_id = request.line_ids.warehouse_id[:1]
