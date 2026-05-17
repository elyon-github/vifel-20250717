from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging


class StockQuantRelocationLine(models.TransientModel):
    _name = 'stock.quant.relocation.line'
    _description = 'Stock Quant Relocation Line'
    _order = 'sequence, id'
    
    sequence = fields.Integer(string='#', default=10)
    relocate_wizard_id = fields.Many2one('stock.quant.relocate', required=True, ondelete='cascade')
    
    quant_id = fields.Many2one('stock.quant', string='Original Quant', required=True)
    owner_id = fields.Many2one('res.partner', string="Owner", readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    x_studio_pallet_series_id = fields.Char(string='Pallet Series', readonly=True)
    package_id = fields.Many2one('stock.quant.package', string='Package', readonly=True)
    current_location = fields.Many2one('stock.location', string="Current Location", readonly=True)
    new_location = fields.Many2one('stock.location', string="New Location")
    x_studio_production_date = fields.Date(string='Production Date', readonly=True)
    x_studio_expiration_date = fields.Date(string='Expiration Date', readonly=True)
    x_studio_2nd_uom = fields.Float(string='Total Quantity', readonly=True)
    x_studio_quantity_uom = fields.Many2one('uom.uom', string='Quantity UOM', readonly=True)
    x_studio_total_units = fields.Float(string='Total Packs', readonly=True)
    x_studio_min_quantity_uom = fields.Many2one('uom.uom', string='Packs UOM', readonly=True)
    quantity = fields.Float(string='Weight (KG)', readonly=True, digits='Product Unit of Measure')
    building = fields.Many2one('x_warehouse_building', string="Building", compute="_compute_building", store=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        related='quant_id.location_id.warehouse_id', store=True, readonly=True)
    bf_pallet_char = fields.Char(
        string="BF Pallet #",
        related='quant_id.bf_pallet_char', readonly=True)

    @api.depends('relocate_wizard_id.building')
    def _compute_building(self):
        for record in self:
            if record.relocate_wizard_id.building:
                record.building = record.relocate_wizard_id.building.id
            else:
                record.building = self.env['x_warehouse_building'].search([], limit=1)