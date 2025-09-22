# -*- coding: utf-8 -*-


from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError, UserError
from odoo.osv import expression
import logging
from datetime import datetime, timedelta, date
import re
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.osv.expression import AND, OR
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
from collections import defaultdict
_logger = logging.getLogger(__name__)
from ast import literal_eval


class StockMove(models.Model):
    _inherit = 'stock.move'
    quant_ids_picked = fields.Many2many('stock.quant', string="Quant IDs", copy=False)
    
    automatically_added = fields.Boolean()
    reason_for_adjustment = fields.Char(string="Reason for Adjustment")
    def regenerate_move_lines(self):
        """Generate new move lines based on number of lines specified"""
        self.ensure_one()
        
        # Delete existing move lines
        existing_move_lines = self.move_line_ids
        
        for lines in existing_move_lines:
            if lines.x_studio_pallet_series_id:
                # Pass the initial pallet series assigned to the unused_pallet_series_ids field (json-array)
                lines.owner_id.push_unused_pallet(lines.x_studio_pallet_series_id)
            if lines.location_dest_id:
                # Unreserve the move.lines for the locations assigned
                lines.location_dest_id.remove_reservation()
                    
            if lines.result_package_id:
                # Unreserve the move.lines for the package assigned
                lines.result_package_id.remove_reservation()
        
        if existing_move_lines:
            existing_move_lines.unlink()
        
        # Create new move lines
        move_lines_data = []
        is_blast_freeze = self.picking_id.x_studio_is_a_blast_freezer
        generic_blast_freeze_package_id = self.env['stock.quant.package'].search([('name', 'ilike', 'GENERIC METAL PALLET')], limit=1)
        
        # Get number of lines from the move or picking
        number_of_lines = self.x_studio_number_of_lines or self.picking_id.x_studio_number_of_lines or 1
        
        for i in range(number_of_lines):
            move_lines_data.append({
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'move_id': self.id,
                'picking_id': self.picking_id.id,
                # 'result_package_id': generic_blast_freeze_package_id.id if is_blast_freeze else False,
                'x_studio_quantity_uom': self.x_studio_packaging_unit.id if self.x_studio_packaging_unit else False,
                'x_studio_min_quantity_uom': self.x_studio_min_unit.id if self.x_studio_min_unit else False,
            })
        
        # Create the move lines
        created_lines = []
        for line_data in move_lines_data:
            created_lines.append(self.env['stock.move.line'].create(line_data))
        
        return created_lines
    def _update_reserved_quantity(self, need, location_id, quant_ids=None, lot_id=None, package_id=None, owner_id=None, strict=True):
        """ Create or update move lines and reserves quantity from quants
            Expects the need (qty to reserve) and location_id to reserve from.
            `quant_ids` can be passed as an optimization since no search on the database
            is performed and reservation is done on the passed quants set
        """

        
        self.ensure_one()
        if quant_ids is None:
            quant_ids = self.env['stock.quant']
        if not lot_id:
            lot_id = self.env['stock.lot']
        if not package_id:
            package_id = self.env['stock.quant.package']
        if not owner_id:
            owner_id = self.env['res.partner']
        

        quants = quant_ids._get_reserve_quantity(
            self.product_id, location_id, need, product_packaging_id=self.product_packaging_id,
            uom_id=self.product_uom, lot_id=lot_id, package_id=package_id, owner_id=self.partner_id, x_studio_container_number=self.x_studio_container_number, quant_ids_picked= self.quant_ids_picked.ids, strict=strict)


        # _logger.info(self)
        taken_quantity = 0
        rounding = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        # Find a candidate move line to update or create a new one.


        for reserved_quant, quantity, in quants:
            
            taken_quantity += quantity
            to_update = next((line for line in self.move_line_ids if line._reservation_is_updatable(quantity, reserved_quant)), False)
            if to_update:
                uom_quantity = self.product_id.uom_id._compute_quantity(quantity, to_update.product_uom_id, rounding_method='HALF-UP')
                uom_quantity = float_round(uom_quantity, precision_digits=rounding)
                uom_quantity_back_to_product_uom = to_update.product_uom_id._compute_quantity(uom_quantity, self.product_id.uom_id, rounding_method='HALF-UP')
            if to_update and float_compare(quantity, uom_quantity_back_to_product_uom, precision_digits=rounding) == 0:
                to_update.with_context(reserved_quant=reserved_quant).quantity += uom_quantity
            else:
                if self.product_id.tracking == 'serial':
                    vals_list = self._add_serial_move_line_to_vals_list(reserved_quant, quantity)
                    if vals_list:
                        self.env['stock.move.line'].with_context(reserved_quant=reserved_quant).create(vals_list)
                else:
                    self.env['stock.move.line'].with_context(reserved_quant=reserved_quant).create(self._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant))

        return taken_quantity
    
    def select_quants(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Pallet Stocks',
            'res_model': 'select_quant.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_stock_move_id': self.id,
                'default_product_id': self.product_id.id,  # Ensure you're passing the ID, not the record itself
                'default_owner_id': self.partner_id.id,    # Ensure you're passing the ID, not the record itself
                'default_location_id': self.picking_id.location_id.id,  # Ensure you're passing the ID, not the record itself
                'default_quant_ids_picked': self.quant_ids_picked.ids,  # Pass the IDs of the quant_ids, not the records
                'default_demand': self.product_uom_qty,
                'default_transfer_id': self.picking_id.id,
                'default_move_line_ids': self.move_line_ids.ids
            },
        }



    def write(self, vals):
        # Check if we have incoming moves and need to prevent unreservation
        if 'product_uom_qty' in vals:
            has_incoming_moves = any(move.picking_type_id.code == 'incoming' for move in self)
            if has_incoming_moves:
                # Set context to prevent unreservation for incoming moves
                return super(StockMove, self.with_context(do_not_unreserve=True)).write(vals)
        
        # For non-incoming moves, proceed with normal logic
        return super(StockMove, self).write(vals)


class stock_move_line_Override(models.Model):
    _inherit = 'stock.move.line'
    _order = 'product_id asc'

    warehouseman = fields.Many2one(
        'res.partner', 
        string="Warehouseman", 
        domain="[('category_id.name', '=', 'Warehouseman')]"
    )

    adjustment_batch_number = fields.Char(string="Adjustment Batch #")

    x_studio_reason_for_adjustment = fields.Char(string="Reason for Adjustment")
    x_studio_loading_dock_no = fields.Char(string="Loading Dock No.")
    x_studio_source = fields.Char(string="Source")
    x_studio_gate_pass = fields.Char(string="Source")

    x_studio_truck_time = fields.Datetime(string="Truck Time")
    x_studio_start_time = fields.Datetime(string="Start Time")
    x_studio_end_time = fields.Datetime(string="End Time")
    x_studio_truck_number = fields.Char(string="Truck's Plate")
    x_studio_record_reference = fields.Char(string="Record Reference")
    x_studio_container_number = fields.Char(string="Container #", compute="_compute_container_number", store=True)
    
    x_studio_building_dropped = fields.Char(string="Building", compute="_compute_x_studio_building_dropped", store=True)
    original_record_reference = fields.Many2one('stock.picking', compute="_compute_x_studio_building_dropped", store=True)
    
    adjustment_reference_id = fields.Many2one('stock.picking', string="Adjustment Referenced RR")
    is_relocation = fields.Boolean(string="Is Relocation")
    bf_pallet_char = fields.Char(string="Pallet # - Text", compute='_compute_bf_pallet_char', readonly=False, store=True) 
    is_blast_freeze = fields.Boolean(related="picking_id.x_studio_is_a_blast_freezer", string="Is a Blast Freeze Transaction")
    computed_quant_id = fields.Many2one('stock.quant', string="quant_id", compute="_computed_computed_quant_id")
    is_return = fields.Boolean(string="Is a Return")
    is_quant_detail_adjusted = fields.Boolean(string="Quant Details Edited")
    is_package_multiple_withdraw = fields.Boolean(
        string="Is Package In Multiple Transfers",
        compute="_compute_is_package_multiple_withdraw",
        store=False,
    )
    reserved_quantity_on_validation = fields.Float(string="Reserved Quantity on Validation")



        
    @api.depends('quant_id')
    def _compute_container_number(self):
        for record in self:
            if record['picking_code'] == 'outgoing' or not record['picking_code']:
                location = self.env['stock.location'].browse(record['location_id'].id)
                
                for quants in location.quant_ids:
                    if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                        record['x_studio_container_number'] = quants.x_studio_container_number
                        
                        
            else:
                record['x_studio_container_number'] = ''
    
            

    @api.depends('quant_id')
    def _compute_x_studio_building_dropped(self):
        for record in self:
            if record['picking_code'] == 'outgoing' or not record['picking_code']:
                location = self.env['stock.location'].browse(record['location_id'].id)
                
                for quants in location.quant_ids:
                    if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                        record['x_studio_building_dropped'] = quants.x_studio_building_dropped
                        record['original_record_reference'] = quants.original_record_reference
            else:
                record['x_studio_building_dropped'] = ''
                record['original_record_reference'] = False
        

    def get_second_top_parent(self, location_path):
        parts = location_path.split('/')
        if len(parts) >= 2:
            second_parent = parts[1]
            if second_parent == 'M':
                return 'M'
            elif second_parent == 'A':
                return 'A'
        return ''

    
    def build_adjustment_change_map(self, move_lines):
        """
        Build structured change data grouped by batch_number -> owner_id -> adjustment_reference_id -> timestamp.
        Returns:
            dict: {
                'batch_001': {
                    'Client A': {
                        'REF001': {
                            'reference_document_name': 'Reference Document Name',
                            'timestamps': {
                                'MM/DD/YY HH:MM:SS': [
                                    {
                                        'field': 'Product', 
                                        'old_value': 'Apple', 
                                        'new_value': 'Orange',
                                        'pallet_series_id': 'PALLET123'
                                    },
                                    ...
                                ],
                                ...
                            }
                        },
                        ...
                    },
                    ...
                },
                ...
            }
        """
        from collections import defaultdict
        import re
        
        # Create nested defaultdict structure
        result = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
            'reference_document_name': '',
            'timestamps': defaultdict(list)
        })))
    
        move_lines = move_lines.filtered(lambda l: l.is_quant_detail_adjusted)
    
        for line in move_lines:
            # Get grouping keys
            batch_number = line.adjustment_batch_number or 'Unknown Batch'
            client = line.owner_id.name or 'Unknown Client'
            reference_id = line.adjustment_reference_id.id if line.adjustment_reference_id else 'No Reference'
            reference_name = line.adjustment_reference_id.name if line.adjustment_reference_id else 'No Reference Document'
            pallet_series = line.x_studio_pallet_series_id or 'No Pallet'
            
            # Set reference document name (only needs to be set once per group)
            if not result[batch_number][client][reference_id]['reference_document_name']:
                result[batch_number][client][reference_id]['reference_document_name'] = reference_name
            
            # Parse reference field for changes
            ref = line.reference or ''
            matches = re.findall(r'CORRECTION \(([\d/ :]+) by [^)]+\):\s*((?:\[[^\]]+\]\s*)+)', ref)
    
            for timestamp, changes_str in matches:
                changes = re.findall(r'\[([^\]]+)\]', changes_str)
                for change in changes:
                    # Ex: "Product: Apple → Orange"
                    if '→' in change:
                        field, values = change.split(':', 1)
                        old, new = [v.strip() for v in values.split('→', 1)]
                        result[batch_number][client][reference_id]['timestamps'][timestamp].append({
                            'product_name': line.product_id.name,
                            'field': field.strip(),
                            'old_value': old,
                            'new_value': new,
                            'pallet_series_id': pallet_series,
                        })
    
        # Convert defaultdicts to regular dicts for easier template handling
        def convert_defaultdict(d):
            if isinstance(d, defaultdict):
                d = dict(d)
                for key, value in d.items():
                    d[key] = convert_defaultdict(value)
            return d
        
        return convert_defaultdict(result)

        
    @api.constrains('lot_id', 'product_id')
    def _check_lot_product(self):

        return
        # for line in self:
        #     if line.lot_id and line.product_id != line.lot_id.sudo().product_id:
        #         raise ValidationError(_(
        #             'This lot %(lot_name)s is incompatible with this product %(product_name)s',
        #             lot_name=line.lot_id.name,
        #             product_name=line.product_id.display_name
        #         ))

    @api.constrains('x_studio_2nd_uom', 'x_studio_total_units', 'x_studio_actual_min', 'x_studio_actual_packaging')
    def _check_whole_numbers(self):
        for record in self:
            if record.product_id:
                if isinstance(record.x_studio_2nd_uom, float) and not record.x_studio_2nd_uom.is_integer():
                    raise ValidationError("Please only enter whole numbers in Quantity UOM.")
                if isinstance(record.x_studio_total_units, float) and not record.x_studio_total_units.is_integer():
                    raise ValidationError("Please only enter whole numbers in Minimum UOM.")
                if isinstance(record.x_studio_actual_min, float) and not record.x_studio_actual_min.is_integer():
                    raise ValidationError("Please only enter whole numbers in Actual Minimum UOM.")
                if isinstance(record.x_studio_actual_packaging, float) and not record.x_studio_actual_packaging.is_integer():
                    raise ValidationError("Please only enter whole numbers in Actual Quantity UOM.")
                    
    @api.depends('quant_id')
    def _compute_bf_pallet_char(self):
        for record in self:
            if record.picking_code == 'outgoing' or not record.picking_code:
                location = self.env['stock.location'].browse(record.location_id.id)
                for quants in location.quant_ids:
                    if (
                        record.product_id.id == quants.product_id.id and
                        record.owner_id == quants.owner_id and
                        record.lot_id.id == quants.lot_id.id
                    ):
                        record.bf_pallet_char = quants.bf_pallet_char
                        break  # Optional: stops at first match
                else:
                    record.bf_pallet_char = ''
            else:
                record.bf_pallet_char = ''
    
    @api.depends('package_id', 'result_package_id')
    def _compute_is_package_multiple_withdraw(self):
        for line in self:
            # Skip computation if the record is not yet saved (i.e., has a temporary ID)
            if not isinstance(line.id, int):
                line.is_package_multiple_withdraw = False
                continue
    
            picking_id = line.picking_id
            is_blast_freeze, is_receiving = picking_id.operation_type_checker(picking_id.picking_type_id)
    
            if not is_receiving and not is_blast_freeze:
                if not line.package_id or not isinstance(line.package_id.id, int):
                    line.is_package_multiple_withdraw = False
                    continue
    
                # Count how many active move lines use this package
                package_count = self.env['stock.move.line'].search_count([
                    ('package_id', '=', line.package_id.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('id', '!=', line.id),  # Exclude self
                    ('picking_id', '!=', line.picking_id.id)
                ])
    
                line.is_package_multiple_withdraw = package_count > 0
    
            elif is_receiving:
                if not line.result_package_id or not isinstance(line.result_package_id.id, int):
                    line.is_package_multiple_withdraw = False
                    continue
    
                package_count = self.env['stock.move.line'].search_count([
                    ('result_package_id', '=', line.result_package_id.id),
                    ('id', '!=', line.id),  # Exclude current line
                    ('picking_id', '=', line.picking_id.id)
                ])
    
                line.is_package_multiple_withdraw = package_count > 0
    
            elif is_blast_freeze:
                line.is_package_multiple_withdraw = False

    
    @api.depends('lot_id')
    def _computed_computed_quant_id(self):
        for record in self:
            if record.lot_id:
                lots = self.env['stock.quant'].search([('lot_id', '=', record.lot_id.id)])
                record.computed_quant_id = lots[0] if lots else False
            else:
                record.computed_quant_id = False
    def unlink(self):
        # Get related stock moves before deleting move lines
        moves = self.mapped('move_id')

        # Proceed with the deletion
        res = super(stock_move_line_Override, self).unlink()



    
    
    @api.onchange('result_package_id')        
    def assign_pallet_series_on_already_used_pallets(self):
        picking_id = self.picking_id.id
        owner = self.owner_id.name
    
        for record in self:
            if record.picking_type_id and record.picking_id.picking_type_code == 'incoming' and record.result_package_id and record.product_id:
                # Exclude the current record ID to avoid self-inclusion in search results
                self_id = self.extract_id_from_newid(record.id)
                previous_location = record._origin.location_dest_id
    
                # Search for move lines with the same picking and result package, having a non-empty pallet series
                move_line_ids = self.env['stock.move.line'].search([
                    ('picking_id', '=', record.picking_id.id),
                    ('result_package_id', '=', record.result_package_id.id),
                    ('x_studio_pallet_series_id', '!=', False)
                ], limit=1)
                
                # Check for unmatched result packages and pallet series
                unmatched_package = self._get_unmatched_ids(picking_id, 'result_package_id')
                unmatched_pallet_series = self._get_unmatched_ids(picking_id, 'x_studio_pallet_series_id')

                
                if unmatched_package and (not unmatched_pallet_series or False in unmatched_pallet_series):
                    reuse_recycle = record.owner_id.get_smallest_pallet_series_ids(1)
                    if reuse_recycle and not unmatched_pallet_series:
                        for pallet_id in reuse_recycle:
                            
                            record.location_dest_id = self.env['stock.location'].browse(record.x_studio_initial_location)
                            record.x_studio_pallet_series_id = pallet_id
                            
                    else:
  
                        if not unmatched_pallet_series or (not unmatched_pallet_series or False in unmatched_pallet_series):
                            record.x_studio_pallet_series_id = f"{record.owner_id.x_studio_client_unique_code_1}-{record.owner_id.x_studio_pallet_series_id}"
                            temp_series_id = int(record.owner_id.x_studio_pallet_series_id) + 1
                            record.owner_id.x_studio_pallet_series_id = temp_series_id
    

                            

                # Update location and pallet series based on matched move lines
                if move_line_ids and not move_line_ids.location_dest_id.child_ids:
                    # Unreserve the current location
                    record.location_dest_id.x_studio_is_reserved = False
    
                    # Check if other move lines are using the previous location
                    move_lines = self.env['stock.move.line'].search([
                        ('picking_id', '=', record.picking_id.id),
                        ('location_dest_id', '=', previous_location.id),
                        ('id', '!=', self_id)
                    ])
    
                    # Unreserve previous location if no other move lines use it
                    if previous_location and not move_lines:
                        previous_location.write({
                            'x_studio_is_reserved': False,
                            'x_studio_receiving_report_id': False,
                        })
    
                    # Push unused pallet series if unmatched pallet series exist
                    if record._origin.x_studio_pallet_series_id and unmatched_pallet_series:
                        record.owner_id.push_unused_pallet(record._origin.x_studio_pallet_series_id)
    
                    # Assign location and pallet series from the matched move line
                    record.location_dest_id = move_line_ids.location_dest_id
                    record.x_studio_pallet_series_id = move_line_ids.x_studio_pallet_series_id
                    

                # _logger.info(f"Test Location{record.location_dest_id.id}")


        
    @api.onchange('location_dest_id')
    def unreserve_onchange_location(self):
        for record in self:
            
            if record.product_id:
                
                previous_location = record._origin.location_dest_id if record._origin else None
                report_id = record.picking_id.id
                picking_id = self[0].picking_id.id
                self_id = self.extract_id_from_newid(record.id)
                unmatched_locations = self._get_unmatched_ids(picking_id, 'location_dest_id.id')
                unmatched_package = self._get_unmatched_ids(picking_id, 'result_package_id.id')
                location = self.location_dest_id
                
                if not unmatched_locations and unmatched_package and not location.x_studio_is_an_aisle and self.location_dest_id:
                    # raise UserError(f"Please set locations First")
                    raise UserError(f"{self.location_dest_id.complete_name} can't have two or more pallets")

                # raise UserError(self_id)
                if self_id:
                    # Check if others are still using the location
                    move_lines = self.env['stock.move.line'].search([
                        ('picking_id', '=', report_id), 
                        ('location_dest_id', '=', previous_location.id), 
                        ('id', '!=', self_id)
                    ])

                    # Reserve the new location
                    if not record.location_dest_id.child_ids or not record.location_dest_id.x_studio_receiving_report_id and record.picking_type_id and record.picking_id.picking_type_code == 'incoming':
                        
                        if record.location_dest_id and not record.location_dest_id.child_ids and not record.location_dest_id.x_studio_is_an_aisle:
                            # raise UserError("Eh")
                            record.location_dest_id.write({
                                'x_studio_is_reserved': True,
                                'x_studio_receiving_report_id': report_id,
                            })
                    else:
                        raise UserError("Oops, it seems like someone already reserved the location. Please select another location.")    
                        
                    # Remove reservation from previous location if no other moves are using it
                    
                    if previous_location and not move_lines:

                        previous_location.write({
                            'x_studio_is_reserved': False,
                            'x_studio_receiving_report_id': False,
                        })
                else:

                    # Check if others are still using the location
                    # move_lines = self.env['stock.move.line'].search([
                    #     ('picking_id', '=', report_id), 
                    #     # ('location_dest_id', '=', previous_location.id), 
                    #     # ('id', '!=', self_id)
                    # ])

                    # Reserve the new location
                    if not record.location_dest_id.child_ids or not record.location_dest_id.x_studio_receiving_report_id and record.picking_type_id and record.picking_id.picking_type_code == 'incoming':
                        
                        if record.location_dest_id and not record.location_dest_id.child_ids and not record.location_dest_id.x_studio_is_an_aisle:
                            # raise UserError("Eh")
                            record.location_dest_id.write({
                                'x_studio_is_reserved': True,
                                'x_studio_receiving_report_id': report_id,
                            })
                    else:
                        raise UserError("Oops, it seems like someone already reserved the location. Please select another location.")    

            


    @api.onchange('result_package_id')
    def unreserve_onchange_pallet(self):

        for record in self:
            if record.product_id:
                previous_pallet = record._origin.result_package_id if record._origin else None
                report_id = record.picking_id.id
                self_id = self.extract_id_from_newid(record.id)
                if self_id:
                    # Check if others are still using the pallet
                    move_lines = self.env['stock.move.line'].search([
                        ('picking_id', '=', report_id), 
                        ('result_package_id', '=', previous_pallet.id), 
                        ('id', '!=', self_id)
                    ])

                    # Reserve the new pallet
                    if not record.result_package_id.x_studio_receiving_report_id or record.picking_id.id == record.result_package_id.x_studio_receiving_report_id.id and record.picking_type_id and record.picking_id.picking_type_code == 'incoming' and not record.location_dest_id.x_studio_is_an_aisle:
                        if record.result_package_id:
                            record.result_package_id.write({
                                'x_studio_is_reserved': True,
                                'x_studio_receiving_report_id': report_id,
                            })
                    else:
                        raise UserError("Oops, it seems like someone already reserved the pallet. Please select another pallet.")
                        
                    # Remove reservation from previous pallet if no other moves are using it
                    if previous_pallet and not move_lines:
                        previous_pallet.write({
                            'x_studio_is_reserved': False,
                            'x_studio_receiving_report_id': False,
                        })
 

    @api.ondelete(at_uninstall=True)
    def unreserve_ondelete_location(self):

        # Get the picking_id from the first record (all should have the same picking_id)
        if self[0].picking_type_id and self[0].picking_id.picking_type_code == 'incoming':
            
            picking_id = self[0].picking_id.id
            owner = self[0].owner_id.name

            # Get unmatched locations and unmatched pallet series
            unmatched_locations = self._get_unmatched_ids(picking_id, 'location_dest_id.id')
            unmatched_pallet_series = self._get_unmatched_ids(picking_id, 'x_studio_pallet_series_id')
            unmatched_package = self._get_unmatched_ids(picking_id, 'result_package_id.id')

            #Todo, consider if has unmatch
            
            for pallet_series in unmatched_pallet_series:
                if pallet_series:
                    self[0].owner_id.push_unused_pallet(pallet_series)
    
    
            # Update locations if unmatched locations exist
            if unmatched_locations:
                self.env['stock.location'].browse(unmatched_locations).write({
                    'x_studio_is_reserved': False,
                    'x_studio_receiving_report_id': ''
                })
    
            if unmatched_package:
                test = self.env['stock.quant.package'].browse(unmatched_package)
                self.env['stock.quant.package'].browse(unmatched_package).write({
                    'x_studio_is_reserved': False,
                    'x_studio_receiving_report_id': ''
                })


        
    def _get_unmatched_ids(self, picking_id, field_name):
        # Get all ids from selected records
        selected_ids = self.mapped(field_name)
        
        # Get all ids from unselected move lines related to the same picking
        unselected_ids = self.env['stock.move.line'].search([
            ('picking_id', '=', picking_id),
            ('id', 'not in', self.ids)
        ]).mapped(field_name)
    
        # Find ids in selected that do not have a match in unselected
        unmatched_ids = set(selected_ids) - set(unselected_ids)
        
        return unmatched_ids


                        
    def extract_id_from_newid(self, newid):

        
        # Already an integer
        if isinstance(newid, int):
            return newid
            
        # Ensure that newid is a string before processing below
        newid = str(newid)
        # Check if the string starts with "NewId_"
        if newid[:6] == "NewId_":
            # Return false because its an memory address
            if len(newid[6:]) > 13:
                return False

            # Extract the numeric part after "NewId_"
            # Start from index 6 to skip "NewId_"
            return int(newid[6:])
        else:
            raise ValueError(f"Invalid NewId format: {newid}")




    def sort_by_batch(self):
        sorted_docs = sorted(self, key=lambda line: (line.x_relocate_batch, line.owner_id.name))
        return sorted_docs

    def group_by_batch_and_owner(self):
        # First, sort the records using the existing sort_by_batch logic
        sorted_docs = self.sort_by_batch()
        
        # Initialize variables for grouping
        groups = []
        current_batch = None
        current_owner = None
        group_lines = []
    
        for line in sorted_docs:
            if current_batch is None:
                current_batch = line.x_relocate_batch
                current_owner = line.owner_id
            
            # Check if the current line belongs to the same batch and owner
            if line.x_relocate_batch != current_batch or line.owner_id != current_owner:
                # Save the current group and reset variables
                groups.append({
                    'batch': current_batch,
                    'owner': current_owner,
                    'lines': group_lines,
                })
                group_lines = []
                current_batch = line.x_relocate_batch
                current_owner = line.owner_id
            
            # Add the current line to the group
            group_lines.append(line)
    
        # Append the last group
        if group_lines:
            groups.append({
                'batch': current_batch,
                'owner': current_owner,
                'lines': group_lines,
            })
        
        return groups

    

    
    @api.onchange('x_studio_expiration_date')
    def onchange_expiry_date(self):
        for record in self:
            if not record.x_studio_expiration_date or record.picking_id.picking_type_code != 'incoming':
                continue
    
            product = record.product_id
            today = fields.Date.today()
            warning = None
    
            # Retrieve expiration rules for the product
            expiry_rules = product.client_expiry_table_ids.filtered(
                lambda r: record.owner_id in r.partner_ids
            )
    
            if not expiry_rules:
                # Fallback: Global Config
                global_config_expiry = self.env['x_inventory_static_var'].search([
                    ('x_studio_warehouse.id', '=', record.owner_id.x_studio_warehouse.id),
                    ('x_name', 'ilike', 'Global Acceptable Expiry Range')
                ], limit=1)
    
                fallback_days = 15  # Default if no config or invalid
                if global_config_expiry and isinstance(global_config_expiry.x_studio_float_value, (int, float)):
                    fallback_days = global_config_expiry.x_studio_float_value
    
                acceptable_date = today + timedelta(days=fallback_days)
    
                if record.x_studio_expiration_date < acceptable_date:
                    warning = {
                        'title': "Expiration Threshold Warning!",
                        'message': (
                            f"\nExpiration date is outside the acceptable {int(fallback_days)}-day global threshold.\n\n"
                            f"Entered Expiration Date: {record.x_studio_expiration_date.strftime('%B %d, %Y')}\n"
                            f"Minimum Acceptable Date: {acceptable_date.strftime('%B %d, %Y')}"
                        ),
                    }
            else:
                current_variants = product.product_template_variant_value_ids.mapped('name') or [product.name]
                product_brand_expiry = expiry_rules.mapped('line_attribute_value_ids.name')
    
                for line in expiry_rules:
                    not_acceptable = today + timedelta(days=line.expiry_date_range_id.x_studio_float_value)
                    if (record.x_studio_expiration_date < not_acceptable and
                        (not product_brand_expiry or any(variant in product_brand_expiry for variant in current_variants))):
                        warning = {
                            'title': "Expiration Threshold Warning!",
                            'message': (
                                f"\nExpiration date is outside the acceptable expiration date range. "
                                f"Please review the Product.\n\n"
                                f"Entered Expiration Date: {record.x_studio_expiration_date.strftime('%B %d, %Y')}\n"
                                f"Acceptable Expiration Date Range: {not_acceptable.strftime('%B %d, %Y')}"
                            ),
                        }
                        break
    
            if warning:
                return {'warning': warning}




    def expiry_date_range_checker(self):
        for record in self:
            if not record.x_studio_expiration_date or not record.product_id or record.picking_id.picking_type_code != 'incoming':
                continue
    
            product = record.product_id
            template = product.product_tmpl_id
            today = fields.Date.today()
    
            # Determine if the product has variant values
            variant_names = product.product_template_variant_value_ids.mapped('name') or [product.name]
    
            # Access the proper expiry table lines
            expiry_lines = product.client_expiry_table_ids or template.client_expiry_table_ids
            matching_lines = expiry_lines.filtered(lambda line: record.owner_id in line.partner_ids)
            product_brand_expiry = matching_lines.mapped('line_attribute_value_ids.name')
    
            # Case 1: Partner-specific expiry lines exist
            if matching_lines:
                for line in matching_lines:
                    not_acceptable = today + timedelta(days=line.expiry_date_range_id.x_studio_float_value)
                    if (record.x_studio_expiration_date < not_acceptable and
                        (not product_brand_expiry or any(name in product_brand_expiry for name in variant_names))):
                        return True  # Not acceptable
            else:
                # Case 2: No matching line — fallback to global expiry threshold
                global_config_expiry = self.env['x_inventory_static_var'].search([
                    ('x_studio_warehouse.id', '=', record.owner_id.x_studio_warehouse.id),
                    ('x_name', 'ilike', 'Global Acceptable Expiry Range')
                ], limit=1)
    
                fallback_days = global_config_expiry.x_studio_float_value if global_config_expiry else 15
                acceptable_date = today + timedelta(days=fallback_days)
    
                if record.x_studio_expiration_date < acceptable_date:
                    return True  # Not acceptable by global rule
    
            return False  # Acceptable
    
        

    
    
    @api.depends('move_id', 'move_id.location_id', 'move_id.location_dest_id', 'result_package_id')
    def _compute_location_id(self):
        for line in self:
            if not line.location_id:
                line.location_id = line.move_id.location_id or line.picking_id.location_id
            if not line.location_dest_id:
                line.location_dest_id = line.move_id.location_dest_id or line.picking_id.location_dest_id
            if line.result_package_id.location_id:
                line.location_dest_id = line.result_package_id.location_id

    @api.model
    def call_server_action(self, action_type):
        picking_id = self.env.context.get('default_picking_id')
        if not picking_id:
            raise UserError(_("No picking ID found in context."))

        # Search for the stock.picking record using the provided picking_id
        picking = self.env['stock.picking'].search([('id', '=', picking_id)], limit=1)
        if not picking:
            raise UserError(_("No stock.picking record found with ID %s.") % picking_id)

        # Map action types to their respective server action IDs
        action_ids = {
            'auto_fill_pd_ed': 341,
            'auto_fill_locations': 300,
            'reserve_locations': 301,
            'unreserve_locations': 302,
            'reserve_pallets': 338,
            'assign_pallet_series': 347,
            'verify_pallet_lines': 348
        }

        # Get the action ID based on the action_type parameter
        action_id = action_ids.get(action_type)
        if action_id is None:
            raise UserError(_("Invalid action type: %s") % action_type)

        # Find the server action using the mapped ID
        action = self.env['ir.actions.server'].browse(action_id)
        if not action:
            raise UserError(_("Server action with ID %s not found.") % action_id)

        # Prepare context for executing the action
        context = {
            'active_model': 'stock.picking',
            'active_ids': [picking.id],
            'active_id': picking.id,
        }

        return action.with_context(context).run()

    def call_server_action_auto_fill_pd_ed(self):
        return self.call_server_action('auto_fill_pd_ed')

    def call_server_action_auto_fill_locations(self):
        return self.call_server_action('auto_fill_locations')

    def call_server_action_reserve_locations(self):
        return self.call_server_action('reserve_locations')

    def call_server_action_unreserve_locations(self):
        return self.call_server_action('unreserve_locations')
        
    def call_server_action_reserve_pallets(self):
        return self.call_server_action('reserve_pallets')
    def call_server_action_assign_pallet_series(self):
        return self.call_server_action('assign_pallet_series')
    def call_server_action_verify_pallet_series(self):
        return self.call_server_action('verify_pallet_lines')




    
    
    # Add these methods to your model class
    
    
    def old_rr_quantity(self, doc):
        """
        Returns the original packaging quantity from the reference document
        """
        record = self.env['stock.picking'].search([('name', '=', doc)])
        return record.total_quantity or 0

    
    def old_rr_weight(self, doc):
        """
        Returns the original weight from the reference document
        """
        record = self.env['stock.picking'].search([('name', '=', doc)])
        return record.total_weight or 0

    
    def get_adjustment_totals(self, batch_number):
        """
        Calculate total adjustments for packaging quantity and weight for a specific batch
        Returns a dictionary with packaging_total and weight_total
        """
        # Get all documents in the batch
        batch_docs = self.search([('adjustment_batch_number', '=', batch_number)])
        
        packaging_total = 0
        weight_total = 0
        
        # Build the adjustment change map for this batch
        grouped_changes = self.build_adjustment_change_map(batch_docs)
        
        if batch_number in grouped_changes:
            for client_name, references in grouped_changes[batch_number].items():
                for reference_id, reference_info in references.items():
                    for timestamp, changes in reference_info['timestamps'].items():
                        for change in changes:
                            if change['field'] == 'Packaging Quantity':
                                old_val = float(change['old_value'] or 0)
                                new_val = float(change['new_value'] or 0)
                                packaging_total += (new_val - old_val)
                            elif change['field'] == 'Weight (KG)':
                                old_val = float(change['old_value'] or 0)
                                new_val = float(change['new_value'] or 0)
                                weight_total += (new_val - old_val)
        
        return {
            'packaging_total': packaging_total,
            'weight_total': weight_total
        }
    
    def has_packaging_or_weight_adjustments(self, batch_number):
        """
        Check if the batch has any packaging quantity or weight adjustments
        Returns a dictionary indicating which types of adjustments exist
        """
        batch_docs = self.search([('adjustment_batch_number', '=', batch_number)])
        grouped_changes = self.build_adjustment_change_map(batch_docs)
        
        has_packaging = False
        has_weight = False
        
        if batch_number in grouped_changes:
            for client_name, references in grouped_changes[batch_number].items():
                for reference_id, reference_info in references.items():
                    for timestamp, changes in reference_info['timestamps'].items():
                        for change in changes:
                            if change['field'] == 'Packaging Quantity':
                                has_packaging = True
                            elif change['field'] == 'Weight (KG)':
                                has_weight = True
        
        return {
            'has_packaging_changes': has_packaging,
            'has_weight_changes': has_weight
        }












# from odoo import models, fields, api
# from odoo.exceptions import ValidationError, UserError
# from datetime import datetime, timedelta
# import logging
# _logger = logging.getLogger(__name__)

# class PalletKilosRecordModel(models.Model):
#     _name = 'pallet_kilos_record_model.pallet_kilos_record_model'
#     _description = 'Pallet Kilos Record Model'
#     _order = 'end_time asc, id asc'  # Critical for running balance
    
#     # Basic identification fields
#     report_no = fields.Char(string="Report No.", readonly=True)
#     owner_id = fields.Many2one('res.partner', 'Owner', ondelete='set null', readonly=True, index=True)
#     warehouse = fields.Many2one('stock.warehouse', 'Warehouse', ondelete='set null', readonly=True, index=True)
#     record_reference = fields.Many2one('stock.picking', 'Record Reference', store=True, ondelete='set null', 
#                                       readonly=True, index=True)

#     remarks = fields.Char(string="Remarks", readonly=True)
#     active = fields.Boolean(string="active", default=True)
#     # Adjusted document - this replaces the original reference for computations
#     readjustment_document = fields.Many2one('stock.picking', string="Adjusted Document Reference", 
#                                           ondelete='set null', readonly=True, index=True,
#                                           help="When set, this document replaces the original reference for all calculations")
    
#     # Effective document - computed field that returns either adjusted or original reference
#     effective_document = fields.Many2one('stock.picking', string="Effective Document", 
#                                        compute='_compute_effective_document', store=True,
#                                        help="The document used for all calculations (adjusted if available, otherwise original)")
#     operation_type_id = fields.Many2one(string="Operation Type", related="effective_document.picking_type_id", store=True)
    
#     # Storage operation fields - these will be populated directly, not computed
#     pallets_received = fields.Float(store=True, string="Pallets Received", readonly=True)
#     pallets_withdrawn = fields.Float(store=True, string="Pallets Withdrawn", readonly=True)
#     kilos_received = fields.Float(store=True, string="Kilos Received", readonly=True)
#     kilos_withdrawn = fields.Float(store=True, string="Kilos Withdrawn", readonly=True)
    
#     # Operation fields - stored, not computed
#     packaging_received = fields.Float(string="Packaging Received", readonly=True, store=True)
#     packaging_withdrawn = fields.Float(string="Packaging Withdrawn", readonly=True, store=True)
#     units_received = fields.Float(string="Units Received", readonly=True, store=True)
#     units_withdrawn = fields.Float(string="Units Withdrawn", readonly=True, store=True)

#     # Balance fields - stored, calculated via method calls
#     total_balance_in_units = fields.Float(store=True, string="Total Balance in Packs", readonly=True, group_operator=False)
#     total_balance_in_packaging = fields.Float(store=True, string="Total Balance in Quantity", readonly=True, group_operator=False)
#     total_balance_in_kilos = fields.Float(store=True, string="Total Balance in Kilos (KG)", readonly=True, group_operator=False)
#     total_balance_in_pallets = fields.Float(store=True, string="Total Balance in Pallets", readonly=True, group_operator=False)

#     # Return fields - stored, not computed
#     return_id = fields.Many2one('stock.picking', readonly=True, string="Return RR ID")
#     return_heads = fields.Float(string="Total Return Units", readonly=True)
#     return_packaging = fields.Float(string="Total Return Packaging", readonly=True)
#     return_pallets = fields.Float(string="Total Return Pallets", readonly=True)
#     return_kilos = fields.Float(string="Total Return Kilos", readonly=True)

#     adjustment_heads = fields.Float(string="Total Adjustment Units")
#     adjustment_packaging = fields.Float(string="Total Adjustment Packaging", readonly=True)
#     adjustment_pallets = fields.Float(string="Total Adjustment Pallets", readonly=True)
#     adjustment_kilos = fields.Float(string="Total Adjustment Kilos", readonly=True)

    
#     # Beginning balance fields - stored, calculated via method calls
#     beginning_balance_in_pallets = fields.Float(string="Beginning Balance in Pallets", readonly=True, store=True)
#     beginning_balance_in_kilos = fields.Float(string="Beginning Balance in Kilos", readonly=True, store=True)
    
#     # Rate fields
#     holding_rate = fields.Float(string='Holding Rate', related='owner_id.x_studio_holding_rate', store=True)
#     handling_rate = fields.Float(string='Handling Rate', related='owner_id.x_studio_handling_rate', store=True)
    
#     # Vehicle fields - stored
#     truck_type = fields.Selection(
#         selection=[
#             ('4wheeler', '4 Wheeler'),
#             ('6wheeler', '6 Wheeler'),
#             ('10wheeler', '10 Wheeler'),
#             ('20ft_container', '20ft Container'),
#             ('40ft_container', '40ft Container'),
#             ('N/A', 'N/A')
#         ],
#         string="Truck Type", readonly=True, store=True
#     )
#     trucks_plate = fields.Char(string="Truck's Plate #", readonly=True, store=True)
#     gate_pass = fields.Char(string="Gate Pass #", readonly=True, store=True)
#     start_time = fields.Datetime(string="Start Time", readonly=True, store=True, index=True)  # INDEX IS CRITICAL
#     end_time = fields.Datetime(string="End Time", readonly=True, store=True)
    
#     # Maximum values
#     max_pallets = fields.Many2one('x_inventory_static_var', 'Max Pallets', 
#                                  default=lambda self: self._get_static_var('Max Pallets'))
#     max_kg = fields.Many2one('x_inventory_static_var', 'Max Kilograms', 
#                            default=lambda self: self._get_static_var('Max Kilograms'))

#     # Running balance fields - stored, not computed
#     overall_pallets = fields.Float(string='Overall Pallets', store=True, group_operator=False)
#     overall_kilos = fields.Float(string='Overall Kilos', store=True, group_operator=False)
    
#     # Add blast freezer flag for efficient filtering
#     is_blast_freezer = fields.Boolean(string="Is Blast Freezer", store=True, index=True)

#     @api.model
#     def _get_static_var(self, var_name):
#         """Get static variable from inventory_static_var model by name"""
#         return self.env['x_inventory_static_var'].search([
#             ('x_studio_use_case', '=', 'XLSX Variables'),
#             ('x_name', 'ilike', var_name)
#         ], limit=1)

#     @api.depends('record_reference', 'readjustment_document')
#     def _compute_effective_document(self):
#         """Compute the effective document to use for calculations"""
#         for record in self:
#             record.effective_document = record.readjustment_document or record.record_reference

#     def _populate_operations_data(self):
#         """Populate operation data from effective document - called explicitly, not computed"""
#         for record in self:
#             if not record.effective_document:
#                 continue
                
#             units_received = 0
#             units_withdrawn = 0
#             packaging_received = 0
#             packaging_withdrawn = 0
#             kilos_received = 0
#             kilos_withdrawn = 0
#             pallets = set()
#             pallet_count = 0
            
#             # Get move lines data from effective document
#             for line in record.effective_document.move_ids_without_package:
#                 units_received += line.x_studio_min_actual_demand
#                 packaging_received += line.x_studio_actual_packaging_demand
#                 units_withdrawn += line.x_studio_min_actual_demand
#                 packaging_withdrawn += line.x_studio_actual_packaging_demand
#                 kilos_received += line.quantity
#                 kilos_withdrawn += line.quantity

#             # Count unique pallets
#             if record.effective_document.picking_type_code in ['outgoing']:
#                 for move_line in record.effective_document.move_line_ids:
#                     if move_line.picking_id.x_studio_is_a_blast_freezer:
#                         if move_line.bf_pallet_char not in pallets:
#                             pallet_count += 1
#                             pallets.add(move_line.bf_pallet_char)
#                     else:
#                         if move_line.package_id and move_line.package_id.id not in pallets:
#                             if move_line.package_id.x_studio_total_quantity == 0:
#                                 pallet_count += 1
#                                 pallets.add(move_line.package_id.id)
#             else:
#                 for move_line in record.effective_document.move_line_ids:
#                     if move_line.picking_id.x_studio_is_a_blast_freezer:
#                         if move_line.bf_pallet_char not in pallets:
#                             pallet_count += 1
#                             pallets.add(move_line.bf_pallet_char)
#                     else:
#                         if move_line.result_package_id and move_line.result_package_id.id not in pallets:
#                             pallet_count += 1
#                             pallets.add(move_line.result_package_id.id)
                    
#             # Set values based on picking type
#             picking_code = record.effective_document.picking_type_id.code
            
#             if picking_code == 'incoming':
#                 record.write({
#                     'units_received': units_received,
#                     'packaging_received': packaging_received,
#                     'kilos_received': kilos_received,
#                     'pallets_received': pallet_count,
#                     'units_withdrawn': 0,
#                     'packaging_withdrawn': 0,
#                     'kilos_withdrawn': 0,
#                     'pallets_withdrawn': 0,
#                     'is_blast_freezer': record.effective_document.x_studio_is_a_blast_freezer or False
#                 })
#             elif picking_code == 'outgoing':
#                 record.write({
#                     'units_withdrawn': units_withdrawn,
#                     'packaging_withdrawn': packaging_withdrawn,
#                     'kilos_withdrawn': kilos_withdrawn,
#                     'pallets_withdrawn': pallet_count,
#                     'units_received': 0,
#                     'packaging_received': 0,
#                     'kilos_received': 0,
#                     'pallets_received': 0,
#                     'is_blast_freezer': record.effective_document.x_studio_is_a_blast_freezer or False
#                 })

#     def _populate_returns_data(self):
#         """Populate return data from effective document - called explicitly"""
#         for record in self:
#             if not record.effective_document:
#                 continue
                
#             return_heads = 0
#             return_packaging = 0
#             return_pallets = 0
#             return_kilos = 0
#             return_id = False
#             pallets = set()

#             for returns in record.effective_document.return_ids:
#                 if returns.state == 'done' and returns.return_reason == 'Partial Withdraw' and not returns.x_studio_voided:
#                     return_id = returns.id
#                     for line_ids in returns.move_line_ids:
#                         return_heads += line_ids.x_studio_total_units
#                         return_packaging += line_ids.x_studio_2nd_uom
#                         return_kilos += line_ids.quantity
#                         if line_ids.result_package_id and line_ids.result_package_id.id not in pallets:
#                             return_pallets += 1
#                             pallets.add(line_ids.result_package_id.id)
#                     break

#             record.write({
#                 'return_id': return_id,
#                 'return_heads': return_heads,
#                 'return_packaging': return_packaging,
#                 'return_pallets': return_pallets,
#                 'return_kilos': return_kilos,
#             })

#     def _populate_vehicle_data(self):
#         """Populate vehicle data from effective document"""
#         for record in self:
#             if record.effective_document:
#                 record.write({
#                     'truck_type': record.effective_document.truck_type,
#                     'trucks_plate': record.effective_document.x_studio_trucks_plate_,
#                     'gate_pass': record.effective_document.x_studio_gate_pass,
#                     'start_time': record.effective_document.x_studio_start_time,
#                     'end_time': record.effective_document.x_studio_end_time,
#                 })


#     def _recalculate_running_balances(self, warehouse_id, blast_freezer_flag, from_datetime=None):
#         """
#         Efficiently recalculate running balances for all records in a warehouse after a given datetime
#         - overall_* fields: warehouse-wide totals (all owners)
#         - total_balance_* and beginning_balance_* fields: per owner
#         """
#         domain = [
#             ('warehouse', '=', warehouse_id),
#             ('is_blast_freezer', '=', blast_freezer_flag),
#         ]
        
#         if from_datetime:
#             domain.append(('start_time', '>=', from_datetime))
        
#         # Get all affected records in chronological order
#         records_to_update = self.search(domain, order='start_time asc, id asc')
        
#         if not records_to_update:
#             return
        
#         # Get the previous warehouse-wide balance (for overall_* fields)
#         if from_datetime:
#             prev_warehouse_record = self.search([
#                 ('warehouse', '=', warehouse_id),
#                 ('is_blast_freezer', '=', blast_freezer_flag),
#                 ('start_time', '<', from_datetime)
#             ], order='start_time desc, id desc', limit=1)
            
#             if prev_warehouse_record:
#                 running_pallets = prev_warehouse_record.overall_pallets
#                 running_kilos = prev_warehouse_record.overall_kilos
#             else:
#                 running_pallets = running_kilos = 0
#         else:
#             running_pallets = running_kilos = 0

#         # Track per-owner balances
#         owner_balances = {}
        
#         # Get previous balances for each owner
#         if from_datetime:
#             # Get the last record for each owner before from_datetime
#             owners_in_scope = records_to_update.mapped('owner_id')
#             for owner in owners_in_scope:
#                 if not owner:
#                     continue
                    
#                 prev_owner_record = self.search([
#                     ('warehouse', '=', warehouse_id),
#                     ('is_blast_freezer', '=', blast_freezer_flag),
#                     ('owner_id', '=', owner.id),
#                     ('start_time', '<', from_datetime)
#                 ], order='start_time desc, id desc', limit=1)
                
#                 if prev_owner_record:
#                     owner_balances[owner.id] = {
#                         'total_pallets': prev_owner_record.total_balance_in_pallets,
#                         'total_kilos': prev_owner_record.total_balance_in_kilos,
#                         'total_units': prev_owner_record.total_balance_in_units,
#                         'total_packaging': prev_owner_record.total_balance_in_packaging,
#                     }
#                 else:
#                     owner_balances[owner.id] = {
#                         'total_pallets': 0,
#                         'total_kilos': 0,
#                         'total_units': 0,
#                         'total_packaging': 0,
#                     }
#         else:
#             # Initialize all owner balances to 0
#             owners_in_scope = records_to_update.mapped('owner_id')
#             for owner in owners_in_scope:
#                 if owner:
#                     owner_balances[owner.id] = {
#                         'total_pallets': 0,
#                         'total_kilos': 0,
#                         'total_units': 0,
#                         'total_packaging': 0,
#                     }
    
#         # Batch update all records
#         updates = []
#         for record in records_to_update:
#             # Calculate warehouse-wide running totals (overall_* fields) including adjustments
#             running_pallets += (record.pallets_received - record.pallets_withdrawn + record.adjustment_pallets)
#             running_kilos += (record.kilos_received - record.kilos_withdrawn + record.adjustment_kilos)
            
#             # Calculate per-owner balance totals
#             if not record.owner_id:
#                 # Skip records without owner
#                 updates.append({
#                     'id': record.id,
#                     'overall_pallets': running_pallets,
#                     'overall_kilos': running_kilos,
#                     'beginning_balance_in_pallets': 0,
#                     'beginning_balance_in_kilos': 0,
#                     'total_balance_in_units': 0,
#                     'total_balance_in_packaging': 0,
#                     'total_balance_in_kilos': 0,
#                     'total_balance_in_pallets': 0,
#                 })
#                 continue
                
#             owner_id = record.owner_id.id
            
#             # Store beginning balance (before this record's operation)
#             beginning_pallets = owner_balances[owner_id]['total_pallets']
#             beginning_kilos = owner_balances[owner_id]['total_kilos']
            
#             # Calculate new balance totals for this owner including adjustments
#             # Handle opening balance records (no effective_document)
#             if not record.effective_document and record.remarks == 'imported via opening balance':
#                 # For opening balance, use the received amounts directly
#                 owner_balances[owner_id]['total_packaging'] += record.packaging_received
#                 owner_balances[owner_id]['total_units'] += record.units_received
#                 owner_balances[owner_id]['total_kilos'] += record.kilos_received
#                 owner_balances[owner_id]['total_pallets'] += record.pallets_received
#             # Calculate new balance totals for this owner including adjustments
#             elif record.effective_document and record.effective_document.picking_type_id.code == 'outgoing':
#                 owner_balances[owner_id]['total_packaging'] -= record.packaging_withdrawn
#                 owner_balances[owner_id]['total_units'] -= record.units_withdrawn
#                 owner_balances[owner_id]['total_kilos'] -= record.kilos_withdrawn
#                 owner_balances[owner_id]['total_pallets'] -= record.pallets_withdrawn
#             elif record.effective_document and record.effective_document.picking_type_id.code == 'incoming':
#                 owner_balances[owner_id]['total_packaging'] += record.packaging_received
#                 owner_balances[owner_id]['total_units'] += record.units_received
#                 owner_balances[owner_id]['total_kilos'] += record.kilos_received
#                 owner_balances[owner_id]['total_pallets'] += record.pallets_received
                
#             # Apply adjustments to owner balances
#             owner_balances[owner_id]['total_packaging'] += record.adjustment_packaging
#             owner_balances[owner_id]['total_units'] += record.adjustment_heads
#             owner_balances[owner_id]['total_kilos'] += record.adjustment_kilos
#             owner_balances[owner_id]['total_pallets'] += record.adjustment_pallets
    
#             updates.append({
#                 'id': record.id,
#                 'overall_pallets': running_pallets,
#                 'overall_kilos': running_kilos,
#                 'beginning_balance_in_pallets': beginning_pallets,
#                 'beginning_balance_in_kilos': beginning_kilos,
#                 'total_balance_in_units': owner_balances[owner_id]['total_units'],
#                 'total_balance_in_packaging': owner_balances[owner_id]['total_packaging'],
#                 'total_balance_in_kilos': owner_balances[owner_id]['total_kilos'],
#                 'total_balance_in_pallets': owner_balances[owner_id]['total_pallets'],
#             })
    
#         # Batch write all updates
#         for update in updates:
#             record_id = update.pop('id')
#             self.browse(record_id).write(update)

#     @api.model
#     def create(self, vals):
#         """Override create to handle backdated insertions"""
#         record = super(PalletKilosRecordModel, self).create(vals)
        
#         # Populate all data first
#         record._populate_vehicle_data()
#         record._populate_operations_data()
#         record._populate_returns_data()
        
#         # Check if this is a backdated insertion
#         if record.start_time and record.warehouse:
#             later_records = self.search([
#                 ('warehouse', '=', record.warehouse.id),
#                 ('is_blast_freezer', '=', record.is_blast_freezer),
#                 ('start_time', '>', record.start_time),
#                 ('id', '!=', record.id)
#             ], limit=1)
            
#             if later_records:
#                 # This is a backdated insertion - recalculate from this point forward
#                 _logger.info(f"Backdated insertion detected for warehouse {record.warehouse.name} at {record.start_time}")
#                 record._recalculate_running_balances(
#                     record.warehouse.id, 
#                     record.is_blast_freezer, 
#                     record.start_time
#                 )
#             else:
#                 # This is the latest record - just calculate its balance
#                 record._recalculate_running_balances(
#                     record.warehouse.id, 
#                     record.is_blast_freezer, 
#                     record.start_time
#                 )
        
#         return record

#     def write(self, vals):
#         """Override write to handle document changes, start_time changes, and adjustment field changes"""
#         # Store original values for comparison
#         original_data = {}
#         adjustment_fields = [
#             'adjustment_heads', 'adjustment_packaging', 
#             'adjustment_pallets', 'adjustment_kilos'
#         ]
        
#         for record in self:
#             original_data[record.id] = {
#                 'start_time': record.start_time,
#                 'warehouse_id': record.warehouse.id if record.warehouse else None,
#                 'is_blast_freezer': record.is_blast_freezer,
#                 # Store original adjustment values
#                 'adjustment_heads': record.adjustment_heads,
#                 'adjustment_packaging': record.adjustment_packaging,
#                 'adjustment_pallets': record.adjustment_pallets,
#                 'adjustment_kilos': record.adjustment_kilos,
#             }
        
#         result = super(PalletKilosRecordModel, self).write(vals)
        
#         # Handle document changes
#         if 'record_reference' in vals or 'readjustment_document' in vals:
#             for record in self:
#                 record._populate_vehicle_data()
#                 record._populate_operations_data()
#                 record._populate_returns_data()
    
#         # Handle adjustment field changes - first subtract old values, then recalculate
#         if any(field in vals for field in adjustment_fields):
#             for record in self:
#                 if record.warehouse and record.start_time:
#                     old_data = original_data[record.id]
                    
#                     # Calculate the net change in adjustments
#                     adjustment_changes = {
#                         'heads': record.adjustment_heads - old_data['adjustment_heads'],
#                         'packaging': record.adjustment_packaging - old_data['adjustment_packaging'],
#                         'pallets': record.adjustment_pallets - old_data['adjustment_pallets'],
#                         'kilos': record.adjustment_kilos - old_data['adjustment_kilos'],
#                     }
                    
#                     # Log the adjustment changes for debugging
#                     if any(change != 0 for change in adjustment_changes.values()):
#                         _logger.info(f"Adjustment changes for record {record.id}: {adjustment_changes}")
                    
#                     # Recalculate from this record's start_time forward since adjustments affect running balances
#                     record._recalculate_running_balances(
#                         record.warehouse.id,
#                         record.is_blast_freezer,
#                         record.start_time
#                     )
    
#         # Handle start_time changes (potential backdating)
#         elif 'start_time' in vals:
#             for record in self:
#                 old_data = original_data[record.id]
#                 if (record.start_time != old_data['start_time'] and 
#                     record.warehouse and record.start_time):
                    
#                     # Recalculate from the earlier of old or new start_time
#                     earliest_time = min(record.start_time, old_data['start_time']) if old_data['start_time'] else record.start_time
#                     record._recalculate_running_balances(
#                         record.warehouse.id,
#                         record.is_blast_freezer,
#                         earliest_time
#                     )
        
#         return result

#     def unlink(self):
#         """Override unlink to recalculate balances after deletion"""
#         records_to_recalc = []
#         for record in self:
#             if record.warehouse and record.start_time:
#                 records_to_recalc.append({
#                     'warehouse_id': record.warehouse.id,
#                     'is_blast_freezer': record.is_blast_freezer,
#                     'start_time': record.start_time,
#                 })
        
#         result = super(PalletKilosRecordModel, self).unlink()
        
#         # Recalculate balances for affected warehouses
#         for data in records_to_recalc:
#             self._recalculate_running_balances(
#                 data['warehouse_id'],
#                 data['is_blast_freezer'],
#                 data['start_time']
#             )
        
#         return result

#     def manual_recalculate_all(self):
#         """Manual method to recalculate all running balances - for maintenance"""
#         warehouses = self.search([]).mapped('warehouse')
#         for warehouse in warehouses:
#             for blast_freezer in [True, False]:
#                 self._recalculate_running_balances(warehouse.id, blast_freezer)

#     def resync_all(self):
#         """Resync current record"""
#         for record in self:
#             record._populate_vehicle_data()
#             record._populate_operations_data()
#             record._populate_returns_data()
#             record._recalculate_running_balances(
#                 record.warehouse.id,
#                 record.is_blast_freezer,
#                 record.start_time
#             )

#     def resync_all_2(self):
#         """Resync all records in chronological order"""
#         all_records = self.search([], order='start_time asc')
#         warehouses_processed = set()
        
#         for record in all_records:
#             record._populate_vehicle_data()
#             record._populate_operations_data()
#             record._populate_returns_data()
            
#             # Only recalculate once per warehouse-blast_freezer combination
#             key = (record.warehouse.id, record.is_blast_freezer)
#             if key not in warehouses_processed:
#                 record._recalculate_running_balances(record.warehouse.id, record.is_blast_freezer)
#                 warehouses_processed.add(key)



#     @api.model
#     def import_opening_balances_from_quants(self, quant_ids):
#         """
#         Import opening balances from selected stock.quant records
#         Creates PalletKilosRecordModel records grouped by owner+warehouse
#         """
#         if not quant_ids:
#             raise UserError("No stock quant records selected.")
        
#         # Get selected quants
#         quants = self.env['stock.quant'].browse(quant_ids)
        
#         # Validate quants haven't been imported before
#         existing_records = self.search([
#             ('remarks', '=', 'imported via opening balance')
#         ])
        
#         # Get current datetime in UTC+8
#         from datetime import datetime, timezone, timedelta
#         utc_plus_8 = timezone(timedelta(hours=8))
#         current_time = datetime.now(utc_plus_8).replace(tzinfo=None) - timedelta(days=5)  # Remove timezone info for Odoo
        
#         # Group quants by owner + warehouse
#         grouped_data = {}
        
#         for quant in quants:
#             if not quant.location_id.warehouse_id:
#                 _logger.warning(f"Skipping quant {quant.id} - no warehouse found for location {quant.location_id.name}")
#                 continue
                
#             key = (quant.owner_id.id if quant.owner_id else False, quant.location_id.warehouse_id.id)
            
#             if key not in grouped_data:
#                 grouped_data[key] = {
#                     'owner_id': quant.owner_id.id if quant.owner_id else False,
#                     'warehouse_id': quant.location_id.warehouse_id.id,
#                     'total_units': 0,
#                     'total_packaging': 0,
#                     'total_kilos': 0,
#                     'unique_packages': set(),
#                     'quant_ids': []
#                 }
            
#             # Accumulate totals
#             grouped_data[key]['total_units'] += quant.x_studio_total_units or 0
#             grouped_data[key]['total_packaging'] += quant.x_studio_2nd_uom or 0
#             grouped_data[key]['total_kilos'] += quant.inventory_quantity_auto_apply or 0
            
#             # Track unique packages (pallets)
#             if quant.package_id:
#                 grouped_data[key]['unique_packages'].add(quant.package_id.id)
                
#             grouped_data[key]['quant_ids'].append(quant.id)
        
#         if not grouped_data:
#             raise UserError("No valid stock quant records found with warehouse information.")
        
#         # Check for duplicates - see if any of these quants were already imported
#         all_quant_ids = []
#         for data in grouped_data.values():
#             all_quant_ids.extend(data['quant_ids'])
        
#         # This is a simple check - you might want to implement a more sophisticated tracking system
#         # For now, we'll just warn but not block
        
#         created_records = []
        
#         # Create opening balance records
#         for (owner_id, warehouse_id), data in grouped_data.items():
            
#             # Generate report number for opening balance
#             report_no = f"OB-{warehouse_id}-{current_time.strftime('%Y%m%d%H%M%S')}"
#             if owner_id:
#                 owner_name = self.env['res.partner'].browse(owner_id).name
#                 report_no += f"-{owner_name[:3].upper()}"
            
#             vals = {
#                 'report_no': report_no,
#                 'owner_id': owner_id,
#                 'warehouse': warehouse_id,
#                 'record_reference': False,  # No source document
#                 'readjustment_document': False,
#                 'active': True,
                
#                 # Opening balance - show as received (initial stock coming in)
#                 'pallets_received': len(data['unique_packages']),
#                 'pallets_withdrawn': 0,
#                 'kilos_received': data['total_kilos'],
#                 'kilos_withdrawn': 0,
#                 'packaging_received': data['total_packaging'],
#                 'packaging_withdrawn': 0,
#                 'units_received': data['total_units'],
#                 'units_withdrawn': 0,
                
#                 # Balance fields from quant data (for opening balance, these equal the received amounts)
#                 'total_balance_in_units': data['total_units'],
#                 'total_balance_in_packaging': data['total_packaging'],
#                 'total_balance_in_kilos': data['total_kilos'],
#                 'total_balance_in_pallets': len(data['unique_packages']),
                
#                 # Beginning balance is zero for opening records (this IS the beginning)
#                 'beginning_balance_in_pallets': 0,
#                 'beginning_balance_in_kilos': 0,
                
#                 # Return and adjustment fields are zero
#                 'return_heads': 0,
#                 'return_packaging': 0,
#                 'return_pallets': 0,
#                 'return_kilos': 0,
#                 'adjustment_heads': 0,
#                 'adjustment_packaging': 0,
#                 'adjustment_pallets': 0,
#                 'adjustment_kilos': 0,
                
#                 # Vehicle fields are blank (no transport involved)
#                 'truck_type': 'N/A',
#                 'trucks_plate': '',
#                 'gate_pass': '',
#                 'start_time': current_time,
#                 'end_time': current_time,
                
#                 # Blast freezer flag
#                 'is_blast_freezer': False,
                
#                 # Special remarks
#                 'remarks': 'imported via opening balance',
#             }
            
#             # Create the record (this will trigger the create() method which handles balance calculations)
#             record = self.create(vals)
#             created_records.append(record)
            
#             _logger.info(f"Created opening balance record {record.id} for warehouse {warehouse_id}, owner {owner_id}")
        
#         # After all records are created, recalculate overall warehouse totals
#         # Group by warehouse for recalculation
#         warehouses_to_recalc = set()
#         for record in created_records:
#             warehouses_to_recalc.add(record.warehouse.id)
        
#         for warehouse_id in warehouses_to_recalc:
#             # Recalculate from the beginning since these are opening balances
#             self._recalculate_running_balances(warehouse_id, False, None)
        
#         return {
#             'type': 'ir.actions.client',
#             'tag': 'display_notification',
#             'params': {
#                 'title': 'Opening Balances Imported',
#                 'message': f'Successfully created {len(created_records)} opening balance records.',
#                 'type': 'success',
#                 'sticky': False,
#             }
#         }