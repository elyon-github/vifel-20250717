from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

logger = logging.getLogger(__name__)

class FastEncodeRRWizard(models.TransientModel):
    _name = 'stock.move.line.fast_encode_rr'
    _description = 'Stock Move Line Fast Encode RR'
        
    transfer_id = fields.Integer(string="Transfer ID")
    line_ids = fields.One2many(
        'stock.move.line.fast_encode_rr.line', 'wizard_id', string="Pallet Lines", readonly=False
    )
    def action_confirm(self):
        """Apply wizard changes back to stock.move.line"""
        for line in self.line_ids:
            if line.stock_move_line:
                move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                move_line.write({
                    'result_package_id': line.result_package_id,
                    'bf_pallet_char': line.bf_pallet_char,
                    'x_studio_2nd_uom': line.quantity,
                    'x_studio_total_units': line.min_uom_unit,
                    'quantity': line.kilogram,
                })
                
                for ml in move_line:
                    # Only assign pallet series if this pallet is already used by another line
                    if ml.result_package_id and self._is_pallet_already_used(ml):
                        ml.assign_pallet_series_on_already_used_pallets()
                    
                    # ml.unreserve_onchange_pallet()
        
        return {'type': 'ir.actions.act_window_close'}
    
    def _is_pallet_already_used(self, move_line):
        """Check if this pallet is already used by another line in the same transfer"""
        existing_usage = self.env['stock.move.line'].search([
            ('picking_id', '=', move_line.picking_id.id),
            ('result_package_id', '=', move_line.result_package_id.id),
            ('x_studio_pallet_series_id', '!=', False),  # Has a pallet series already
            ('id', '!=', move_line.id)  # Exclude current line
        ], limit=1)
        
        return bool(existing_usage)

class FastEncodeRRWizardLine(models.TransientModel):
    _name = 'stock.move.line.fast_encode_rr.line'
    _description = 'Stock Move Line Fast Encode RR Line'
    _order = 'pallet_series_id asc'
    
    wizard_id = fields.Many2one('stock.move.line.fast_encode_rr', string="Wizard", ondelete='cascade')
    transfer_id = fields.Integer(string="Transfer ID", related='wizard_id.transfer_id', store=True)
    stock_move_line = fields.Integer(string="Move Line ID")
    
    product_id = fields.Many2one('product.product', string="Products", readonly="1")
    pallet_series_id = fields.Char(string='Pallet Series ID', readonly="1")
    result_package_id = fields.Many2one('stock.quant.package', string='RR Pallet #')
    pallet_number = fields.Many2one('stock.quant.package', string='BFRR Pallet #')
    bf_pallet_char = fields.Char(string="Pallet # - Text")
    quantity = fields.Float(string="Quantity")
    min_uom_unit = fields.Float(string="Packs")
    kilogram = fields.Float(string="Weight (KG)")
    previous_result_package_id = fields.Many2one('stock.quant.package', string='Previous RR Pallet #', copy=False)

    def write(self, vals):
        """Override write to handle pallet changes"""
        # Handle pallet logic before write if result_package_id is changing
        if 'result_package_id' in vals:
            # Store each record's previous value individually before the batch write
            previous_values = {}
            for record in self:
                previous_values[record.id] = record.result_package_id.id if record.result_package_id else False
            
            # Perform the write
            result = super(FastEncodeRRWizardLine, self).write(vals)
            
            # Handle pallet logic after write for each record
            for record in self:
                # Set the previous value for this specific record
                record.previous_result_package_id = previous_values.get(record.id, False)
                record._handle_pallet_change()
            
            return result
        else:
            # No pallet change, just do normal write
            return super(FastEncodeRRWizardLine, self).write(vals)


    def extract_id_from_newid(self, newid):
        # Already an integer
        if isinstance(newid, int):
            return newid
        
        # None or False
        if not newid:
            return False
            
        # Ensure that newid is a string before processing below
        newid = str(newid)
        
        # Check if the string starts with "NewId_"
        if newid.startswith("NewId_"):
            # Return false because its a memory address
            if len(newid[6:]) > 13:
                return False
            # Extract the numeric part after "NewId_"
            return int(newid[6:])
        else:
            raise ValueError(f"Invalid NewId format: {newid}")

    
    def _handle_pallet_change(self):
        """Separate method to handle pallet reservation logic"""
        
        if not self.product_id or not self.transfer_id:
            return
        
        report_id = self.transfer_id
        picking = self.env['stock.picking'].browse(report_id)
        id = self.extract_id_from_newid(self.id)
        if not picking:
            return
        
        # Check if others are using the previous pallet
        if self.previous_result_package_id:
            wizard_lines_using_previous = self.env['stock.move.line.fast_encode_rr.line'].search([
                ('transfer_id', '=', report_id),
                ('result_package_id', '=', self.previous_result_package_id.id),
                ('id', '!=', id)
            ])
            
            move_lines_using_previous = self.env['stock.move.line'].search([
                ('picking_id', '=', report_id),
                ('result_package_id', '=', self.previous_result_package_id.id)
            ])
            
            # Unreserve if no one else is using it
            if not wizard_lines_using_previous and not move_lines_using_previous:
                self.previous_result_package_id.write({
                    'x_studio_is_reserved': False,
                    'x_studio_receiving_report_id': False,
                })
        
        # Reserve the new pallet
        if self.result_package_id and picking.picking_type_code == 'incoming':
            # Check if the new pallet is already being used by other wizard lines OR move lines
            wizard_lines_using_new = self.env['stock.move.line.fast_encode_rr.line'].search([
                ('transfer_id', '=', report_id),
                ('result_package_id', '=', self.result_package_id.id),
                ('id', '!=', id)
            ])
            
            move_lines_using_new = self.env['stock.move.line'].search([
                ('picking_id', '=', report_id),
                ('result_package_id', '=', self.result_package_id.id)
            ])
            
            # If other wizard lines or move lines are using this pallet in the SAME transfer
            if wizard_lines_using_new or move_lines_using_new:
                # Just make sure it's reserved for THIS transfer (or not reserved yet)
                if self.result_package_id.x_studio_receiving_report_id and \
                   self.result_package_id.x_studio_receiving_report_id.id != report_id:
                    # It's reserved for a DIFFERENT transfer - this is an error
                    raise UserError("Oops, it seems like someone already reserved the pallet for another transfer. Please select another pallet.")
                
                # It's either not reserved yet, or reserved for this transfer - reserve it
                if not self.result_package_id.x_studio_is_reserved or \
                   not self.result_package_id.x_studio_receiving_report_id:
                    self.result_package_id.write({
                        'x_studio_is_reserved': True,
                        'x_studio_receiving_report_id': report_id,
                    })
                return
            
            # No one else is using it, so we need to reserve it
            if not self.result_package_id.x_studio_receiving_report_id or \
               self.result_package_id.x_studio_receiving_report_id.id == report_id:
                self.result_package_id.write({
                    'x_studio_is_reserved': True,
                    'x_studio_receiving_report_id': report_id,
                })
            else:
                raise UserError("Oops, it seems like someone already reserved the pallet. Please select another pallet.")