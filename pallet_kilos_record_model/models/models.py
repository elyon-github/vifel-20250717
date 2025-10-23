from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
import json

_logger = logging.getLogger(__name__)

class PalletKilosRecordModel(models.Model):
    _name = 'pallet_kilos_record_model.pallet_kilos_record_model'
    _description = 'Pallet Kilos Record Model'
    _order = 'end_time asc, id asc'  # Critical for running balance

    # Basic identification fields
    report_no = fields.Char(string="Report No.", readonly=True)
    owner_id = fields.Many2one('res.partner', 'Owner', ondelete='set null', readonly=True, index=True)
    warehouse = fields.Many2one('stock.warehouse', 'Warehouse', ondelete='set null', readonly=True, index=True)
    record_reference = fields.Many2one('stock.picking', 'Record Reference', store=True, ondelete='set null', readonly=True, index=True)
    remarks = fields.Char(string="Remarks", readonly=True)
    active = fields.Boolean(string="active", default=True)

    # Adjusted document - this replaces the original reference for computations
    readjustment_document = fields.Many2one('stock.picking', string="Adjusted Document Reference", ondelete='set null', readonly=True, index=True, help="When set, this document replaces the original reference for all calculations")

    # Effective document - computed field that returns either adjusted or original reference
    effective_document = fields.Many2one('stock.picking', string="Effective Document", compute='_compute_effective_document', store=True, help="The document used for all calculations (adjusted if available, otherwise original)")
    operation_type_id = fields.Many2one(string="Operation Type", related="effective_document.picking_type_id", store=True)

    # Storage operation fields - these will be populated directly, not computed
    pallets_received = fields.Float(store=True, string="Pallets Received", readonly=True)
    pallets_withdrawn = fields.Float(store=True, string="Pallets Withdrawn", readonly=True)
    kilos_received = fields.Float(store=True, string="Kilos Received", readonly=True)
    kilos_withdrawn = fields.Float(store=True, string="Kilos Withdrawn", readonly=True)

    # Operation fields - stored, not computed
    packaging_received = fields.Float(string="Packaging Received", readonly=True, store=True)
    packaging_withdrawn = fields.Float(string="Packaging Withdrawn", readonly=True, store=True)
    units_received = fields.Float(string="Units Received", readonly=True, store=True)
    units_withdrawn = fields.Float(string="Units Withdrawn", readonly=True, store=True)

    # Balance fields - stored, calculated via method calls
    total_balance_in_units = fields.Float(store=True, string="Total Balance in Packs", readonly=True, group_operator=False)
    total_balance_in_packaging = fields.Float(store=True, string="Total Balance in Quantity", group_operator=False)
    total_balance_in_kilos = fields.Float(store=True, string="Total Balance in Kilos (KG)", readonly=True, group_operator=False)
    total_balance_in_pallets = fields.Float(store=True, string="Total Balance in Pallets", readonly=True, group_operator=False)

    # Return fields - stored, not computed
    return_id = fields.Many2one('stock.picking', readonly=True, string="Return RR ID")
    return_heads = fields.Float(string="Total Return Units", readonly=True)
    return_packaging = fields.Float(string="Total Return Packaging", readonly=True)
    return_pallets = fields.Float(string="Total Return Pallets", readonly=True)
    return_kilos = fields.Float(string="Total Return Kilos", readonly=True)

    adjustment_heads = fields.Float(string="Total Adjustment Units", readonly=True)
    adjustment_packaging = fields.Float(string="Total Adjustment Packaging", readonly=True)
    adjustment_pallets = fields.Float(string="Total Adjustment Pallets", readonly=True)
    adjustment_kilos = fields.Float(string="Total Adjustment Kilos", readonly=True)

    # Beginning balance fields - stored, calculated via method calls
    beginning_balance_in_pallets = fields.Float(string="Beginning Balance in Pallets", readonly=True, store=True)
    beginning_balance_in_kilos = fields.Float(string="Beginning Balance in Kilos", readonly=True, store=True)

    # Rate fields
    holding_rate = fields.Float(string='Holding Rate', related='owner_id.x_studio_holding_rate', store=True)
    handling_rate = fields.Float(string='Handling Rate', related='owner_id.x_studio_handling_rate', store=True)

    # Vehicle fields - stored
    truck_type = fields.Selection(
        selection=[
            ('4wheeler', '4 Wheeler'),
            ('6wheeler', '6 Wheeler'),
            ('10wheeler', '10 Wheeler'),
            ('20ft_container', '20ft Container'),
            ('40ft_container', '40ft Container'),
            ('N/A', 'N/A')
        ],
        string="Truck Type", readonly=True, store=True
    )
    trucks_plate = fields.Char(string="Truck's Plate #", readonly=True, store=True)
    gate_pass = fields.Char(string="Gate Pass #", readonly=True, store=True)
    start_time = fields.Datetime(string="Start Time",  store=True, index=True)  # INDEX IS CRITICAL
    end_time = fields.Datetime(string="End Time", readonly=True, store=True)

    # Maximum values
    max_pallets = fields.Many2one('x_inventory_static_var', 'Max Pallets', default=lambda self: self._get_static_var('Max Pallets'))
    max_kg = fields.Many2one('x_inventory_static_var', 'Max Kilograms', default=lambda self: self._get_static_var('Max Kilograms'))

    # Running balance fields - stored, not computed
    overall_pallets = fields.Float(string='Overall Pallets', store=True, group_operator=False)
    overall_kilos = fields.Float(string='Overall Kilos', store=True, group_operator=False)

    # Add blast freezer flag for efficient filtering
    is_blast_freezer = fields.Boolean(string="Is Blast Freezer", store=True, index=True)

    # NEW: Building-level balances JSON field
    total_balances = fields.Json(string="Total Balances")
    building_operations_temp = fields.Json(string="Operations Temp")
    
    @api.model
    def _get_static_var(self, var_name):
        """Get static variable from inventory_static_var model by name"""
        return self.env['x_inventory_static_var'].search([
            ('x_studio_use_case', '=', 'XLSX Variables'),
            ('x_name', 'ilike', var_name)
        ], limit=1)

    @api.depends('record_reference', 'readjustment_document')
    def _compute_effective_document(self):
        """Compute the effective document to use for calculations"""
        for record in self:
            record.effective_document = record.readjustment_document or record.record_reference

    def _get_building_name(self, building_record):
        """Get building name or default"""
        if building_record and building_record.x_name:
            return building_record.x_name
        return "MAIN"

    def _populate_operations_data(self):
        """Populate operation data from effective document - called explicitly, not computed"""
        for record in self:
            if not record.effective_document:
                continue

            units_received = 0
            units_withdrawn = 0
            packaging_received = 0
            packaging_withdrawn = 0
            kilos_received = 0
            kilos_withdrawn = 0
            pallets = set()
            pallet_count = 0

            # NEW: Building-level tracking
            building_operations = {}

            # Get move lines data from effective document
            for line in record.effective_document.move_line_ids:
                if record.effective_document.picking_type_code in ['outgoing']:
                    units_withdrawn += line.x_studio_withdraw_units
                    packaging_withdrawn += line.x_studio_affected_2nd_uom
                    kilos_withdrawn += line.quantity
                else:
                    units_received += line.x_studio_total_units
                    packaging_received += line.x_studio_2nd_uom
                    kilos_received += line.quantity
                    
            # Count unique pallets and track by building
            if record.effective_document.picking_type_code in ['outgoing']:
                for move_line in record.effective_document.move_line_ids:
                    # Get building for outgoing operations
                    building = move_line.location_id.x_studio_building if move_line.location_id else None
                    building_name = self._get_building_name(building)
                    
                    # Initialize building tracking
                    if building_name not in building_operations:
                        building_operations[building_name] = {
                            'units': 0,
                            'packaging': 0,
                            'kilos': 0,
                            'pallets': set()
                        }
                    
                    # Add quantities to building totals
                    building_operations[building_name]['units'] += move_line.x_studio_withdraw_units or 0
                    building_operations[building_name]['packaging'] += move_line.x_studio_affected_2nd_uom or 0
                    building_operations[building_name]['kilos'] += move_line.quantity or 0

                    if move_line.picking_id.x_studio_is_a_blast_freezer:
                        if move_line.bf_pallet_char and move_line.bf_pallet_char not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.bf_pallet_char)
                            building_operations[building_name]['pallets'].add(move_line.bf_pallet_char)
                    else:
                        if move_line.package_id and move_line.package_id.id not in pallets:
                            
                            if move_line.reserved_quantity_on_validation == 0:

                                pallet_count += 1
                                pallets.add(move_line.package_id.id)
                                building_operations[building_name]['pallets'].add(move_line.package_id.id)
            else:
                for move_line in record.effective_document.move_line_ids:
                    # Get building for incoming operations
                    building = move_line.location_dest_id.x_studio_building if move_line.location_dest_id else None
                    building_name = self._get_building_name(building)
                    
                    # Initialize building tracking
                    if building_name not in building_operations:
                        building_operations[building_name] = {
                            'units': 0,
                            'packaging': 0,
                            'kilos': 0,
                            'pallets': set()
                        }
                    
                    # Add quantities to building totals
                    building_operations[building_name]['units'] += move_line.x_studio_total_units or 0
                    building_operations[building_name]['packaging'] += move_line.x_studio_2nd_uom or 0
                    building_operations[building_name]['kilos'] += move_line.quantity or 0

                    if move_line.picking_id.x_studio_is_a_blast_freezer:
                        if move_line.bf_pallet_char and move_line.bf_pallet_char not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.bf_pallet_char)
                            building_operations[building_name]['pallets'].add(move_line.bf_pallet_char)
                    else:
                        if move_line.result_package_id and move_line.result_package_id.id not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.result_package_id.id)
                            building_operations[building_name]['pallets'].add(move_line.result_package_id.id)

            # Convert pallet sets to counts for building operations
            for building_name in building_operations:
                building_operations[building_name]['pallets'] = len(building_operations[building_name]['pallets'])

            # Store building_operations temporarily on the record for later use
            # We don't write this to the database, just set it as an attribute
            record.building_operations_temp = building_operations

            # Set values based on picking type
            picking_code = record.effective_document.picking_type_id.code
            write_vals = {
                'is_blast_freezer': record.effective_document.x_studio_is_a_blast_freezer or False,
            }

            if picking_code == 'incoming':
                write_vals.update({
                    'units_received': units_received,
                    'packaging_received': packaging_received,
                    'kilos_received': kilos_received,
                    'pallets_received': pallet_count,
                    'units_withdrawn': 0,
                    'packaging_withdrawn': 0,
                    'kilos_withdrawn': 0,
                    'pallets_withdrawn': 0,
                })
            elif picking_code == 'outgoing':
                write_vals.update({
                    'units_withdrawn': units_withdrawn,
                    'packaging_withdrawn': packaging_withdrawn,
                    'kilos_withdrawn': kilos_withdrawn,
                    'pallets_withdrawn': pallet_count,
                    'units_received': 0,
                    'packaging_received': 0,
                    'kilos_received': 0,
                    'pallets_received': 0,
                })

            record.write(write_vals)

    def _populate_returns_data(self):
        """Populate return data from effective document - called explicitly"""
        for record in self:
            if not record.effective_document:
                continue

            return_heads = 0
            return_packaging = 0
            return_pallets = 0
            return_kilos = 0
            return_id = False
            pallets = set()

            for returns in record.effective_document.return_ids:
                if returns.state == 'done' and returns.return_reason == 'Partial Withdraw' and not returns.x_studio_voided:
                    return_id = returns.id
                    for line_ids in returns.move_line_ids:
                        return_heads += line_ids.x_studio_total_units
                        return_packaging += line_ids.x_studio_2nd_uom
                        return_kilos += line_ids.quantity
                        if line_ids.result_package_id and line_ids.result_package_id.id not in pallets:
                            return_pallets += 1
                            pallets.add(line_ids.result_package_id.id)
                    break

            record.write({
                'return_id': return_id,
                'return_heads': return_heads,
                'return_packaging': return_packaging,
                'return_pallets': return_pallets,
                'return_kilos': return_kilos,
            })

    def _populate_vehicle_data(self):
        """Populate vehicle data from effective document"""
        for record in self:
            if record.effective_document:
                record.write({
                    'truck_type': record.effective_document.truck_type,
                    'trucks_plate': record.effective_document.x_studio_trucks_plate_,
                    'gate_pass': record.effective_document.x_studio_gate_pass,
                    'start_time': record.effective_document.x_studio_start_time,
                    'end_time': record.effective_document.x_studio_end_time,
                })



    def _recalculate_running_balances(self, warehouse_id, blast_freezer_flag, from_datetime=None, from_create_date=None):
        """
        Fixed version: Properly calculate beginning balances for both main fields and building JSON
        """
        domain = [
            ('warehouse', '=', warehouse_id),
            ('is_blast_freezer', '=', blast_freezer_flag),
            ('active', '=', True),  # CRITICAL FIX: Exclude archived records
        ]
        
        if from_datetime and from_create_date:
            domain.extend([
                '|',
                ('start_time', '>=', from_datetime),
                ('create_date', '>=', from_create_date),
            ])
        elif from_datetime:
            domain.append(('start_time', '>=', from_datetime))
            
        # Get all affected records in chronological order
        records_to_update = self.search(domain, order='start_time asc, id asc')
        
        if not records_to_update:
            return
    
        # Get the previous warehouse-wide balance (for overall_* fields)
        if from_datetime:
            prev_warehouse_record = self.search([
                ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', blast_freezer_flag),
                ('start_time', '<', from_datetime)
            ], order='start_time desc, id desc', limit=1)
            
            if prev_warehouse_record:
                running_pallets = prev_warehouse_record.overall_pallets
                running_kilos = prev_warehouse_record.overall_kilos
            else:
                running_pallets = running_kilos = 0
        else:
            running_pallets = running_kilos = 0
    
        # Track per-owner AND per-building balances
        owner_building_balances = {}
        
        # Get previous balances for each owner
        owners_in_scope = records_to_update.mapped('owner_id')
        for owner in owners_in_scope:
            if not owner:
                continue
                
            # FIXED: Get the actual previous record for this specific owner
            prev_owner_record = None
            if from_datetime:
                prev_owner_record = self.search([
                    ('warehouse', '=', warehouse_id),
                    ('is_blast_freezer', '=', blast_freezer_flag),
                    ('owner_id', '=', owner.id),
                    ('start_time', '<', from_datetime)
                ], order='start_time desc, id desc', limit=1)
            
            if prev_owner_record and prev_owner_record.total_balances:
                # Start with previous building-specific balances
                owner_building_balances[owner.id] = json.loads(json.dumps(prev_owner_record.total_balances))
            else:
                # FIXED: No previous record means all buildings start with zero balances
                owner_building_balances[owner.id] = {}
    
        # Batch update all records
        updates = []
        for record in records_to_update:
            # Calculate warehouse-wide running totals (overall_* fields) including adjustments
            running_pallets += (record.pallets_received - record.pallets_withdrawn + record.adjustment_pallets)
            running_kilos += (record.kilos_received - record.kilos_withdrawn + record.adjustment_kilos)
    
            # Handle records without owner
            if not record.owner_id:
                updates.append({
                    'id': record.id,
                    'overall_pallets': running_pallets,
                    'overall_kilos': running_kilos,
                    'beginning_balance_in_pallets': 0,
                    'beginning_balance_in_kilos': 0,
                    'total_balance_in_units': 0,
                    'total_balance_in_packaging': 0,
                    'total_balance_in_kilos': 0,
                    'total_balance_in_pallets': 0,
                    'total_balances': {"MAIN": {
                        'total_balance_in_units': 0,
                        'total_balance_in_packaging': 0,
                        'total_balance_in_kilos': 0,
                        'total_balance_in_pallets': 0,
                        'beginning_balance_in_pallets': 0,
                        'beginning_balance_in_kilos': 0,
                    }}
                })
                continue
    
            owner_id = record.owner_id.id
            
            # FIXED: Calculate beginning balances BEFORE applying current operation
            # This should match exactly what the main record fields do
            
            # For main record fields: get previous owner record
            prev_owner_record = self.search([
                ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', blast_freezer_flag),
                ('owner_id', '=', owner_id),
                '|',
                ('start_time', '<', record.start_time),  # Earlier timestamp
                '&',
                ('start_time', '=', record.start_time),  # Same timestamp
                ('id', '<', record.id)  # But lower ID (created earlier)
            ], order='start_time desc, create_date desc, id desc', limit=1)
            
            if prev_owner_record:
                # Beginning balance is the total balance from the previous record
                main_beginning_pallets = prev_owner_record.total_balance_in_pallets
                main_beginning_kilos = prev_owner_record.total_balance_in_kilos
                
                # FIXED: Building beginning balances should come from previous record's building totals
                if prev_owner_record.total_balances:
                    building_beginning_balances = json.loads(json.dumps(prev_owner_record.total_balances))
                else:
                    building_beginning_balances = {}
            else:
                # FIXED: No previous record = all beginning balances are zero
                main_beginning_pallets = 0
                main_beginning_kilos = 0
                building_beginning_balances = {}
            
            # Initialize owner's building balances if not exists (for current calculation)
            if owner_id not in owner_building_balances:
                owner_building_balances[owner_id] = {}
    
            # Start with the building balances BEFORE this operation (i.e., the beginning balances)
            record_building_balances = dict(building_beginning_balances)  # Copy beginning balances
            
            # Get building operations for this record
            current_building_ops = getattr(record, 'building_operations_temp', {})
            
            if not current_building_ops and record.effective_document:
                current_building_ops = self._calculate_building_operations_for_record(record)
    
            # Handle opening balance records
            if not record.effective_document and record.remarks == 'imported via opening balance':
                building_name = "EXPANSION"
                if building_name not in record_building_balances:
                    record_building_balances[building_name] = {
                        'total_balance_in_units': 0,
                        'total_balance_in_packaging': 0,
                        'total_balance_in_kilos': 0,
                        'total_balance_in_pallets': 0,
                        'beginning_balance_in_pallets': 0,  # FIXED: Will be set below
                        'beginning_balance_in_kilos': 0,    # FIXED: Will be set below
                    }
                
                # FIXED: Set beginning balance (before this operation) for this building
                record_building_balances[building_name]['beginning_balance_in_pallets'] = record_building_balances[building_name].get('total_balance_in_pallets', 0)
                record_building_balances[building_name]['beginning_balance_in_kilos'] = record_building_balances[building_name].get('total_balance_in_kilos', 0)
                
                # Apply opening balance operation
                record_building_balances[building_name]['total_balance_in_units'] += record.units_received
                record_building_balances[building_name]['total_balance_in_packaging'] += record.packaging_received
                record_building_balances[building_name]['total_balance_in_kilos'] += record.kilos_received
                record_building_balances[building_name]['total_balance_in_pallets'] += record.pallets_received
            
            # Process building operations for regular documents
            elif current_building_ops:
                for building_name, operations in current_building_ops.items():
                    # Initialize building if it doesn't exist
                    if building_name not in record_building_balances:
                        record_building_balances[building_name] = {
                            'total_balance_in_units': 0,
                            'total_balance_in_packaging': 0,
                            'total_balance_in_kilos': 0,
                            'total_balance_in_pallets': 0,
                            'beginning_balance_in_pallets': 0,  # FIXED: New building starts with 0
                            'beginning_balance_in_kilos': 0,    # FIXED: New building starts with 0
                        }
    
                    # FIXED: Set beginning balance for this building (before current operation)
                    record_building_balances[building_name]['beginning_balance_in_pallets'] = record_building_balances[building_name].get('total_balance_in_pallets', 0)
                    record_building_balances[building_name]['beginning_balance_in_kilos'] = record_building_balances[building_name].get('total_balance_in_kilos', 0)
                    # raise UserError(str(operations))
                    # Apply operations to the specific building
                    if record.effective_document.picking_type_id.code == 'incoming':
                        record_building_balances[building_name]['total_balance_in_units'] += operations.get('units', 0)
                        record_building_balances[building_name]['total_balance_in_packaging'] += operations.get('packaging', 0)
                        record_building_balances[building_name]['total_balance_in_kilos'] += operations.get('kilos', 0)
                        record_building_balances[building_name]['total_balance_in_pallets'] += operations.get('pallets', 0)
                    elif record.effective_document.picking_type_id.code == 'outgoing':
                        record_building_balances[building_name]['total_balance_in_units'] -= operations.get('units', 0)
                        record_building_balances[building_name]['total_balance_in_packaging'] -= operations.get('packaging', 0)
                        record_building_balances[building_name]['total_balance_in_kilos'] -= operations.get('kilos', 0)
                        record_building_balances[building_name]['total_balance_in_pallets'] -= operations.get('pallets', 0)
    
            # FIXED: Apply adjustments proportionally to buildings that have balances
            if record.adjustment_heads or record.adjustment_packaging or record.adjustment_kilos or record.adjustment_pallets:
                buildings_with_balances = [
                    name for name, data in record_building_balances.items() 
                    if data.get('total_balance_in_units', 0) > 0 or 
                       data.get('total_balance_in_packaging', 0) > 0 or
                       data.get('total_balance_in_kilos', 0) > 0 or
                       data.get('total_balance_in_pallets', 0) > 0
                ]
                
                num_buildings = len(buildings_with_balances) if buildings_with_balances else 1
                
                if not buildings_with_balances:
                    # MAINs with balances, create "MAIN"
                    building_name = "MAIN"
                    if building_name not in record_building_balances:
                        record_building_balances[building_name] = {
                            'total_balance_in_units': 0,
                            'total_balance_in_packaging': 0,
                            'total_balance_in_kilos': 0,
                            'total_balance_in_pallets': 0,
                            'beginning_balance_in_pallets': 0,
                            'beginning_balance_in_kilos': 0,
                        }
                    buildings_with_balances = [building_name]
    
                # Distribute adjustments only to buildings with existing balances
                for building_name in buildings_with_balances:
                    record_building_balances[building_name]['total_balance_in_units'] += record.adjustment_heads / num_buildings
                    record_building_balances[building_name]['total_balance_in_packaging'] += record.adjustment_packaging / num_buildings
                    record_building_balances[building_name]['total_balance_in_kilos'] += record.adjustment_kilos / num_buildings
                    record_building_balances[building_name]['total_balance_in_pallets'] += record.adjustment_pallets / num_buildings
    
            # FIXED: For buildings that didn't have operations but existed in previous record,
            # set their beginning balances correctly
            for building_name, building_data in record_building_balances.items():
                if 'beginning_balance_in_pallets' not in building_data:
                    # This building came from previous record but didn't get processed above
                    building_data['beginning_balance_in_pallets'] = building_data.get('total_balance_in_pallets', 0)
                    building_data['beginning_balance_in_kilos'] = building_data.get('total_balance_in_kilos', 0)
    
            # Update owner's building balances for next iteration
            owner_building_balances[owner_id] = record_building_balances
    
            # Calculate totals across all buildings for this owner
            total_units = sum(building_data.get('total_balance_in_units', 0) for building_data in record_building_balances.values())
            total_packaging = sum(building_data.get('total_balance_in_packaging', 0) for building_data in record_building_balances.values())
            total_kilos = sum(building_data.get('total_balance_in_kilos', 0) for building_data in record_building_balances.values())
            total_pallets = sum(building_data.get('total_balance_in_pallets', 0) for building_data in record_building_balances.values())
    
            updates.append({
                'id': record.id,
                'overall_pallets': running_pallets,
                'overall_kilos': running_kilos,
                'beginning_balance_in_pallets': main_beginning_pallets,  # FIXED: Use calculated beginning balance
                'beginning_balance_in_kilos': main_beginning_kilos,      # FIXED: Use calculated beginning balance
                'total_balance_in_units': total_units,
                'total_balance_in_packaging': total_packaging,
                'total_balance_in_kilos': total_kilos,
                'total_balance_in_pallets': total_pallets,
                'total_balances': record_building_balances  # FIXED: Contains correct beginning balances per building
            })
    
        # Batch write all updates
        for update in updates:
            record_id = update.pop('id')
            self.browse(record_id).write(update)
    
    
    def _calculate_building_operations_for_record(self, record):
        """
        Helper method to calculate building operations for a record
        """
        building_operations = {}
        
        if record.effective_document.picking_type_code == 'outgoing':
            for move_line in record.effective_document.move_line_ids:
                building = move_line.location_id.x_studio_building if move_line.location_id else None
                building_name = self._get_building_name(building)
                
                if building_name not in building_operations:
                    building_operations[building_name] = {
                        'units': 0, 'packaging': 0, 'kilos': 0, 'pallets': 0
                    }
                
                building_operations[building_name]['units'] += move_line.x_studio_withdraw_units or 0
                building_operations[building_name]['packaging'] += move_line.x_studio_affected_2nd_uom or 0
                building_operations[building_name]['kilos'] += move_line.quantity or 0
        else:  # incoming
            for move_line in record.effective_document.move_line_ids:
                building = move_line.location_dest_id.x_studio_building if move_line.location_dest_id else None
                building_name = self._get_building_name(building)
                
                if building_name not in building_operations:
                    building_operations[building_name] = {
                        'units': 0, 'packaging': 0, 'kilos': 0, 'pallets': 0
                    }
                
                building_operations[building_name]['units'] += move_line.x_studio_total_units or 0
                building_operations[building_name]['packaging'] += move_line.x_studio_2nd_uom or 0
                building_operations[building_name]['kilos'] += move_line.quantity or 0
        
        return building_operations

    @api.model
    def create(self, vals):
        """Override create to handle backdated insertions"""
        record = super(PalletKilosRecordModel, self).create(vals)

        # Populate all data first
        record._populate_vehicle_data()
        record._populate_operations_data()
        record._populate_returns_data()

        # Check if this is a backdated insertion
        if record.start_time and record.warehouse:
            later_records = self.search([
                ('warehouse', '=', record.warehouse.id),
                ('is_blast_freezer', '=', record.is_blast_freezer),
                ('start_time', '>', record.start_time),
                ('id', '!=', record.id)
            ], limit=1)

            if later_records:
                # This is a backdated insertion - recalculate from this point forward
                _logger.info(f"Backdated insertion detected for warehouse {record.warehouse.name} at {record.start_time}")
                record._recalculate_running_balances(
                    record.warehouse.id,
                    record.is_blast_freezer,
                    record.start_time
                )
            else:
                # This is the latest record - just calculate its balance
                record._recalculate_running_balances(
                    record.warehouse.id,
                    record.is_blast_freezer,
                    record.start_time
                )

        return record

    def write(self, vals):
        """Override write to handle document changes, start_time changes, and adjustment field changes"""
        # Store original values for comparison
        original_data = {}
        adjustment_fields = [
            'adjustment_heads', 'adjustment_packaging', 
            'adjustment_pallets', 'adjustment_kilos'
        ]
        
        for record in self:
            original_data[record.id] = {
                'start_time': record.start_time,
                'warehouse_id': record.warehouse.id if record.warehouse else None,
                'is_blast_freezer': record.is_blast_freezer,
                # Store original adjustment values
                'adjustment_heads': record.adjustment_heads,
                'adjustment_packaging': record.adjustment_packaging,
                'adjustment_pallets': record.adjustment_pallets,
                'adjustment_kilos': record.adjustment_kilos,
            }

        result = super(PalletKilosRecordModel, self).write(vals)

        # Handle document changes
        if 'record_reference' in vals or 'readjustment_document' in vals:
            for record in self:
                record._populate_vehicle_data()
                record._populate_operations_data()
                record._populate_returns_data()

        # Handle adjustment field changes - first subtract old values, then recalculate
        if any(field in vals for field in adjustment_fields):
            for record in self:
                if record.warehouse and record.start_time:
                    old_data = original_data[record.id]
                    
                    # Calculate the net change in adjustments
                    adjustment_changes = {
                        'heads': record.adjustment_heads - old_data['adjustment_heads'],
                        'packaging': record.adjustment_packaging - old_data['adjustment_packaging'],
                        'pallets': record.adjustment_pallets - old_data['adjustment_pallets'],
                        'kilos': record.adjustment_kilos - old_data['adjustment_kilos'],
                    }
                    
                    # Log the adjustment changes for debugging
                    if any(change != 0 for change in adjustment_changes.values()):
                        _logger.info(f"Adjustment changes for record {record.id}: {adjustment_changes}")
                    
                    # Recalculate from this record's start_time forward since adjustments affect running balances
                    record._recalculate_running_balances(
                        record.warehouse.id,
                        record.is_blast_freezer,
                        record.start_time
                    )

        # Handle start_time changes (potential backdating)
        elif 'start_time' in vals:
            for record in self:
                old_data = original_data[record.id]
                if (record.start_time != old_data['start_time'] and 
                    record.warehouse and record.start_time):
                    # Recalculate from the earlier of old or new start_time
                    earliest_time = min(record.start_time, old_data['start_time']) if old_data['start_time'] else record.start_time
                    record._recalculate_running_balances(
                        record.warehouse.id,
                        record.is_blast_freezer,
                        earliest_time
                    )

        return result

    def unlink(self):
        """Override unlink to recalculate balances after deletion"""
        records_to_recalc = []
        for record in self:
            if record.warehouse and record.start_time:
                records_to_recalc.append({
                    'warehouse_id': record.warehouse.id,
                    'is_blast_freezer': record.is_blast_freezer,
                    'start_time': record.start_time,
                })

        result = super(PalletKilosRecordModel, self).unlink()

        # Recalculate balances for affected warehouses
        for data in records_to_recalc:
            self._recalculate_running_balances(
                data['warehouse_id'],
                data['is_blast_freezer'],
                data['start_time']
            )

        return result

    def manual_recalculate_all(self):
        """Manual method to recalculate all running balances - for maintenance"""
        warehouses = self.search([]).mapped('warehouse')
        for warehouse in warehouses:
            for blast_freezer in [True, False]:
                self._recalculate_running_balances(warehouse.id, blast_freezer)

    def resync_all(self):
        """Resync current record"""
        for record in self:
            record._populate_vehicle_data()
            record._populate_operations_data()
            record._populate_returns_data()
            record._recalculate_running_balances(
                record.warehouse.id,
                record.is_blast_freezer,
                record.start_time
            )

    def resync_all_2(self):
        """Resync all records in chronological order"""
        all_records = self.search([], order='start_time desc, id desc')
        warehouses_processed = set()
        
        for record in all_records:
            record._populate_vehicle_data()
            record._populate_operations_data()
            record._populate_returns_data()
            
            # Only recalculate once per warehouse-blast_freezer combination
            key = (record.warehouse.id, record.is_blast_freezer)
            if key not in warehouses_processed:
                record._recalculate_running_balances(record.warehouse.id, record.is_blast_freezer)
                warehouses_processed.add(key)

    @api.model
    def import_opening_balances_from_quants(self, quant_ids):
        """
        Import opening balances from selected stock.quant records
        Creates PalletKilosRecordModel records grouped by owner+warehouse+building
        """
        if not quant_ids:
            raise UserError("No stock quant records selected.")

        # Get selected quants
        quants = self.env['stock.quant'].browse(quant_ids)

        # Validate quants haven't been imported before
        existing_records = self.search([
            ('remarks', '=', 'imported via opening balance')
        ])

        # Get current datetime in UTC+8
        from datetime import datetime, timezone, timedelta
        utc_plus_8 = timezone(timedelta(hours=8))
        current_time = datetime.now(utc_plus_8).replace(tzinfo=None) - timedelta(days=5)  # Remove timezone info for Odoo

        # Group quants by owner + warehouse + building
        grouped_data = {}
        for quant in quants:
            if not quant.location_id.warehouse_id:
                _logger.warning(f"Skipping quant {quant.id} - no warehouse found for location {quant.location_id.name}")
                continue

            # Get building for this quant
            building = quant.location_id.x_studio_building if quant.location_id else None
            building_name = self._get_building_name(building)
            
            key = (
                quant.owner_id.id if quant.owner_id else False,
                quant.location_id.warehouse_id.id,
                building_name
            )

            if key not in grouped_data:
                grouped_data[key] = {
                    'owner_id': quant.owner_id.id if quant.owner_id else False,
                    'warehouse_id': quant.location_id.warehouse_id.id,
                    'building_name': building_name,
                    'total_units': 0,
                    'total_packaging': 0,
                    'total_kilos': 0,
                    'unique_packages': set(),
                    'quant_ids': []
                }

            # Accumulate totals
            grouped_data[key]['total_units'] += quant.x_studio_total_units or 0
            grouped_data[key]['total_packaging'] += quant.x_studio_2nd_uom or 0
            grouped_data[key]['total_kilos'] += quant.inventory_quantity_auto_apply or 0

            # Track unique packages (pallets)
            if quant.package_id:
                grouped_data[key]['unique_packages'].add(quant.package_id.id)

            grouped_data[key]['quant_ids'].append(quant.id)

        if not grouped_data:
            raise UserError("No valid stock quant records found with warehouse information.")

        # Create opening balance records
        created_records = []
        
        # Group by owner+warehouse for record creation (one record per owner+warehouse)
        owner_warehouse_data = {}
        for (owner_id, warehouse_id, building_name), data in grouped_data.items():
            ow_key = (owner_id, warehouse_id)
            if ow_key not in owner_warehouse_data:
                owner_warehouse_data[ow_key] = {
                    'owner_id': owner_id,
                    'warehouse_id': warehouse_id,
                    'total_units': 0,
                    'total_packaging': 0,
                    'total_kilos': 0,
                    'total_pallets': 0,
                    'buildings': {}
                }
            
            # Aggregate totals
            owner_warehouse_data[ow_key]['total_units'] += data['total_units']
            owner_warehouse_data[ow_key]['total_packaging'] += data['total_packaging']
            owner_warehouse_data[ow_key]['total_kilos'] += data['total_kilos']
            owner_warehouse_data[ow_key]['total_pallets'] += len(data['unique_packages'])
            
            # Store building-specific data
            owner_warehouse_data[ow_key]['buildings'][building_name] = {
                'total_balance_in_units': data['total_units'],
                'total_balance_in_packaging': data['total_packaging'],
                'total_balance_in_kilos': data['total_kilos'],
                'total_balance_in_pallets': len(data['unique_packages']),
                'beginning_balance_in_pallets': 0,
                'beginning_balance_in_kilos': 0,
            }

        for (owner_id, warehouse_id), data in owner_warehouse_data.items():
            # Generate report number for opening balance
            report_no = f"OB-{warehouse_id}-{current_time.strftime('%Y%m%d%H%M%S')}"
            if owner_id:
                owner_name = self.env['res.partner'].browse(owner_id).name
                report_no += f"-{owner_name[:3].upper()}"

            vals = {
                'report_no': report_no,
                'owner_id': owner_id,
                'warehouse': warehouse_id,
                'record_reference': False,  # No source document
                'readjustment_document': False,
                'active': True,

                # Opening balance - show as received (initial stock coming in)
                'pallets_received': data['total_pallets'],
                'pallets_withdrawn': 0,
                'kilos_received': data['total_kilos'],
                'kilos_withdrawn': 0,
                'packaging_received': data['total_packaging'],
                'packaging_withdrawn': 0,
                'units_received': data['total_units'],
                'units_withdrawn': 0,

                # Balance fields from quant data (for opening balance, these equal the received amounts)
                'total_balance_in_units': data['total_units'],
                'total_balance_in_packaging': data['total_packaging'],
                'total_balance_in_kilos': data['total_kilos'],
                'total_balance_in_pallets': data['total_pallets'],

                # Beginning balance is zero for opening records (this IS the beginning)
                'beginning_balance_in_pallets': 0,
                'beginning_balance_in_kilos': 0,

                # Return and adjustment fields are zero
                'return_heads': 0,
                'return_packaging': 0,
                'return_pallets': 0,
                'return_kilos': 0,
                'adjustment_heads': 0,
                'adjustment_packaging': 0,
                'adjustment_pallets': 0,
                'adjustment_kilos': 0,

                # Vehicle fields are blank (no transport involved)
                'truck_type': 'N/A',
                'trucks_plate': '',
                'gate_pass': '',
                'start_time': current_time,
                'end_time': current_time,

                # Blast freezer flag
                'is_blast_freezer': False,

                # Building-level balances
                'total_balances': data['buildings'],

                # Special remarks
                'remarks': 'imported via opening balance',
            }

            # Create the record (this will trigger the create() method which handles balance calculations)
            record = self.create(vals)
            created_records.append(record)
            _logger.info(f"Created opening balance record {record.id} for warehouse {warehouse_id}, owner {owner_id}")

        # After all records are created, recalculate overall warehouse totals
        # Group by warehouse for recalculation
        warehouses_to_recalc = set()
        for record in created_records:
            warehouses_to_recalc.add(record.warehouse.id)

        for warehouse_id in warehouses_to_recalc:
            # Recalculate from the beginning since these are opening balances
            self._recalculate_running_balances(warehouse_id, False, None)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Opening Balances Imported',
                'message': f'Successfully created {len(created_records)} opening balance records with building-level tracking.',
                'type': 'success',
                'sticky': False,
            }
        }