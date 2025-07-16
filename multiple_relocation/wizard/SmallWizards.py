from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
class PartialPackageNoticeWizard(models.TransientModel):
    _name = 'wizard.partial.package.notice'
    _description = 'Missing Quants in Package'

    picking_id = fields.Many2one('stock.picking', readonly=True)
    quant_ids = fields.Many2many('stock.quant', readonly=True, string="Unselected Quants")

    # def action_proceed_with_missing_quants(self):
    #     # Call your transfer function again but with a flag to ignore missing quant validation    
    #     context = dict(self.env.context)
    #     context['ignore_missing_quants'] = True
    #     raise UserError(self.quant_ids)
    #     return self.env['stock.quant'].with_context(context).create_transfer_stock_move(self.picking_id.id, self.quant_ids)
        
    def action_proceed_with_missing_quants(self):
        context = dict(self.env.context, ignore_missing_quants=True)
    
        Quant = self.env['stock.quant']
        selected_quant_ids = context.get('default_selected_quant_ids') or []
        selected_quants = Quant.browse(selected_quant_ids)
    
        all_quants = selected_quants | self.quant_ids
        # raise UserError(all_quants)
        return Quant.with_context(context).create_transfer_stock_move(
            self.picking_id.id, all_quants
        )
