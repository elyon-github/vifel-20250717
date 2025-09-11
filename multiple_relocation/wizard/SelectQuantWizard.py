from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)
class SelectQuantWizard(models.TransientModel):
    _name = 'select_quant.wizard'
    _description = 'Wizard to Select Stock Quants'

        
    stock_move_id = fields.Integer(string="Stock Move ID")

    
    quant_ids_picked = fields.Many2many(
        'stock.quant',
        string='Pallet Stocks',
        help='Select stock quants related to this record',
        copy=False
    )

    product_id = fields.Many2one(
        'product.product', 
        string='Product',
        help='Filter quants by specific product'
    )
    
    owner_id = fields.Many2one(
        'res.partner', 
        string='Owner',
        help='Filter quants by owner'
    )
    
    location_id = fields.Many2one(
        'stock.location', 
        string='Source Location',
        help='Filter quants by location'
        
    )

    demand = fields.Float(string="Demand")
    
    transfer_id = fields.Integer(string="Transfer ID")

    move_line_ids = fields.Many2many(
        'stock.move.line',

    )

    stock_moves_multiple_withdraw = fields.Many2many('stock.move.line', 'rel_stock_move_lines')

    automatically_fetched_quantity = fields.Boolean(string="Automatically Fetched using a Button")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        
        # Get move_line_ids from context
        move_line_ids = self.env.context.get('default_move_line_ids', [])
        transfer_id = self.env.context.get('default_transfer_id')
        stock_move_id = self.env.context.get('default_stock_move_id')
        if not move_line_ids:
            return res
        
        # Find related lot_ids
        move_lines = self.env['stock.move.line'].browse(move_line_ids)
        lot_ids = move_lines.mapped('lot_id.id').copy()
        # quant_ids = move_lines.mapped('computed_quant_id.id')
        
        # Search for stock.moves with these lots and not done
        same_quant_stocks_picked = self.env['stock.move.line'].search([
            ('lot_id', 'in', lot_ids),
            ('state', '!=', 'done'), ('picking_id.id', '!=', transfer_id),
            ('picking_id.picking_type_code', '=', 'outgoing')
        ])

        existing_vals = res.get('quant_ids_picked') or []
        has_existing_quants = any(cmd[0] == 6 and cmd[2] for cmd in existing_vals)
        if not has_existing_quants:
            initial_quant_ids = self.env['stock.quant'].search([
                ('lot_id', 'in', lot_ids),
                ('location_id.usage', '=', 'internal'),
                # ('picking_id.id', '=', transfer_id),
            ])
            # Get related quant IDs from move lines
            
            res['quant_ids_picked'] = [(6, 0, initial_quant_ids.ids)]
            # Assign stock move_quant_ids
            # self.env['stock.move'].search([('id', '=', stock_move_id)]).quant_ids_picked = [(6, 0, initial_quant_ids.ids)]

        
        # Update res with the stock moves
        res['stock_moves_multiple_withdraw'] = [(6, 0, same_quant_stocks_picked.ids)]
        
        return res
        

    # @api.model
    # def _prepare_stock_moves(self, context):
    #     move_line_ids = self.env['stock.move.line'].search([('id', 'in', context.get('default_move_line_ids'))])
    #     lot_ids = move_line_ids.mapped('lot_id.id')

    #     same_quant_stocks_picked = self.env['stock.move'].search([
    #         ('move_line_ids.lot_id', 'in', lot_ids),
    #         ('state', '!=', 'done')
    #     ])

    #     self.stock_moves_multiple_withdraw = [(6, 0, same_quant_stocks_picked.ids)]
    #     raise UserError(self.stock_moves_multiple_withdraw)

    
    def action_confirm(self):
        # Browse the stock.move record and the transfer (picking)
        this_stock_move = self.env['stock.move'].browse(self.stock_move_id)
        transfer_id = self.env['stock.picking'].browse(self.transfer_id)
        
        # Basic validation
        if not this_stock_move.exists():
            raise UserError("The Stock Move record does not exist.")
        
        # --- Identify packages to work with ---
        # Get currently selected packages in this wizard
        selected_packages = self.quant_ids_picked.mapped('package_id')
        
        # Get previously selected packages from the stock move
        previous_packages = this_stock_move.quant_ids_picked.mapped('package_id')
        
        # Identify packages to remove (those that were previously selected but aren't anymore)
        packages_to_remove = previous_packages - selected_packages
        packages_to_add = selected_packages - previous_packages
        packages_unchanged = selected_packages & previous_packages
        
        # --- Step 1: Handle removals first ---
        if packages_to_remove:
            # Find all quants and move lines related to these packages in the entire transfer
            for move in transfer_id.move_ids:
                # Remove quants for these packages
                quants_to_remove = move.quant_ids_picked.filtered(
                    lambda q: q.package_id in packages_to_remove
                )
                if quants_to_remove:
                    move.write({'quant_ids_picked': [(3, quant.id) for quant in quants_to_remove]})
                
                # Remove move lines for these packages
                move_lines_to_remove = move.move_line_ids.filtered(
                    lambda ml: ml.package_id in packages_to_remove
                )
                if move_lines_to_remove:
                    move_lines_to_remove.unlink()
        
        # --- Step 2: Process packages to add or keep ---
        if packages_to_add or packages_unchanged:
            packages_to_process = packages_to_add | packages_unchanged
            
            # Get all quants from these packages with positive quantity and valid lot
            all_package_quants = self.env['stock.quant'].search([
                ('package_id', 'in', packages_to_process.ids),
                ('lot_id', '!=', False),
                ('quantity', '>', 0),
                ('owner_id', '=', self.owner_id.id if self.owner_id else False)
            ])

            all_package_quants = all_package_quants.filtered(lambda q: q.available_quantity > 0)

            
            # Group quants by product for processing - critically important to separate by product
            quants_by_product = {}
            for quant in all_package_quants:
                if quant.product_id.id not in quants_by_product:
                    quants_by_product[quant.product_id.id] = []
                quants_by_product[quant.product_id.id].append(quant)
            
            # Track processed combinations to avoid duplicates
            processed_combinations = set()
            
            # First process main product
            main_product_id = this_stock_move.product_id.id
            if main_product_id in quants_by_product:
                main_product_quants = quants_by_product[main_product_id]
                
                # Clear existing quant selections for this product in this move
                # to avoid duplicates (will re-add all needed quants)
                # existing_quants = this_stock_move.quant_ids_picked
                # if existing_quants:
                #     this_stock_move.write({'quant_ids_picked': [(5, 0, 0)]})
                
                # Process all quants for the main product
                for quant in main_product_quants:
                    key = (quant.product_id.id, quant.location_id.id, quant.package_id.id, quant.lot_id.id)
                    if key in processed_combinations:
                        continue
                    processed_combinations.add(key)

                    # Add to quant_ids_picked
                    
                    this_stock_move.write({'quant_ids_picked': [(4, quant.id)]})
                    
                    # Check if move line exists
                    existing_line = this_stock_move.move_line_ids.filtered(
                        lambda ml: ml.lot_id.id == quant.lot_id.id and 
                                  ml.package_id.id == quant.package_id.id
                    )
                    
                    if existing_line:
                        # Update existing line
                        existing_line.write({'quantity': quant.available_quantity})
                    else:
                        # Create new move line
                        self.env['stock.move.line'].create({
                            'picking_id': transfer_id.id,
                            'move_id': this_stock_move.id,
                            'product_id': quant.product_id.id,
                            'quantity': quant.available_quantity,
                            'lot_id': quant.lot_id.id,
                            'package_id': quant.package_id.id,
                            'location_id': this_stock_move.location_id.id,
                            'location_dest_id': this_stock_move.location_dest_id.id if this_stock_move.location_dest_id else 5,
                            'quant_id': quant.id,
                            'computed_quant_id': quant.id,
                        })
                
                # Update quantity for main move
                this_stock_move.product_uom_qty = sum(this_stock_move.quant_ids_picked.mapped('quantity'))
                
                # Remove the main product as it's already processed
                del quants_by_product[main_product_id]
            
            # Now process other products (products other than the main one)
            for product_id, product_quants in quants_by_product.items():
                if not product_quants:
                    continue
                    
                # Find existing move for this product or create new one
                existing_move = transfer_id.move_ids.filtered(
                    lambda m: m.id != this_stock_move.id and m.product_id.id == product_id
                )

                if existing_move:
                    target_move = existing_move[0]
                    
                    # CRITICAL: Clear any existing quants for this move to avoid carrying over
                    # quants from other products
                    # if target_move.quant_ids_picked:
                    #     target_move.write({'quant_ids_picked': [(5, 0, 0)]})
                        
                    # Also clear any move lines
                    if target_move.move_line_ids:
                        target_move.move_line_ids.unlink()

                else:
                    # Create new move for this product
                    target_move = self.env['stock.move'].create({
                        'name': product_quants[0].product_id.name,
                        'picking_id': transfer_id.id,
                        'product_id': product_id,
                        'product_uom': product_quants[0].product_id.uom_id.id,
                        'product_uom_qty': sum(q.available_quantity for q in product_quants),
                        'location_id': this_stock_move.location_id.id,
                        'location_dest_id': this_stock_move.location_dest_id.id,
                        'automatically_added': True,
                        'quant_ids_picked': False
                    })

                    # raise UserError(target_move.product_id.name)
                # Process all quants for this product only

                for quant in product_quants:
                    key = (quant.product_id.id, quant.location_id.id, quant.package_id.id, quant.lot_id.id)
                    if key in processed_combinations:
                        continue
                    processed_combinations.add(key)
                    
                    # Add quant to this product's move ONLY if it belongs to this product
                    if quant.product_id.id == product_id:

                        target_move.write({'quant_ids_picked': [(4, quant.id)]})
                        # if 'BELLY' in quant.product_id.name:
                        #     raise UserError(target_move.quant_ids_picked)
                        # Create new move line
                        self.env['stock.move.line'].create({
                            'picking_id': transfer_id.id,
                            'move_id': target_move.id,
                            'product_id': quant.product_id.id,
                            'quantity': quant.available_quantity,
                            'lot_id': quant.lot_id.id,
                            'package_id': quant.package_id.id,
                            'location_id': target_move.location_id.id,
                            'location_dest_id': target_move.location_dest_id.id if target_move.location_dest_id else 5,
                            'quant_id': quant.id,
                            'computed_quant_id': quant.id,
                        })
                        _logger.info(quant.product_id.id)
                # Update quantity for this move
                target_move.product_uom_qty = sum(target_move.quant_ids_picked.mapped('quantity'))
        
        # --- Step 3: Clean up empty moves ---
        # Delete any moves with no quants left
        for move in transfer_id.move_ids:
            if move.id != this_stock_move.id:  # Don't delete the main move
                if not move.quant_ids_picked or sum(move.quant_ids_picked.mapped('quantity')) <= 0:
                    move.move_line_ids.unlink()
                    move.unlink()
        
        # Update destination location for all move lines
        location = self.env['stock.location'].browse(5)
        for move in transfer_id.move_ids:
            move.move_line_ids.write({'location_dest_id': location.id})


    
    def auto_adjust_line_values(record):
        """Automatically adjust values based on availability"""
        # Get the move lines from the current record and from other transfers
        current_move_lines = record.move_line_ids
        other_move_lines = record.stock_moves_multiple_withdraw
        record.automatically_fetched_quantity = True
        # Group move lines by lot_id
        lot_to_lines = {}
        updated_lines = set()  # Track which lines we've updated to avoid double-processing
    
        # First collect all move lines by lot_id (both current and from other transfers)
        for move_line in current_move_lines + other_move_lines:
            if not move_line.lot_id:
                continue
                
            lot_id = move_line.lot_id.id
            if lot_id not in lot_to_lines:
                lot_to_lines[lot_id] = {
                    'current_lines': [],
                    'other_lines': [],
                    'max_2nd_uom': move_line.x_studio_max_2nd_uom,
                    'max_total_units': move_line.x_studio_max_total_units,
                    'max_quant': move_line.x_studio_max_quant,
                    'lot_name': move_line.lot_id.name
                }
            
            if move_line in current_move_lines:
                lot_to_lines[lot_id]['current_lines'].append(move_line)
            else:
                lot_to_lines[lot_id]['other_lines'].append(move_line)
        
        # For each lot, calculate availability and adjust values
        for lot_id, data in lot_to_lines.items():
            current_lines = data['current_lines']
            other_lines = data['other_lines']
            
            # Skip if no current lines (nothing to adjust)
            if not current_lines:
                continue
                
            # Get maximum values
            max_2nd_uom = data['max_2nd_uom']
            max_total_units = data['max_total_units']
            max_quant = data['max_quant']
            
            # Calculate sums from other transfer records
            other_affected_2nd_uom_sum = sum(line.x_studio_affected_2nd_uom for line in other_lines)
            other_withdraw_units_sum = sum(line.x_studio_withdraw_units for line in other_lines)
            other_quantity_sum = sum(line.quantity for line in other_lines)
            
            # Calculate available amounts
            available_2nd_uom = max_2nd_uom - other_affected_2nd_uom_sum
            available_withdraw_units = max_total_units - other_withdraw_units_sum
            available_quantity = max_quant - other_quantity_sum
            # raise UserError(available_2nd_uom)
            # Make sure we never use negative values
            available_2nd_uom = max(0, available_2nd_uom)
            available_withdraw_units = max(0, available_withdraw_units)
            available_quantity = max(0, available_quantity)
            
            # For each current line, directly assign the available values
            # If multiple lines, each will get the full available amount until they're all processed
            for line in current_lines:
                if line.id in updated_lines:
                    continue  # Skip if already updated
                
                # Directly set the available values (capped at the original value)
                line.x_studio_affected_2nd_uom = available_2nd_uom
                line.x_studio_withdraw_units = available_withdraw_units
                line.quantity = available_quantity

                
                # Update the available amounts for the next line
                available_2nd_uom -= line.x_studio_affected_2nd_uom
                available_withdraw_units -= line.x_studio_withdraw_units
                available_quantity -= line.quantity
                
                # Make sure we never use negative values
                available_2nd_uom = max(0, available_2nd_uom)
                available_withdraw_units = max(0, available_withdraw_units)
                available_quantity = max(0, available_quantity)
                
                updated_lines.add(line.id)

        return True


    def reset_values_for_multiple(self):
        for record in self:
            current_move_lines = record.move_line_ids
    
            for line in current_move_lines:
                if line.is_package_multiple_withdraw:
                    line.x_studio_affected_2nd_uom = 0
                    line.x_studio_withdraw_units = 0
                    line.quantity = 0
        # return {}
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
            

class StockAdjustmentAdd(models.TransientModel):
    _inherit = 'stock.inventory.adjustment.name'
    
    quant_ids = fields.Many2many('stock.quant', string="Quantities")
    inventory_adjustment_name = fields.Char(default="Quantity Updated", string="Inventory Reason")
    
    def action_apply(self):
        # Filter quants where inventory_quantity_set is True
        quants = self.quant_ids.filtered(lambda q: q.inventory_quantity_set)
        
        # Optional: Remove or comment out the UserError for production
        # raise UserError(self.quant_ids)  # For debugging purposes
        
        # Ensure action_apply_inventory exists on the quant model
        return quants.with_context(inventory_name=self.inventory_adjustment_name).action_apply_inventory()









