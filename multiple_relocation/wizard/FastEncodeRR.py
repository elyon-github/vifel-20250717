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
        
        # Check if this is a blast freeze operation
        is_blast_freeze = self.env.context.get('is_blast_freeze', False)
        
        if is_blast_freeze:
            # Simple write for blast freeze - no pallet series grouping or reservations
            for line in self.line_ids:
                if line.stock_move_line:
                    move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                    move_line.write({
                        'result_package_id': line.result_package_id.id if line.result_package_id else False,
                        'bf_pallet_char': line.bf_pallet_char,
                        'x_studio_2nd_uom': line.quantity,
                        'x_studio_total_units': line.min_uom_unit,
                        'quantity': line.kilogram,
                    })
            return {'type': 'ir.actions.act_window_close'}
        
        # Normal logic for non-blast-freeze operations
        # Get all move lines for this transfer to track pallet and location changes
        if not self.line_ids:
            return {'type': 'ir.actions.act_window_close'}
        
        transfer_id = self.line_ids[0].transfer_id
        
        # Track pallets and locations that were previously used (before wizard changes)
        previous_pallets = set()
        previous_locations = set()
        for line in self.line_ids:
            if line.stock_move_line:
                move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                if move_line.result_package_id:
                    previous_pallets.add(move_line.result_package_id.id)
                if move_line.location_dest_id:
                    previous_locations.add(move_line.location_dest_id.id)
        
        # First pass: Build mappings of pallet_id -> first pallet_series_id and first location
        pallet_to_first_series = {}
        pallet_to_first_location = {}
        wizard_series_to_recycle = set()  # Track which series will be replaced
        current_pallets = set()  # Track pallets being used after wizard changes
        current_locations = set()  # Track locations being used after wizard changes
        
        for line in self.line_ids:
            if line.result_package_id:
                pallet_id = line.result_package_id.id
                current_pallets.add(pallet_id)
                
                # Only store the first series and location for each pallet
                if pallet_id not in pallet_to_first_series:
                    pallet_to_first_series[pallet_id] = line.pallet_series_id
                    pallet_to_first_location[pallet_id] = line.location_dest_id.id if line.location_dest_id else False
                    if line.location_dest_id:
                        current_locations.add(line.location_dest_id.id)
                else:
                    # This line's series will be replaced, mark it for recycling
                    wizard_series_to_recycle.add(line.pallet_series_id)
            
            # Track locations even if no pallet is set
            if line.location_dest_id:
                current_locations.add(line.location_dest_id.id)
        
        # Second pass: Check if pallets are already used by OTHER existing move lines
        # If so, prioritize their existing series and location, recycle wizard series accordingly
        for pallet_id, wizard_series in pallet_to_first_series.items():
            existing_line = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('result_package_id', '=', pallet_id),
                ('x_studio_pallet_series_id', '!=', False),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            if existing_line:
                # Existing line found - use its series and location instead
                # Mark the wizard's first series for this pallet as unused too
                wizard_series_to_recycle.add(wizard_series)
                pallet_to_first_series[pallet_id] = existing_line.x_studio_pallet_series_id
                pallet_to_first_location[pallet_id] = existing_line.location_dest_id.id if existing_line.location_dest_id else False
        
        # Third pass: Apply changes to stock.move.line
        for line in self.line_ids:
            if line.stock_move_line:
                move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                
                # Determine which pallet_series_id and location_dest_id to use
                pallet_series_to_use = line.pallet_series_id
                location_dest_to_use = line.location_dest_id.id if line.location_dest_id else False
                
                if line.result_package_id:
                    # Use the determined series and location for this pallet
                    pallet_series_to_use = pallet_to_first_series.get(line.result_package_id.id, line.pallet_series_id)
                    location_dest_to_use = pallet_to_first_location.get(line.result_package_id.id, location_dest_to_use)
                
                # Build the values to write
                write_vals = {
                    'result_package_id': line.result_package_id.id if line.result_package_id else False,
                    'bf_pallet_char': line.bf_pallet_char,
                    'x_studio_2nd_uom': line.quantity,
                    'x_studio_total_units': line.min_uom_unit,
                    'quantity': line.kilogram,
                    'x_studio_pallet_series_id': pallet_series_to_use,
                }
                
                # Only write location_dest_id if we have a valid value
                if location_dest_to_use:
                    write_vals['location_dest_id'] = location_dest_to_use
                
                # Write all the values
                move_line.write(write_vals)
                
                # Reserve the pallet if it's not already reserved
                if line.result_package_id and not line.result_package_id.x_studio_is_reserved:
                    line.result_package_id.write({
                        'x_studio_is_reserved': True, 
                        'x_studio_receiving_report_id': transfer_id
                    })
                
                # Reserve the location if it's not already reserved
                if location_dest_to_use:
                    location = self.env['stock.location'].browse(location_dest_to_use)
                    if location.exists() and not location.x_studio_is_reserved:
                        location.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': transfer_id
                        })
        
        # Fourth pass: Remove reservations for pallets that are no longer being used
        removed_pallets = previous_pallets - current_pallets
        for pallet_id in removed_pallets:
            # Check if this pallet is still used by other move lines in the same transfer
            other_usage = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('result_package_id', '=', pallet_id),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            # Only remove reservation if no other lines are using it
            if not other_usage:
                pallet = self.env['stock.quant.package'].browse(pallet_id)
                if pallet.exists():
                    pallet.remove_reservation()
        
        # Fifth pass: Remove reservations for locations that are no longer being used
        removed_locations = previous_locations - current_locations
        for location_id in removed_locations:
            # Check if this location is still used by other move lines in the same transfer
            other_usage = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('location_dest_id', '=', location_id),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            # Only remove reservation if no other lines are using it
            if not other_usage:
                location = self.env['stock.location'].browse(location_id)
                if location.exists():
                    location.remove_reservation()
        
        # Sixth pass: Push unused pallet series back to owner
        self._recycle_unused_pallet_series(wizard_series_to_recycle)
        
        return {'type': 'ir.actions.act_window_close'}
    
    def _recycle_unused_pallet_series(self, series_to_recycle):
        """Push unused pallet series back to the owner's pool"""
        if not series_to_recycle:
            return
        
        # Get the picking to find the owner
        if not self.line_ids:
            return
        
        picking = self.env['stock.picking'].browse(self.line_ids[0].transfer_id)
        if not picking:
            return
        
        # For each series that needs recycling, verify it's not being used anywhere
        for series_id in series_to_recycle:
            # Check if this series is actually being used in the final move lines
            series_in_use = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', series_id)
            ], limit=1)
            
            # Only push back if it's truly unused
            if not series_in_use:
                # Find the owner from any move line in this picking
                move_line_with_owner = self.env['stock.move.line'].search([
                    ('picking_id', '=', picking.id),
                    ('owner_id', '!=', False)
                ], limit=1)
                
                if move_line_with_owner and move_line_with_owner.owner_id:
                    move_line_with_owner.owner_id.push_unused_pallet(series_id)
    



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
    location_dest_id = fields.Many2one('stock.location', string='Destination Location')
    
    has_duplicate_pallet = fields.Boolean(
        string='Has Duplicate Pallet',
        compute='_compute_has_duplicate_pallet',
        store=False
    )
    
    @api.depends('result_package_id', 'wizard_id.line_ids.result_package_id')
    def _compute_has_duplicate_pallet(self):
        """Check if this line's pallet is used by other lines in the wizard"""
        for record in self:
            if not record.result_package_id:
                record.has_duplicate_pallet = False
                continue
            
            # Count how many lines in this wizard have the same pallet
            duplicate_count = self.search_count([
                ('wizard_id', '=', record.wizard_id.id),
                ('result_package_id', '=', record.result_package_id.id)
            ])
            
            # If more than 1, then this pallet is duplicated
            record.has_duplicate_pallet = duplicate_count > 1