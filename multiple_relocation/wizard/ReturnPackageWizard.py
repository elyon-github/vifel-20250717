from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)

class ReturnPackageWizardLine(models.TransientModel):
    _name = 'return.package.wizard.line'
    _description = 'Line for Returning Packages'

    wizard_id = fields.Many2one('return.package.wizard', string="Wizard")
    select_package = fields.Boolean(string="Select")
    result_package_id = fields.Many2one('stock.quant.package', string="Pallet #" , domain="[('location_id', '=', False), ('x_studio_is_reserved', '=', False)]")
    pallet_series_id = fields.Char(string='Pallet Series ID')
    bf_pallet_char = fields.Char(string="Pallet # - Text")
    product_id = fields.Many2one('product.product', string="Products")
    quantity = fields.Float(string="Actual Weight (KG)", digits='Product Unit of Measure')
    production_date=fields.Date(string="Production Date")
    expiration_date=fields.Date(string="Expiration Date")
    container_number = fields.Char(string="Container #")
    return_counter = fields.Integer(string="No. of Returns")
    stock_move_line = fields.Integer(string="Move Line ID")
    pack_uom_unit = fields.Float(string="Actual Quantity")
    min_uom_unit = fields.Float(string="Actual Packs")
    location_dest_id = fields.Many2one(
        'stock.location', string="Destination Location",
        domain=[('usage', '=', 'internal'), ('child_ids', '=', False)])
    location_dest_id_is_fallback = fields.Boolean(string="Location is Fallback", default=False)
    result_package_id_is_fallback = fields.Boolean(string="Pallet is Fallback", default=False)
    pack_uom = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    min_uom = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    actual_quantity = fields.Float(string="Original Weight (KG)", digits='Product Unit of Measure')
    actual_pack_uom_unit = fields.Float(string="Original Quantity Unit")
    actual_min_uom_unit = fields.Float(string="Original Packs Unit")
    is_a_blast_freeze = fields.Boolean(related="wizard_id.is_a_blast_freeze")
    has_pack_sync_issue = fields.Boolean(string="Pack UOM Sync Issue", compute="_compute_sync_issues")
    has_min_sync_issue = fields.Boolean(string="Min UOM Sync Issue", compute="_compute_sync_issues")
    has_qty_sync_issue = fields.Boolean(string="Quantity Sync Issue", compute="_compute_sync_issues")
    location_id = fields.Many2one('stock.location')
    picking_id = fields.Many2one('stock.picking')
    pallet_type = fields.Char(string="Pallet Type")
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        related='wizard_id.warehouse_id', readonly=True)
    lot_id = fields.Many2one('stock.lot')
    x_studio_building_dropped = fields.Char(string="Building")
    original_record_reference = fields.Many2one('stock.picking')
    
    @api.onchange('pallet_series_id', 'product_id','pack_uom','min_uom')
    def onchange_fields(self):
        raise UserError("You cannot change values for this field")

    @api.depends('pack_uom_unit', 'min_uom_unit', 'quantity', 
                 'actual_pack_uom_unit', 'actual_min_uom_unit', 'actual_quantity')
    def _compute_sync_issues(self):
        for line in self:
            # Check if pack uom has sync issue (reduced but others not reduced proportionally)
            
            line.has_pack_sync_issue = (
                line.pack_uom_unit < line.actual_pack_uom_unit and
                line.pack_uom_unit == line.actual_pack_uom_unit and 
                line.pack_uom_unit > 0
            )

            # Check if min uom has sync issue
            line.has_min_sync_issue = (
                line.min_uom_unit < line.actual_min_uom_unit and
                line.min_uom_unit == line.actual_min_uom_unit and 
                line.min_uom_unit > 0
            )
            
            # Check if quantity has sync issue
            line.has_qty_sync_issue = (
                line.quantity < line.actual_quantity and
                line.quantity == line.actual_quantity
            )

    @api.onchange('pack_uom_unit', 'min_uom_unit', 'quantity')
    def _validate_field_values(self):
        # Check for negative values
        if self.pack_uom_unit < 0:
            raise ValidationError("Packaging Unit must be a non-negative value.")
        if self.pack_uom_unit > self.actual_pack_uom_unit and self.wizard_id.return_reason != 'Wrong Details Encoded':
            raise ValidationError("Packaging Unit must not be greater than the initial withdrawal.")
        if self.min_uom_unit < 0:
            raise ValidationError("Minimum Unit must be a non-negative value.")
        if self.min_uom_unit > self.actual_min_uom_unit and self.wizard_id.return_reason != 'Wrong Details Encoded':
            raise ValidationError("Minimum Unit must not be greater than the initial withdrawal.")
        if self.quantity < 0:
            raise ValidationError("Quantity must be a non-negative value.")
        if self.quantity > self.actual_quantity and self.wizard_id.return_reason != 'Wrong Details Encoded':
            raise ValidationError("Quantity must not be greater than the initial withdrawal.")


class ReturnPackageWizard(models.TransientModel):
    _name = 'return.package.wizard'
    _description = 'Wizard for Returning Packages'

    package_line_ids = fields.One2many(
        'return.package.wizard.line', 'wizard_id', string="Pallets", readonly=False
    )
    picking_id = fields.Many2one('stock.picking', string="Source Document", readonly=True)
    location_id = fields.Many2one(
        'stock.location', string="Destination Location", readonly=False,
        domain=[('usage', '=', 'internal'), ('child_ids', '=', False)])
    lines_computed = fields.Boolean(string="Lines Computed", default=False, readonly=True)
    picking_type_id = fields.Many2one('stock.picking.type', string="Picking Type", readonly=False)
    is_a_blast_freeze = fields.Boolean(related='picking_id.x_studio_is_a_blast_freezer')
    select_all = fields.Boolean(string="Select All")
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        related='picking_id.picking_type_id.warehouse_id', readonly=True)
    existing_return_picking_id = fields.Many2one('stock.picking', string="Existing Return", compute="_compute_existing_return", readonly=True)
    return_reason = fields.Selection(
    [
        ('Partial Withdraw', 'Partial Withdraw'),
        ('Wrong Details Encoded', 'Wrong Details Encoded'),
        ('Void Transfer', 'Void Transfer'),
        ('Others', 'Others'),
        
    ],
    string="Return Reason",
    required=True
)
    other_reasons = fields.Char(string="Please specify other reasons.")
    has_sync_warnings = fields.Boolean(string="Has Synchronization Warnings", compute="_compute_sync_warnings")
    sync_warning_message = fields.Html(string="Warning Message", compute="_compute_sync_warnings")
    
    @api.depends('picking_id')
    def _compute_existing_return(self):
        """Compute if there's an existing return for this picking"""
        for wizard in self:
            if wizard.picking_id:
                existing_return = wizard._find_existing_return()
                wizard.existing_return_picking_id = existing_return.id if existing_return else False
            else:
                wizard.existing_return_picking_id = False

    @api.onchange('picking_id', 'return_reason')
    def _compute_location_and_packages(self):
        if self.picking_id:
            # Derive the RR header destination from the building preset of the
            # source move lines: move_line.location_id.x_studio_building.x_studio_preset_location
            preset_location_id = False
            for ml in self.picking_id.move_line_ids:
                building = ml.location_id.x_studio_building
                if building and building.x_studio_preset_location:
                    preset_location_id = building.x_studio_preset_location.id
                    break
            self.location_id = preset_location_id or self.picking_id.location_id.id
            
            # Check if there's an existing return and auto-populate fields
            existing_return = self._find_existing_return()
            if existing_return:
                # Auto-populate return reason and other reasons from existing return
                if existing_return.return_reason and not self.return_reason:
                    self.return_reason = existing_return.return_reason
                if existing_return.other_reasons and not self.other_reasons:
                    self.other_reasons = existing_return.other_reasons
            
            # Handle context-based overrides
            if self.env.context.get('is_for_revision'):
                self.return_reason = 'Wrong Details Encoded'

            if self.env.context.get('voided'):
                self.return_reason = 'Void Transfer'
                
            if not self.lines_computed:
                self.package_line_ids = [(5, 0, 0)]
                move_lines = self.picking_id.move_line_ids
                lines = []
                # Lines sharing the same pallet_series_id share the same recommended package;
                # lines with different (or empty) series must get distinct packages.
                series_to_package = {}
                used_package_ids = set()
                for move_line in move_lines:
                    location_dest_id = False
                    pallet_result_id = False
                    result_package_id_is_fallback = False
                    owner_id = self.picking_id.partner_id.id
                    package_occupying_owners = []
                    series_id = move_line.x_studio_pallet_series_id
                    # A source location/package that's already reserved for the existing
                    # return we're appending to is treated as available — no need to fall
                    # back to an aisle or an NP pallet.
                    location_reserved_for_existing = bool(
                        existing_return
                        and move_line.location_id.x_studio_is_reserved
                        and move_line.location_id.x_studio_receiving_report_id
                        and move_line.location_id.x_studio_receiving_report_id.id == existing_return.id
                    )
                    package_reserved_for_existing = bool(
                        existing_return
                        and move_line.package_id
                        and move_line.package_id.x_studio_is_reserved
                        and move_line.package_id.x_studio_receiving_report_id
                        and move_line.package_id.x_studio_receiving_report_id.id == existing_return.id
                    )
                    # PSI-REMAINDER-FIRST: when this pallet series still has
                    # stock in the warehouse (partial withdrawal), the return
                    # MUST land on that remainder's pallet # and location so
                    # the quants merge back into one — same rule as the void
                    # path (_create_return_rr_from_wr).
                    remainder = self.picking_id._find_psi_remainder_quant(
                        move_line.owner_id or self.picking_id.partner_id,
                        series_id, prefer_package=move_line.package_id)
                    if remainder:
                        location_dest_id = remainder.location_id.id
                        pallet_result_id = remainder.package_id.id
                        used_package_ids.add(pallet_result_id)
                        if series_id:
                            series_to_package[series_id] = (
                                pallet_result_id, False)
                    if not location_dest_id and (not move_line.location_id.x_studio_is_reserved or location_reserved_for_existing):
                        occupying_owners = move_line.location_id.x_studio_occupied_by_1.ids
                        package_occupying_owners = (move_line.package_id.quant_ids.mapped('x_studio_pallet_series_id') if move_line.package_id else [])
                        if (location_reserved_for_existing
                                or move_line.owner_id.id in occupying_owners
                                or not move_line.location_id.x_studio_occupied_by_1.ids):
                            location_dest_id = move_line.location_id.id
                        if location_dest_id and move_line.package_id and (
                                package_reserved_for_existing
                                or (move_line.package_id.location_id.id == location_dest_id
                                    and move_line.x_studio_pallet_series_id in package_occupying_owners)):
                            pallet_result_id = move_line.package_id.id

                    # Fallback: if location_dest_id is still blank, find an aisle location under the same building
                    location_dest_id_is_fallback = False
                    if not location_dest_id and move_line.location_id:
                        if move_line.location_id.x_studio_building:
                            # First try: find aisle location in the same building
                            building = move_line.location_id.x_studio_building
                            aisle_location = self.env['stock.location'].search([
                                ('x_studio_is_an_aisle', '=', True),
                                ('x_studio_building', '=', building.id)
                            ], limit=1)
                            if aisle_location:
                                location_dest_id = aisle_location.id
                                location_dest_id_is_fallback = True

                        # Fallback to any aisle location if not found in building
                        if not location_dest_id:
                            aisle_location = self.env['stock.location'].search([
                                ('x_studio_is_an_aisle', '=', True)
                            ], limit=1)
                            if aisle_location:
                                location_dest_id = aisle_location.id
                                location_dest_id_is_fallback = True

                    # Package recommendation: enforce uniqueness across lines, but share
                    # the same package across lines that have the same pallet_series_id.
                    if series_id and series_id in series_to_package:
                        pallet_result_id, result_package_id_is_fallback = series_to_package[series_id]
                    else:
                        # Drop the organic match if that package is already taken by an earlier series
                        if pallet_result_id and pallet_result_id in used_package_ids:
                            pallet_result_id = False

                        # Reuse the original move_line.package_id if it is free
                        # (no location, not reserved) OR if it's already reserved
                        # specifically for the existing return we're appending to.
                        package = move_line.package_id
                        if (not pallet_result_id
                                and package
                                and not package.location_id
                                and package.id not in used_package_ids
                                and (not package.x_studio_is_reserved
                                     or (existing_return
                                         and package.x_studio_receiving_report_id.id == existing_return.id))):
                            pallet_result_id = package.id

                        # Final fallback: pick a fresh unreserved/unlocated "NP" pallet
                        # that hasn't been recommended on an earlier line in this wizard
                        if not pallet_result_id:
                            np_pallet = self.env['stock.quant.package'].search([
                                ('name', 'ilike', 'NP'),
                                ('location_id', '=', False),
                                ('x_studio_is_reserved', '=', False),
                                ('id', 'not in', list(used_package_ids)),
                            ], limit=1)
                            if np_pallet:
                                pallet_result_id = np_pallet.id
                                result_package_id_is_fallback = True

                        if pallet_result_id:
                            used_package_ids.add(pallet_result_id)
                            if series_id:
                                series_to_package[series_id] = (pallet_result_id, result_package_id_is_fallback)
                    
                    if self.return_reason != 'Partial Withdraw':

                                
                        lines.append((0, 0, {
                            'select_package': False,
                            'result_package_id': pallet_result_id,
                            'result_package_id_is_fallback': result_package_id_is_fallback,
                            'location_dest_id': location_dest_id,
                            'location_dest_id_is_fallback': location_dest_id_is_fallback,
                            'pallet_series_id': move_line.x_studio_pallet_series_id,
                            'bf_pallet_char': move_line.bf_pallet_char,
                            'product_id': move_line.product_id.id,
                            'expiration_date': move_line.x_studio_expiration_date,
                            'x_studio_building_dropped': move_line.x_studio_building_dropped,
                            'original_record_reference': move_line.original_record_reference,
                            'production_date': move_line.x_studio_production_date,
                            'lot_id': move_line.lot_id.id,
                            'stock_move_line': move_line.id,
                            'return_counter': move_line.x_studio_return_count,
                            'container_number': move_line.x_studio_container_number,
                            'pack_uom_unit': move_line.x_studio_affected_2nd_uom,
                            'min_uom_unit': move_line.x_studio_withdraw_units,
                            'quantity': move_line.quantity,
                            'pack_uom': move_line.x_studio_quantity_uom_delivery,
                            'min_uom': move_line.x_studio_min_quantity_uom,
                            'actual_pack_uom_unit': move_line.x_studio_affected_2nd_uom,
                            'actual_min_uom_unit': move_line.x_studio_withdraw_units,
                            'actual_quantity': move_line.quantity,
                            'location_id':  self.picking_id.location_id.id,

                        }))
                    else:
                        # Only add line for Partial Withdraw if quantity has a value (was edited)
                        partial_quantity = move_line.quantity - move_line.x_studio_actual_kg
                        
                        if partial_quantity > 0:
                            lines.append((0, 0, {
                                    'select_package': True,
                                    'result_package_id': pallet_result_id,
                                    'result_package_id_is_fallback': result_package_id_is_fallback,
                                    'location_dest_id': location_dest_id,
                                    'location_dest_id_is_fallback': location_dest_id_is_fallback,
                                    'pallet_series_id': move_line.x_studio_pallet_series_id,
                                    'bf_pallet_char': move_line.bf_pallet_char,
                                    'product_id': move_line.product_id.id,
                                    'expiration_date': move_line.x_studio_expiration_date,
                                    'x_studio_building_dropped': move_line.x_studio_building_dropped,
                                    'original_record_reference': move_line.original_record_reference,
                                    'production_date': move_line.x_studio_production_date,
                                    'lot_id': move_line.lot_id.id,
                                    'stock_move_line': move_line.id,
                                    'return_counter': move_line.x_studio_return_count,
                                    'container_number': move_line.x_studio_container_number,
                                    'pack_uom_unit': move_line.x_studio_affected_2nd_uom - move_line.x_studio_actual_packaging,
                                    'min_uom_unit': move_line.x_studio_withdraw_units - move_line.x_studio_actual_min,
                                    'quantity': partial_quantity,
                                    'pack_uom': move_line.x_studio_quantity_uom_delivery,
                                    'min_uom': move_line.x_studio_min_quantity_uom,
                                    'actual_pack_uom_unit': move_line.x_studio_affected_2nd_uom,
                                    'actual_min_uom_unit': move_line.x_studio_withdraw_units,
                                    'actual_quantity': move_line.quantity,
                                   'location_id':  self.picking_id.location_id.id,

                                }))

                self.package_line_ids = lines
                self.lines_computed = True

    @api.onchange('select_all')
    def select_all_pallets(self):
        if self.select_all:
            for line in self.package_line_ids:
                line.select_package =  True
        else:
            for line in self.package_line_ids:
                line.select_package =  False

    @api.depends('package_line_ids.select_package', 'package_line_ids.pack_uom_unit', 
                 'package_line_ids.min_uom_unit', 'package_line_ids.quantity',
                 'package_line_ids.actual_pack_uom_unit', 'package_line_ids.actual_min_uom_unit', 
                 'package_line_ids.actual_quantity')
    def _compute_sync_warnings(self):
        for wizard in self:
            selected_packages = wizard.package_line_ids
            warning_lines = []
            has_warnings = False

            for record in selected_packages:
                
                if (record.pack_uom_unit < record.actual_pack_uom_unit or
                    record.min_uom_unit < record.actual_min_uom_unit or
                    record.quantity < record.actual_quantity):
        
                    errors = []
                    
                    # Check which UoMs are not synchronized
                    if record.pack_uom_unit == record.actual_pack_uom_unit and record.pack_uom_unit:
                        errors.append("Packaging Unit")
                    if record.min_uom_unit == record.actual_min_uom_unit and record.min_uom_unit:
                        errors.append("Minimum Unit")
                    if record.quantity == record.actual_quantity:
                        errors.append("Quantity")
                    
                    if errors:
                        has_warnings = True
                        pallet_name = record.pallet_series_id or record.bf_pallet_char or "Unknown"
                        warning_lines.append(f"<li><strong>Pallet {pallet_name}:</strong> {', '.join(errors)} should also be reduced to maintain synchronization.</li>")
            
            wizard.has_sync_warnings = has_warnings
            if warning_lines:
                wizard.sync_warning_message = f"""
                <div class="alert alert-warning">
                    <strong><i class="fa fa-warning"></i> Synchronization Warning</strong>
                    <p>The following synchronization issues were detected:</p>
                    <ul>{''.join(warning_lines)}</ul>
                    <p><em>You can still proceed, but please review the highlighted values.</em></p>
                </div>
                """
            else:
                wizard.sync_warning_message = False



    def _find_existing_return(self):
        """Find existing return picking that is not cancelled or validated.

        Void returns are excluded UNLESS this wizard is running the void
        flow itself (voided context): a manual partial return must never
        append onto a void-equivalent document — its lines mirror the
        voided WR exactly and are guarded against edits. Manual returns
        get their own return RR instead."""
        domain = [
            ('return_id', '=', self.picking_id.id),
            ('state', 'in', ['draft', 'waiting', 'confirmed', 'assigned']),
        ]
        if not self.env.context.get('voided'):
            domain.append(('is_void_return', '=', False))
        return self.env['stock.picking'].search(domain, limit=1)

    def _get_unique_identifier(self, package):
        """Get unique identifier for a package based on product, pallet, and dates"""
        pallet_id = package.bf_pallet_char if self.is_a_blast_freeze else package.pallet_series_id
        return (
            package.product_id.id,
            pallet_id,
            package.production_date,
            package.expiration_date
        )

    def _get_existing_move_line_identifier(self, move_line):
        """Get unique identifier from existing move line"""
        pallet_id = move_line.bf_pallet_char if self.is_a_blast_freeze else move_line.x_studio_pallet_series_id
        return (
            move_line.product_id.id,
            pallet_id,
            move_line.x_studio_production_date,
            move_line.x_studio_expiration_date
        )

    def _update_existing_move_line(self, existing_move_line, package):
        """Override existing move line with new quantities while preserving existing data"""
        # Store old quantities to calculate the difference for stock.move update
        old_quantity = existing_move_line.quantity
        old_pack_uom = existing_move_line.x_studio_2nd_uom
        old_min_uom = existing_move_line.x_studio_total_units
        
        # Calculate return count properly - increment from the original counter
        return_count = package.return_counter + 1 if self.return_reason not in ['Wrong Details Encoded', 'Void Transfer', 'Others'] else package.return_counter
        
        # Prepare update values - only update what's provided in the package
        update_values = {
            'quantity': package.quantity,
            'x_studio_2nd_uom': package.pack_uom_unit,
            'x_studio_total_units': package.min_uom_unit,
            'x_studio_return_count': return_count,
        }
        
        # Only update fields if they have values in the package (preserve existing if not provided)
        if package.expiration_date:
            update_values['x_studio_expiration_date'] = package.expiration_date
        if package.x_studio_building_dropped:
            update_values['x_studio_building_dropped'] = package.x_studio_building_dropped
        if package.original_record_reference:
            update_values['original_record_reference'] = package.original_record_reference
        if package.production_date:
            update_values['x_studio_production_date'] = package.production_date
        if package.lot_id:
            update_values['lot_id'] = package.lot_id.id
        if package.container_number:
            update_values['x_studio_container_number'] = package.container_number
        if package.min_uom:
            update_values['x_studio_min_quantity_uom'] = package.min_uom
        if package.pack_uom:
            update_values['x_studio_quantity_uom'] = package.pack_uom
        
        # Always preserve pallet identifiers unless specifically provided
        if package.pallet_series_id and package.pallet_series_id != existing_move_line.x_studio_pallet_series_id:
            update_values['x_studio_pallet_series_id'] = package.pallet_series_id
        if package.bf_pallet_char and package.bf_pallet_char != existing_move_line.bf_pallet_char:
            update_values['bf_pallet_char'] = package.bf_pallet_char
        
        # Update the move line
        existing_move_line.write(update_values)
        
        # Handle location reservation - remove from source location
        if package.location_dest_id:
            try:
                package.location_dest_id.remove_reservation()
            except Exception as e:
                _logger.warning(f"Could not remove reservation from location {package.location_dest_id.name}: {e}")
        
        # Handle package and destination location reservation
        return_picking_id = existing_move_line.picking_id.id
        
        # Set package reservation
        if package.result_package_id:
            try:
                package.result_package_id.write({
                    'x_studio_is_reserved': True,
                    'x_studio_receiving_report_id': return_picking_id
                })
            except Exception as e:
                _logger.warning(f"Could not set package reservation for {package.result_package_id.name}: {e}")
        
        # Set destination location reservation
        if package.location_dest_id:
            try:
                package.location_dest_id.write({
                    'x_studio_is_reserved': True,
                    'x_studio_receiving_report_id': return_picking_id
                })
            except Exception as e:
                _logger.warning(f"Could not set location reservation for {package.location_dest_id.name}: {e}")
        
        # Calculate the difference and update the corresponding stock.move quantities
        move = existing_move_line.move_id
        quantity_diff = package.quantity - old_quantity
        pack_uom_diff = package.pack_uom_unit - old_pack_uom
        min_uom_diff = package.min_uom_unit - old_min_uom
        
        move.write({
            'product_uom_qty': move.product_uom_qty + quantity_diff,
            'x_studio_demand_packaging': move.x_studio_demand_packaging + pack_uom_diff,
            'x_studio_min_uom': move.x_studio_min_uom + min_uom_diff,
            'state': 'assigned',
        })

    def action_process_return(self):
        selected_packages = self.package_line_ids.filtered(lambda line: line.select_package)
        
        # Check if we should create a blank return or process with selected packages

        
        # Check for existing return
        existing_return = self._find_existing_return()
        if not selected_packages and not existing_return:
            # Create blank return without any move lines
            return self._create_blank_return()
            
        if existing_return:
            fields_map = {
                'truck_type': self.picking_id.truck_type,
                'x_studio_truck_time': self.picking_id.x_studio_end_time,
                'x_studio_driver': self.picking_id.x_studio_driver,
                'x_studio_start_time': self.picking_id.x_studio_start_time,
                'x_studio_end_time': self.picking_id.x_studio_start_time if self.return_reason == 'Void Transfer' else False,
                'x_studio_trucks_plate_': self.picking_id.x_studio_trucks_plate_,
                'x_studio_loading_dock_no': self.picking_id.x_studio_loading_dock_no,
                'x_studio_source': 'RETURN',
                'x_studio_checked_by': self.picking_id.x_studio_checked_by,
                'x_studio_approved_by': self.picking_id.x_studio_approved_by,
            }
            
            vals = {field: value for field, value in fields_map.items() if not getattr(existing_return, field)}
            
            if vals:
                existing_return.write(vals)
            # Append to existing return
            return self._append_to_existing_return(existing_return, selected_packages)
        else:
            
            # Create new return with selected packages
            return self._create_new_return_with_packages(selected_packages)

    def _return_source_location_id(self):
        """Source location for a return RR.

        The return picking is built with picking_id.copy(), so without this it
        silently inherits the WR's SOURCE location — an internal bin/building
        (e.g. "M") — and the RR then looks like stock arriving from inside the
        warehouse instead of from the client. Goods coming back belong to the
        supplier/vendor side, exactly like a normal receipt.

        Mirrors stock.picking._onchange_picking_type: picking-type default,
        else the partner's supplier location, else the standard Vendors
        location. (RECEIVING types here have no default_location_src_id, which
        is why normal RRs land on Partners/Vendors via the partner fallback.)
        """
        self.ensure_one()
        if self.picking_type_id.default_location_src_id:
            return self.picking_type_id.default_location_src_id.id
        partner = self.picking_id.partner_id
        if partner and partner.property_stock_supplier:
            return partner.property_stock_supplier.id
        supplier_loc = self.env.ref('stock.stock_location_suppliers',
                                    raise_if_not_found=False)
        return supplier_loc.id if supplier_loc else False

    def _create_blank_return(self):
        """Create a blank return picking without any move lines"""
        # Always force the incoming picking type — never trust pre-set values
        # which may have leaked from the parent form's context (e.g. default_picking_type_id)
        warehouse_id = self.picking_id.picking_type_id.warehouse_id.id
        self.picking_type_id = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('is_blast_freeze_operation', '=', self.picking_id.picking_type_id.is_blast_freeze_operation),
            ('warehouse_id', '=', warehouse_id)
        ], limit=1)
        
        # Create blank picking
        new_picking = self.picking_id.copy(default={
            'picking_type_id': self.picking_type_id.id,
            'location_dest_id': self.location_id.id,
            # was hardcoded id 4 (Partners/Vendors) - derived now so it stays
            # correct across databases and for BF picking types
            'location_id': self._return_source_location_id(),
            'return_id': self.picking_id.id,
            'return_reason': self.return_reason,
            'x_studio_for_revision': True if self.return_reason == 'Wrong Details Encoded' else False,
            'other_reasons': self.other_reasons,
            'x_studio_end_time': self.picking_id.x_studio_start_time if self.return_reason == 'Void Transfer' else False,
        })

        # Remove any existing move lines from the copied picking
        for move_line in new_picking.move_ids_without_package:
            move_line.unlink()

        return {
            'type': 'ir.actions.act_window',
            'name': 'New Return Record',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': new_picking.id,
            'target': 'current',
        }

    def _append_to_existing_return(self, existing_return, selected_packages):
        """Append selected packages to existing return picking"""
        
        # Update existing return with current wizard values if they've been changed
        update_values = {}
        if self.return_reason and self.return_reason != existing_return.return_reason:
            update_values['return_reason'] = self.return_reason
        if self.other_reasons and self.other_reasons != existing_return.other_reasons:
            update_values['other_reasons'] = self.other_reasons
        if self.location_id and self.location_id.id != existing_return.location_dest_id.id:
            update_values['location_dest_id'] = self.location_id.id
        
        if update_values:
            existing_return.write(update_values)
        
        # Get existing move lines for comparison
        existing_move_lines = existing_return.move_line_ids
        
        # Create mapping of existing unique identifiers to move lines
        existing_identifier_map = {}
        for move_line in existing_move_lines:
            identifier = self._get_existing_move_line_identifier(move_line)
            if all(identifier):  # Only add if all identifier components are present
                existing_identifier_map[identifier] = move_line

        # Separate packages into existing and new
        packages_to_update = []
        packages_to_create = []
        
        for package in selected_packages:
            identifier = self._get_unique_identifier(package)
            if all(identifier) and identifier in existing_identifier_map:
                packages_to_update.append((package, existing_identifier_map[identifier]))
            else:
                packages_to_create.append(package)

        # Update existing move lines
        for package, existing_move_line in packages_to_update:
            self._update_existing_move_line(existing_move_line, package)

        # Create new move lines for packages that don't exist
        if packages_to_create:
            self._create_new_move_lines_for_existing_return(existing_return, packages_to_create)

        # Final state normalization: any move whose quantity changed during this
        # wizard run can get flipped back to 'confirmed'/'waiting' by Odoo's
        # reservation recomputation. Force the picking and its moves to 'assigned'
        # so the return doesn't show "Waiting for Availability".
        existing_return.move_ids_without_package.write({'state': 'assigned'})
        existing_return.write({'state': 'assigned'})

        return {
            'type': 'ir.actions.act_window',
            'name': 'Updated Return Record',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': existing_return.id,
            'target': 'current',
        }
    
    def _create_new_move_lines_for_existing_return(self, existing_return, packages_to_create):
        """Create new move lines for packages in existing return"""
        
        # First, aggregate by product_id for stock.move level
        product_data = {}
        for package in packages_to_create:
            product_id = package.product_id.id
            
            if product_id not in product_data:
                product_data[product_id] = {
                    'quantity': 0,
                    'counter': 0,
                    'demand_packaging': 0,
                    'demand_min': 0,
                    'pack_uom': package.pack_uom.id,
                    'min_uom': package.min_uom.id,
                    'packages': []
                }
            
            product_data[product_id]['quantity'] += package.quantity
            product_data[product_id]['counter'] += 1
            product_data[product_id]['demand_packaging'] += package.pack_uom_unit
            product_data[product_id]['demand_min'] += package.min_uom_unit
            product_data[product_id]['packages'].append(package)
    
        # Check for existing moves by product_id and update/create accordingly
        existing_moves = existing_return.move_ids_without_package
        existing_move_map = {move.product_id.id: move for move in existing_moves}
        
        move_line_mapping = {}
    
        # Handle stock.move level (grouped by product_id)
        for product_id, data in product_data.items():
            if product_id in existing_move_map:
                # Update existing move for this product
                existing_move = existing_move_map[product_id]
                if not existing_move.move_line_ids:
                    # The move exists but has no move lines underneath — its current
                    # quantities are stale planned values. Overwrite them with this
                    # batch's totals so we don't double-count.
                    existing_move.write({
                        'location_id': 5,
                        'product_uom_qty': data['quantity'],
                        'x_studio_number_of_lines': data['counter'],
                        'x_studio_demand_packaging': data['demand_packaging'],
                        'x_studio_min_uom': data['demand_min'],
                        'state': 'assigned',
                    })
                else:
                    # Move already has move lines accounting for its current totals — add on top.
                    existing_move.write({
                        'location_id': 5,
                        'product_uom_qty': existing_move.product_uom_qty + data['quantity'],
                        'x_studio_number_of_lines': existing_move.x_studio_number_of_lines + data['counter'],
                        'x_studio_demand_packaging': existing_move.x_studio_demand_packaging + data['demand_packaging'],
                        'x_studio_min_uom': existing_move.x_studio_min_uom + data['demand_min'],
                        'state': 'assigned',
                    })

                # Map all packages of this product to the existing move
                for package in data['packages']:
                    move_line_mapping[package] = existing_move
                    
            else:
                # Create new move for this product
                new_move = self.env['stock.move'].create({
                    'name': self.env['product.product'].browse(product_id).display_name,
                    'product_id': product_id,
                    'product_uom_qty': data['quantity'],
                    'product_uom': self.env['product.product'].browse(product_id).uom_id.id,
                    'picking_id': existing_return.id,
                    'location_id': self.picking_id.location_dest_id.id,  # Source location
                    'location_dest_id': existing_return.location_dest_id.id,
                    'x_studio_number_of_lines': data['counter'],
                    'x_studio_demand_packaging': data['demand_packaging'],
                    'x_studio_min_uom': data['demand_min'],
                    'x_studio_packaging_unit': data['pack_uom'],
                    'x_studio_min_unit': data['min_uom'],
                    'reference': existing_return.name,
                    'state': 'assigned'
                })
                
                # Map all packages of this product to the new move
                for package in data['packages']:
                    move_line_mapping[package] = new_move
    
        # Create stock.move.line records (one per package with unique identifier)
        move_line_values = []
        for package in packages_to_create:
            move = move_line_mapping.get(package)
            if move:
                move_line_values.append({
                    'move_id': move.id,
                    'product_id': package.product_id.id,
                    'quantity': package.quantity,
                    'result_package_id': package.result_package_id.id,
                    'location_dest_id': package.location_dest_id.id,
                    'location_id': move.location_id.id,  # Set from the move
                    # set at CREATE time (not the later write) so the RR
                    # lot-assigner AR#10 can never see the line unflagged
                    # and stamp a fresh lot — the original lot must survive
                    # for the quant merge keys to match
                    'is_return': True,
                    'lot_id': package.lot_id.id,
                })

        # Create stock.move.line records
        if move_line_values:
            created_move_lines = self.env['stock.move.line'].create(move_line_values)

            # Update the additional fields after creation
            for package, move_line in zip(packages_to_create, created_move_lines):
                # Calculate return count properly - increment from the original counter
                return_count = package.return_counter + 1 if self.return_reason not in ['Wrong Details Encoded', 'Void Transfer', 'Others'] else package.return_counter
                
                move_line.write({
                    'is_return': True,
                    'picking_id': existing_return.id,
                    'x_studio_expiration_date': package.expiration_date,
                    'x_studio_building_dropped': package.x_studio_building_dropped,
                    'original_record_reference': package.original_record_reference,
                    'x_studio_production_date': package.production_date,
                    'lot_id': package.lot_id.id,
                    'x_studio_return_count': return_count,
                    'x_studio_pallet_series_id': package.pallet_series_id,
                    'bf_pallet_char': package.bf_pallet_char,
                    'x_studio_container_number': package.container_number,
                    'x_studio_2nd_uom': package.pack_uom_unit,
                    'x_studio_total_units': package.min_uom_unit,
                    'x_studio_min_quantity_uom': package.min_uom,
                    'x_studio_quantity_uom': package.pack_uom,
                })
                
                # Handle location reservation - remove from source location
                if package.location_dest_id:
                    try:
                        package.location_dest_id.remove_reservation()
                    except Exception as e:
                        _logger.warning(f"Could not remove reservation from location {package.location_dest_id.name}: {e}")
                
                # Handle package and destination location reservation
                return_picking_id = existing_return.id
                
                # Set package reservation
                if package.result_package_id:
                    try:
                        package.result_package_id.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': return_picking_id
                        })
                    except Exception as e:
                        _logger.warning(f"Could not set package reservation for {package.result_package_id.name}: {e}")
                
                # Set destination location reservation
                if package.location_dest_id:
                    try:
                        package.location_dest_id.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': return_picking_id
                        })
                    except Exception as e:
                        _logger.warning(f"Could not set location reservation for {package.location_dest_id.name}: {e}")

    def _create_new_return_with_packages(self, selected_packages):
        """Create new return picking with selected packages (original logic)"""
        # Always force the incoming picking type — never trust pre-set values
        # which may have leaked from the parent form's context (e.g. default_picking_type_id)
        warehouse_id = self.picking_id.picking_type_id.warehouse_id.id
        self.picking_type_id = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('is_blast_freeze_operation', '=', self.picking_id.picking_type_id.is_blast_freeze_operation),
            ('warehouse_id', '=', warehouse_id)
        ], limit=1)

        # Copy the picking record
        new_picking = self.picking_id.copy(default={
            'picking_type_id': self.picking_type_id.id,
            'location_dest_id': self.location_id.id,
            # WITHOUT THIS the copy() inherits the WR's internal source ("M")
            # and the return RR looks like stock arriving from inside the
            # warehouse. Returned goods come from the client side.
            'location_id': self._return_source_location_id(),
            'return_id': self.picking_id.id,
            'return_reason': self.return_reason,
            'x_studio_for_revision': True if self.return_reason == 'Wrong Details Encoded' else False,
            'other_reasons': self.other_reasons,
            'x_studio_start_time': self.picking_id.x_studio_start_time,
            'x_studio_end_time': self.picking_id.x_studio_start_time if self.return_reason == 'Void Transfer' else False,
            'x_studio_truck_time': self.picking_id.x_studio_truck_time,
            'truck_type': self.picking_id.truck_type,
            'x_studio_trucks_plate_': self.picking_id.x_studio_trucks_plate_,
            'x_studio_driver': self.picking_id.x_studio_driver,
            'x_studio_loading_dock_no': self.picking_id.x_studio_loading_dock_no,
            'x_studio_source': self.picking_id.name,
            'x_studio_client_reference': 'N/A',
            'x_studio_source': 'RETURN' if self.return_reason != 'Void Transfer' else 'VOIDED', 
            'x_studio_record_remarks': 'OTHERS' if self.return_reason == 'Void Transfer' else 'SERVED IN GOOD CONDITION WITH COMPLETE QTY',
            'x_studio_remarks': 'VOIDED' if self.return_reason == 'Void Transfer' else False,
        })

        product_data = {}

        for package in selected_packages:
            product_id = package.product_id.id
            quantity = package.quantity
            demand_packaging = package.pack_uom_unit
            demand_min = package.min_uom_unit
            pack_uom = package.pack_uom.id,
            min_uom = package.min_uom.id

            if product_id not in product_data:
                product_data[product_id] = {
                    'quantity': 0,
                    'counter': 0,
                    'demand_packaging': 0,
                    'demand_min': 0,
                }

            product_data[product_id]['quantity'] += quantity
            product_data[product_id]['counter'] += 1
            product_data[product_id]['demand_packaging'] += demand_packaging
            product_data[product_id]['demand_min'] += demand_min
            product_data[product_id]['min_uom'] = min_uom
            product_data[product_id]['pack_uom'] = pack_uom

        # Remove any existing move lines from the copied picking
        for move_line in new_picking.move_ids_without_package:
            move_line.unlink()

        move_line_mapping = {}

        # Create a stock.move for each product in product_data
        for product_id, data in product_data.items():
            move = self.env['stock.move'].create({
                'name': self.env['product.product'].browse(product_id).display_name,
                'product_id': product_id,
                'product_uom_qty': data['quantity'],
                'product_uom': self.env['product.product'].browse(product_id).uom_id.id,
                'picking_id': new_picking.id,
                'location_id': 4,
                'location_dest_id': new_picking.location_dest_id.id,
                'x_studio_number_of_lines': data['counter'],
                'x_studio_demand_packaging': data['demand_packaging'],
                'x_studio_min_uom': data['demand_min'],
                'x_studio_packaging_unit': data['pack_uom'][0] if isinstance(data['pack_uom'], tuple) and data['pack_uom'] else None,
                'x_studio_min_unit': data['min_uom'][0] if isinstance(data['min_uom'], tuple) and data['min_uom'] else None,
                'reference': new_picking.id,
                'state': 'assigned'
            })
            move_line_mapping[product_id] = move

        # Create stock.move.line records for each selected package
        move_line_values = []
        for package in selected_packages:
            move = move_line_mapping.get(package.product_id.id)
            if move:
                move_line_values.append({
                    'move_id': move.id,
                    'product_id': package.product_id.id,
                    'quantity': package.quantity,
                    'result_package_id': package.result_package_id.id,
                    'location_dest_id': package.location_dest_id.id,
                    # set at CREATE time (not the later write) so the RR
                    # lot-assigner AR#10 can never see the line unflagged
                    # and stamp a fresh lot
                    'is_return': True,
                    'lot_id': package.lot_id.id,
                })

        # Create stock.move.line records
        if move_line_values:
            created_move_lines = self.env['stock.move.line'].create(move_line_values)

            # Update the additional fields after creation
            for package, move_line in zip(selected_packages, created_move_lines):
                # Calculate return count properly - increment from the original counter
                return_count = package.return_counter + 1 if self.return_reason not in ['Wrong Details Encoded', 'Void Transfer', 'Others'] else package.return_counter

                move_line.write({
                    'is_return': True,
                    'picking_id': new_picking.id,
                    'x_studio_expiration_date': package.expiration_date,
                    'x_studio_building_dropped': package.x_studio_building_dropped,
                    'original_record_reference': package.original_record_reference,
                    'x_studio_production_date': package.production_date,
                    'lot_id': package.lot_id.id,
                    'x_studio_return_count': return_count,
                    'x_studio_pallet_series_id': package.pallet_series_id,
                    'bf_pallet_char': package.bf_pallet_char,
                    'x_studio_container_number': package.container_number,
                    'x_studio_2nd_uom': package.pack_uom_unit,
                    'x_studio_total_units': package.min_uom_unit,
                    'x_studio_min_quantity_uom': package.min_uom,
                    'x_studio_quantity_uom': package.pack_uom,
                })
                
                # Handle location reservation - remove from source location
                if package.location_dest_id:
                    try:
                        package.location_dest_id.remove_reservation()
                    except Exception as e:
                        _logger.warning(f"Could not remove reservation from location {package.location_dest_id.name}: {e}")
                
                # Handle package and destination location reservation
                return_picking_id = new_picking.id
                
                # Set package reservation
                if package.result_package_id:
                    try:
                        package.result_package_id.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': return_picking_id
                        })
                    except Exception as e:
                        _logger.warning(f"Could not set package reservation for {package.result_package_id.name}: {e}")
                
                # Set destination location reservation
                if package.location_dest_id:
                    try:
                        package.location_dest_id.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': return_picking_id
                        })
                    except Exception as e:
                        _logger.warning(f"Could not set location reservation for {package.location_dest_id.name}: {e}")

        return {
            'type': 'ir.actions.act_window',
            'name': 'New Return Record',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': new_picking.id,
            'target': 'current',
            'state': 'assigned'
        }
