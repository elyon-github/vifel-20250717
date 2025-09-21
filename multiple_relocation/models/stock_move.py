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


class ensure_ownership(models.Model):
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