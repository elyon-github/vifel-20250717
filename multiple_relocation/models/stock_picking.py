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

class picking_type(models.Model):
    _inherit = 'stock.picking.type'

    is_blast_freeze_operation = fields.Boolean(string="Is a Blast Freeze Operation?")


class transfer_locations(models.Model):
    _inherit = 'stock.picking'

    next_step_status = fields.Char(compute="_compute_next_step_status", default=lambda self: self._default_next_step_status())
    location_id = fields.Many2one(
        'stock.location', "Source Location",
         store=True,  readonly=False,
        check_company=True, required=True, domain="[('id', 'in', allowed_value_ids)]")

    def _default_next_step_status(self):
        # Get picking_type_id from context
        picking_type_id = self.env.context.get('default_picking_type_id')
        
        if picking_type_id:
            # Search for the record
            picking_type = self.env['stock.picking.type'].browse(picking_type_id)
            is_blast_freeze, is_receiving = self.operation_type_checker(picking_type)
            
            if is_receiving:
                return 'Starting'
            else:
                return 'Set Location'
        
        return 'Starting'
                

    # api.depends('move_ids_without_package.x_studio_number_of_lines')
    def _compute_next_step_status(self):
        for record in self:
            # Default to blank
            record.next_step_status = ''
    
            if record.state == 'done':
                continue
    
            is_blast_freeze, is_receiving = record.operation_type_checker(record.picking_type_id)
    
            if is_receiving:
    
                # Receiving step
                if not record.move_ids_without_package and not record.partner_id:
                    record.next_step_status = 'Starting'
                elif not record.move_line_ids and not record.return_id:
                    # Check if any line is missing number_of_lines
                    if any(not line.x_studio_number_of_lines for line in record.move_ids_without_package) or not record.move_ids_without_package:
                        record.next_step_status = 'Estimate Pallet Lines'
                    else:
                        record.next_step_status = 'Generate Pallet Lines'

                elif not record.move_line_ids and record.return_id:
                    record.next_step_status = 'Go back to wr'
                elif record.move_line_ids and is_blast_freeze:
                    record.next_step_status = 'BF Complete Pallet Details'

                elif record.move_line_ids and record.return_id:
                    record.next_step_status = 'Return RR Complete Pallet Details'
                elif record.move_line_ids and not is_blast_freeze:
                    record.next_step_status = 'RR Complete Pallet Details'

            else:
                active_returns = record.return_ids.filtered(lambda r: r.state != 'cancel')
                if not record.quant_count and not record.move_line_ids:
                    record.next_step_status = 'Set Location'
                elif record.move_line_ids and any(r.state in ['draft', 'ready'] for r in record.return_ids):
                    record.next_step_status = 'Already has return'
                elif record.move_line_ids and not active_returns:
                    record.next_step_status = 'To create return'
                elif not record.move_line_ids:
                    record.next_step_status = 'Select Stocks'
                    
                
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
        'stock.location', compute="_compute_allowed_value_ids", string="Allowed Locations"
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

    show_return_alert = fields.Boolean(
        compute="_compute_show_return_alert",
        store=False
    )

    @api.depends("return_ids.state")
    def _compute_show_return_alert(self):
        for rec in self:
            # True if at least one return_id is in draft or assigned
            rec.show_return_alert = any(
                r.state in ("draft", "assigned") for r in rec.return_ids
            )
    
            
    
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

    def convert_location_string(self, s):
        parts = s.split('/')
        try:
            if len(parts) < 7:
                return s
            
            part_3 = parts[2]
            part_4 = parts[3]
            part_5 = parts[4]
            part_6 = parts[5]
            part_7 = parts[6]
            
            digit = ''.join(filter(str.isdigit, part_7))
            if not digit:
                return s
            
            return f"{part_3}{part_4}{part_5}{part_6}.{digit}"
        
        except Exception:
            return s

    
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
                
                # Find the previous record to start recalculation from
                previous_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search([
                    ('warehouse', '=', warehouse_id),
                    ('is_blast_freezer', '=', is_blast_freezer),
                    ('start_time', '<', start_time),
                    ('active', '=', True)
                ], order='start_time desc', limit=1)
    
                if previous_record:
                    recalc_from_time = previous_record.start_time
                else:
                    recalc_from_time = None  # Recalculate from beginning
    
                # Recalculate running balances from the previous record forward
                pallet_record._recalculate_running_balances(
                    warehouse_id, 
                    is_blast_freezer, 
                    recalc_from_time
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
            
            # Unmark as voided
            record.x_studio_voided = False
            record.x_studio_for_revision = False
            
            # Find the related pallet kilos record that was deactivated during void
            # Search for records that reference this document (either as main reference or readjustment)
            pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].with_context(active_test=False).search([
                '|',
                ('record_reference', '=', record.id),
                ('readjustment_document', '=', record.id)
            ], order='create_date desc', limit=1)
            
            if not pallet_record:
                # If not found by direct reference, search by effective_document
                # This handles cases where the record might have been adjusted
                pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].with_context(active_test=False).search([
                    ('effective_document', '=', record.id)
                ], order='create_date desc', limit=1)
            
            if pallet_record:
                # Store data needed for recalculation
                warehouse_id = pallet_record.warehouse.id
                is_blast_freezer = pallet_record.is_blast_freezer
                start_time = pallet_record.start_time
                
                # Determine how to reactivate based on the record's original structure
                if pallet_record.record_reference.id == record.id:
                    # This record was the main reference - simply reactivate
                    pallet_record.active = True
                    _logger.info("Reactivated pallet kilos record with main reference: %s", record.name)
                    
                elif pallet_record.readjustment_document and pallet_record.readjustment_document.id == record.id:
                    # This record was a readjustment - restore the readjustment link
                    pallet_record.active = True
                    # readjustment_document should already be set to record.id
                    _logger.info("Reactivated pallet kilos record with readjustment reference: %s", record.name)
                    
                else:
                    # Fallback: set as readjustment document and activate
                    pallet_record.readjustment_document = record.id
                    pallet_record.active = True
                    _logger.info("Set as readjustment document and activated pallet kilos record: %s", record.name)
                
                # Refresh the record data after reactivation
                # This is crucial to ensure the data reflects the unvoided document
                pallet_record._populate_vehicle_data()
                pallet_record._populate_operations_data()
                pallet_record._populate_returns_data()
                
                # Find the previous record to start recalculation from
                previous_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search([
                    ('warehouse', '=', warehouse_id),
                    ('is_blast_freezer', '=', is_blast_freezer),
                    ('start_time', '<', start_time),
                    ('active', '=', True)
                ], order='start_time desc', limit=1)
    
                if previous_record:
                    recalc_from_time = previous_record.start_time
                else:
                    recalc_from_time = None  # Recalculate from beginning
    
                # Recalculate running balances from the previous record forward
                pallet_record._recalculate_running_balances(
                    warehouse_id, 
                    is_blast_freezer, 
                    recalc_from_time
                )
                
                _logger.info("Successfully unvoided transfer and restored Pallet Kilos Log: %s", record.name)
            else:
                _logger.error("No pallet kilos record found for transfer: %s. Cannot complete unvoid operation.", record.name)
                raise UserError(_("No associated pallet kilos record found for transfer %s. Cannot unvoid.") % record.name)

    
                
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
            record.action_confirm()

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
            # Fallback (if nothing was processed)
            return {'type': 'ir.actions.client', 'tag': 'reload'}
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
        # Fallback (if nothing was processed)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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

            if not is_receiving and picking.state == 'done':
                picking.quant_count = False
                return
            if picking.picking_type_id.code == 'incoming':
                domain = [('lot_id', 'in', lot_ids), ('package_id', '!=', False)]
            elif picking.picking_type_id.code == 'outgoing' and not is_blast_freeze:
                # child_location_ids = self.env['stock.location'].search([
                #     ('id', 'child_of', picking.location_id.id)
                # ]).ids
                # domain = [
                #     ('location_id', 'in', child_location_ids),
                #     ('owner_id', '=', picking.partner_id.id if picking.partner_id else False),
                #     ('package_id', '!=', False),
                #     ('lot_id', '!=', False),
                #     ('lot_id', 'not in', lot_ids),
                #     ('quantity', '!=', 0),
                #     # ('x_studio_record_reference', '!=', False),
                #     ('id', 'not in', picking.move_line_ids.mapped('computed_quant_id.id'))
                # ]
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
            elif picking.picking_type_id.code == 'outgoing' and is_blast_freeze:
                child_location_ids = self.env['stock.location'].search([
                                    ('id', 'child_of', self.location_id.id)
                                ]).ids
                domain = [
                    ('location_id', 'in', child_location_ids),  # Get all child locations, including self
                    ('owner_id', '=', self.partner_id.id if self.partner_id else False),
                    ('lot_id', 'not in', lot_ids),
                    ('quantity', '>', 0),
                    # ('package_id', '!=', False),
                    ('lot_id', '!=', False),
                    # ('x_studio_record_reference', '!=', False),
                    ('id', 'not in', self.move_line_ids.mapped('computed_quant_id.id'))]
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
                ('quantity', '>', 0),
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
            'domain': [('picking_id', '=', self.id)],
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
                        "&",    # first AND
                        "&",    # second AND (for warehouse + new condition)
                        "|", "|", "|", "|", 
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1", "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1", "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.x_studio_occupied_by_1", "in", record.partner_id.id),
                        ("child_ids.child_ids.x_studio_occupied_by_1", "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1", "in", record.partner_id.id),
                        ("warehouse_id.code", "=", record.x_studio_warehouse_sh),
                        ("child_ids.child_ids.x_studio_is_a_blast_freezer", "=", False)
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

