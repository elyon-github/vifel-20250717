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
    
    quant_relocation_line_ids = fields.One2many('stock.quant.relocation.line', 'relocate_wizard_id', string='Quant Relocation')

    building = fields.Many2one('x_warehouse_building', string="Building", required=True)
    is_a_blast_freezer = fields.Boolean(
        string="Is Blast Freezer",
        compute='_compute_is_a_blast_freezer')
    allowed_location_ids = fields.Many2many(
        'stock.location',
        string="Allowed Destinations",
        compute='_compute_allowed_location_ids')

    @api.depends('quant_relocation_line_ids.x_studio_is_a_blast_freezer')
    def _compute_is_a_blast_freezer(self):
        # Wizard is BF if any of its lines is BF.
        for wizard in self:
            wizard.is_a_blast_freezer = any(
                line.x_studio_is_a_blast_freezer
                for line in wizard.quant_relocation_line_ids
            )

    @api.depends('building', 'quant_relocation_line_ids.warehouse_id', 'quant_relocation_line_ids.x_studio_is_a_blast_freezer')
    def _compute_allowed_location_ids(self):
        # ONE search per unique (warehouse, BF) key across all lines.
        # - BF quants: any leaf location under the chosen building, regardless
        #   of occupancy or reservation status (BF locations can always be
        #   reused).
        # - Non-BF quants: aisle OR (no receiving report AND empty AND not
        #   reserved).
        Location = self.env['stock.location']
        for wizard in self:
            if not wizard.building:
                wizard.allowed_location_ids = Location
                continue
            keys = {(line.warehouse_id.id, bool(line.x_studio_is_a_blast_freezer))
                    for line in wizard.quant_relocation_line_ids if line.warehouse_id}
            if not keys:
                wizard.allowed_location_ids = Location
                continue
            result = Location
            for wh_id, is_bf in keys:
                base_domain = [
                    ('child_ids', '=', False),
                    ('location_id.location_id.location_id.location_id', '!=', False),
                    ('warehouse_id', '=', wh_id),
                    ('x_studio_building', '=', wizard.building.id),
                    ('x_studio_is_a_blast_freezer', '=', is_bf),
                ]
                if not is_bf:
                    base_domain += [
                        '|',
                            ('x_studio_is_an_aisle', '=', True),
                            '&', '&',
                                ('x_studio_receiving_report_id', '=', False),
                                '|',
                                    ('x_studio_total_quantity', '=', 0),
                                    ('x_studio_total_quantity', '=', False),
                                ('x_studio_is_reserved', '=', False),
                    ]
                result |= Location.search(base_domain)
            wizard.allowed_location_ids = result
    
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        
        # Get selected quants from context
        quant_ids = self.env.context.get('active_ids', [])
        if not quant_ids:
            raise UserError(_("Please select at least one stock quant to correct."))
            
        # Validate selected quants
        quants = self.env['stock.quant'].browse(quant_ids)
        
        # Check for reserved quantities in selected quants
        reserved_quants = quants.filtered(lambda q: q.reserved_quantity > 0)
        if reserved_quants:
            raise UserError(_("Cannot relocate Pallets with reserved Quantities. "
                            "Please unreserve the following Pallets first:\n%s") % 
                          '\n'.join(reserved_quants.mapped('product_id.name')))
        
        # ============================================
        # Auto-include missing quants from same package
        # ============================================
        package_ids = quants.mapped('package_id').filtered(lambda p: p)
        
        all_quants_to_include = quants
        
        for package in package_ids:
            # Find ALL quants for this package
            all_package_quants = self.env['stock.quant'].search([
                ('package_id', '=', package.id),
                ('quantity', '>', 0)
            ])
            
            # Add missing quants using |= to avoid duplicates
            all_quants_to_include |= all_package_quants
        
        # Check for reserved quantities in auto-included quants
        reserved_quants = all_quants_to_include.filtered(lambda q: q.reserved_quantity > 0)
        if reserved_quants:
            raise UserError(_("Cannot relocate Pallets with reserved Quantities. "
                            "Please unreserve the following Pallets first:\n%s") % 
                          '\n'.join(reserved_quants.mapped('product_id.name')))
        
        # Set the quant_ids field with all quants (original + auto-added)
        res['quant_ids'] = [(6, 0, all_quants_to_include.ids)]
        
        # Create wizard lines with proper sequence
        line_vals = []
        for sequence_num, quant in enumerate(all_quants_to_include, start=1):
            line_vals.append({
                'sequence': sequence_num,
                'quant_id': quant.id,
                'owner_id': quant.owner_id.id,
                'product_id': quant.product_id.id,
                'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
                'package_id': quant.package_id.id,
                'current_location': quant.location_id.id,
                'new_location': quant.x_studio_dest_relocation,
                'x_studio_production_date': quant.x_studio_production_date,
                'x_studio_expiration_date': quant.x_studio_expiration_date,
                'x_studio_2nd_uom': quant.x_studio_2nd_uom,
                'x_studio_quantity_uom': quant.x_studio_quantity_uom.id,
                'x_studio_total_units': quant.x_studio_total_units,
                'x_studio_min_quantity_uom': quant.x_studio_min_quantity_uom.id,
                'quantity': quant.quantity,
            })
        
        res['quant_relocation_line_ids'] = [(0, 0, vals) for vals in line_vals]
        return res
    
    
    def _validate_new_locations_set(self):
        """Validate that all lines have a new location set"""
        errors = []
        for line in self.quant_relocation_line_ids:
            if not line.new_location:
                errors.append(f"Line #{line.sequence}: Pallet {line.x_studio_pallet_series_id or 'N/A'} - Missing new location")
        return errors
    
    
    def _validate_reserved_and_conflicting_locations(self):
        """Check if locations are reserved by system or conflicting within wizard"""
        errors = []
        reserved_by_system = {}
        conflicting_lines = {}
        
        # Check for system-reserved locations
        for line in self.quant_relocation_line_ids:
            if line.new_location and line.new_location.x_studio_is_reserved:
                if hasattr(line.new_location, 'x_studio_receiving_report_id') and line.new_location.x_studio_receiving_report_id:
                    if line.new_location.id not in reserved_by_system:
                        reserved_by_system[line.new_location.id] = {
                            'location': line.new_location,
                            'lines': []
                        }
                    reserved_by_system[line.new_location.id]['lines'].append(line)
        
        # Check for conflicts within the wizard
        location_usage = {}
        for line in self.quant_relocation_line_ids:
            if line.new_location:
                if line.new_location.id not in location_usage:
                    location_usage[line.new_location.id] = {
                        'location': line.new_location,
                        'lines': []
                    }
                location_usage[line.new_location.id]['lines'].append(line)
        
        # Find locations used by multiple lines (conflicts)
        for loc_id, data in location_usage.items():
            if len(data['lines']) > 1:
                packages = set([l.package_id.id for l in data['lines'] if l.package_id])
                if len(packages) > 1 or not packages:
                    conflicting_lines[loc_id] = data
        
        # Create error messages
        for loc_id, data in reserved_by_system.items():
            line_numbers = ', '.join([f"#{l.sequence}" for l in data['lines']])
            errors.append(f"Location '{data['location'].vifel_location_name}' is already reserved for incoming stock. Cannot use in Line(s): {line_numbers}")
        
        for loc_id, data in conflicting_lines.items():
            line_numbers = ', '.join([f"#{l.sequence}" for l in data['lines']])
            if not data['location'].x_studio_is_an_aisle:
                errors.append(f"Location '{data['location'].vifel_location_name}' selected multiple times. Conflicting Line(s): {line_numbers}")
        
        return errors
    
    
    def _validate_package_split(self):
        """Check that packages are not split across different locations"""
        errors = []
        package_location_map = {}
        
        for line in self.quant_relocation_line_ids:
            if line.package_id and line.new_location:
                if line.package_id.id in package_location_map:
                    prev_location = package_location_map[line.package_id.id]['location']
                    prev_line = package_location_map[line.package_id.id]['line']
                    if prev_location.id != line.new_location.id:
                        errors.append(
                            f"Line #{line.sequence}: Package '{line.package_id.name}' cannot be split - "
                            f"it's already assigned to '{prev_location.vifel_location_name}' in Line #{prev_line.sequence}. "
                            f"All items in the same package must go to the same location."
                        )
                else:
                    package_location_map[line.package_id.id] = {
                        'location': line.new_location,
                        'line': line
                    }
        
        return errors
    
    
    def _log_multiple_packages_per_location(self):
        """Log warning when multiple packages are going to same location"""
        location_package_map = {}
        
        for line in self.quant_relocation_line_ids:
            if line.new_location and line.package_id:
                if line.new_location.id not in location_package_map:
                    location_package_map[line.new_location.id] = []
                if line.package_id.id not in [p.id for p in location_package_map[line.new_location.id]]:
                    location_package_map[line.new_location.id].append(line.package_id)
        
        for loc_id, packages in location_package_map.items():
            if len(packages) > 1:
                location = self.env['stock.location'].browse(loc_id)
                package_names = ', '.join([p.name for p in packages])
                _logger.info(f"Location '{location.vifel_location_name}' will contain multiple packages: {package_names}")
    
    
    def _validate_location_suitability(self):
        """Validate that locations are suitable (not view, active, etc)"""
        errors = []
        view_locations = {}
        inactive_locations = {}
        
        for line in self.quant_relocation_line_ids:
            if line.new_location:
                if line.new_location.usage == 'view':
                    if line.new_location.id not in view_locations:
                        view_locations[line.new_location.id] = {
                            'location': line.new_location,
                            'lines': []
                        }
                    view_locations[line.new_location.id]['lines'].append(line)
                
                if not line.new_location.active:
                    if line.new_location.id not in inactive_locations:
                        inactive_locations[line.new_location.id] = {
                            'location': line.new_location,
                            'lines': []
                        }
                    inactive_locations[line.new_location.id]['lines'].append(line)
        
        for loc_id, data in view_locations.items():
            line_numbers = ', '.join([f"#{l.sequence}" for l in data['lines']])
            errors.append(f"Cannot relocate to '{data['location'].vifel_location_name}' - it's a view location. Used in Line(s): {line_numbers}")
        
        for loc_id, data in inactive_locations.items():
            line_numbers = ', '.join([f"#{l.sequence}" for l in data['lines']])
            errors.append(f"Location '{data['location'].vifel_location_name}' is inactive. Used in Line(s): {line_numbers}")
        
        return errors
    
    
    def _validate_same_location_relocation(self):
        """Check if new location is same as current location"""
        errors = []
        same_locations = {}
        
        for line in self.quant_relocation_line_ids:
            if line.new_location and line.current_location:
                if line.new_location.id == line.current_location.id:
                    if line.current_location.id not in same_locations:
                        same_locations[line.current_location.id] = {
                            'location': line.current_location,
                            'lines': []
                        }
                    same_locations[line.current_location.id]['lines'].append(line)
        
        for loc_id, data in same_locations.items():
            line_numbers = ', '.join([f"#{l.sequence}" for l in data['lines']])
            errors.append(f"New location is the same as current location '{data['location'].vifel_location_name}'. Used in Line(s): {line_numbers}")
        
        return errors
    
    
    def _update_destination_locations(self):
        """Write destination locations to quant records"""
        for line in self.quant_relocation_line_ids:
            line.quant_id.write({
                'x_studio_dest_relocation': line.new_location.id
            })
    
    
    def _validate_quants_before_relocation(self):
        """Validate quants for special holding, reserved quantities, and missing destinations"""
        for quant in self.quant_ids:
            if quant.x_studio_special_holding:
                raise UserError('\nYou cannot relocate pallets that are on Special Holding State')
            
            if quant.reserved_quantity > 0:
                raise UserError(
                    f"\nRecord with a Product of {quant.product_id.display_name} and a Pallet of {quant.package_id.name} "
                    f"seems to have quantities reserved on a picking record. Please release them before relocating the stock record."
                )
            
            if not quant.x_studio_dest_relocation and not quant.x_studio_dest_relocation.x_studio_is_an_aisle:
                raise UserError(f"It seems like a record with a Pallet Series ID of {quant.x_studio_pallet_series_id} has no Relocation Location set.")
            
            # Check if there are other quants with the same package that don't have relocation location set
            if quant.package_id:
                other_quants = self.env['stock.quant'].search([
                    ('package_id', '=', quant.package_id.id),
                    ('quantity', '!=', 0),
                    ('id', '!=', quant.id),
                    ('x_studio_dest_relocation', '=', False)
                ])
                
                quants_without_dest = other_quants.filtered(
                    lambda q: not q.x_studio_dest_relocation or not q.x_studio_dest_relocation.x_studio_is_an_aisle
                )
                
                if quants_without_dest:
                    error_msg = f"\nPallet '{quant.package_id.name}' has other quants without a relocation destination set:\n\n"
                    for q in quants_without_dest:
                        error_msg += f"  • Product: {q.product_id.display_name}\n"
                        error_msg += f"    Location: {q.location_id.vifel_location_name}\n"
                        error_msg += f"    Quantity: {q.quantity}\n"
                        error_msg += f"    Pallet Series ID: {q.x_studio_pallet_series_id}\n\n"
                    error_msg += "Please set relocation destinations for all quants in this pallet before proceeding."
                    raise UserError(error_msg)
    
    
    def _perform_relocation(self, x_reloc_batch_number):
        """Group and relocate quants"""
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
                
                # Move quants as a group
                quants.move_quants(
                    location_dest_id=dest_location_id,
                    package_dest_id=self.dest_package_id,
                    message=self.message,
                    warehouseman=self.warehouseman,
                    x_reloc_batch_number=x_reloc_batch_number,
                    x_studio_pallet_series_id=quants[0].x_studio_pallet_series_id,
                    bf_pallet_char=quants[0].bf_pallet_char
                )
    
    
    def _handle_post_relocation_actions(self):
        """Handle lot and product actions after relocation"""
        lot_ids = self.quant_ids.mapped('lot_id')
        product_ids = self.quant_ids.mapped('product_id')
    
        if self.env.context.get('default_lot_id', False) and len(lot_ids) == 1:
            lot_ids.action_lot_open_quants()
        elif self.env.context.get('single_product', False) and len(product_ids) == 1:
            product_ids.action_update_quantity_on_hand()
    
    
    def action_relocate_quants(self):
        """Main relocation function - orchestrates all validation and relocation steps"""
        self.ensure_one()
        
        # ============================================
        # VALIDATION PHASE
        # ============================================
        errors = []
        
        # Run all validation checks
        errors.extend(self._validate_new_locations_set())
        errors.extend(self._validate_reserved_and_conflicting_locations())
        errors.extend(self._validate_package_split())
        errors.extend(self._validate_location_suitability())
        errors.extend(self._validate_same_location_relocation())
        
        # Log warnings (non-blocking)
        self._log_multiple_packages_per_location()
        
        # If there are any errors, raise them all at once
        if errors and self.quant_relocation_line_ids and not self.quant_relocation_line_ids[0].quant_id.x_studio_record_reference.x_studio_is_a_blast_freezer:
            error_msg = "❌ Relocation Validation Failed:\n\n" + "\n".join([f"  • {err}" for err in errors])
            raise UserError(error_msg)
        
        # ============================================
        # WRITE PHASE
        # ============================================
        self._update_destination_locations()
        
        # ============================================
        # RELOCATION LOGIC
        # ============================================
        relocation_form_series = self.env['ir.sequence'].search([('code', '=', 'relocate.form.series')], limit=1)
        x_reloc_batch_number = relocation_form_series.next_by_id()
        
        # Original quant check logic (preserved)
        quanties = self.env['stock.quant'].search([("package_id.id", "!=", False)])
        for quant in quanties:
            for line_quants in self.quant_ids:
                if line_quants.x_studio_dest_relocation.id == quant.location_id.id and not quant.x_studio_dest_relocation.id and not line_quants.x_studio_dest_relocation.x_studio_is_an_aisle:
                    pass
        
        # Validate quants before relocation
        self._validate_quants_before_relocation()
        
        # Perform the actual relocation
        self._perform_relocation(x_reloc_batch_number)
        
        # Handle post-relocation actions
        self._handle_post_relocation_actions()



        
    
    # def action_relocate_quants(self):
    #     self.ensure_one()


    #     # First, update the x_studio_dest_relocation field for all quants from wizard lines
    #     for line in self.quant_relocation_line_ids:
    #         if line.new_location:
    #             line.quant_id.write({
    #                 'x_studio_dest_relocation': line.new_location.id
    #             })
    #         else:
    #             raise UserError(_(f"Please set a new location for Pallet {line.x_studio_pallet_series_id or 'N/A'}"))
                
    #     relocation_form_series = self.env['ir.sequence'].search([('code', '=', 'relocate.form.series')], limit=1)
    #     x_reloc_batch_number = relocation_form_series.next_by_id()

        
    #     quanties = self.env['stock.quant'].search([("package_id.id", "!=", False)])
        
    #     for quant in quanties:
    #         for line_quants in self.quant_ids:
    #             if line_quants.x_studio_dest_relocation.id == quant.location_id.id and not quant.x_studio_dest_relocation.id and not line_quants.x_studio_dest_relocation.x_studio_is_an_aisle:
                    
    #                 pass
        
    #     for quant in self.quant_ids:
    #         if quant.x_studio_special_holding:
    #             raise UserError('\nYou cannot relocate pallets that are on Special Holding State')
    #         if quant.available_quantity != quant.quantity:
    #             raise UserError(f"\nRecord with a Product of {quant.product_id.display_name} and a Pallet of {quant.package_id.name} seems to have quantites reserved on a picking record. Please release them before relocating the stock record.")
        
    #         if not quant.x_studio_dest_relocation and not quant.x_studio_dest_relocation.x_studio_is_an_aisle:
    #             raise UserError(f"It seems like a record with a Pallet Series ID of {quant.x_studio_pallet_series_id} has no Relocation Location set.")

    #         # Check if there are other quants with the same package that don't have relocation location set
    #         if quant.package_id:
    #             other_quants = self.env['stock.quant'].search([
    #                 ('package_id', '=', quant.package_id.id),
    #                 ('quantity', '!=', 0),
    #                 ('id', '!=', quant.id),
    #                 ('x_studio_dest_relocation', '=', False)
    #             ])
                
    #             quants_without_dest = other_quants.filtered(
    #                 lambda q: not q.x_studio_dest_relocation or not q.x_studio_dest_relocation.x_studio_is_an_aisle
    #             )
                
    #             if quants_without_dest:
    #                 error_msg = f"\nPallet '{quant.package_id.name}' has other quants without a relocation destination set:\n\n"
    #                 for q in quants_without_dest:
    #                     error_msg += f"  • Product: {q.product_id.display_name}\n"
    #                     error_msg += f"    Location: {q.location_id.complete_name}\n"
    #                     error_msg += f"    Quantity: {q.quantity}\n"
    #                     error_msg += f"    Pallet Series ID: {q.x_studio_pallet_series_id}\n\n"
    #                 error_msg += "Please set relocation destinations for all quants in this pallet before proceeding."
    #                 raise UserError(error_msg)
                    
    #     # Group quants by package_id and location_id
    #     grouped_quants = {}
    #     for quant in self.quant_ids:
    #         key = (quant.package_id.id, quant.location_id.id)
    #         if key not in grouped_quants:
    #             grouped_quants[key] = self.env['stock.quant']
    #         grouped_quants[key] |= quant
        
    #     for (package_id, location_id), quants in grouped_quants.items():
    #         dest_location_id = quants[0].x_studio_dest_relocation
            
    #         if dest_location_id:
    #             # Handle partial package unpacking first
    #             if self.is_partial_package and not self.dest_package_id:
    #                 quants_to_unpack = quants.filtered(lambda q: not all(sub_q in quants.ids for sub_q in q.package_id.quant_ids.ids))
    #                 for unpack_quant in quants_to_unpack:
    #                     unpack_quant.move_quants(
    #                         location_dest_id=dest_location_id, 
    #                         message=self.message, 
    #                         unpack=True,
    #                         warehouseman=self.warehouseman,
    #                         x_reloc_batch_number=x_reloc_batch_number
    #                     )
    #                 quants -= quants_to_unpack
                
    #             # Move quants as a group - the move_quants method will handle individual field values
    #             quants.move_quants(
    #                 location_dest_id=dest_location_id,
    #                 package_dest_id=self.dest_package_id,
    #                 message=self.message,
    #                 warehouseman=self.warehouseman,
    #                 x_reloc_batch_number=x_reloc_batch_number,
    #                 x_studio_pallet_series_id=quants[0].x_studio_pallet_series_id,
    #                 bf_pallet_char=quants[0].bf_pallet_char
    #             )
            
    
    #     # Handle lot and product actions
    #     lot_ids = self.quant_ids.mapped('lot_id')
    #     product_ids = self.quant_ids.mapped('product_id')
    
    #     if self.env.context.get('default_lot_id', False) and len(lot_ids) == 1:
    #         lot_ids.action_lot_open_quants()
    #     elif self.env.context.get('single_product', False) and len(product_ids) == 1:
    #         product_ids.action_update_quantity_on_hand()


class OverrideStockQuant(models.Model):
    _inherit = 'stock.quant'

    x_studio_special_holding = fields.Boolean()
    bf_pallet_char = fields.Char(string="Pallet # - Text")
    x_studio_for_tth = fields.Boolean(string="Is TTH")
    x_studio_batch = fields.Char(string="Batch #", store=True)
    x_studio_prodcode = fields.Char(string="Prodcode", store=True, compute="_compute_x_studio_prodcode")
    location_is_bf = fields.Boolean(
        string="Location is Blast Freezer",
        related='location_id.x_studio_is_a_blast_freezer',
        store=True, readonly=True)
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
        
    x_studio_aging_days = fields.Integer(
        string='Aging Day/s',
        compute='_compute_aging_days',
        store=True,
        help='Number of days from today to expiration date. Negative values indicate expired items.',
        group_operator='avg'  # or 'max', 'min', 'sum' depending on what makes sense
    )


                
    @api.depends('x_studio_expiration_date', 'x_studio_batch')
    def _compute_x_studio_prodcode(self):
        for record in self:
            record['x_studio_prodcode'] = f"{record.x_studio_expiration_date.strftime('%d%b%Y').upper()}{record.x_studio_batch}{record.location_id.warehouse_id.code}" if record.x_studio_expiration_date and record.x_studio_batch else ''    
    
    @api.onchange('x_studio_dest_relocation')
    def reserve_unreserve_location_onchange(self):
        for record in self:
            previous_location = record._origin.x_studio_dest_relocation

            # Make sure we check the field properly — parentheses in the domain were misplaced
            same_location_relocation = self.env['stock.quant'].search([
                ('x_studio_dest_relocation', '=', previous_location.id), ('id', '!=', record.extract_id_from_newid(record.id))
            ])
        

            # Only attempt to remove reservation if the previous location exists
            # and no other quant record uses the same relocation
            if previous_location and not same_location_relocation:
                previous_location.remove_reservation()
        
            # Mark the new relocation as reserved
            if record.x_studio_dest_relocation:
                record.x_studio_dest_relocation.write({
                    'x_studio_is_reserved': True,
                })



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
            
    @api.depends('x_studio_expiration_date')
    def _compute_aging_days(self):
        """
        Compute aging days based on expiration date (adjusted to UTC+8)
        Positive values: days until expiration
        Negative values: days since expiration (expired)
        """
        # Get today in UTC then shift to UTC+8
        today_utc8 = (datetime.utcnow() + timedelta(hours=8)).date()

        for record in self:
            if record.x_studio_expiration_date:
                # Calculate the difference in days
                delta = record.x_studio_expiration_date - today_utc8
                record.x_studio_aging_days = delta.days
            else:
                # If no expiration date is set, aging days is 0
                record.x_studio_aging_days = 0

    def recompute_aging_days(self):
        """
        Method to recompute aging days for all records
        This will be called by the scheduled action
        """
        # Get all records that have an expiration date
        records_with_expiration = self.search([('x_studio_expiration_date', '!=', False)])
        
        # Force recomputation of the aging days field
        records_with_expiration._compute_aging_days()
        
        return True
    
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
        """ Override to handle the "inventory mode" and create the inventory move. 
        Removed the UserError restriction for quant editing.
        """
        forbidden_fields = self._get_forbidden_fields_write()
        if self._is_inventory_mode() and any(field for field in forbidden_fields if field in vals.keys()):
            if any(quant.location_id.usage == 'inventory' for quant in self):
                # Do nothing when user tries to modify manually a inventory loss
                return self
            # Remove the UserError and just proceed with sudo
            # We skip calling super() here to avoid the original restriction
            from odoo import models
            return models.Model.write(self.sudo(), vals)

        return super().write(vals)
        
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
            ('lot_id', '=', self.lot_id.id),
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
        selected_owners_by_pkg = {}
        for quant in records:
            if not quant.available_quantity:
                continue
            pkg_id = quant.package_id.id
            if pkg_id:
                selected_packages.setdefault(pkg_id, set()).add(quant.id)
                if quant.owner_id:
                    selected_owners_by_pkg.setdefault(pkg_id, set()).add(quant.owner_id.id)

        # For each package, check for missing quants
        all_missing_quants = self.env['stock.quant']
        Quant = self.env['stock.quant']

        for pkg_id, selected_quant_ids in selected_packages.items():
            # Restrict missing-quant suggestions to quants whose owner matches
            # one of the user-selected quants in this package. Quants without
            # an owner_id are excluded (no owner = no match).
            allowed_owner_ids = selected_owners_by_pkg.get(pkg_id, set())
            if not allowed_owner_ids:
                continue

            all_package_quants = Quant.search([
                ('package_id', '=', pkg_id),
                ('x_studio_pallet_series_id', '!=', False),
                ("quantity", ">", 0),
                ('owner_id', 'in', list(allowed_owner_ids)),
            ])

            selected_quant_ids = selected_quant_ids or set()
            all_package_quant_ids = set(all_package_quants.ids)
            missing_ids = all_package_quant_ids - selected_quant_ids

            if missing_ids:
                # Skip quants that are 100% reserved/picked by another transfer
                # (available_quantity <= 0). The user can't add them anyway, so
                # there's no point flagging the package as "incomplete" because
                # of them.
                missing_quants = all_package_quants.filtered(
                    lambda q: q.id in missing_ids and q.available_quantity > 0
                )
                if missing_quants:
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
                        raise UserError(f"You cannot move the same Pallet into multiple Locations. Relocate to this Location {first_init_loc.vifel_location_name}")
                if self.x_studio_dest_relocation.id == quant.location_id.id:
                    raise UserError("You selected the same location. Please relocate to another location")

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



    def _get_inventory_move_values(self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False, warehouseman=False, x_reloc_batch_number=False, x_studio_pallet_series_id=False, bf_pallet_char=False, x_studio_2nd_uom=False, x_studio_quantity_uom=False):
        """ Called when user manually set a new quantity (via `inventory_quantity`)
        just before creating the corresponding stock move.

        :param location_id: `stock.location`
        :param location_dest_id: `stock.location`
        :param package_id: `stock.quant.package`
        :param package_dest_id: `stock.quant.package`
        :return: dict with all values needed to create a new `stock.move` with its move line.
        """
        # raise UserError(qty)
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
                'adjusted_quantity': qty,
                'location_id': location_id.id,
                'location_dest_id': location_dest_id.id,
                'company_id': self.company_id.id or self.env.company.id,
                'lot_id': self.lot_id.id,
                'package_id': package_id.id if package_id else False,
                'result_package_id': package_dest_id.id if package_dest_id else False,
                'x_studio_2nd_uom': x_studio_2nd_uom if x_studio_2nd_uom else False,
                'x_studio_quantity_uom': x_studio_quantity_uom if x_studio_quantity_uom else False,
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
                quant.bf_pallet_char,
                quant.x_studio_2nd_uom,
                quant.x_studio_quantity_uom.id,
            ))
        
        moves = self.env['stock.move'].create(move_vals)
        moves._action_done()


    reservation_tags = fields.Many2many(
        'stock.picking',  # Adjust comodel_name
        string='Reservation Tags',
        compute='_compute_reservation_tags',
        store=False,
        help="Tags from transfers where this quant was reserved",
        readonly=False
    )
    color = fields.Integer(string="Color")  # standard color field

    @api.depends('lot_id', 'reserved_quantity')
    def _compute_reservation_tags(self):
        for quant in self:
            pickings = self.env['stock.picking']
            
            if quant.lot_id and quant.reserved_quantity > 0:
                # Find move lines that have this quant reserved
                reserved_move_lines = self.env['stock.move.line'].search([
                    ('lot_id', '=', quant.lot_id.id),
                    ('location_id', '=', quant.location_id.id),
                    ('product_id', '=', quant.product_id.id),
                    ('state', 'in', ['assigned', 'partially_available'])
                ])
                
                # Get pickings from reserved move lines
                pickings = reserved_move_lines.mapped('picking_id')
            
            quant.reservation_tags = pickings
