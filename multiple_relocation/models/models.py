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


class multiple_relocation(models.TransientModel):
    _inherit = 'stock.quant.relocate'


    warehouseman = fields.Many2one(
        'res.partner', 
        string="Warehouseman", 
        domain="[('category_id.name', '=', 'Warehouseman')]"
    )
    
    def action_relocate_quants(self):
        self.ensure_one()
        relocation_form_series = self.env['ir.sequence'].search([('code', '=', 'relocate.form.series')], limit=1)
        x_reloc_batch_number = relocation_form_series.next_by_id()
        
        quanties = self.env['stock.quant'].search([("package_id.id", "!=", False)])
        for quant in quanties:
            for line_quants in self.quant_ids:
                if line_quants.x_studio_dest_relocation.id == quant.location_id.id and not quant.x_studio_dest_relocation.id and not line_quants.x_studio_dest_relocation.x_studio_is_an_aisle:
                    # raise UserError(f"Please assign a relocation location for the pallet {quant.package_id.name} first")
                    pass
        
        for quant in self.quant_ids:
            if quant.x_studio_special_holding:
                raise UserError('\nYou cannot relocate pallets that are on Special Holding State')
            if quant.available_quantity != quant.quantity:
                raise UserError(f"\nRecord with a Product of {quant.product_id.display_name} and a Pallet of {quant.package_id.name} seems to have quantites reserved on a picking record. Please release them before relocating the stock record.")
        
            if not quant.x_studio_dest_relocation and not quant.x_studio_dest_relocation.x_studio_is_an_aisle:
                raise UserError(f"It seems like a record with a Pallet Series ID of {quant.x_studio_pallet_series_id} has no Relocation Location set.")
        
        # Group quants by package_id and location_id
        grouped_quants = {}
        for quant in self.quant_ids:
            key = (quant.package_id.id, quant.location_id.id)
            if key not in grouped_quants:
                grouped_quants[key] = self.env['stock.quant']
            grouped_quants[key] |= quant
    
        for (package_id, location_id), quants in grouped_quants.items():
            dest_location_id = quants[0].x_studio_dest_relocation
            if dest_location_id:
                # Handle partial package unpacking first
                if self.is_partial_package and not self.dest_package_id:
                    quants_to_unpack = quants.filtered(lambda q: not all(sub_q in quants.ids for sub_q in q.package_id.quant_ids.ids))
                    for unpack_quant in quants_to_unpack:
                        unpack_quant.move_quants(
                            location_dest_id=dest_location_id, 
                            message=self.message, 
                            unpack=True,
                            warehouseman=self.warehouseman,
                            x_reloc_batch_number=x_reloc_batch_number
                        )
                    quants -= quants_to_unpack
                
                # Move quants as a group - the move_quants method will handle individual field values
                quants.move_quants(
                    location_dest_id=dest_location_id,
                    package_dest_id=self.dest_package_id,
                    message=self.message,
                    warehouseman=self.warehouseman,
                    x_reloc_batch_number=x_reloc_batch_number,
                    x_studio_pallet_series_id=quants[0].x_studio_pallet_series_id,
                    bf_pallet_char=quants[0].bf_pallet_char
                )
            
    
        # Handle lot and product actions
        lot_ids = self.quant_ids.mapped('lot_id')
        product_ids = self.quant_ids.mapped('product_id')
    
        if self.env.context.get('default_lot_id', False) and len(lot_ids) == 1:
            lot_ids.action_lot_open_quants()
        elif self.env.context.get('single_product', False) and len(product_ids) == 1:
            product_ids.action_update_quantity_on_hand()

        

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


        

    
    # def write(self, vals):
    #     # Call the super method
    #     result = super(stock_move_line_Override, self).write(vals)

    #     for record in self:
    #         # Ensure location_dest_id exists and check its child_ids
    #         if record.location_dest_id and not record.location_dest_id.child_ids and record.picking_id.picking_type_code == 'incoming' and not record.location_dest_id.x_studio_is_an_aisle:
    #             record.location_dest_id.write({
    #                 'x_studio_is_reserved': True,
    #                 'x_studio_receiving_report_id': record.picking_id.id
    #             })
        
    #     return result
        
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
                        
                    # Remove reservation from previous location if no other moves are using it
                    
                    # if previous_location and not move_lines:

                    #     previous_location.write({
                    #         'x_studio_is_reserved': False,
                    #         'x_studio_receiving_report_id': False,
                    #     })




                    


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

    
    # @api.onchange('x_studio_expiration_date')
    # def onchange_expiry_date(self):
    #     for record in self:
    #         if record.x_studio_expiration_date:
    #             expiry_date_range = record.env['product.product'].search([('id', '=', record.product_id.id)])
    #             product_brand_expiry = expiry_date_range.client_expiry_table_ids.mapped('line_attribute_value_ids.name')
                
    #             warning = None
    #             for line in expiry_date_range.client_expiry_table_ids:
    #                 if record.owner_id in line.partner_ids:
    #                     today = fields.Date.today()
    #                     not_acceptable = today + timedelta(days=line.expiry_date_range_id.x_studio_float_value)
    #                     current_variant = record.product_id.product_template_variant_value_ids.name
    #                     # Check if product_brand_expiry is empty OR the variant is in the expiry list
    #                     if (record.x_studio_expiration_date < not_acceptable and 
    #                         (not product_brand_expiry or current_variant in product_brand_expiry)):
    #                         warning = {
    #                             'title': "Expiration Threshold Warning!",
    #                             'message': (
    #                                 f"\nExpiration date is outside the acceptable expiration date range. "
    #                                 f"Please review the Product.\n\n"
    #                                 f"Entered Expiration Date: {datetime.strptime(str(record.x_studio_expiration_date), '%Y-%m-%d').strftime('%B %d, %Y')}\n"
    #                                 f"Acceptable Expiration Date Range: {datetime.strptime(str(not_acceptable), '%Y-%m-%d').strftime('%B %d, %Y')}"
    #                             ),
    #                         }
    #                         break
                
    #             if warning:
    #                 return {'warning': warning}

    
    @api.onchange('x_studio_expiration_date')
    def onchange_expiry_date(self):
        for record in self:
            if not record.x_studio_expiration_date:
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
            if not record.x_studio_expiration_date or not record.product_id:
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

class ensure_ownership(models.Model):
    _inherit = 'stock.move'
    quant_ids_picked = fields.Many2many('stock.quant', string="Quant IDs", copy=False)

    automatically_added = fields.Boolean()

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

    # To FIX by RALPH
    # @api.model
    # def _prepare_merge_moves_distinct_fields(self):
    #     fields = [
    #         'product_id', 'price_unit', 'procure_method', 'location_id', 'location_dest_id',
    #         'product_uom', 'restrict_partner_id', 'scrapped', 'origin_returned_move_id',
    #         'package_level_id', 'propagate_cancel', 'description_picking',
    #         'product_packaging_id', 'x_studio_packaging_unit','x_studio_min_unit','x_studio_client_ref'
    #     ]
    
    #     if self.env['ir.config_parameter'].sudo().get_param('stock.merge_only_same_date'):
    #         fields.append('date')
    #     if self.env.context.get('merge_extra'):
    #         fields.pop(fields.index('procure_method'))
    #     if not self.env['ir.config_parameter'].sudo().get_param('stock.merge_ignore_date_deadline'):
    #         fields.append('date_deadline')
    #     return fields

    # def _merge_moves_fields(self):
    #         """ This method will return a dict of stock move’s values that represent the values of all moves in `self` merged. """
    #         merge_extra = self.env.context.get('merge_extra')
    #         state = self._get_relevant_state_among_moves()
    #         origin = '/'.join(set(self.filtered(lambda m: m.origin).mapped('origin')))
            
    #         return {
    #             'product_uom_qty': sum(self.mapped('product_uom_qty')) if not merge_extra else self[0].product_uom_qty,
    #             'x_studio_demand_packaging': sum(self.mapped('x_studio_demand_packaging')),
    #             'x_studio_min_uom': sum(self.mapped('x_studio_min_uom')),
    #             'date': min(self.mapped('date')) if all(p.move_type == 'direct' for p in self.picking_id) else max(self.mapped('date')),
    #             'move_dest_ids': [(4, m.id) for m in self.mapped('move_dest_ids')],
    #             'move_orig_ids': [(4, m.id) for m in self.mapped('move_orig_ids')],
    #             'state': state,
    #             'origin': origin,
    #         }


class OverrideStockQuant(models.Model):
    _inherit = 'stock.quant'

    x_studio_special_holding = fields.Boolean()
    bf_pallet_char = fields.Char(string="Pallet # - Text") 
    truck_type = fields.Selection(
        string="Truck Type",
        selection=[
            ('4wheeler', '4 Wheeler'),
            ('6wheeler', '6 Wheeler'),
            ('10wheeler', '10 Wheeler'),
            ('20ft_container', '20ft Container'),
            ('40ft_container', '40ft Container'),
            ('N/A', 'N/A')
        ]
    )

    x_studio_building_dropped = fields.Char(string="Building")
    original_record_reference = fields.Many2one('stock.picking')
    
    # def get_move_lines_with_changes(self):
    #     for record in self:
    #         domain = [
    #             ('x_studio_pallet_series_id', '=', self.x_studio_pallet_series_id),
    #             ('lot_id', '=', self.lot_id.id),
    #             ('is_quant_detail_adjusted', '!=', False)
    #         ]
    #         if self.package_id:
    #             domain += [
    #                 '|',
    #                     ('package_id', '=', self.package_id.id),
    #                     ('result_package_id', '=', self.package_id.id),
    #             ]

    #         return self.env['stock.move.line'].search(domain)

    
    def re_sync_pallet_kilos_from_quants(self, records):
        # Get unique owner_ids and create grouped array
        owner_ids = list(set(records.mapped('owner_id')))
        result = [
            {'owner_id': records.filtered(lambda r: r.owner_id == owner_id)}
            for owner_id in owner_ids
        ]
        
        # Loop through groups
        for group in result:
            owner_records = group['owner_id']
            owner_name = owner_records[0].owner_id.name if owner_records and owner_records[0].owner_id else 'No Owner'
            print(f"Owner: {owner_name}")
            
            for record in owner_records:
                # Process each record in the group
                print(f"  Record: {record.name}")

    
    def write(self, vals):
        """ Override to handle the "inventory mode" and create the inventory move. """
        forbidden_fields = self._get_forbidden_fields_write()
        if self._is_inventory_mode() and any(field for field in forbidden_fields if field in vals.keys()):
            if any(quant.location_id.usage == 'inventory' for quant in self):
                # Do nothing when user tries to modify manually a inventory loss
                return
            self = self.sudo()
            # raise UserError(_("Quant's editing is restricted, you can't do this operation."))
        return super(OverrideStockQuant, self).write(vals)
        
    @api.model_create_multi
    def create(self, vals_list):
        """ Override to handle the "inventory mode" and create a quant as
        superuser the conditions are met.
        """
        quants = self.env['stock.quant']
        is_inventory_mode = self._is_inventory_mode()
        allowed_fields = self._get_inventory_fields_create()
        for vals in vals_list:
            if is_inventory_mode and any(f in vals for f in ['inventory_quantity', 'inventory_quantity_auto_apply']):
                # if any(field for field in vals.keys() if field not in allowed_fields):
                #     raise UserError(_("Quant's creation is restricted, you can't do this operation."))
                auto_apply = 'inventory_quantity_auto_apply' in vals
                inventory_quantity = vals.pop('inventory_quantity_auto_apply', False) or vals.pop(
                    'inventory_quantity', False) or 0
                # Create an empty quant or write on a similar one.
                product = self.env['product.product'].browse(vals['product_id'])
                location = self.env['stock.location'].browse(vals['location_id'])
                lot_id = self.env['stock.lot'].browse(vals.get('lot_id'))
                package_id = self.env['stock.quant.package'].browse(vals.get('package_id'))
                owner_id = self.env['res.partner'].browse(vals.get('owner_id'))
                quant = self.env['stock.quant']
                if not self.env.context.get('import_file'):
                    # Merge quants later, to make sure one line = one record during batch import
                    quant = self._gather(product, location, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True)
                if lot_id:
                    if self.env.context.get('import_file') and lot_id.product_id != product:
                        lot_name = lot_id.name
                        lot_id = self.env['stock.lot'].search([('product_id', '=', product.id), ('name', '=', lot_name)], limit=1)
                        if not lot_id:
                            company_id = location.company_id or self.env.company
                            lot_id = self.env['stock.lot'].create({'name': lot_name, 'product_id': product.id, 'company_id': company_id.id})
                        vals['lot_id'] = lot_id.id
                    quant = quant.filtered(lambda q: q.lot_id)
                if quant:
                    quant = quant[0].sudo()
                else:
                    quant = self.sudo().create(vals)
                    if 'quants_cache' in self.env.context:
                        self.env.context['quants_cache'][
                            quant.product_id.id, quant.location_id.id, quant.lot_id.id, quant.package_id.id, quant.owner_id.id
                        ] |= quant
                if auto_apply:
                    quant.write({'inventory_quantity_auto_apply': inventory_quantity})
                else:
                    # Set the `inventory_quantity` field to create the necessary move.
                    quant.inventory_quantity = inventory_quantity
                    quant.user_id = vals.get('user_id', self.env.user.id)
                    quant.inventory_date = fields.Date.today()
                quants |= quant
            else:
                quant = super().create(vals)
                if 'quants_cache' in self.env.context:
                    self.env.context['quants_cache'][
                        quant.product_id.id, quant.location_id.id, quant.lot_id.id, quant.package_id.id, quant.owner_id.id
                    ] |= quant
                quants |= quant
                if self._is_inventory_mode():
                    quant._check_company()
        return quants

    @api.model
    def _update_available_quantity(self, product_id, location_id, quantity=False, reserved_quantity=False, lot_id=None, package_id=None, owner_id=None, in_date=None):
        """ Increase or decrease `quantity` or 'reserved quantity' of a set of quants for a given set of
        product_id/location_id/lot_id/package_id/owner_id.

        :param product_id:
        :param location_id:
        :param quantity:
        :param lot_id:
        :param package_id:
        :param owner_id:
        :param datetime in_date: Should only be passed when calls to this method are done in
                                 order to move a quant. When creating a tracked quant, the
                                 current datetime will be used.
        :return: tuple (available_quantity, in_date as a datetime)
        """
        # if not (quantity or reserved_quantity):
        #     raise ValidationError(_('Quantity or Reserved Quantity should be set.'))
        self = self.sudo()
        quants = self._gather(product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True)
        if lot_id and quantity > 0:
            quants = quants.filtered(lambda q: q.lot_id)

        if location_id.should_bypass_reservation():
            incoming_dates = []
        else:
            incoming_dates = [quant.in_date for quant in quants if quant.in_date and
                              float_compare(quant.quantity, 0, precision_rounding=quant.product_uom_id.rounding) > 0]
        if in_date:
            incoming_dates += [in_date]
        # If multiple incoming dates are available for a given lot_id/package_id/owner_id, we
        # consider only the oldest one as being relevant.
        if incoming_dates:
            in_date = min(incoming_dates)
        else:
            in_date = fields.Datetime.now()

        quant = None
        if quants:
            # see _acquire_one_job for explanations
            self._cr.execute("SELECT id FROM stock_quant WHERE id IN %s ORDER BY lot_id LIMIT 1 FOR NO KEY UPDATE SKIP LOCKED", [tuple(quants.ids)])
            stock_quant_result = self._cr.fetchone()
            if stock_quant_result:
                quant = self.browse(stock_quant_result[0])

        if quant:
            vals = {'in_date': in_date}
            if quantity:
                vals['quantity'] = quant.quantity + quantity
            if reserved_quantity:
                vals['reserved_quantity'] = quant.reserved_quantity + reserved_quantity
            quant.write(vals)
        else:
            vals = {
                'product_id': product_id.id,
                'location_id': location_id.id,
                'lot_id': lot_id and lot_id.id,
                'package_id': package_id and package_id.id,
                'owner_id': owner_id and owner_id.id,
                'in_date': in_date,
            }
            if quantity:
                vals['quantity'] = quantity
            if reserved_quantity:
                vals['reserved_quantity'] = reserved_quantity
            self.create(vals)
        return self._get_available_quantity(product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True, allow_negative=True), in_date
        
    def action_view_stock_moves(self):
        self.ensure_one()
        
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_line_action")
    
        # Set domain
        domain = [
            # ('x_studio_pallet_series_id', '=', self.x_studio_pallet_series_id),
            # ('lot_id', '=', self.lot_id.id),
        ]
        if self.package_id:
            domain += [
                '|',
                    ('package_id', '=', self.package_id.id),
                    ('result_package_id', '=', self.package_id.id),
            ]
        action['domain'] = domain
    
        # Set context
        action['context'] = literal_eval(action.get('context') or '{}')
        action['context']['search_default_product_id'] = self.product_id.id
    
        # Force the use of custom tree view
        action['views'] = [(self.env.ref('multiple_relocation.view_move_line_tree_custom_history').id, 'tree')]
    
        return action
        
    def create_transfer_stock_move(self, picking_id, records):
        picking = self.env['stock.picking'].browse(picking_id)
        if not picking:
            raise UserError("Picking not found.")
    
        StockMove = self.env['stock.move']
        StockMoveLine = self.env['stock.move.line']
        ctx = self.env.context
        
        # **1. Validate package integrity**
        selected_packages = {}
        for quant in records:
            if not quant.available_quantity:
                continue
            package_name = quant.package_id.name
            if package_name:
                selected_packages.setdefault(package_name, set()).add(quant.id)
    
        # For each package, check for missing quants
        all_missing_quants = self.env['stock.quant']
        Quant = self.env['stock.quant']
        
        for package_name, selected_quant_ids in selected_packages.items():
            # Get all quants for this package
            all_package_quants = Quant.search([
                ('package_id', '=', package_name),
                ('x_studio_pallet_series_id', '!=', False)
            ])
        
            selected_quant_ids = selected_quant_ids or set()
            all_package_quant_ids = set(all_package_quants.ids)
            missing_ids = all_package_quant_ids - selected_quant_ids
        
            if missing_ids:
                missing_quants = all_package_quants.filtered(lambda q: q.id in missing_ids)
                all_missing_quants |= missing_quants
        
        if all_missing_quants:
            if not ctx.get('ignore_missing_quants'):
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'wizard.partial.package.notice',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_picking_id': picking.id,
                        'default_quant_ids': all_missing_quants.ids,
                        'default_selected_quant_ids': [q.id for q in records],
                    }
                }
            else:
                records |= all_missing_quants
    
        # **2. Get existing stock moves for this picking**
        existing_moves = StockMove.search([('picking_id', '=', picking.id)])
        
        # Create a lookup dictionary for existing moves
        existing_moves_lookup = {}
        for move in existing_moves:
            key = (
                move.product_id.id,
                move.x_studio_packaging_unit.id if move.x_studio_packaging_unit else False,
                move.x_studio_min_unit.id if move.x_studio_min_unit else False
            )
            existing_moves_lookup[key] = move
    
        # **3. Process Stock Moves with merging logic**
        grouped_data = {}
        moves_to_update = {}  # Track moves that need quantity updates
        
        for quant in records:
            product = quant.product_id
            prod_id = product.id
            if not quant.available_quantity:
                continue
                
            # Create the merge key based on matching criteria
            merge_key = (
                prod_id,
                quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,  # matches x_studio_packaging_unit
                quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False  # matches x_studio_min_unit
            )
            
            # Check if we can merge with existing move
            existing_move = existing_moves_lookup.get(merge_key)
            
            if existing_move:
                # Merge with existing move
                if merge_key not in moves_to_update:
                    moves_to_update[merge_key] = {
                        'move': existing_move,
                        'additional_qty': 0.0,
                        'quant_ids': [],
                        'move_line_vals': [],
                    }
                
                moves_to_update[merge_key]['additional_qty'] += quant.available_quantity
                moves_to_update[merge_key]['quant_ids'].append(quant.id)
                
                # Create move line for existing move
                move_line_vals = {
                    'move_id': existing_move.id,
                    'picking_id': picking.id,
                    'product_id': prod_id,
                    'product_uom_id': quant.product_uom_id.id,
                    'quantity': quant.available_quantity,
                    'location_id': quant.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'lot_id': quant.lot_id.id if quant.lot_id else False,
                    'package_id': quant.package_id.id if quant.package_id else False,
                    'result_package_id': False,
                    'owner_id': quant.owner_id.id if quant.owner_id else False,
                }
                moves_to_update[merge_key]['move_line_vals'].append(move_line_vals)
                
            else:
                # Create new move (original logic)
                if merge_key not in grouped_data:
                    # Prepare move_vals; add 'automatically_added': True if ignore flag is set
                    move_vals = {
                        'picking_id': picking.id,
                        'product_id': prod_id,
                        'name': product.display_name,
                        'product_uom': quant.product_uom_id.id,
                        'location_id': quant.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                        'product_uom_qty': 0.0,
                        'x_studio_packaging_unit': quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
                        'x_studio_min_unit': quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False,
                    }
                    if ctx.get('ignore_missing_quants'):
                        move_vals['automatically_added'] = True
    
                    grouped_data[merge_key] = {
                        'move_vals': move_vals,
                        'total_qty': 0.0,
                        'quant_ids': [],
                        'move_line_vals': [],
                    }
    
                grouped_data[merge_key]['total_qty'] += quant.available_quantity
                grouped_data[merge_key]['quant_ids'].append(quant.id)
    
                move_line_vals = {
                    'move_id': False,  # To be updated after creation
                    'picking_id': picking.id,
                    'product_id': prod_id,
                    'product_uom_id': quant.product_uom_id.id,
                    'quantity': quant.available_quantity,
                    'location_id': quant.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'lot_id': quant.lot_id.id if quant.lot_id else False,
                    'package_id': quant.package_id.id if quant.package_id else False,
                    'result_package_id': False,
                    'owner_id': quant.owner_id.id if quant.owner_id else False,
                }
                grouped_data[merge_key]['move_line_vals'].append(move_line_vals)
    
        # **4. Update existing moves**
        all_move_lines = []
        for merge_key, update_data in moves_to_update.items():
            move = update_data['move']
            # Update the move quantity
            new_qty = move.product_uom_qty + update_data['additional_qty']
            move.write({
                'product_uom_qty': new_qty,
                'quant_ids_picked': [(4, q_id) for q_id in update_data['quant_ids']]
            })
            
            # Add move lines for the merged quantities
            all_move_lines.extend(update_data['move_line_vals'])
    
        # **5. Create new moves**
        moves_by_product = {}
        for merge_key, data in grouped_data.items():
            data['move_vals']['product_uom_qty'] = data['total_qty']
            move = StockMove.create(data['move_vals'])
            moves_by_product[merge_key] = move
    
            move.write({'quant_ids_picked': [(4, q_id) for q_id in data['quant_ids']]})
    
            for ml_vals in data['move_line_vals']:
                ml_vals['move_id'] = move.id
            all_move_lines.extend(data['move_line_vals'])
    
        # **6. Create all move lines at once**
        if all_move_lines:
            StockMoveLine.create(all_move_lines)
            
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }





    
    @api.onchange('x_studio_dest_relocation')
    def _onchange_destination_relocation(self):
        if self.x_studio_dest_relocation:
            # Combined search to minimize database queries
            quant_records = self.env['stock.quant'].search([
                '|',
                ('x_studio_dest_relocation.id', '=', self.x_studio_dest_relocation.id),
                ('package_id.id', '=', self.package_id.id)
            ], order='x_studio_dest_relocation')
    
            # Use sets to check for duplicates and inconsistencies
            relocation_ids = set()
            package_ids = set()
            first_init_loc = None
            assigned_loc={}
    
            for quant in quant_records:
                if quant.x_studio_dest_relocation.id == self.x_studio_dest_relocation.id:
                    if quant.package_id.id != self.package_id.id and not self.x_studio_dest_relocation.x_studio_is_an_aisle:
                        raise UserError("It seems like the last location you've selected is already chosen as another relocation location. Please change the location.")
                if quant.package_id.id == self.package_id.id:
                    first_init_loc = quant.x_studio_dest_relocation
                    if first_init_loc != self.x_studio_dest_relocation and first_init_loc:
                        raise UserError(f"You cannot move the same Pallet into multiple Locations. Relocate to this Location {first_init_loc.complete_name}")
                if self.x_studio_dest_relocation.id == quant.location_id.id:
                    raise UserError("You selected the same location. Please relocate to another location")
       


    # def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=0, x_studio_container_number=None):

    #     removal_strategy = self._get_removal_strategy(product_id, location_id)
    #     domain = self._get_gather_domain(product_id, location_id, lot_id, package_id, owner_id, strict)
    #     domain, order = self._get_removal_strategy_domain_order(domain, removal_strategy, qty)
    
    #     quants_cache = self.env.context.get('quants_cache')
    #     if quants_cache is not None and strict and removal_strategy != 'least_packages':
    #         res = self.env['stock.quant']
    #         if lot_id:
    #             res |= quants_cache[product_id.id, location_id.id, lot_id.id, package_id.id, owner_id.id]
    #         res |= quants_cache[product_id.id, location_id.id, False, package_id.id, owner_id.id]
    #     else:
    #         res = self.search(domain, order=order)
    
    #     # Handle multiple container numbers
    #     container_priority = {}
    #     if x_studio_container_number:
    #         container_numbers = [cn.strip() for cn in x_studio_container_number.split(',')]
    #         for idx, container in enumerate(container_numbers):
    #             container_priority[container] = idx
    
    #         res = res.sorted(key=lambda q: (
    #             container_priority.get(q.x_studio_container_number, float('inf')),  # First: prioritize based on container order
    #             q.x_studio_expiration_date if q.x_studio_expiration_date else date.max,  # Second: sort by expiration date (earliest first)
    #             q.id  # Tie-breaker: use the quant ID in reverse order
    #         ))
    #     else:
    #         res = res.sorted(key=lambda q: (
    #             q.x_studio_expiration_date if q.x_studio_expiration_date else date.max,  # Sort by expiration date (earliest first)
    #             q.id  # Tie-breaker: use the quant ID in reverse order
    #         ))
    
    #     return res.sorted(key=lambda q: (q.x_studio_special_holding, not q.lot_id))

    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, qty=0, x_studio_container_number=None, quant_ids_picked=None):
        removal_strategy = self._get_removal_strategy(product_id, location_id)
        domain = self._get_gather_domain(product_id, location_id, lot_id, package_id, owner_id, strict)
        domain, order = self._get_removal_strategy_domain_order(domain, removal_strategy, qty)
        
        quants_cache = self.env.context.get('quants_cache')
        if quants_cache is not None and strict and removal_strategy != 'least_packages':
            res = self.env['stock.quant']
            if lot_id:
                res |= quants_cache[product_id.id, location_id.id, lot_id.id, package_id.id, owner_id.id]
            res |= quants_cache[product_id.id, location_id.id, False, package_id.id, owner_id.id]
        else:
            res = self.search(domain, order=order)
            
        # If quant_ids are provided, filter quants based on the selected quant_ids
        if quant_ids_picked:
            # Filter the quants by quant_ids first (top priority)
            res = res.filtered(lambda q: q.id in quant_ids_picked)
        
        # Handle multiple container numbers with "like" matching (case-insensitive)
        if x_studio_container_number:
            # Split input into list of lowercase substrings to match
            container_patterns = [cn.strip().lower() for cn in x_studio_container_number.split(',')]
    
            def get_container_priority(quant):
                # Convert the quant's container number to lowercase and check for matches
                quant_container = (quant.x_studio_container_number or "").lower()
                for idx, pattern in enumerate(container_patterns):
                    if pattern in quant_container:
                        return idx  # Return index as priority
                return float('inf')  # If no match, assign low priority
    
            # Sort by container priority, expiration date, and ID
            res = res.sorted(key=lambda q: (
                get_container_priority(q),  # First: prioritize based on "like" matching
                q.x_studio_expiration_date if q.x_studio_expiration_date else date.max,  # Second: sort by expiration date
                q.id  # Tie-breaker: quant ID
            ))
        else:
            # Default sorting if no container number is provided
            res = res.sorted(key=lambda q: (
                q.x_studio_expiration_date if q.x_studio_expiration_date else date.max,  # Sort by expiration date
                q.id  # Tie-breaker: quant ID
            ))
  
        return res

        

    def _get_reserve_quantity(self, product_id, location_id, quantity, product_packaging_id=None, uom_id=None, lot_id=None, package_id=None, owner_id=None, x_studio_container_number=None, quant_ids_picked=None, strict=False ):
        """ Get the quantity available to reserve for the set of quants
        sharing the combination of `product_id, location_id` if `strict` is set to False or sharing
        the *exact same characteristics* otherwise. If no quants are in self, `_gather` will do a search to fetch the quants
        Typically, this method is called before the `stock.move.line` creation to know the reserved_qty that could be use.
        It's also called by `_update_reserve_quantity` to find the quant to reserve.

        :return: a list of tuples (quant, quantity_reserved) showing on which quant the reservation
            could be done and how much the system is able to reserve on it
        """

        self = self.sudo()
        rounding = product_id.uom_id.rounding
        
        quants = self._gather(product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict, qty=quantity, x_studio_container_number=x_studio_container_number, quant_ids_picked=quant_ids_picked)
            
        # avoid quants with negative qty to not lower available_qty
        available_quantity = quants._get_available_quantity(product_id, location_id, lot_id, package_id, owner_id, strict)

        # do full packaging reservation when it's needed
        if product_packaging_id and product_id.product_tmpl_id.categ_id.packaging_reserve_method == "full":
            available_quantity = product_packaging_id._check_qty(available_quantity, product_id.uom_id, "DOWN")

        quantity = min(quantity, available_quantity)

        # `quantity` is in the quants unit of measure. There's a possibility that the move's
        # unit of measure won't be respected if we blindly reserve this quantity, a common usecase
        # is if the move's unit of measure's rounding does not allow fractional reservation. We chose
        # to convert `quantity` to the move's unit of measure with a down rounding method and
        # then get it back in the quants unit of measure with an half-up rounding_method. This
        # way, we'll never reserve more than allowed. We do not apply this logic if
        # `available_quantity` is brought by a chained move line. In this case, `_prepare_move_line_vals`
        # will take care of changing the UOM to the UOM of the product.
        if not strict and uom_id and product_id.uom_id != uom_id:
            quantity_move_uom = product_id.uom_id._compute_quantity(quantity, uom_id, rounding_method='DOWN')
            quantity = uom_id._compute_quantity(quantity_move_uom, product_id.uom_id, rounding_method='HALF-UP')

        if quants.product_id.tracking == 'serial':
            if float_compare(quantity, int(quantity), precision_rounding=rounding) != 0:
                quantity = 0

        reserved_quants = []

        if float_compare(quantity, 0, precision_rounding=rounding) > 0:
            # if we want to reserve
            available_quantity = sum(quants.filtered(lambda q: float_compare(q.quantity, 0, precision_rounding=rounding) > 0).mapped('quantity')) - sum(quants.mapped('reserved_quantity'))
        elif float_compare(quantity, 0, precision_rounding=rounding) < 0:
            # if we want to unreserve
            available_quantity = sum(quants.mapped('reserved_quantity'))
            if float_compare(abs(quantity), available_quantity, precision_rounding=rounding) > 0:
                raise UserError(_('It is not possible to unreserve more products of %s than you have in stock.', product_id.display_name))
        else:
            return reserved_quants

        negative_reserved_quantity = defaultdict(float)
        for quant in quants:
            if float_compare(quant.quantity - quant.reserved_quantity, 0, precision_rounding=rounding) < 0:
                negative_reserved_quantity[(quant.location_id, quant.lot_id, quant.package_id, quant.owner_id)] += quant.quantity - quant.reserved_quantity
        for quant in quants:
            if float_compare(quantity, 0, precision_rounding=rounding) > 0:
                max_quantity_on_quant = quant.quantity - quant.reserved_quantity
                if float_compare(max_quantity_on_quant, 0, precision_rounding=rounding) <= 0:
                    continue
                negative_quantity = negative_reserved_quantity[(quant.location_id, quant.lot_id, quant.package_id, quant.owner_id)]
                if negative_quantity:
                    negative_qty_to_remove = min(abs(negative_quantity), max_quantity_on_quant)
                    negative_reserved_quantity[(quant.location_id, quant.lot_id, quant.package_id, quant.owner_id)] += negative_qty_to_remove
                    max_quantity_on_quant -= negative_qty_to_remove
                if float_compare(max_quantity_on_quant, 0, precision_rounding=rounding) <= 0:
                    continue
                max_quantity_on_quant = min(max_quantity_on_quant, quantity)
                reserved_quants.append((quant, max_quantity_on_quant))
                quantity -= max_quantity_on_quant
                available_quantity -= max_quantity_on_quant
            else:
                max_quantity_on_quant = min(quant.reserved_quantity, abs(quantity))
                reserved_quants.append((quant, -max_quantity_on_quant))
                quantity += max_quantity_on_quant
                available_quantity += max_quantity_on_quant

            if float_is_zero(quantity, precision_rounding=rounding) or float_is_zero(available_quantity, precision_rounding=rounding):
                break
        return reserved_quants


    
    # Add Total to available_quantity and inventory_quantity_auto_apply columns on Group By
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        # Call the parent method and get the result
        res = super(OverrideStockQuant, self).read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        
        # Check if 'available_quantity' or 'inventory_quantity_auto_apply' is in the fields list
        if 'available_quantity' in fields or 'inventory_quantity_auto_apply' in fields:
            for line in res:
                if '__domain' in line:
                    lines = self.search(line['__domain'])
                    
                    # Compute the total for available_quantity if it is in fields
                    if 'available_quantity' in fields:
                        total_available_quantity = sum(record.available_quantity for record in lines)
                        line['available_quantity'] = total_available_quantity

                    # Compute the total for inventory_quantity_auto_apply if it is in fields
                    if 'inventory_quantity_auto_apply' in fields:
                        total_inventory_quantity_auto_apply = sum(record.inventory_quantity_auto_apply for record in lines)
                        line['inventory_quantity_auto_apply'] = total_inventory_quantity_auto_apply
        
        return res



    def _get_inventory_move_values(self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False, warehouseman=False, x_reloc_batch_number=False, x_studio_pallet_series_id=False, bf_pallet_char=False):
        """ Called when user manually set a new quantity (via `inventory_quantity`)
        just before creating the corresponding stock move.

        :param location_id: `stock.location`
        :param location_dest_id: `stock.location`
        :param package_id: `stock.quant.package`
        :param package_dest_id: `stock.quant.package`
        :return: dict with all values needed to create a new `stock.move` with its move line.
        """
        self.ensure_one()
        if self.env.context.get('inventory_name'):
            name = self.env.context.get('inventory_name')
        elif fields.Float.is_zero(qty, 0, precision_rounding=self.product_uom_id.rounding):
            name = _('Product Quantity Confirmed')
        else:
            name = _('Product Quantity Updated')
        if self.user_id and self.user_id.id != SUPERUSER_ID:
            name += f' ({self.user_id.display_name})'

        return {
            'name': name,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'product_uom_qty': qty,
            'company_id': self.company_id.id or self.env.company.id,
            'state': 'confirmed',
            'location_id': location_id.id,
            'location_dest_id': location_dest_id.id,
            'restrict_partner_id':  self.owner_id.id,
            'is_inventory': True,
            'picked': True,
            'move_line_ids': [(0, 0, {
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom_id.id,
                'quantity': qty,
                'location_id': location_id.id,
                'location_dest_id': location_dest_id.id,
                'company_id': self.company_id.id or self.env.company.id,
                'lot_id': self.lot_id.id,
                'package_id': package_id.id if package_id else False,
                'result_package_id': package_dest_id.id if package_dest_id else False,
                'owner_id': self.owner_id.id,
                'warehouseman': warehouseman.id if warehouseman else '',
                'x_relocate_batch': x_reloc_batch_number,
                'x_studio_pallet_series_id': x_studio_pallet_series_id,
                'bf_pallet_char': bf_pallet_char,
                'is_relocation': True if x_reloc_batch_number else False,
            })]
        }


    def move_quants(self, location_dest_id=False, package_dest_id=False, message=False, unpack=False, warehouseman=False, x_reloc_batch_number=False, x_studio_pallet_series_id=False, bf_pallet_char=False):
        """ Directly move a stock.quant to another location and/or package by creating a stock.move.

        :param location_dest_id: `stock.location` destination location for the quants
        :param package_dest_id: `stock.quant.package´ destination package for the quants
        :param message: String to fill the reference field on the generated stock.move
        :param unpack: set to True when needing to unpack the quant
        """

        message = message or _('Quantity Relocated')
        move_vals = []
        for quant in self:
            result_package_id = package_dest_id  # temp variable to kAeep package_dest_id unchanged
            if not unpack and not package_dest_id:
                result_package_id = quant.package_id
            move_vals.append(quant.with_context(inventory_name=message)._get_inventory_move_values(
                quant.quantity,
                quant.location_id,
                location_dest_id or quant.location_id,
                quant.package_id,
                result_package_id,
                warehouseman,
                x_reloc_batch_number,
                quant.x_studio_pallet_series_id,
                quant.bf_pallet_char
            ))
        
        moves = self.env['stock.move'].create(move_vals)
        moves._action_done()
        

class picking_type(models.Model):
    _inherit = 'stock.picking.type'

    is_blast_freeze_operation = fields.Boolean(string="Is a Blast Freeze Operation?")


class transfer_locations(models.Model):
    _inherit = 'stock.picking'


    location_id = fields.Many2one(
        'stock.location', "Source Location",
         store=True,  readonly=False,
        check_company=True, required=True, domain="[('id', 'in', allowed_value_ids)]")


    location_dest_id = fields.Many2one(
        'stock.location', "Destination Location",
       store=True,  readonly=False,
        check_company=True, required=True, domain="[('id', 'in', allowed_value_ids)]")

    total_quantity = fields.Float(string="Total Quantity", compute="_compute_totals", store=True)
    total_weight = fields.Float(string="Total Weight (KG)", compute="_compute_totals", store=True)

    vifel_type_of_operation = fields.Selection(string="Operation Type", store=True, compute="_comupute_vifel_type_of_operation", selection=[
        ('BFRR', 'BF RECEIVING'),
        ('BFWR', 'BF WITHDRAWING'),
        ('RR', 'RECEIVING'),
        ('WR', 'WITHDRAWING'),
    ])
    truck_type = fields.Selection(
        string="Truck Type",
        selection=[
            ('4wheeler', '4 Wheeler'),
            ('6wheeler', '6 Wheeler'),
            ('10wheeler', '10 Wheeler'),
            ('20ft_container', '20ft Container'),
            ('40ft_container', '40ft Container'),
            ('N/A', 'N/A')
        ]
    )
    allowed_product_ids = fields.Many2many('product.product', compute="_compute_allowed_product_ids", string="Allowed Products")
    allowed_value_ids = fields.Many2many(
        'stock.location', compute="_compute_allowed_value_ids", string="Allowed Locations", store=True
    )

    gentle_reminder = fields.Char(string="Reminder")

    quant_count = fields.Integer(string="Quants", compute="_compute_quant_count")

    return_reason = fields.Selection(
    [
        ('Partial Withdraw', 'Partial Withdraw'),
        ('Wrong Details Encoded', 'Wrong Details Encoded'),
        ('Void Transfer', 'Void Transfer'),
        ('Others', 'Others')
    ],
    string="Return Reason",
    readonly=True,
    copy=False
)

    other_reasons = fields.Char(string="Specific Reason for Return", readonly=True, copy=False)

    return_id_already_done = fields.Boolean(string="Return Already Validated", compute="_compute_return_id_already_validated", store=True)

    @api.depends('return_ids.state')
    def _compute_return_id_already_validated(self):
        for record in self:
            already_done = False
            if record.return_ids:
                for rr_return_id in record.return_ids:
                    if rr_return_id.state == 'done':
                        already_done = True
                        break
            record.return_id_already_done = already_done
            
    
    def process_move_lines_get_total_out(self, move_lines):
        """
        Simple function to group stock move lines by UOM delivery and sum packaging/kg
        
        Args:
            move_lines: stock.move.line recordset or list of IDs
        
        Returns:
            List of dicts: [
                {'uom': 'Boxes', 'packaging': 700.0, 'kg': 500.0},
                {'uom': 'Sacks', 'packaging': 350.0, 'kg': 250.0}
            ]
        
        QWeb Usage:
        <t t-foreach="totals" t-as="total">
            <tr>
                <td><span t-esc="total['uom']"/></td>
                <td><span t-esc="total['packaging']"/></td>
                <td><span t-esc="total['kg']"/></td>
            </tr>
        </t>
        """
        # Handle if move_lines is passed as IDs
        if isinstance(move_lines, (list, tuple)):
            move_lines = self.env['stock.move.line'].browse(move_lines)
        
        # Group by UOM delivery
        grouped = {}
        
        for line in move_lines:
            uom = line.x_studio_quantity_uom_delivery.name if line.x_studio_quantity_uom_delivery else ''
            packaging = float(line.x_studio_actual_packaging or 0)
            kg = float(line.x_studio_actual_kg or 0)
            
            if uom not in grouped:
                grouped[uom] = {'packaging': 0, 'kg': 0}
            
            grouped[uom]['packaging'] += packaging
            grouped[uom]['kg'] += kg
        
        # Convert to list format for easy QWeb iteration
        result = []
        for uom, totals in grouped.items():
            result.append({
                'uom': uom,
                'packaging': totals['packaging'],
                'kg': totals['kg']
            })
        
        return result
    # @api.model
    def _get_max_days_back_config(self):
        """Get the maximum days back configuration from static variables"""
        config = self.env['x_inventory_static_var'].search([
            ('x_studio_use_case', '=', 'Date Constraints'),
            ('x_name', 'ilike', 'Max Acceptable Truck Time / Start Time'),
            ('x_studio_warehouse', '=', self.picking_type_id.warehouse_id.id)
        ], limit=1)
        
        if config and config.x_studio_float_value:
            return config.x_studio_float_value
        else:
            # Default to 7 days if no configuration found
            return 7
    
    @api.constrains('x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time')
    def _check_date_not_too_old(self):
        """
        Constraint to ensure truck_time, start_time, and end_time are not older 
        than the configured maximum days back
        """
        max_days_back = self._get_max_days_back_config()
        cutoff_datetime = datetime.now() - timedelta(days=max_days_back)
        
        for record in self:
            # Check truck_time
            if record.x_studio_truck_time and record.x_studio_truck_time < cutoff_datetime:
                raise ValidationError(
                    f"Truck Time cannot be more than {int(max_days_back)} days ago. "
                    f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
                )
            
            # Check start_time
            if record.x_studio_start_time and record.x_studio_start_time < cutoff_datetime:
                raise ValidationError(
                    f"Start Time cannot be more than {int(max_days_back)} days ago. "
                    f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
                )
            
            # Check end_time
            if record.x_studio_end_time and record.x_studio_end_time < cutoff_datetime:
                raise ValidationError(
                    f"End Time cannot be more than {int(max_days_back)} days ago. "
                    f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
                )
    
    def operation_type_checker(self, operation_type_record):
        is_receiving = operation_type_record.code == 'incoming'
        return operation_type_record.is_blast_freeze_operation, is_receiving

    @api.depends('picking_type_id')
    def _comupute_vifel_type_of_operation(self):
        for record in self:
            is_blast_freeze, is_receiving = record.operation_type_checker(record.picking_type_id)

            if not is_blast_freeze and is_receiving:
                record.vifel_type_of_operation = 'RR'
            elif not is_blast_freeze and not is_receiving:
                record.vifel_type_of_operation = 'WR'
            elif is_blast_freeze and is_receiving:
                record.vifel_type_of_operation = 'BFRR'
            elif is_blast_freeze and not is_receiving:
                record.vifel_type_of_operation = 'BFWR'
            else:
                record.vifel_type_of_operation = 'RR'

    
    @api.depends('move_ids_without_package.quantity', 'move_ids_without_package.x_studio_actual_packaging_demand')
    def _compute_totals(self):
        for record in self:
            total_quantity = 0
            total_weight = 0
            for move in record.move_ids_without_package:
                total_quantity += move.x_studio_actual_packaging_demand
                total_weight += move.quantity

            record.total_quantity = total_quantity
            record.total_weight = total_weight
            
    
    def void_transfer(self):
        """Mark transfer as voided and deactivate the latest associated pallet kilos record."""
        for record in self:
            if not self.env.user.has_group('multiple_relocation.inventory_super_admin'):
                raise UserError(_("You do not have permission to void transfers."))
    
            record.x_studio_voided = True
    
            # Find the latest related pallet kilos record
            pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
                [('effective_document', '=', record.id), ('active', '=', True)],
                order='create_date desc',
                limit=1
            )
            
            if pallet_record:
                # Store data needed for recalculation before deactivating
                warehouse_id = pallet_record.warehouse.id
                is_blast_freezer = pallet_record.is_blast_freezer
                start_time = pallet_record.start_time
                
                # Deactivate the record
                if pallet_record.readjustment_document and pallet_record.readjustment_document.id == record.id:
                    pallet_record.readjustment_document = False
                pallet_record.active = False
                
                _logger.info("Deactivated pallet kilos record: %s", pallet_record.effective_document.name)
                
                # Recalculate running balances from this point forward
                # Use the model's efficient recalculation method
                pallet_record._recalculate_running_balances(
                    warehouse_id, 
                    is_blast_freezer, 
                    start_time
                )
                
                _logger.info("Voided transfer and archived Pallet Kilos Log: %s", record.name)
            else:
                _logger.warning("No pallet kilos record found for transfer: %s", record.name)
    
    def unvoid_transfer(self):
        """Reverse the void operation: unmark transfer as voided and reactivate the associated pallet kilos record."""
        for record in self:
            if not self.env.user.has_group('multiple_relocation.inventory_super_admin'):
                raise UserError(_("You do not have permission to unvoid transfers."))
            
            # Check if the record is actually voided
            if not record.x_studio_voided:
                _logger.warning("Transfer %s is not voided, cannot unvoid.", record.name)
                continue
                
            record.x_studio_voided = False
            
            # Find the latest related pallet kilos record (including inactive ones)
            domain = []
            if record.x_studio_re_adjustment_for_document:
                domain = [('effective_document', '=', record.x_studio_re_adjustment_for_document.id)]
            else:
                domain = [('effective_document', '=', record.id)]
            
            pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].with_context(active_test=False).search(
                domain,
                order='create_date desc',
                limit=1
            )
            
            if pallet_record:
                # Store data needed for recalculation
                warehouse_id = pallet_record.warehouse.id
                is_blast_freezer = pallet_record.is_blast_freezer
                start_time = pallet_record.start_time
                
                # Reactivate the record
                if not pallet_record.active and not pallet_record.readjustment_document:
                    pallet_record.active = True
                    _logger.info("Reactivated pallet kilos record: %s", pallet_record.effective_document.name)
                elif not pallet_record.readjustment_document:
                    pallet_record.readjustment_document = record.id
                    pallet_record.active = True  # Ensure it's active when restoring readjustment
                    _logger.info("Restored readjustment document link for pallet kilos record: %s", pallet_record.effective_document.name)
                
                # Refresh the record data after reactivation
                pallet_record._populate_vehicle_data()
                pallet_record._populate_operations_data()
                pallet_record._populate_returns_data()
                
                # Recalculate running balances from this point forward
                pallet_record._recalculate_running_balances(
                    warehouse_id, 
                    is_blast_freezer, 
                    start_time
                )
                
                _logger.info("Unvoided transfer and restored Pallet Kilos Log: %s", record.name)
            else:
                _logger.warning("No pallet kilos record found for transfer: %s", record.name)

    
                
    def get_grouped_move_lines_for_report(self):
        """
        Preprocess move lines for report rendering.
        Groups lines by item description key and marks which ones should display the description.
        
        Returns:
            tuple: (processed_lines, grand_total_by_uom)
            - processed_lines: List of dictionaries with processed move line data
            - grand_total_by_uom: Dictionary with UOM totals for grand total
        """
        all_move_lines = []
        
        # Collect all move lines
        for move in self.move_ids:
            for line in move.move_line_ids:
                all_move_lines.append(line)
        
        # Sort by product name (optional - adjust sorting as needed)
        sorted_move_lines = sorted(all_move_lines, key=lambda l: l.product_id.name if l.product_id else '')
        
        processed_lines = []
        seen_descriptions = set()
        grand_total_by_uom = {}
        
        # First pass: determine if we have only one pallet and one product
        unique_descriptions = set()
        for line in sorted_move_lines:
            move = line
            product_name = line.product_id.name if line.product_id else ''
            container_number = move.x_studio_container_number or ''
            
            # Format dates
            production_date = ''
            if move.x_studio_production_date:
                production_date = move.x_studio_production_date.strftime('%b%d.%Y').upper()
            
            expiration_date = ''
            if move.x_studio_expiration_date:
                expiration_date = move.x_studio_expiration_date.strftime('%b%d.%Y').upper()
            
            description_key = f"{product_name}|{container_number}|{production_date}|{expiration_date}"
            unique_descriptions.add(description_key)
        
        # Check if we should hide details (only one pallet AND only one product)
        is_single_pallet_single_product = len(unique_descriptions) == 1 and len(sorted_move_lines) == 1
        
        # Second pass: process lines
        # Track seen descriptions per page
        seen_descriptions_current_page = set()
        items_per_page = 15  # Should match your XML template
        
        for line_index, line in enumerate(sorted_move_lines):
            move = line
            
            # Create the description key for grouping
            product_name = line.product_id.name if line.product_id else ''
            container_number = move.x_studio_container_number or ''
            
            # Format dates
            production_date = ''
            if move.x_studio_production_date:
                production_date = move.x_studio_production_date.strftime('%b%d.%Y').upper()
            
            expiration_date = ''
            if move.x_studio_expiration_date:
                expiration_date = move.x_studio_expiration_date.strftime('%b%d.%Y').upper()
            
            # Create the description key for grouping (used to determine uniqueness)
            description_key = f"{product_name}|{container_number}|{production_date}|{expiration_date}"
            
            # Create the formatted description for display
            description_parts = []
            if product_name:
                description_parts.append(product_name)
            if container_number:
                description_parts.append(container_number)
            if production_date and expiration_date:
                description_parts.append(f"{production_date} - {expiration_date}")
            elif production_date:
                description_parts.append(production_date)
            elif expiration_date:
                description_parts.append(expiration_date)
            
            formatted_description = '<br/>'.join(description_parts)
            
            # Determine if this line should start a new page
            # Check if we're at the beginning of a new page (except for the first line)
            is_new_page = line_index > 0 and line_index % items_per_page == 0
            
            # If starting a new page, reset the seen descriptions for current page
            if is_new_page:
                seen_descriptions_current_page = set()
            
            # Determine if we should show the description
            # Show if: first occurrence of this key on current page OR starting a new page
            show_description = False
            if description_key not in seen_descriptions_current_page or is_new_page:
                show_description = True
                seen_descriptions_current_page.add(description_key)
            
            # Get UOM and quantity
            uom = move.x_studio_quantity_uom.name if move and move.x_studio_quantity_uom else move.x_studio_quantity_uom_delivery.name
            quantity = line.x_studio_2nd_uom or move.x_studio_affected_2nd_uom
            
            # Add to grand total by UOM
            if uom:
                if uom not in grand_total_by_uom:
                    grand_total_by_uom[uom] = 0
                grand_total_by_uom[uom] += quantity
            
            # Build pallet number with fallback logic
            if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_no = f"{line.package_id.name}"
            elif line.picking_id.x_studio_is_a_blast_freezer:
                pallet_no = line.bf_pallet_char
            else:
                pallet_no = line.result_package_id.name if line.result_package_id else ''
    
            # Append processed line
            processed_lines.append({
                'pallet_no': pallet_no,
                'item_description': formatted_description,
                'show_description': show_description,
                'description_key': description_key,  # Keep for new page logic
                'quantity': quantity,
                'uom': uom,
                'weight': line.quantity or 0,
                'weight_uom': line.product_uom_id.name if line.product_uom_id else '',
                'original_line': line,  # Reference for any additional data
                'is_new_page': is_new_page  # Flag for new page starts
            })
        
        # Add "***Nothing Follows***" to the very last row after all pallets are rendered
        if processed_lines:
            # Always add "Nothing Follows" as a separate line to preserve product details
            last_line = processed_lines[-1].copy()
            
            # Create the "Nothing Follows" line
            nothing_follows_line = last_line.copy()
            nothing_follows_line['item_description'] = '***Nothing Follows***'
            nothing_follows_line['show_description'] = True
            nothing_follows_line['description_key'] = 'nothing_follows'
            nothing_follows_line['pallet_no'] = ''  # Clear pallet number for "Nothing Follows"
            nothing_follows_line['quantity'] = 0
            nothing_follows_line['weight'] = 0
            nothing_follows_line['uom'] = ''
            nothing_follows_line['weight_uom'] = ''
            
            processed_lines.append(nothing_follows_line)
    
        return processed_lines, grand_total_by_uom
    
    def get_uom_totals_for_page(self, processed_lines, start_idx, end_idx):
        """
        Calculate UOM totals for a specific page range.
        
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
        
        Returns:
            dict: Dictionary with UOM totals for the page
        """
        page_total_by_uom = {}
        
        for line_data in processed_lines[start_idx:end_idx]:
            uom = line_data['uom']
            quantity = line_data['quantity']
            
            if uom:
                if uom not in page_total_by_uom:
                    page_total_by_uom[uom] = 0
                page_total_by_uom[uom] += quantity
        
        return page_total_by_uom


    def get_weight_totals_for_page(self, processed_lines, start_idx, end_idx):
        """
        Calculate UOM totals for a specific page range.
        
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
        
        Returns:
            dict: Dictionary with UOM totals for the page
        """
        page_weight_by_uom = {}
        
        for line_data in processed_lines[start_idx:end_idx]:
            uom = line_data['uom']
            weight = line_data['weight']
            
            if uom:
                if uom not in page_weight_by_uom:
                    page_weight_by_uom[uom] = 0
                page_weight_by_uom[uom] += weight
        
        return page_weight_by_uom

    def get_pallet_count_for_page(self, processed_lines, start_idx, end_idx):
        """
        Calculate unique pallet count for a specific page range.
        Only counts pallets that appear for the FIRST time in the entire dataset
        and happen to be on this specific page.
        
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
        
        Returns:
            int: Number of unique pallets that first appear on this page
        """
        # First, build a map of which line index each pallet first appears at
        first_occurrence = {}
        
        for idx, line_data in enumerate(processed_lines):
            line = line_data['original_line']
            pallet_id = None
            
            # Get the pallet identifier using the same logic as the original
            if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('package', line.package_id.id)
            elif line.result_package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('result_package', line.result_package_id.id)
            elif line.bf_pallet_char and line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('bf_pallet', line.bf_pallet_char)
            
            if pallet_id and pallet_id not in first_occurrence:
                first_occurrence[pallet_id] = idx
        
        # Now count pallets that first appear in this page range
        page_pallet_count = 0
        
        for line_idx in range(start_idx, min(end_idx, len(processed_lines))):
            line_data = processed_lines[line_idx]
            line = line_data['original_line']
            
            # Check if this line contains a pallet's first occurrence
            if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('package', line.package_id.id)
                if first_occurrence.get(pallet_id) == line_idx:
                    page_pallet_count += 1 if line.reserved_quantity_on_validation == 0 else 0
            elif line.result_package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('result_package', line.result_package_id.id)
                if first_occurrence.get(pallet_id) == line_idx:
                    page_pallet_count += 1 if line.reserved_quantity_on_validation == 0 else 0
            elif line.bf_pallet_char and line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('bf_pallet', line.bf_pallet_char)
                if first_occurrence.get(pallet_id) == line_idx:
                    page_pallet_count += 1
        
        return page_pallet_count
    
    def preprocess_stock_move_data(self, doc):
            """
            Preprocess stock move data to group by product + production date + expiration date
            and prepare consolidated data for rendering
            """
            
            # Dictionary to group move lines by unique SKU combination
            grouped_moves = defaultdict(lambda: {
                'product_id': None,
                'base_name': None,
                'product_name': '',
                'production_date': None,
                'expiration_date': None,
                'container_number': None,
                'qty_demand': 0,
                'weight_demand': 0,
                'qty_actual': 0,
                'weight_actual': 0,
                'packaging_qty': 0,
                'uom_name': '',
                'packaging_unit_name': '',
                'pallet_count': 0,
                'package_ids': set(),
                'processed_moves': set()  # Track which moves we've already processed GLOBALLY
            })
            
            # Track moves that have been processed globally (across all groups)
            globally_processed_moves = set()
    
            package_ids = set()
            # Process each move
            for move in doc.move_ids:
                # Process each move line within the move
                for move_line in move.move_line_ids:
                    # Create unique key based on product + production date + expiration date
                    prod_date = move_line.x_studio_production_date if hasattr(move_line, 'x_studio_production_date') else None
                    exp_date = move_line.x_studio_expiration_date if hasattr(move_line, 'x_studio_expiration_date') else None
                    cont_number = move_line.x_studio_container_number if hasattr(move_line, 'x_studio_container_number') else None
                    
                    # Convert dates to string for consistent grouping
                    prod_date_str = prod_date.strftime('%Y-%m-%d') if prod_date else 'No Prod Date'
                    exp_date_str = exp_date.strftime('%Y-%m-%d') if exp_date else 'No Exp Date'
                    
                    # Create unique key
                    key = f"{move.product_id.id}_{prod_date_str}_{exp_date_str}_{cont_number}"
                    
                    # Initialize or update grouped data
                    if grouped_moves[key]['product_id'] is None:
                        grouped_moves[key]['product_id'] = move.product_id
                        
                        # Build product name with dates
                        base_name = move.product_id.name or move.product_id.name
                        date_info = []
                        grouped_moves[key]['sort_name'] = base_name
                        if prod_date:
                            date_info.append(f"{prod_date.strftime('%b').upper()}.{prod_date.day}.{prod_date.year}")
            
                        if exp_date:
                            date_info.append(f"- {exp_date.strftime('%b').upper()}.{exp_date.day}.{exp_date.year}")
                            
                        if date_info:
                            if cont_number:
                                grouped_moves[key]['product_name'] = f"{base_name} <br/>{cont_number} <br/>{' '.join(date_info)} "
                            else:
                                grouped_moves[key]['product_name'] = f"{base_name} <br/>{', '.join(date_info)} "
                        else:
                            grouped_moves[key]['product_name'] = base_name
                            
                        grouped_moves[key]['production_date'] = prod_date
                        grouped_moves[key]['expiration_date'] = exp_date
                        grouped_moves[key]['container_number'] = cont_number
                        grouped_moves[key]['uom_name'] = move.x_studio_packaging_unit.name if hasattr(move, 'x_studio_packaging_unit') and move.x_studio_packaging_unit else ''
                        grouped_moves[key]['packaging_unit_name'] = move.x_studio_packaging_unit.name if hasattr(move, 'x_studio_packaging_unit') and move.x_studio_packaging_unit else ''
        
                    # Add move-level quantities (documented/demand) only ONCE per move globally
                    # This ensures same product quantities are not duplicated across different date groups
                    if move.id not in globally_processed_moves:
                        # grouped_moves[key]['qty_actual'] += move.x_studio_actual_packaging_demand if hasattr(move, 'x_studio_actual_packaging_demand') else 0
                        grouped_moves[key]['qty_demand'] += move.x_studio_demand_packaging if hasattr(move, 'x_studio_demand_packaging') else 0
                        grouped_moves[key]['weight_demand'] += move.product_uom_qty if hasattr(move, 'product_uom_qty') else 0
                        globally_processed_moves.add(move.id)
                    
                    # Add move line specific quantities (actual quantities)
                    # These are added for each move line since they're line-specific
                    grouped_moves[key]['qty_actual'] += move_line.quantity if hasattr(move_line, 'quantity') else 0
                    grouped_moves[key]['weight_actual'] += move_line.quantity if hasattr(move_line, 'quantity') else 0
                    grouped_moves[key]['packaging_qty'] += move_line.x_studio_2nd_uom if move_line.x_studio_2nd_uom else move_line.x_studio_affected_2nd_uom

                    # Track unique packages for pallet count
                    if move_line.package_id and not move_line.picking_id.x_studio_is_a_blast_freezer:
                        grouped_moves[key]['package_ids'].add(move_line.package_id.id)
                        if move_line.package_id.id not in package_ids:
                            package_ids.add(move_line.package_id.id)
                            grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 else 0

                    elif move_line.bf_pallet_char and move_line.picking_id.x_studio_is_a_blast_freezer:
                        
                        grouped_moves[key]['package_ids'].add(move_line.bf_pallet_char)
                        if move_line.bf_pallet_char not in package_ids:
                            package_ids.add(move_line.bf_pallet_char)
                            grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 else 0

                    elif move_line.result_package_id:
                        grouped_moves[key]['package_ids'].add(move_line.result_package_id.id)
                        if move_line.result_package_id.id not in package_ids:
                            package_ids.add(move_line.result_package_id.id)
                            grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 else 0
                            

    
                    
            # Convert to list and calculate final pallet counts
            processed_moves = []
            for key, data in grouped_moves.items():
                del data['package_ids']  # Remove set as it's not needed in template
                del data['processed_moves']  # Remove tracking set
                processed_moves.append(data)
            
            # Sort by product name for consistent ordering
            processed_moves.sort(key=lambda x: x['sort_name'])
            
            # Add "***Nothing Follows***" to the last item's product_name
            if processed_moves:
                last_item = processed_moves[-1]
                last_item['product_name'] += " <br/>***Nothing Follows***"
            
            return processed_moves
    
    def group_quantities_by_uom(self, moves):
        """
        Group quantities by UOM and return separate qty and uom strings
        """
        uom_totals = defaultdict(float)
        uom_totals_demand = defaultdict(float)
        uom_totals_actual = defaultdict(float)
        uom_total_actual_kg = defaultdict(float)
        uom_total_demand_kg = defaultdict(float)
        for move in moves:
            uom = move['uom_name'] or 'Units'
            uom_totals[uom] += move['qty_actual']
            uom_totals_demand[uom] += move['qty_demand']
            uom_totals_actual[uom] += move['packaging_qty']
            uom_demand = move['uom_name'] or 'Units'
            uom_total_actual_kg[uom] += move['qty_actual']
            uom_total_demand_kg[uom] += move['weight_demand']
            
        
        # Format the grouped quantities and UOMs separately
        qty_parts = []
        uom_parts = []
        qty_demand_parts = []
        qty_actual_parts = []

        kg_demand_parts = []
        kg_actual_parts = []
        
        for uom, qty in uom_totals.items():
            qty_parts.append(f"{qty:,.2f}")
            uom_parts.append(uom)
            
        for uom, qty in uom_totals_demand.items():
            qty_demand_parts.append(f"{qty:,.2f}")

        for uom, qty in uom_totals_actual.items():
            qty_actual_parts.append(f"{qty:,.2f}")

        for uom, kg in uom_total_actual_kg.items():
            kg_actual_parts.append(f"{kg:,.2f}")

        for uom, kg in uom_total_demand_kg.items():
            kg_demand_parts.append(f"{kg:,.2f}")

        
        return {
            'qty_formatted': "<br/>".join(qty_parts) if qty_parts else "0",
            'uom_formatted': "<br/>".join(uom_parts) if uom_parts else "",
            'qty_demand_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.2f}" for part in qty_demand_parts]) if qty_demand_parts else "0.00",
            'qty_actual_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.2f}" for part in qty_actual_parts]) if qty_actual_parts else "0.00",
            'kg_actual_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.2f}" for part in kg_actual_parts]) if kg_actual_parts else "0.00",
            'kg_demand_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.2f}" for part in kg_demand_parts]) if kg_demand_parts else "0.00"
        }
            
    def calculate_page_data(self, processed_moves, page_size=9):
        """
        Calculate pagination data for the processed moves
        """
        total_items = len(processed_moves)
        pages_count = (total_items + page_size - 1) // page_size if total_items > 0 else 1
        
        page_data = []
        for page_num in range(pages_count):
            start_idx = page_num * page_size
            end_idx = min(start_idx + page_size, total_items)
            
            page_moves = processed_moves[start_idx:end_idx]
            
            # Calculate page totals
            uom_data = self.group_quantities_by_uom(page_moves)
            page_totals = {
                'qty_demand': sum(move['qty_demand'] for move in page_moves),
                'qty_demand_formatted': uom_data['qty_demand_formatted'],
                'weight_demand': sum(move['weight_demand'] for move in page_moves),
                'qty_actual': sum(move['qty_actual'] for move in page_moves),
                'weight_actual': sum(move['weight_actual'] for move in page_moves),
                'packaging_qty': sum(move['packaging_qty'] for move in page_moves),
                'pallet_count': sum(move['pallet_count'] for move in page_moves),
                'qty_formatted': uom_data['qty_formatted'],
                'qty_actual_formatted': uom_data['qty_actual_formatted'],
                # 'pallet_count': sum(move['pallet_count'] for move in page_moves),
                'uom_formatted': uom_data['uom_formatted'],
                'kg_actual_formatted': uom_data['kg_actual_formatted'],
                'kg_demand_formatted': uom_data['kg_demand_formatted'],
            }
            
            page_data.append({
                'page_num': page_num,
                'moves': page_moves,
                'totals': page_totals,
                'blank_rows': page_size - len(page_moves)
            })
        
        # Calculate grand totals
        grand_uom_data = self.group_quantities_by_uom(processed_moves)
        grand_totals = {
            'qty_demand': sum(move['qty_demand'] for move in processed_moves),
            'weight_demand': sum(move['weight_demand'] for move in processed_moves),
            'qty_actual': sum(move['qty_actual'] for move in processed_moves),
            'weight_actual': sum(move['weight_actual'] for move in processed_moves),
            'packaging_qty': sum(move['packaging_qty'] for move in processed_moves),
            'pallet_count': sum(move['pallet_count'] for move in processed_moves),
            'qty_formatted': grand_uom_data['qty_formatted'],
            'qty_demand_formatted':  grand_uom_data['qty_demand_formatted'],
            'qty_actual_formatted': grand_uom_data['qty_actual_formatted'],
            'uom_formatted': grand_uom_data['uom_formatted'],
            'kg_actual_formatted': grand_uom_data['kg_actual_formatted'],
            'kg_demand_formatted': grand_uom_data['kg_demand_formatted'],
        }

        return {
            'pages': page_data,
            'pages_count': pages_count,
            'grand_totals': grand_totals
        }
    
    # Example usage in Odoo controller or model method:
    def prepare_report_data(self):
        """
        Method to be called before rendering the report template
        """
        processed_moves = self.preprocess_stock_move_data(self)
        pagination_data = self.calculate_page_data(processed_moves)
        
        return {
            'doc': self,
            'processed_moves': processed_moves,
            'pagination_data': pagination_data
        }

    # Picklist
    def get_picklist_page_totals_by_uom(self, page_start_index, page_end_index):
        """
        Calculate page totals grouped by UOM for picklist
        Returns dictionary with UOM as key and totals as values
        """
        page_totals = {}
        
        for i in range(page_start_index, min(page_end_index, len(self.move_line_ids))):
            move_line = self.move_line_ids[i]
            uom_name = move_line.x_studio_quantity_uom_delivery.name if move_line.x_studio_quantity_uom_delivery else 'Unknown'
            
            if uom_name not in page_totals:
                page_totals[uom_name] = {
                    'qty': 0,
                    'packs': 0,
                    'kg': 0,
                    'uom': move_line.x_studio_quantity_uom_delivery
                }
            
            # Add to totals
            page_totals[uom_name]['qty'] += move_line.x_studio_actual_packaging or 0
            page_totals[uom_name]['packs'] += move_line.x_studio_actual_min or 0
            page_totals[uom_name]['kg'] += move_line.x_studio_actual_kg or 0
        
        return page_totals
    
    def get_picklist_grand_totals_by_uom(self):
        """
        Calculate grand totals grouped by UOM for picklist
        Returns dictionary with UOM as key and totals as values
        """
        grand_totals = {}
        
        for move_line in self.move_line_ids:
            uom_name = move_line.x_studio_quantity_uom_delivery.name if move_line.x_studio_quantity_uom_delivery else 'Unknown'
            
            if uom_name not in grand_totals:
                grand_totals[uom_name] = {
                    'qty': 0,
                    'packs': 0,
                    'kg': 0,
                    'uom': move_line.x_studio_quantity_uom_delivery
                }
            
            # Add to totals
            grand_totals[uom_name]['qty'] += move_line.x_studio_affected_2nd_uom or 0
            grand_totals[uom_name]['packs'] += move_line.x_studio_withdraw_units or 0
            grand_totals[uom_name]['kg'] += move_line.x_studio_actual_kg or 0
        
        return grand_totals
    
    def get_picklist_sorted_uom_list(self):
        """
        Get sorted list of UOMs present in the picklist
        Returns list of UOM names sorted alphabetically
        """
        uom_set = set()
        for move_line in self.move_line_ids:
            uom_name = move_line.x_studio_quantity_uom_delivery.name if move_line.x_studio_quantity_uom_delivery else 'Unknown'
            uom_set.add(uom_name)
        
        return sorted(list(uom_set))

    
    def auto_fix_discrepancy(self):
        for record in self:
            stock_moves = record.move_ids_without_package
            
            for lines in stock_moves:
                lines['x_studio_demand_packaging'] = lines.x_studio_actual_packaging_demand
                lines['x_studio_min_uom'] = lines.x_studio_min_actual_demand
                lines['product_uom_qty'] = lines.quantity

    def generate_lines(self):
        """Generate lines for all moves in the picking"""
        successful_count = 0
        failed_count = 0
        
        for record in self:
            for move in record.move_ids_without_package:
                try:
                    if move.exists():
                        move.regenerate_move_lines()
                        successful_count += 1
                except Exception as e:
                    failed_count += 1
                    _logger.error(f"Error processing stock move {move.id}: {str(e)}")
                    continue
        
        # Provide user feedback
        if successful_count > 0:
            message = f"Successfully Created {successful_count} Product Detailed Operations"
            if failed_count > 0:
                message += f", {failed_count} Product Detailed Operations failed"
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Generation Complete',
                    'message': message,
                    'type': 'success' if failed_count == 0 else 'warning',
                    'sticky': False,
                }
            }
                
    # Unreserve Moveline Reserved Locations
    def write(self, vals):
        for record in self:
            old_location = record.location_dest_id
            move_line_orig_locations = {
                line.id: line.location_dest_id for line in record.move_line_ids
            }
    
            res = super(transfer_locations, record).write(vals)
    
            if 'location_dest_id' in vals:
                if record.picking_type_id.code == 'incoming':
                    for line in record.move_line_ids:
                        old_dest = move_line_orig_locations.get(line.id)
                        if old_dest:
                            old_dest.write({
                                'x_studio_is_reserved': False,
                                'x_studio_receiving_report_id': False
                            })
    
            return res


    def get_branch_from_location(self, type=None):
        """Returns 'ANNEX' if 2nd from root is 'A', 'MAIN' if it's 'M', otherwise returns the name."""
        for rec in self:
            if type == 'RR':
                loc = rec.location_dest_id
            else:
                loc = rec.location_id
            hierarchy = []
            while loc:
                hierarchy.append(loc)
                loc = loc.location_id
            # Go from root to leaf
            reversed_hierarchy = hierarchy[::-1]
            if len(reversed_hierarchy) >= 2:
                second_from_root = reversed_hierarchy[1]
                if second_from_root.name == 'A':
                    return 'ANNEX'
                elif second_from_root.name == 'M':
                    return 'MAIN'
                else:
                    return second_from_root.name
            return ''
            
    # @api.depends('move_line_ids.lot_id')
    def _compute_quant_count(self):
        for picking in self:
            lot_ids = picking.move_line_ids.mapped('lot_id.id')  # Get lot/serial numbers

            domain = []
            is_blast_freeze, is_receiving = picking.operation_type_checker(picking.picking_type_id)
            if picking.picking_type_id.code == 'incoming':
                domain = [('lot_id', 'in', lot_ids), ('package_id', '!=', False)]
            elif picking.picking_type_id.code == 'outgoing' and not is_blast_freeze:
                child_location_ids = self.env['stock.location'].search([
                    ('id', 'child_of', picking.location_id.id)
                ]).ids
                domain = [
                    ('location_id', 'in', child_location_ids),
                    ('owner_id', '=', picking.partner_id.id if picking.partner_id else False),
                    ('package_id', '!=', False),
                    ('lot_id', '!=', False),
                    ('lot_id', 'not in', lot_ids),
                    ('quantity', '!=', 0),
                    # ('x_studio_record_reference', '!=', False),
                    ('id', 'not in', picking.move_line_ids.mapped('computed_quant_id.id'))
                ]
            elif picking.picking_type_id.code == 'outgoing' and is_blast_freeze:
                child_location_ids = self.env['stock.location'].search([
                    ('id', 'child_of', picking.location_id.id)
                ]).ids
                domain = [
                    ('location_id', 'in', child_location_ids),
                    ('owner_id', '=', picking.partner_id.id if picking.partner_id else False),
                    # ('package_id', '!=', False),
                    ('lot_id', '!=', False),
                    ('lot_id', 'not in', lot_ids),
                    ('quantity', '!=', 0),
                    # ('x_studio_record_reference', '!=', False),
                    ('id', 'not in', picking.move_line_ids.mapped('computed_quant_id.id'))
                ]
            # Compute count based on filtered quants
            picking.quant_count = self.env['stock.quant'].search_count(domain)
           

    def action_open_related_quant(self):
        """ Action for the smart button to open stock quants related to this picking using lot/serial numbers """
        self.ensure_one()
        lot_ids = self.move_line_ids.mapped('lot_id.id')
        domain = []
        is_blast_freeze, is_receiving = self.operation_type_checker(self.picking_type_id)
        if self.picking_type_id.code == 'incoming':
            domain = [('lot_id', 'in', lot_ids), ('package_id', '!=', False )]
        elif self.picking_type_id.code == 'outgoing' and not is_blast_freeze:
            child_location_ids = self.env['stock.location'].search([
                    ('id', 'child_of', self.location_id.id)
                ]).ids
            domain = [
                ('location_id', 'in', child_location_ids),  # Get all child locations, including self
                ('owner_id', '=', self.partner_id.id if self.partner_id else False),
                ('lot_id', 'not in', lot_ids),
                ('quantity', '!=', 0),
                ('package_id', '!=', False), ('lot_id', '!=', False),
                # ('x_studio_record_reference', '!=', False),
                ('id', 'not in', self.move_line_ids.mapped('computed_quant_id.id'))]

        elif self.picking_type_id.code == 'outgoing' and is_blast_freeze:
            child_location_ids = self.env['stock.location'].search([
                                ('id', 'child_of', self.location_id.id)
                            ]).ids
            domain = [
                ('location_id', 'in', child_location_ids),  # Get all child locations, including self
                ('owner_id', '=', self.partner_id.id if self.partner_id else False),
                ('lot_id', 'not in', lot_ids),
                ('quantity', '!=', 0),
                # ('package_id', '!=', False),
                ('lot_id', '!=', False),
                # ('x_studio_record_reference', '!=', False),
                ('id', 'not in', self.move_line_ids.mapped('computed_quant_id.id'))]
            
        return {
            'name': 'Stock Quants',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree',
            'res_model': 'stock.quant',
            'view_id': self.env.ref('multiple_relocation.view_stock_quant_tree_custom_2').id,  # Specify the editable tree view
            'domain': domain,
            'context': {'create': False, 'picking_id': self.id, 'state': self.state},
        }
        
    
    @api.depends('location_id', 'location_dest_id', 'truck_type')
    def _compute_allowed_product_ids(self):
        for record in self:
            # Reset allowed product IDs
            record.allowed_product_ids = False

            if record.state == 'done' or not record.partner_id:
                continue

            
            if record.picking_type_code == 'outgoing':
                # Find all quants in the current location and its child locations
                child_locations = self.env['stock.location'].search([('id', 'child_of', record.location_id.id)])
                
                # Search quants where owner_id matches the picking's owner_id
                quants = self.env['stock.quant'].search([
                    ('location_id', 'in', child_locations.ids),
                    ('owner_id', '=', record.owner_id.id),  # Filter by owner_id
                    ('available_quantity', '>', 0)
                ])

                
                # Map the quants to product_ids
                allowed_product_ids = quants.mapped('product_id')
                
                # Set the allowed product ids in Many2many format
                record.allowed_product_ids = [(6, 0, allowed_product_ids.ids)]
   
            else:
                record.allowed_product_ids = self.env['product.product'].search([('sale_ok', '!=', False)])
            
    
        
    def action_return_packages(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Return Packages',
            'res_model': 'return.package.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('multiple_relocation.view_return_package_wizard_form').id,
            'target': 'new',  # 'new' opens in a modal popup, 'self' opens in the same window
            'context': {
                'default_picking_id': self.id,  # Pass the current picking_id to the wizard
                'is_for_revision': self.x_studio_for_revision,
                'default_warehouse_id': self.picking_type_id.warehouse_id.id,
                'voided': self.x_studio_voided
            },
        }
        
    @api.onchange('location_id', 'location_dest_id')
    def _onchange_locations(self):
        (self.move_ids | self.move_ids_without_package).update({
            "location_id": self.location_id,
            "location_dest_id": self.location_dest_id
        })
        # Unreserve onchange
            
            
                    
        if self._origin.location_id != self.location_id and any(line.quantity for line in self.move_ids.move_line_ids):
            self.move_ids.move_line_ids = [(5, 0, 0)]
            return {'warning': {
                    'title': _("Locations to update"),
                    'message': _("You might want to update the locations of this transfer's operations")
                    }
            }
            
    @api.onchange('location_dest_id')
    def _onchange_locations_receipt(self):
        for record in self:
            
           if record.picking_type_id and record.picking_type_code == 'incoming':
                for move_lines in record.move_line_ids:
                    location_dest_id = move_lines.location_dest_id
                    
                    location_dest_id.x_studio_is_reserved = False
                    location_dest_id.x_studio_receiving_report_id = ""

    @api.onchange('result_package_id')
    def _onchange_pallet_receipt(self):
        for record in self:
            if record.picking_type_id and record.picking_type_code == 'incoming':
                for move_lines in record.move_line_ids:
                    if move_lines.result_package_id:
                        move_lines.result_package_id.x_studio_is_reserved = False
            

    def action_detailed_operations(self):
        view_id = self.env.ref('stock.view_stock_move_line_detailed_operation_tree').id
        return {
            'name': _('Detailed Operations'),
            'view_mode': 'tree',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line',
            'views': [(view_id, 'tree')],
            'domain': [('id', 'in', self.move_line_ids.ids)],
            'context': {
                'create': self.state != 'done' or not self.is_locked,
                'default_picking_id': self.id,
                'default_location_id': self.location_id.id,
                'default_location_dest_id': self.location_dest_id.id,
                'default_company_id': self.company_id.id,
                'show_lots_text': self.show_lots_text,
                'picking_code': self.picking_type_code,
                'picking_type_code': self.picking_type_code,
                'picking_type_id': self.picking_type_id.id,
                # 'x_studio_is_reserved': self.x_studio_is_reserved,
                'x_studio_verified': self.x_studio_verified,
                'x_studio_record_lines_counter': self.x_studio_record_lines_counter,
                'state': self.state,
                'is_blast_freeze': self.x_studio_is_a_blast_freezer,
                # 'parent_location': self.location_dest_id,
            },
            'target': 'current'
        }
        

        
    def multiple_products_in_one_pallet(self):    
        locs_and_pallets_expiration = []
        move_lines = self.move_line_ids
        conflicting_pallets = {}  # To store conflicting products for each pallet
    
        for line in move_lines:
            location, package = line.location_dest_id, line.result_package_id
    
            # Check if the package (pallet) is already in our tracker
            for data in locs_and_pallets_expiration:
                if line.result_package_id.id and data['package_id'] == line.result_package_id.id and data['product_id'] != line.product_id.id:
                    # Store the conflicting products in a dictionary with pallet id as key
                    if line.result_package_id.name not in conflicting_pallets:
                        conflicting_pallets[line.result_package_id.name] = [data['display_name']]
                    
                    # Add the current product to the conflict list if it's not already added
                    if line.product_id.display_name not in conflicting_pallets[line.result_package_id.name]:
                        conflicting_pallets[line.result_package_id.name].append(line.product_id.display_name)
            
            # Track the current line's package and product details
            locs_and_pallets_expiration.append({
                'location_id': location.id,
                'package_id': package.id,
                'product_id': line.product_id.id,
                'display_name': line.product_id.display_name,
                'x_studio_production_date': line.x_studio_production_date,
                'x_studio_expiration_date': line.x_studio_expiration_date,
                'x_studio_container_number': line.x_studio_container_number,
            })
    
        # If any conflicting pallets are found, raise an error
        if conflicting_pallets:
            conflict_messages = []
            for pallet, products in conflicting_pallets.items():
                product_list = ", ".join(products)
                conflict_messages.append(f"• Pallet: '{pallet}' contains multiple products: {product_list}")

            
            # Use \n to create line breaks
            self.gentle_reminder = "Reminder:\n" + "\n".join(conflict_messages) + "\n\nAre you sure you want to insert each line of multiple products into a single pallet?"
        else:
            self.gentle_reminder = ""

  



            
         
    
    @api.depends('x_studio_is_a_blast_freezer', 'partner_id', 'x_studio_warehouse_sh', 'x_studio_preferred_locations')
    def _compute_allowed_value_ids(self):
        for record in self:
            if record.state == 'done' or not record.partner_id:
                record.allowed_value_ids = []
                continue
    
            if record.picking_type_code == 'outgoing':
                if record.x_studio_is_a_blast_freezer:
                    locations_with_partner_quants = self.env['stock.quant'].search([
                        ('owner_id', '=', record.partner_id.id),
                        ('location_id.x_studio_is_a_blast_freezer', '=', True)
                    ]).mapped('location_id.id')
                    
                    record.allowed_value_ids = self.env['stock.location'].browse(locations_with_partner_quants)
                else:
                    allowed_locations = self.env["stock.location"].search([
                        "&", 
                        "|", 
                        "|", 
                        "|", 
                        "|",
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by", "=", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by", "=", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.x_studio_occupied_by", "=", record.partner_id.id),
                        ("child_ids.child_ids.x_studio_occupied_by", "=", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by", "=", record.partner_id.id),
                        ("warehouse_id.code", "=", record.x_studio_warehouse_sh)
                    ])
                    record.allowed_value_ids = allowed_locations
    
            elif record.picking_type_code == 'incoming':
                if record.x_studio_is_a_blast_freezer:
                    record.allowed_value_ids = self.env['stock.location'].search(['|', ('x_studio_is_a_blast_freezer', '=', True), ('name', '=', 'BF'), ('warehouse_id.id', '=', record.partner_id.x_studio_warehouse.id)])
                else:
                    domain = [
                        '&',
                        ('child_ids.child_ids', '!=', False),
                        ('name', '!=', 'Stock'),
                        ('warehouse_id.code', '=', record.x_studio_warehouse_sh),
                        ('location_id.location_id', '!=', False),
                        ('name', 'not ilike', "BF"),

                    ]
                    
                    # If there are preferred locations, add the filter for preferred locations
                    if record.x_studio_preferred_locations:
                        domain += [
                            '|',
                            ('location_id', 'in', record.x_studio_preferred_locations.ids),
                            '|',
                            ('location_id.location_id', 'in', record.x_studio_preferred_locations.ids),
                            ('location_id.location_id.location_id', 'in', record.x_studio_preferred_locations.ids),
                        ]
                    
                    # Perform the search with the updated domain
                    record.allowed_value_ids = self.env['stock.location'].search(domain)
    
            else:
                record.allowed_value_ids = []


    def has_generated_an_ncr(self):
        self.x_studio_has_generated_an_ncr = True
        return 
    # Call on Adjustment Report Remarks
    
    # @api.onchange('x_studio_hidden_field')
    def GetRemarks(self):
        Remarks = []
        
        for msg in self.message_ids:
            if msg.body and msg.mail_activity_type_id.name == "Request for Revision":
                div_match = re.search(r'<div>(.*?)</div>', msg.body, re.DOTALL)
                div_count = len(re.findall(r'<div>', msg.body))
                if div_match and div_count > 1:
                    div_content = div_match.group(1)
                    # Check if div_content contains o_mail_note_title
                    if 'o_mail_note_title' not in div_content:
                        cleaned_content = re.sub(r'<br\s*/?>', '\n', div_content)  # Replace <br> tags with newlines
                        cleaned_content = re.sub(r'\s*\n\s*', '\n', cleaned_content).strip()  # Remove extra whitespace around newlines
                        Remarks.append(cleaned_content)
                elif div_count == 1:
                    Remarks.append("----")
        
        return Remarks

    # This doesnt include the product and quantity modification
    # @api.onchange('x_studio_hidden_field')
    def AuditTrail(self):
        Values = []
        
        # Ensure the record has a validation date
        if not self.date_done:
            return ""
        
        # Filter messages where tracking_value_ids exists and field name contains 'x_studio'
        filtered_messages = [
            msg for msg in self.message_ids
            if msg.tracking_value_ids
            and any(
                hasattr(tracking_value, 'field_id')
                and isinstance(tracking_value.field_id.name, str)
                and 'x_studio' in tracking_value.field_id.name
                and any(
                    getattr(tracking_value, field, False)
                    for field in ['old_value_text', 'old_value_integer', 'old_value_float', 'old_value_datetime', 'old_value_char']
                )
                for tracking_value in msg.tracking_value_ids
            )
        ]
        
        # Define fields in priority order
        fields = ['old_value_text', 'old_value_integer', 'old_value_float', 'old_value_datetime', 'old_value_char']
        new_fields = ['new_value_text', 'new_value_integer', 'new_value_float', 'new_value_datetime', 'new_value_char']
        
        # Retrieve the value with old value
        for msg in filtered_messages:
            for tracking_value in msg.tracking_value_ids:
                # Exclude changes made before the record was validated
                if tracking_value.create_date < self.date_done:
                    continue  # Skip this change
                
                for field, new_field in zip(fields, new_fields):
                    old_value = getattr(tracking_value, field, None)
                    new_value = getattr(tracking_value, new_field, None)
                    if old_value or new_value:
                        Values.insert(0, {
                            'field': tracking_value.field_id.field_description,
                            'old_value': old_value,
                            'new_value': new_value if new_value else None
                        })
        
        # Handle adjustment form series
        if not self.x_studio_set_adjustment_series:
            adjustment_form_series = self.env['ir.sequence'].search([('code', '=', 'adjustment.form.series')], limit=1)
            if not adjustment_form_series:
                raise UserError("Adjustment Form Series sequence not found.")
            
            # Get and increment the next number in the sequence
            next_number = adjustment_form_series.next_by_id()
            self.x_studio_set_adjustment_series = next_number
        
        return Values



class ResPartner(models.Model):
    _inherit = 'res.partner'

    # JSON field to store pallet series IDs
    unused_pallet_series_ids = fields.Json("Unused Pallet Series IDs", default=[])

    def push_unused_pallet(self, pallet_series_id):
        # Extract the integer part after the hyphen
        try:
            series_number = int(pallet_series_id.split('-')[-1])
        except (ValueError, IndexError):
            # raise UserError("Invalid pallet series ID format. Expected format: 'JBL-<integer>'")
            return

        # Get the current list of IDs or initialize it as an empty list if None
        pallet_series_list = self.unused_pallet_series_ids or []

        # Add the new series number if it's not already in the list
        if series_number not in pallet_series_list:
            pallet_series_list.append(series_number)
        
        # Sort the list in ascending order
        pallet_series_list.sort()

        # Update the JSON field with the sorted list
        self.unused_pallet_series_ids = pallet_series_list


    def get_smallest_pallet_series_ids(self, count):
        # Get the current list of IDs or return an empty list if None
        pallet_series_list = self.unused_pallet_series_ids or []
    
        # Sort the list in ascending order to ensure correct order
        sorted_list = sorted(pallet_series_list)
    
        # Get the first 'count' elements, but not more than the available items in the list
        smallest_ids = sorted_list[:min(count, len(sorted_list))]
        if not self.x_studio_client_unique_code_1:
            raise UserError(f"\nIt seems like Client: {self.name} does NOT have a client unique code set. \n\nPlease set it first before we can generate Pallet Series ID.")
        # Prefix each ID with 'JBL-' and return the list
        formatted_ids = [f"{self.x_studio_client_unique_code_1}-{id}" for id in smallest_ids]
    
        # Remove the used pallet IDs from the original list
        self.unused_pallet_series_ids = [id for id in pallet_series_list if id not in smallest_ids]
    
        return formatted_ids

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Many2many field for product attributes
    attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string='Attribute Values',
        compute='_compute_attribute_value_ids',
        store=True,
    )

    # Link to client expiry table
    client_expiry_table_ids = fields.One2many(
        'client.expiry.table', 'product_template_id', string="Client Expiry Tables"
    )

    uom_id = fields.Many2one(
        'uom.uom', 'Unit of Measure',
        default=lambda self: self.env.ref('uom.product_uom_kgm').id,  
        required=True,
        help="Default unit of measure used for all stock operations."
    )
    @api.depends('attribute_line_ids')
    def _compute_attribute_value_ids(self):
        for template in self:
            template.attribute_value_ids = template.attribute_line_ids.mapped('value_ids')

    @api.onchange('attribute_value_ids')
    def _compute_brand_name_domain(self):
        # Get the IDs of attribute_value_ids
        attribute_ids = self.attribute_value_ids.ids if self.attribute_value_ids else []
        return {'domain': {'x_studio_brand_name': [('id', 'in', attribute_ids)]}}

    @api.onchange('name')
    def _onchange_name(self):
        if not self.name:
            return

        # Normalize name: Remove multiple spaces and convert to lowercase
        trimmed_name = " ".join(self.name.split()).strip().lower()

        # Search for products with similar names
        domain = [('name', 'ilike', self.name)]
        if self.id:
            domain.append(('id', '!=', self.id))  # Exclude the current record

        possible_duplicates = self.env['product.product'].search(domain)
        
        for product in possible_duplicates:
            existing_cleaned_name = " ".join(product.name.split()).strip().lower()
            
            if existing_cleaned_name == trimmed_name:
                raise UserError("The Product Name you input '%s' already exists." % self.name)
            

    @api.model
    def create(self, vals):
        # Convert name to uppercase before saving
        if 'name' in vals and vals['name']:
            vals['name'] = vals['name'].upper()
        return super(ProductTemplate, self).create(vals)

    def write(self, vals):
        # Convert name to uppercase before saving
        if 'name' in vals and vals['name']:
            vals['name'] = vals['name'].upper()
        return super(ProductTemplate, self).write(vals)


class ClientExpiryTable(models.Model):
    _name = 'client.expiry.table'

    # Link to Product Template
    product_template_id = fields.Many2one('product.template', string='Product Template')

    # Many2many field for product attribute values
    line_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string='Product Attributes',
        widget='many2many_tags',  # Tags widget for easy selection
        domain=[]  # Initial empty domain, will be dynamically set
    )

    # Client (partner) field - Many2many for selecting multiple partners
    partner_ids = fields.Many2many('res.partner', string='Client', domain="[('category_id.name', '=', 'Client'), ('is_company', '!=', True)]")

    # Expiry date range for the client and product
    expiry_date_range_id = fields.Many2one('x_inventory_static_var', string='Expiry Date Range', domain="[('x_studio_use_case', '=', 'Expiry Date Range')]")

    # New field to store the available attribute values (acting as a container)
    dynamic_attribute_value_ids = fields.Many2many(
        'product.attribute.value', 
        string='Product Attribute',
        compute='_compute_dynamic_attribute_value_ids',
        store=False
    )

    @api.depends('product_template_id')
    def _compute_dynamic_attribute_value_ids(self):
        for record in self:
            if record.product_template_id:
                # Store the attribute values for the selected product template
                record.dynamic_attribute_value_ids = record.product_template_id.attribute_value_ids

    # @api.onchange('product_template_id')
    # def _onchange_product_template(self):
    #     if self.product_template_id:
    #         # Dynamically set the domain for the line_attribute_value_ids based on the product template's attributes
    #         self.line_attribute_value_ids = [(6, 0, self.dynamic_attribute_value_ids.ids)]






class ProductProduct(models.Model):
    _inherit = 'product.product'

    name = fields.Char(compute='_compute_name', store=True, readonly=False)

    
    @api.depends('product_tmpl_id.name', 'product_template_attribute_value_ids.name', 'product_template_attribute_value_ids.attribute_id.name')
    def _compute_name(self):
        for product in self:
            template_name = product.product_tmpl_id.name or ''
            
            variants = [
                f"{v.attribute_id.name}: {v.name}"
                for v in product.product_template_attribute_value_ids
                if v.attribute_id and v.name
            ]
            if variants:
                product.name = f"{template_name} - ({', '.join(variants)})"
            else:
                product.name = template_name



class StockLocation(models.Model):
    _inherit = 'stock.location'

    def remove_reservation(self):
        for record in self:
            record.x_studio_is_reserved = False
            record.x_studio_receiving_report_id = False



class StockQuantPackages(models.Model):
    _inherit = 'stock.quant.package'

    def remove_reservation(self):
        for record in self:
            record.x_studio_is_reserved = False
            record.x_studio_receiving_report_id = False