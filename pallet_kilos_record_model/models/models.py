from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from datetime import datetime, timedelta
import logging
import json

_logger = logging.getLogger(__name__)

class PalletKilosRecordModel(models.Model):
    _name = 'pallet_kilos_record_model.pallet_kilos_record_model'
    _description = 'Pallet Kilos Record Model'
    _order = 'start_time asc, id asc'  # Must match _recalculate_running_balances ordering

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
    kilos_received = fields.Float(store=True, string="Kilos Received", readonly=True, digits='Product Unit of Measure')
    kilos_withdrawn = fields.Float(store=True, string="Kilos Withdrawn", readonly=True, digits='Product Unit of Measure')

    # Operation fields - stored, not computed
    packaging_received = fields.Float(string="Packaging Received", readonly=True, store=True)
    packaging_withdrawn = fields.Float(string="Packaging Withdrawn", readonly=True, store=True)
    units_received = fields.Float(string="Units Received", readonly=True, store=True)
    units_withdrawn = fields.Float(string="Units Withdrawn", readonly=True, store=True)

    # Balance fields - stored, calculated via method calls
    total_balance_in_units = fields.Float(store=True, string="Total Balance in Packs", readonly=True, group_operator=False)
    total_balance_in_packaging = fields.Float(store=True, string="Total Balance in Quantity", group_operator=False)
    total_balance_in_kilos = fields.Float(store=True, string="Total Balance in Kilos (KG)", readonly=True, group_operator=False, digits='Product Unit of Measure')
    total_balance_in_pallets = fields.Float(store=True, string="Total Balance in Pallets", readonly=True, group_operator=False)

    # Return fields - stored, not computed
    return_id = fields.Many2one('stock.picking', readonly=True, string="Return RR ID")
    return_heads = fields.Float(string="Total Return Units", readonly=True)
    return_packaging = fields.Float(string="Total Return Packaging", readonly=True)
    return_pallets = fields.Float(string="Total Return Pallets", readonly=True)
    return_kilos = fields.Float(string="Total Return Kilos", readonly=True, digits='Product Unit of Measure')

    adjustment_heads = fields.Float(string="Total Adjustment Units", readonly=True)
    adjustment_packaging = fields.Float(string="Total Adjustment Packaging", readonly=True)
    adjustment_pallets = fields.Float(string="Total Adjustment Pallets", readonly=True)
    adjustment_kilos = fields.Float(string="Total Adjustment Kilos", readonly=True, digits='Product Unit of Measure')
    # Human-readable explanation of every adjustment posted to this row
    # (re-sync events, residuals, correction pallet legs). Rebuilt by the
    # Re-sync action; remarks keeps a compact plain-text copy for XLSX.
    adjustment_reason_html = fields.Html(
        string="Adjustment Explanation", readonly=True, sanitize=True)

    # Beginning balance fields - stored, calculated via method calls
    beginning_balance_in_pallets = fields.Float(string="Beginning Balance in Pallets", readonly=True, store=True)
    beginning_balance_in_kilos = fields.Float(string="Beginning Balance in Kilos", readonly=True, store=True, digits='Product Unit of Measure')

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
    overall_kilos = fields.Float(string='Overall Kilos', store=True, group_operator=False, digits='Product Unit of Measure')

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
                            # (a per-line stock.move.line search used to run here;
                            # its result was never used — removed for performance)
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
                    # Don't break - accumulate ALL valid partial withdraw returns

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
        """Owner-level running-balance engine (per-building breakdown retired).

        Rebuilds the cumulative balance series for one (warehouse, is_blast_freezer)
        partition directly from each record's stored operation totals:
            total_X = beginning_X + (X_received - X_withdrawn) + adjustment_X
        where beginning_X is the previous record's total for the same owner. This is
        internal-consistency only: it never compares to or forces physical stock --
        genuine ledger-vs-stock gaps are surfaced by Get Unsynced, not corrected here.
        """
        return self._recompute_owner_running_balances(
            warehouse_id, blast_freezer_flag,
            from_datetime=from_datetime, from_create_date=from_create_date)

    def _recompute_owner_running_balances(self, warehouse_id, blast_freezer_flag, from_datetime=None, from_create_date=None):
        domain = [
            ('warehouse', '=', warehouse_id),
            ('is_blast_freezer', '=', blast_freezer_flag),
            ('active', '=', True),
        ]
        if from_datetime and from_create_date:
            domain.extend([
                '|',
                ('start_time', '>=', from_datetime),
                ('create_date', '>=', from_create_date),
            ])
        elif from_datetime:
            domain.append(('start_time', '>=', from_datetime))

        records_to_update = self.search(domain, order='start_time asc, id asc')
        if not records_to_update:
            return

        # Warehouse-wide running totals (all owners) seeded from the most recent prior record
        running_pallets = running_kilos = 0.0
        if from_datetime:
            prev_wh = self.search([
                ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', blast_freezer_flag),
                ('active', '=', True),
                ('start_time', '<', from_datetime),
            ], order='start_time desc, id desc', limit=1)
            if prev_wh:
                running_pallets = prev_wh.overall_pallets
                running_kilos = prev_wh.overall_kilos

        # Per-owner beginning balances, seeded from each owner's most recent prior record
        owner_running = {}
        if from_datetime:
            for owner in records_to_update.mapped('owner_id'):
                if not owner:
                    continue
                prev = self.search([
                    ('warehouse', '=', warehouse_id),
                    ('is_blast_freezer', '=', blast_freezer_flag),
                    ('active', '=', True),
                    ('owner_id', '=', owner.id),
                    ('start_time', '<', from_datetime),
                ], order='start_time desc, id desc', limit=1)
                if prev:
                    owner_running[owner.id] = {
                        'units': prev.total_balance_in_units or 0.0,
                        'packaging': prev.total_balance_in_packaging or 0.0,
                        'kilos': prev.total_balance_in_kilos or 0.0,
                        'pallets': prev.total_balance_in_pallets or 0.0,
                    }

        updates = []
        for record in records_to_update:
            # Warehouse-wide cumulative (all owners) -- unchanged behavior
            running_pallets += (record.pallets_received - record.pallets_withdrawn + record.adjustment_pallets)
            running_kilos += (record.kilos_received - record.kilos_withdrawn + record.adjustment_kilos)

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
                    'total_balances': {},
                })
                continue

            oid = record.owner_id.id
            begin = owner_running.get(
                oid, {'units': 0.0, 'packaging': 0.0, 'kilos': 0.0, 'pallets': 0.0})

            total = {
                'units': begin['units'] + record.units_received - record.units_withdrawn + record.adjustment_heads,
                'packaging': begin['packaging'] + record.packaging_received - record.packaging_withdrawn + record.adjustment_packaging,
                'kilos': begin['kilos'] + record.kilos_received - record.kilos_withdrawn + record.adjustment_kilos,
                'pallets': begin['pallets'] + record.pallets_received - record.pallets_withdrawn + record.adjustment_pallets,
            }
            owner_running[oid] = total

            updates.append({
                'id': record.id,
                'overall_pallets': running_pallets,
                'overall_kilos': running_kilos,
                'beginning_balance_in_pallets': begin['pallets'],
                'beginning_balance_in_kilos': begin['kilos'],
                'total_balance_in_units': total['units'],
                'total_balance_in_packaging': total['packaging'],
                'total_balance_in_kilos': total['kilos'],
                'total_balance_in_pallets': total['pallets'],
                'total_balances': {},
            })

        for update in updates:
            rid = update.pop('id')
            self.browse(rid).write(update)

    def _dead_recalculate_running_balances_legacy(self, warehouse_id, blast_freezer_flag, from_datetime=None, from_create_date=None):
        # RETIRED per-building implementation -- no longer called (kept temporarily for
        # reference; superseded by _recompute_owner_running_balances above).
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
        
        # FIXED: Track calculated balances IN MEMORY during the loop
        calculated_balances = {}  # {record_id: {'total_pallets': X, 'total_kilos': Y, 'total_balances': {...}}}
        
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
    
            # FIXED: Check if we just calculated this previous record's balance in THIS loop
            if prev_owner_record and prev_owner_record.id in calculated_balances:
                # Use the freshly calculated balance (not yet written to DB)
                main_beginning_pallets = calculated_balances[prev_owner_record.id]['total_pallets']
                main_beginning_kilos = calculated_balances[prev_owner_record.id]['total_kilos']
                building_beginning_balances = json.loads(json.dumps(calculated_balances[prev_owner_record.id]['total_balances']))
            elif prev_owner_record:
                # Use the database values (record wasn't in this batch)
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
                    # No buildings with balances, create "MAIN"
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
    
            # FIXED: Store calculated balances in memory for next iteration
            calculated_balances[record.id] = {
                'total_pallets': total_pallets,
                'total_kilos': total_kilos,
                'total_balances': record_building_balances
            }
    
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

        # Guard: If the source picking is a void transfer (is_void_wr or is_void_return),
        # immediately archive this record to prevent phantom entries.
        # The automated action (BA 6) fires on ALL state='done' transitions,
        # including void WRs and void return RRs that will be auto-voided right after.
        source_picking = record.record_reference
        if source_picking and (source_picking.is_void_wr or source_picking.is_void_return):
            _logger.info(
                "Skipping pallet kilos record creation for void transfer %s (is_void_wr=%s, is_void_return=%s)",
                source_picking.name, source_picking.is_void_wr, source_picking.is_void_return
            )
            record.active = False
            return record

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

                # Explicitly rebuild balances: re-population changes the operation
                # totals, and the nested start_time write only triggers a recalc
                # when the new document's start_time differs from the old one.
                # Without this, a revision swap with an unchanged start_time left
                # the running balances stale. Recalculate both the old and new
                # BF partitions in case the document swap moved the record.
                old_data = original_data.get(record.id, {})
                if record.warehouse:
                    times = [t for t in (record.start_time, old_data.get('start_time')) if t]
                    if times:
                        for bf_flag in {record.is_blast_freezer,
                                        old_data.get('is_blast_freezer', record.is_blast_freezer)}:
                            record._recalculate_running_balances(
                                record.warehouse.id, bf_flag, min(times))

        # Handle adjustment field changes - first subtract old values, then recalculate
        # (skip_pkr_recalc: batch operations recalculate once per partition at
        # the end instead of once per row write)
        if (any(field in vals for field in adjustment_fields)
                and not self.env.context.get('skip_pkr_recalc')):
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

    def action_recompute_selected_balances(self):
        """Server-action target: rebuild the running-balance series for every
        (warehouse, is_blast_freezer) partition represented in the selection.

        Balances-only / fast: it uses the already-stored per-record operation
        totals (it does NOT re-read source documents) and NEVER forces the ledger
        to match physical stock. Each affected partition is rebuilt in full from
        the beginning, so selecting all rows cleanly rebuilds everything.
        """
        partitions = set()
        for rec in self:
            if rec.warehouse:
                partitions.add((rec.warehouse.id, rec.is_blast_freezer))
        if not partitions:
            raise UserError("No records with a warehouse were selected.")
        for wh_id, bf in partitions:
            self._recalculate_running_balances(wh_id, bf)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Balances Recomputed',
                'message': 'Recomputed %d record(s) across %d partition(s).' % (
                    len(self), len(partitions)),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_get_unsynced(self):
        """Server-action target (READ-ONLY): print ledger-vs-physical-stock
        discrepancies per (owner, warehouse, is_blast_freezer) partition.

        Ledger side = the latest active record's total_balance_in_kilos for the
        partition. Actual side = sum of on-hand stock.quant.quantity for that owner
        in that warehouse's internal locations, split by blast-freezer flag (so BF
        stock, which has no package, is INCLUDED). Writes nothing -- genuine
        imbalances are surfaced here, never auto-corrected.
        """
        if not self:
            raise UserError("No records selected.")
        Quant = self.env['stock.quant']

        candidates = self.filtered(
            lambda r: r.owner_id and r.warehouse and r.start_time)
        latest = {}
        for rec in candidates.sorted(key=lambda r: (r.start_time, r.id), reverse=True):
            key = (rec.owner_id.id, rec.warehouse.id, rec.is_blast_freezer)
            if key not in latest:
                latest[key] = rec

        rows = []
        for (owner_id, wh_id, bf), rec in latest.items():
            ledger_kilos = rec.total_balance_in_kilos or 0.0
            quants = Quant.search([
                ('owner_id', '=', owner_id),
                ('location_id.usage', '=', 'internal'),
                ('location_id.warehouse_id', '=', wh_id),
                ('location_is_bf', '=', bf),
                ('quantity', '!=', 0),
            ])
            actual_kilos = sum(quants.mapped('quantity'))
            if round(abs(ledger_kilos - actual_kilos), 2) == 0.0:
                continue
            rows.append((
                rec.owner_id.name or 'Unknown',
                rec.warehouse.name or '',
                'BF' if bf else 'Reg',
                ledger_kilos, actual_kilos, ledger_kilos - actual_kilos,
            ))

        if not rows:
            raise UserError("All partitions match. No discrepancies found.")

        rows.sort(key=lambda r: r[0])
        w = (28, 14, 5, 16, 16, 14)
        sep = '+' + '+'.join('-' * x for x in w) + '+'
        header = (
            '| ' + 'Owner'.ljust(w[0] - 2)
            + ' | ' + 'Warehouse'.ljust(w[1] - 2)
            + ' | ' + 'BF'.ljust(w[2] - 2)
            + ' | ' + 'Ledger (kg)'.rjust(w[3] - 2)
            + ' | ' + 'Actual (kg)'.rjust(w[4] - 2)
            + ' | ' + 'Diff'.rjust(w[5] - 2) + ' |'
        )
        lines = [sep, header, sep]
        for owner, wh, bf_label, led, act, diff in rows:
            lines.append(
                '| ' + owner[:w[0] - 2].ljust(w[0] - 2)
                + ' | ' + wh[:w[1] - 2].ljust(w[1] - 2)
                + ' | ' + bf_label.ljust(w[2] - 2)
                + ' | ' + '{:,.2f}'.format(led).rjust(w[3] - 2)
                + ' | ' + '{:,.2f}'.format(act).rjust(w[4] - 2)
                + ' | ' + '{:+,.2f}'.format(diff).rjust(w[5] - 2) + ' |'
            )
            lines.append(sep)
        table = '\n'.join(lines)
        raise UserError(
            "Unsynced partitions: %d of %d (from %d selected)\n\n%s" % (
                len(rows), len(latest), len(self), table))

    def action_resync_pallet_counts(self):
        """Server-action target: make pallet counts accurate per row.

        For every OWNER present in the selection (whole-owner scope):
        1. Re-populate pallets_received/withdrawn from the documents (current
           counting rule).
        2. Re-link the owner's APPROVED stock.quant.adjustment.line records
           to their PKR row (the quant's record reference, else the OLDEST
           row in the owner's regular partition) — the native adjustment
           lines ARE the audit trail shown on the PKR form.
        3. Rebuild adjustment_pallets from recorded history: for packages
           that saw a picking-less exit to the inventory location and hold
           no stock for the owner today, compare how many times the ledger
           COUNTED them received (unique result_package per RR) vs COUNTED
           withdrawn (unique package per WR with
           reserved_quantity_on_validation == 0) and post the imbalance on
           the originating RR row (else the oldest row). Balanced pallets
           get NO event — a partial adjustment followed by a counted WR is
           already fully accounted. (Entry-side events are NOT derived: a
           positive correction line cannot be distinguished from a routine
           +kg fix on an already-stocked pallet — verified 594 false
           positives on one owner. The residual anchor absorbs that side.
           Package swaps are net 0 at owner level.)
        4. Anchor any untraceable residual on the partition's OPENING-BALANCE
           row (the PKR with no stock.picking reference — untraceable drift
           is almost always import/mass-adjustment residue that belongs with
           the opening balance), else the latest row. Clearly remarked, so
           ledger == actual distinct pallets after every run. Idempotent:
           wipe-and-rebuild each run.
        """
        if not self:
            raise UserError("No records selected.")
        owners = self.mapped('owner_id')
        if not owners:
            raise UserError("Selected records have no owner.")
        Quant = self.env['stock.quant']
        MoveLine = self.env['stock.move.line']
        today = fields.Date.context_today(self)
        summary = []
        all_partitions = set()

        for owner in owners:
            rows = self.search([('owner_id', '=', owner.id), ('active', '=', True)])
            partitions = {(r.warehouse.id, bool(r.is_blast_freezer))
                          for r in rows if r.warehouse}
            if not partitions:
                continue
            all_partitions |= partitions

            # -- 1. re-populate document-based pallet counts --------------
            repop = rows.filtered(lambda r: r.effective_document)
            repop._populate_operations_data()

            # -- 2. reset the pallet adjustment floats (rebuilt below).
            #       The kilo/packaging/units FLOATS are never touched here —
            #       they stay live-accumulated by the correction wizard.
            rows.with_context(skip_pkr_recalc=True).write(
                {'adjustment_pallets': 0, 'adjustment_reason_html': False})
            # strip event/residual notes from previous runs (fresh ones are
            # posted below if still needed) so repeated runs don't stack
            for r in rows:
                if r.remarks and 'pallet re-sync' in r.remarks:
                    kept = [p for p in r.remarks.split(' | ')
                            if p and 'pallet re-sync' not in p]
                    r.with_context(skip_pkr_recalc=True).write(
                        {'remarks': ' | '.join(kept) or False})
            # structured explanation entries per row, rendered as an HTML
            # table at the end of the owner pass: (item, pallets, why)
            html_rows = {}

            row_by_doc = {r.effective_document.id: r
                          for r in rows if r.effective_document}
            # fallback for quants with no record reference: the OPENING-
            # BALANCE row (no stock.picking reference) — same anchor the
            # residual uses, so lines and explanations sit together
            fallback_row = self.search([
                ('owner_id', '=', owner.id), ('active', '=', True),
                ('is_blast_freezer', '=', False),
                ('effective_document', '=', False)],
                order='start_time asc, id asc', limit=1) or self.search([
                ('owner_id', '=', owner.id), ('active', '=', True),
                ('is_blast_freezer', '=', False)],
                order='start_time asc, id asc', limit=1)

            # -- 2a. re-link approved adjustment lines to their PKR row ----
            #       (the native stock.quant.adjustment.line records are the
            #       audit trail; no shadow entries are created)
            relinked = 0
            zero_line_by_batch = {}
            AdjLine = self.env['stock.quant.adjustment.line'].sudo()
            if 'pallet_kilos_record_id' in AdjLine._fields:
                adj_lines = AdjLine.search([
                    ('line_state', '=', 'approved'),
                    ('old_owner_id', '=', owner.id)])
                for al in adj_lines:
                    if (al.request_id.batch_number
                            and not (al.new_quantity or 0)
                            and not (al.new_x_studio_2nd_uom or 0)
                            and (al.old_quantity or 0) > 0):
                        # "adjusted to 0" correction — remembered so the
                        # matching pallet event below can cite it and land
                        # on the same PKR row as the line
                        zero_line_by_batch[al.request_id.batch_number] = al
                    quant = al.quant_id.exists()
                    rr = (quant.original_record_reference
                          or quant.x_studio_record_reference) if quant else False
                    if not rr and al.request_id.batch_number:
                        # quant deleted since: recover the RR from the
                        # correction's KG move, which stamps the reference
                        mv = MoveLine.search([
                            ('state', '=', 'done'),
                            ('picking_id', '=', False),
                            ('owner_id', '=', owner.id),
                            ('adjustment_batch_number', '=',
                             al.request_id.batch_number),
                            ('adjustment_reference_id', '!=', False)],
                            limit=1)
                        rr = mv.adjustment_reference_id
                    target = row_by_doc.get(rr.id) if rr else None
                    target = target or fallback_row
                    if target and al.pallet_kilos_record_id.id != target.id:
                        al.pallet_kilos_record_id = target.id
                        relinked += 1

            exit_lines = MoveLine.search([
                ('state', '=', 'done'), ('picking_id', '=', False),
                ('owner_id', '=', owner.id), ('quantity', '>', 0),
                ('package_id', '!=', False),
                ('location_dest_id.usage', '=', 'inventory')])
            exit_pkgs = set(exit_lines.mapped('package_id').ids)
            batch_by_pkg = {}
            for xl in exit_lines:
                if xl.adjustment_batch_number:
                    batch_by_pkg.setdefault(xl.package_id.id, set()).add(
                        xl.adjustment_batch_number)

            # one batched query: which of those packages still hold stock?
            stocked = set()
            if exit_pkgs:
                stocked = {
                    g['package_id'][0] for g in Quant.read_group(
                        [('owner_id', '=', owner.id), ('quantity', '>', 0),
                         ('location_id.usage', '=', 'internal'),
                         ('package_id', 'in', list(exit_pkgs))],
                        ['package_id'], ['package_id'])}
            dead_pkgs = exit_pkgs - stocked

            # batched queries: originating RR per dead package, plus how many
            # times each was COUNTED received (unique result_package per RR)
            # vs COUNTED withdrawn (unique package per WR, only when
            # reserved_quantity_on_validation == 0 — the ledger rule).
            rr_by_pkg = {}
            counted_in = {}
            counted_out = {}
            psi_by_pkg = {}
            if dead_pkgs:
                for line in MoveLine.search([
                        ('state', '=', 'done'),
                        ('result_package_id', 'in', list(dead_pkgs)),
                        ('owner_id', '=', owner.id),
                        ('picking_id.picking_type_id.code', '=', 'incoming')],
                        order='date asc'):
                    rr_by_pkg.setdefault(line.result_package_id.id,
                                         line.picking_id)
                    counted_in.setdefault(line.result_package_id.id,
                                          set()).add(line.picking_id.id)
                    psi = getattr(line, 'x_studio_pallet_series_id', False)
                    if psi:
                        psi_by_pkg.setdefault(line.result_package_id.id, psi)
                for line in MoveLine.search([
                        ('state', '=', 'done'),
                        ('package_id', 'in', list(dead_pkgs)),
                        ('owner_id', '=', owner.id),
                        # NULL counts as 0 — mirrors _populate_operations_data,
                        # where a missing value reads as 0.0 in Python
                        '|', ('reserved_quantity_on_validation', '=', 0),
                             ('reserved_quantity_on_validation', '=', False),
                        ('picking_id.picking_type_id.code', '=', 'outgoing')]):
                    counted_out.setdefault(line.package_id.id,
                                           set()).add(line.picking_id.id)
            # row_by_doc / fallback_row already built before step 2a

            events = 0
            event_pkgs = set()
            pkg_names = {p.id: p.name
                         for p in self.env['stock.quant.package'].browse(list(dead_pkgs))}
            for pkg_id in dead_pkgs:
                # only post an event if the ledger still thinks the pallet is
                # in (or out) — a pallet whose counted receipts and counted
                # withdrawals balance needs NO event, even if a picking-less
                # adjustment moved part of its stock (that exit did not kill
                # the pallet; a later WR did, and the WR already counted it).
                delta = (len(counted_out.get(pkg_id, ()))
                         - len(counted_in.get(pkg_id, ())))
                if not delta:
                    continue
                psi = psi_by_pkg.get(pkg_id)
                ident = ('PSI %s' % psi) if psi \
                    else ('pallet %s' % pkg_names.get(pkg_id, pkg_id))
                # if the pallet died through an approved "adjusted to 0"
                # correction, cite that batch and post the event on the
                # SAME row its adjustment line is linked to
                zline = next(
                    (zero_line_by_batch[b]
                     for b in sorted(batch_by_pkg.get(pkg_id, ()))
                     if b in zero_line_by_batch), None)
                if zline is not None and zline.pallet_kilos_record_id:
                    target = zline.pallet_kilos_record_id
                    why = ('%s was adjusted to 0 quantity by adjustment '
                           'request batch %s, so the pallet left without a '
                           'WR' % (ident, zline.request_id.batch_number))
                else:
                    rr = rr_by_pkg.get(pkg_id)
                    target = row_by_doc.get(rr.id) if rr else None
                    target = target or fallback_row
                    why = ('%s was counted received %dx and withdrawn %dx '
                           'by documents, but holds no stock for this '
                           'owner today — its last exit was never counted'
                           % (ident,
                              len(counted_in.get(pkg_id, ())),
                              len(counted_out.get(pkg_id, ()))))
                if not target:
                    continue
                note = ('pallet re-sync event %s: %+g (%s)'
                        % (today, delta, why))
                target.with_context(skip_pkr_recalc=True).write({
                    'adjustment_pallets': target.adjustment_pallets + delta,
                    'remarks': ((target.remarks + ' | ') if target.remarks
                                else '') + note,
                })
                html_rows.setdefault(target.id, []).append(
                    (ident, '%+g' % delta, why))
                _logger.info('Re-sync: %s -> PKR %s', note, target.id)
                event_pkgs.add(pkg_id)
                events += 1

            # -- 3. residual anchor (NO stored-balance dependency: the owner
            #       ledger total is the plain sum of the flow components, so
            #       one read_group replaces a full partition rebuild here) ----
            residual_notes = []
            for wh_id, bf in partitions:
                grp = self.read_group(
                    [('owner_id', '=', owner.id), ('warehouse', '=', wh_id),
                     ('is_blast_freezer', '=', bf), ('active', '=', True)],
                    ['pallets_received', 'pallets_withdrawn',
                     'adjustment_pallets',
                     'packaging_received', 'packaging_withdrawn',
                     'adjustment_packaging',
                     'units_received', 'units_withdrawn', 'adjustment_heads',
                     'kilos_received', 'kilos_withdrawn', 'adjustment_kilos'],
                    [])[0]
                ledger = ((grp['pallets_received'] or 0)
                          - (grp['pallets_withdrawn'] or 0)
                          + (grp['adjustment_pallets'] or 0))
                ledger_packs = ((grp['packaging_received'] or 0)
                                - (grp['packaging_withdrawn'] or 0)
                                + (grp['adjustment_packaging'] or 0))
                ledger_units = ((grp['units_received'] or 0)
                                - (grp['units_withdrawn'] or 0)
                                + (grp['adjustment_heads'] or 0))
                ledger_kilos = ((grp['kilos_received'] or 0)
                                - (grp['kilos_withdrawn'] or 0)
                                + (grp['adjustment_kilos'] or 0))
                # physical packaging / packs / kilos of the partition (one
                # grouped read; BF and regular split by location_is_bf)
                phys_grp = Quant.read_group(
                    [('owner_id', '=', owner.id), ('quantity', '>', 0),
                     ('location_id.usage', '=', 'internal'),
                     ('location_id.warehouse_id', '=', wh_id),
                     ('location_is_bf', '=', bf)],
                    ['x_studio_2nd_uom', 'x_studio_total_units', 'quantity'],
                    [])
                phys_packs = (phys_grp[0]['x_studio_2nd_uom'] or 0) \
                    if phys_grp else 0
                phys_units = (phys_grp[0]['x_studio_total_units'] or 0) \
                    if phys_grp else 0
                phys_kilos = (phys_grp[0]['quantity'] or 0) \
                    if phys_grp else 0
                if bf:
                    quants = Quant.search_read(
                        [('owner_id', '=', owner.id), ('quantity', '>', 0),
                         ('location_id.usage', '=', 'internal'),
                         ('location_id.warehouse_id', '=', wh_id),
                         ('location_is_bf', '=', True)], ['bf_pallet_char'])
                    actual = len({q['bf_pallet_char'] for q in quants}
                                 - {False, ''})
                else:
                    stocked_ids = {g['package_id'][0] for g in Quant.read_group(
                        [('owner_id', '=', owner.id), ('quantity', '>', 0),
                         ('location_id.usage', '=', 'internal'),
                         ('location_id.warehouse_id', '=', wh_id),
                         ('package_id', '!=', False)],
                        ['package_id'], ['package_id'])}
                    actual = len(stocked_ids)
                residual = ledger - actual
                # packaging / packs residuals: pre-audit-era corrections and
                # opening-balance imports changed quant packs with no
                # document flow and left NO per-event record, so — like the
                # pallet residual — the difference is posted as one anchored
                # adjustment. Forward accuracy is carried by the approved
                # adjustment lines, whose deltas post to the ledger live.
                pack_residual = round(ledger_packs - phys_packs, 3)
                unit_residual = round(ledger_units - phys_units, 3)
                kilo_residual = round(ledger_kilos - phys_kilos, 3)
                if abs(pack_residual) <= 0.5:
                    pack_residual = 0
                if abs(unit_residual) <= 0.5:
                    unit_residual = 0
                if abs(kilo_residual) <= 0.5:
                    kilo_residual = 0
                if round(residual) == 0 and not pack_residual \
                        and not unit_residual and not kilo_residual:
                    continue
                # anchor priority: the partition's opening-balance row (no
                # stock.picking reference — that's where import drift
                # belongs), else the latest documented row
                anchor = self.search([
                    ('owner_id', '=', owner.id), ('warehouse', '=', wh_id),
                    ('is_blast_freezer', '=', bf), ('active', '=', True),
                    ('effective_document', '=', False)],
                    order='start_time asc, id asc', limit=1)
                if not anchor:
                    anchor = self.search([
                        ('owner_id', '=', owner.id), ('warehouse', '=', wh_id),
                        ('is_blast_freezer', '=', bf), ('active', '=', True)],
                        order='start_time desc, id desc', limit=1)
                if not anchor:
                    continue
                # explain the residual with NAMED contributors (regular
                # partitions; BF has no packages to decompose by):
                #  - stocked pallets with no RR and not part of the labeled
                #    opening-balance load (born via correction/adjustment)
                #  - opening-balance pallets gone without a counted WR
                detail_bits = []
                res_html = []
                if not bf and round(residual):
                    # EXACT per-identity decomposition. Pallet swaps
                    # ("Pallet #: A -> B" corrections) are folded into one
                    # identity (net 0 — never flagged); each identity's
                    # contribution = pallets in stock - times counted
                    # received (RRs + opening-balance load) + times counted
                    # withdrawn. The nonzero ones ARE the residual.
                    ob_load_ids = {
                        g['result_package_id'][0]
                        for g in MoveLine.read_group(
                            [('state', '=', 'done'), ('picking_id', '=', False),
                             ('owner_id', '=', owner.id),
                             ('location_id.usage', '=', 'inventory'),
                             ('result_package_id', '!=', False),
                             '|', ('reference', 'ilike', 'opening balance'),
                                  ('reference', 'ilike', 'ob part')],
                            ['result_package_id'], ['result_package_id'])}
                    rc_n = {}
                    for pkg_p, pick_p in {
                            (x['result_package_id'][0], x['picking_id'][0])
                            for x in MoveLine.search_read(
                                [('state', '=', 'done'),
                                 ('owner_id', '=', owner.id),
                                 ('result_package_id', '!=', False),
                                 ('picking_id.picking_type_id.code', '=',
                                  'incoming')],
                                ['picking_id', 'result_package_id'])}:
                        rc_n[pkg_p] = rc_n.get(pkg_p, 0) + 1
                    wc_n = {}
                    for pkg_p, pick_p in {
                            (x['package_id'][0], x['picking_id'][0])
                            for x in MoveLine.search_read(
                                [('state', '=', 'done'),
                                 ('owner_id', '=', owner.id),
                                 ('package_id', '!=', False),
                                 '|',
                                 ('reserved_quantity_on_validation', '=', 0),
                                 ('reserved_quantity_on_validation', '=',
                                  False),
                                 ('picking_id.picking_type_id.code', '=',
                                  'outgoing')],
                                ['picking_id', 'package_id'])}:
                        wc_n[pkg_p] = wc_n.get(pkg_p, 0) + 1
                    parent = {}
                    for sl in MoveLine.search_read(
                            [('state', '=', 'done'), ('picking_id', '=', False),
                             ('owner_id', '=', owner.id),
                             ('package_id', '!=', False),
                             ('result_package_id', '!=', False)],
                            ['package_id', 'result_package_id']):
                        old_id, new_id = (sl['package_id'][0],
                                          sl['result_package_id'][0])
                        if old_id != new_id:
                            parent.setdefault(new_id, old_id)

                    def _root(pid):
                        seen = set()
                        while pid in parent and pid not in seen:
                            seen.add(pid)
                            pid = parent[pid]
                        return pid

                    contrib = {}   # root identity -> [stocked, in, out, members]
                    for p in (set(rc_n) | set(wc_n) | stocked_ids
                              | ob_load_ids):
                        rt = _root(p)
                        d = contrib.setdefault(rt, [0, 0, 0, set()])
                        d[0] += 1 if p in stocked_ids else 0
                        d[1] += rc_n.get(p, 0) + (1 if p in ob_load_ids else 0)
                        d[2] += wc_n.get(p, 0)
                        d[3].add(p)
                    culprits = []
                    for rt, (stk, cin, cout, members) in contrib.items():
                        cval = stk - cin + cout
                        if not cval or members & event_pkgs:
                            continue   # balanced, or already posted as event
                        culprits.append((cval, rt, stk, cin, cout, members))
                    culprits.sort(key=lambda t: (-abs(t[0]), t[1]))
                    if culprits:
                        name_ids = set()
                        for t in culprits[:6]:
                            name_ids.add(t[1])
                            name_ids |= t[5]
                        pkg_name = {p.id: p.name
                                    for p in self.env['stock.quant.package']
                                    .browse(list(name_ids))}
                        bits = []
                        for cval, rt, stk, cin, cout, members in culprits[:6]:
                            name = pkg_name.get(rt, rt)
                            others = sorted(pkg_name.get(m, str(m))
                                            for m in members - {rt})
                            if len(members) > 1 and cval > 0:
                                # consolidation pallet split onto new pallet
                                # numbers: each split-off withdrawal counted,
                                # but no document ever counted the new
                                # pallet(s) in
                                why = ('stock was moved off %s onto new '
                                       'pallet number(s) %s by correction '
                                       'and withdrawn from there (each '
                                       'counted -1 pallet), but no RR ever '
                                       'counted those new pallets in%s'
                                       % (name, ', '.join(others),
                                          '; ' + name + ' itself is still '
                                          'in stock' if stk else ''))
                            elif cval > 0:
                                why = ('%s is in stock today, but on paper '
                                       'it entered %dx and left %dx — '
                                       'stock came back onto it without '
                                       'any receiving document'
                                       % (name, cin, cout))
                            else:
                                why = ('%s was counted into stock %dx '
                                       '(RR/opening balance) but is no '
                                       'longer in stock and no WR ever '
                                       'counted it out — it left '
                                       'undocumented (adjustment or pallet '
                                       'change)' % (name, cin))
                            bits.append('%s %+g: %s' % (name, cval, why))
                            res_html.append((name, '%+g' % cval, why))
                        more = len(culprits) - 6
                        detail_bits.append(
                            '%s%s' % (
                                ' | '.join(bits),
                                ' | and %d more pallet(s) with the same '
                                'kinds of causes' % more
                                if more > 0 else ''))
                        if more > 0:
                            res_html.append(
                                ('Other pallets', '%+g' % sum(
                                    t[0] for t in culprits[6:]),
                                 '%d more pallet(s) with the same kinds '
                                 'of causes' % more))
                # mass bursts (excluding the labeled opening-balance load
                # itself), in the direction of the residual
                if round(residual):
                    burst_dom = [
                        ('state', '=', 'done'), ('picking_id', '=', False),
                        ('owner_id', '=', owner.id), ('quantity', '>', 0),
                        ('reference', 'not ilike', 'opening balance'),
                        ('reference', 'not ilike', 'ob part'),
                        ('location_id.usage' if residual < 0
                         else 'location_dest_id.usage', '=', 'inventory')]
                    bursts = MoveLine.read_group(
                        burst_dom, ['id'], ['date:day'])
                    bursts = sorted(
                        (b for b in bursts if b.get('date_count', 0) >= 20),
                        key=lambda b: -b['date_count'])[:2]
                    if bursts:
                        burst_txt = 'mass inventory adjustment%s: %s' % (
                            ' IN' if residual < 0 else ' OUT (no WR)',
                            '; '.join('%d move(s) on %s'
                                      % (b['date_count'], b['date:day'])
                                      for b in bursts))
                        detail_bits.append(burst_txt)
                        res_html.append(('Mass adjustment', '', burst_txt))
                anchor_vals = {}
                note_parts = []
                entries = html_rows.setdefault(anchor.id, [])
                if round(residual):
                    if detail_bits:
                        suffix = ('. WHY (main identified causes): '
                                  + ' | '.join(detail_bits))
                    elif residual < 0:
                        suffix = ('. WHY: pallets are physically in stock '
                                  'that no receiving document ever counted '
                                  'in')
                    else:
                        suffix = ('. WHY: pallets counted into stock on '
                                  'paper are no longer physically here, and '
                                  'no WR counted them out')
                    note_parts.append(
                        '%+g pallet(s) added here to make the ledger match '
                        'the physical count%s' % (-residual, suffix))
                    anchor_vals['adjustment_pallets'] = \
                        anchor.adjustment_pallets - residual
                    entries.append((
                        'RESIDUAL (total)', '%+g' % -residual,
                        'added on this row (opening balance) so the ledger '
                        'equals the physical pallet count'))
                    if res_html:
                        entries.extend(res_html)
                    elif residual < 0:
                        entries.append((
                            'Unattributed', '%+g' % -residual,
                            'pallets are physically in stock that no '
                            'receiving document ever counted in'))
                    else:
                        entries.append((
                            'Unattributed', '%+g' % -residual,
                            'pallets counted into stock on paper are no '
                            'longer physically here, and no WR counted them '
                            'out'))
                # packaging / packs residuals ride on the same anchor row:
                # no per-event history exists (pre-audit-era corrections,
                # opening-balance import imprecision), so the difference is
                # posted whole and visibly explained
                if pack_residual:
                    note_parts.append(
                        '%+g packaging added (quantity ledger %g vs physical '
                        '%g — packs changed by old corrections/imports that '
                        'left no ledger record)'
                        % (-pack_residual, ledger_packs, phys_packs))
                    anchor_vals['adjustment_packaging'] = \
                        (anchor.adjustment_packaging or 0) - pack_residual
                    entries.append((
                        'RESIDUAL packaging', '%+g' % -pack_residual,
                        'quantity (2nd UOM) ledger %g vs physical %g — '
                        'difference from corrections/imports made before '
                        'the audit trail existed'
                        % (ledger_packs, phys_packs)))
                if unit_residual:
                    note_parts.append(
                        '%+g pack(s)/head(s) added (packs ledger %g vs '
                        'physical %g)' % (-unit_residual, ledger_units,
                                          phys_units))
                    anchor_vals['adjustment_heads'] = \
                        (anchor.adjustment_heads or 0) - unit_residual
                    entries.append((
                        'RESIDUAL packs', '%+g' % -unit_residual,
                        'packs/heads ledger %g vs physical %g — difference '
                        'from corrections/imports made before the audit '
                        'trail existed' % (ledger_units, phys_units)))
                if kilo_residual:
                    note_parts.append(
                        '%+g KG added (kilos ledger %g vs physical %g — '
                        'weight changed by old corrections/imports that '
                        'left no ledger record)'
                        % (-kilo_residual, ledger_kilos, phys_kilos))
                    anchor_vals['adjustment_kilos'] = \
                        (anchor.adjustment_kilos or 0) - kilo_residual
                    entries.append((
                        'RESIDUAL kilos', '%+g' % -kilo_residual,
                        'weight (KG) ledger %g vs physical %g — difference '
                        'from corrections/imports made before the audit '
                        'trail existed' % (ledger_kilos, phys_kilos)))
                note = ('pallet re-sync residual %s: %s'
                        % (today, ' | '.join(note_parts)))
                anchor_vals['remarks'] = ((anchor.remarks + ' | ')
                                          if anchor.remarks else '') + note
                anchor.with_context(skip_pkr_recalc=True).write(anchor_vals)
                residual_notes.append(', '.join(
                    filter(None, [
                        '%+g plt' % -residual if round(residual) else '',
                        '%+g pkg' % -pack_residual if pack_residual else '',
                        '%+g pcs' % -unit_residual if unit_residual else '',
                        '%+g kg' % -kilo_residual if kilo_residual else '',
                    ])))

            # render the collected explanations as an HTML table per row
            # (the plain-text copy already sits in remarks for the XLSX)
            for rid, entries in html_rows.items():
                body = ''.join(
                    '<tr><td>%s</td>'
                    '<td style="text-align:right;white-space:nowrap">'
                    '<b>%s</b></td><td>%s</td></tr>'
                    % tuple(html_escape(str(v)) for v in e)
                    for e in entries)
                self.browse(rid).with_context(
                    skip_pkr_recalc=True).write({
                        'adjustment_reason_html':
                            '<table class="table table-sm table-bordered">'
                            '<thead><tr><th>Pallet / Item</th>'
                            '<th style="text-align:right">Pallets</th>'
                            '<th>Why</th></tr></thead>'
                            '<tbody>%s</tbody></table>' % body})

            summary.append(
                '%s: %d row(s) repopulated, %d adjustment line(s) re-linked, '
                '%d event(s), residual [%s]' % (
                    owner.name, len(repop), relinked, events,
                    ', '.join(residual_notes) or 'none'))

        # -- 4. ONE full rebuild per affected partition, at the very end ----
        for wh_id, bf in all_partitions:
            self._recalculate_running_balances(wh_id, bf)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pallet Counts Re-synced',
                'message': '\n'.join(summary) or 'Nothing to do.',
                'type': 'success',
                'sticky': True,
            },
        }

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

        # Get current datetime in UTC+8
        from datetime import datetime, timezone, timedelta
        utc_plus_8 = timezone(timedelta(hours=8))
        current_time = datetime.now(utc_plus_8).replace(tzinfo=None) - timedelta(days=5)  # Remove timezone info for Odoo

        # Group quants by owner + warehouse + blast-freeze + building.
        # The BF flag comes from the quant's location so BF stock lands in (and is
        # later recalculated for) the correct partition instead of being forced
        # into the regular one.
        grouped_data = {}
        for quant in quants:
            if not quant.location_id.warehouse_id:
                _logger.warning(f"Skipping quant {quant.id} - no warehouse found for location {quant.location_id.name}")
                continue

            # Get building for this quant
            building = quant.location_id.x_studio_building if quant.location_id else None
            building_name = self._get_building_name(building)
            is_bf = bool(getattr(quant, 'location_is_bf', False))

            key = (
                quant.owner_id.id if quant.owner_id else False,
                quant.location_id.warehouse_id.id,
                is_bf,
                building_name
            )

            if key not in grouped_data:
                grouped_data[key] = {
                    'owner_id': quant.owner_id.id if quant.owner_id else False,
                    'warehouse_id': quant.location_id.warehouse_id.id,
                    'is_blast_freezer': is_bf,
                    'building_name': building_name,
                    'total_units': 0,
                    'total_packaging': 0,
                    'total_kilos': 0,
                    'unique_packages': set(),
                    'quant_ids': []
                }

            # Accumulate totals (on-hand quantity, not the inventory-adjustment field)
            grouped_data[key]['total_units'] += quant.x_studio_total_units or 0
            grouped_data[key]['total_packaging'] += quant.x_studio_2nd_uom or 0
            grouped_data[key]['total_kilos'] += quant.quantity or 0

            # Track unique packages (pallets)
            if quant.package_id:
                grouped_data[key]['unique_packages'].add(quant.package_id.id)

            grouped_data[key]['quant_ids'].append(quant.id)

        if not grouped_data:
            raise UserError("No valid stock quant records found with warehouse information.")

        # Create opening balance records
        created_records = []
        skipped_partitions = []

        # Group by owner+warehouse+BF for record creation (one record per partition)
        owner_warehouse_data = {}
        for (owner_id, warehouse_id, is_bf, building_name), data in grouped_data.items():
            ow_key = (owner_id, warehouse_id, is_bf)
            if ow_key not in owner_warehouse_data:
                owner_warehouse_data[ow_key] = {
                    'owner_id': owner_id,
                    'warehouse_id': warehouse_id,
                    'is_blast_freezer': is_bf,
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

        for (owner_id, warehouse_id, is_bf), data in owner_warehouse_data.items():
            # DOUBLE-IMPORT GUARD: refuse to create a second opening balance for a
            # partition that already has one. Running the "Re sync" action twice
            # previously doubled the owner's opening balance silently.
            duplicate = self.search([
                ('remarks', '=', 'imported via opening balance'),
                ('owner_id', '=', owner_id),
                ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', is_bf),
            ], limit=1)
            if duplicate:
                owner_label = (self.env['res.partner'].browse(owner_id).name
                               if owner_id else 'No owner')
                skipped_partitions.append(owner_label)
                _logger.warning(
                    "Skipping opening-balance import for owner %s / warehouse %s / bf=%s: "
                    "record %s already exists. Archive it first to re-import.",
                    owner_label, warehouse_id, is_bf, duplicate.id)
                continue

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

                # Blast freezer flag (from the quants' locations, per partition)
                'is_blast_freezer': is_bf,

                # Building-level balances
                'total_balances': data['buildings'],

                # Special remarks
                'remarks': 'imported via opening balance',
            }

            # Create the record (this will trigger the create() method which handles balance calculations)
            record = self.create(vals)
            created_records.append(record)
            _logger.info(f"Created opening balance record {record.id} for warehouse {warehouse_id}, owner {owner_id}")

        # After all records are created, recalculate each affected
        # (warehouse, blast-freeze) partition from the beginning.
        partitions_to_recalc = set()
        for record in created_records:
            partitions_to_recalc.add((record.warehouse.id, record.is_blast_freezer))

        for warehouse_id, is_bf in partitions_to_recalc:
            # Recalculate from the beginning since these are opening balances
            self._recalculate_running_balances(warehouse_id, is_bf, None)

        message = f'Successfully created {len(created_records)} opening balance record(s).'
        if skipped_partitions:
            message += (
                ' Skipped %d partition(s) that already have an opening balance: %s.'
                % (len(skipped_partitions), ', '.join(sorted(set(skipped_partitions)))))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Opening Balances Imported',
                'message': message,
                'type': 'success' if created_records else 'warning',
                'sticky': bool(skipped_partitions),
            }
        }
