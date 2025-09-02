from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)

class PalletKilosRecordModel(models.Model):
    _name = 'pallet_kilos_record_model.pallet_kilos_record_model'
    _description = 'Pallet Kilos Record Model'
    _order = 'end_time asc, id asc'  # Critical for running balance
    
    # Basic identification fields
    report_no = fields.Char(string="Report No.", readonly=True)
    owner_id = fields.Many2one('res.partner', 'Owner', ondelete='set null', readonly=True, index=True)
    warehouse = fields.Many2one('stock.warehouse', 'Warehouse', ondelete='set null', readonly=True, index=True)
    record_reference = fields.Many2one('stock.picking', 'Record Reference', store=True, ondelete='set null', 
                                      readonly=True, index=True)

    remarks = fields.Char(string="Remarks", readonly=True)
    active = fields.Boolean(string="active", default=True)
    # Adjusted document - this replaces the original reference for computations
    readjustment_document = fields.Many2one('stock.picking', string="Adjusted Document Reference", 
                                          ondelete='set null', readonly=True, index=True,
                                          help="When set, this document replaces the original reference for all calculations")
    
    # Effective document - computed field that returns either adjusted or original reference
    effective_document = fields.Many2one('stock.picking', string="Effective Document", 
                                       compute='_compute_effective_document', store=True,
                                       help="The document used for all calculations (adjusted if available, otherwise original)")
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
    total_balance_in_packaging = fields.Float(store=True, string="Total Balance in Quantity", readonly=True, group_operator=False)
    total_balance_in_kilos = fields.Float(store=True, string="Total Balance in Kilos (KG)", readonly=True, group_operator=False)
    total_balance_in_pallets = fields.Float(store=True, string="Total Balance in Pallets", readonly=True, group_operator=False)

    # Return fields - stored, not computed
    return_id = fields.Many2one('stock.picking', readonly=True, string="Return RR ID")
    return_heads = fields.Float(string="Total Return Units", readonly=True)
    return_packaging = fields.Float(string="Total Return Packaging", readonly=True)
    return_pallets = fields.Float(string="Total Return Pallets", readonly=True)
    return_kilos = fields.Float(string="Total Return Kilos", readonly=True)

    adjustment_heads = fields.Float(string="Total Adjustment Units")
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
    start_time = fields.Datetime(string="Start Time", readonly=True, store=True, index=True)  # INDEX IS CRITICAL
    end_time = fields.Datetime(string="End Time", readonly=True, store=True)
    
    # Maximum values
    max_pallets = fields.Many2one('x_inventory_static_var', 'Max Pallets', 
                                 default=lambda self: self._get_static_var('Max Pallets'))
    max_kg = fields.Many2one('x_inventory_static_var', 'Max Kilograms', 
                           default=lambda self: self._get_static_var('Max Kilograms'))

    # Running balance fields - stored, not computed
    overall_pallets = fields.Float(string='Overall Pallets', store=True, group_operator=False)
    overall_kilos = fields.Float(string='Overall Kilos', store=True, group_operator=False)
    
    # Add blast freezer flag for efficient filtering
    is_blast_freezer = fields.Boolean(string="Is Blast Freezer", store=True, index=True)

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
            
            # Get move lines data from effective document
            for line in record.effective_document.move_ids_without_package:
                units_received += line.x_studio_min_actual_demand
                packaging_received += line.x_studio_actual_packaging_demand
                units_withdrawn += line.x_studio_min_actual_demand
                packaging_withdrawn += line.x_studio_actual_packaging_demand
                kilos_received += line.quantity
                kilos_withdrawn += line.quantity

            # Count unique pallets
            if record.effective_document.picking_type_code in ['outgoing']:
                for move_line in record.effective_document.move_line_ids:
                    if move_line.picking_id.x_studio_is_a_blast_freezer:
                        if move_line.bf_pallet_char not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.bf_pallet_char)
                    else:
                        if move_line.package_id and move_line.package_id.id not in pallets:               
                            if move_line.reserved_quantity_on_validation == 0:
                                pallet_count += 1
                                pallets.add(move_line.package_id.id)
            else:
                for move_line in record.effective_document.move_line_ids:
                    if move_line.picking_id.x_studio_is_a_blast_freezer:
                        if move_line.bf_pallet_char not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.bf_pallet_char)
                    else:
                        if move_line.result_package_id and move_line.result_package_id.id not in pallets:
                            pallet_count += 1
                            pallets.add(move_line.result_package_id.id)
                    
            # Set values based on picking type
            picking_code = record.effective_document.picking_type_id.code
            
            if picking_code == 'incoming':
                record.write({
                    'units_received': units_received,
                    'packaging_received': packaging_received,
                    'kilos_received': kilos_received,
                    'pallets_received': pallet_count,
                    'units_withdrawn': 0,
                    'packaging_withdrawn': 0,
                    'kilos_withdrawn': 0,
                    'pallets_withdrawn': 0,
                    'is_blast_freezer': record.effective_document.x_studio_is_a_blast_freezer or False
                })
            elif picking_code == 'outgoing':
                record.write({
                    'units_withdrawn': units_withdrawn,
                    'packaging_withdrawn': packaging_withdrawn,
                    'kilos_withdrawn': kilos_withdrawn,
                    'pallets_withdrawn': pallet_count,
                    'units_received': 0,
                    'packaging_received': 0,
                    'kilos_received': 0,
                    'pallets_received': 0,
                    'is_blast_freezer': record.effective_document.x_studio_is_a_blast_freezer or False
                })

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


    def _recalculate_running_balances(self, warehouse_id, blast_freezer_flag, from_datetime=None):
        """
        Efficiently recalculate running balances for all records in a warehouse after a given datetime
        - overall_* fields: warehouse-wide totals (all owners)
        - total_balance_* and beginning_balance_* fields: per owner
        """
        domain = [
            ('warehouse', '=', warehouse_id),
            ('is_blast_freezer', '=', blast_freezer_flag),
        ]
        
        if from_datetime:
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

        # Track per-owner balances
        owner_balances = {}
        
        # Get previous balances for each owner
        if from_datetime:
            # Get the last record for each owner before from_datetime
            owners_in_scope = records_to_update.mapped('owner_id')
            for owner in owners_in_scope:
                if not owner:
                    continue
                    
                prev_owner_record = self.search([
                    ('warehouse', '=', warehouse_id),
                    ('is_blast_freezer', '=', blast_freezer_flag),
                    ('owner_id', '=', owner.id),
                    ('start_time', '<', from_datetime)
                ], order='start_time desc, id desc', limit=1)
                
                if prev_owner_record:
                    owner_balances[owner.id] = {
                        'total_pallets': prev_owner_record.total_balance_in_pallets,
                        'total_kilos': prev_owner_record.total_balance_in_kilos,
                        'total_units': prev_owner_record.total_balance_in_units,
                        'total_packaging': prev_owner_record.total_balance_in_packaging,
                    }
                else:
                    owner_balances[owner.id] = {
                        'total_pallets': 0,
                        'total_kilos': 0,
                        'total_units': 0,
                        'total_packaging': 0,
                    }
        else:
            # Initialize all owner balances to 0
            owners_in_scope = records_to_update.mapped('owner_id')
            for owner in owners_in_scope:
                if owner:
                    owner_balances[owner.id] = {
                        'total_pallets': 0,
                        'total_kilos': 0,
                        'total_units': 0,
                        'total_packaging': 0,
                    }
    
        # Batch update all records
        updates = []
        for record in records_to_update:
            # Calculate warehouse-wide running totals (overall_* fields) including adjustments
            running_pallets += (record.pallets_received - record.pallets_withdrawn + record.adjustment_pallets)
            running_kilos += (record.kilos_received - record.kilos_withdrawn + record.adjustment_kilos)
            
            # Calculate per-owner balance totals
            if not record.owner_id:
                # Skip records without owner
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
                })
                continue
                
            owner_id = record.owner_id.id
            
            # Store beginning balance (before this record's operation)
            beginning_pallets = owner_balances[owner_id]['total_pallets']
            beginning_kilos = owner_balances[owner_id]['total_kilos']
            
            # Calculate new balance totals for this owner including adjustments
            # Handle opening balance records (no effective_document)
            if not record.effective_document and record.remarks == 'imported via opening balance':
                # For opening balance, use the received amounts directly
                owner_balances[owner_id]['total_packaging'] += record.packaging_received
                owner_balances[owner_id]['total_units'] += record.units_received
                owner_balances[owner_id]['total_kilos'] += record.kilos_received
                owner_balances[owner_id]['total_pallets'] += record.pallets_received
            # Calculate new balance totals for this owner including adjustments
            elif record.effective_document and record.effective_document.picking_type_id.code == 'outgoing':
                owner_balances[owner_id]['total_packaging'] -= record.packaging_withdrawn
                owner_balances[owner_id]['total_units'] -= record.units_withdrawn
                owner_balances[owner_id]['total_kilos'] -= record.kilos_withdrawn
                owner_balances[owner_id]['total_pallets'] -= record.pallets_withdrawn
            elif record.effective_document and record.effective_document.picking_type_id.code == 'incoming':
                owner_balances[owner_id]['total_packaging'] += record.packaging_received
                owner_balances[owner_id]['total_units'] += record.units_received
                owner_balances[owner_id]['total_kilos'] += record.kilos_received
                owner_balances[owner_id]['total_pallets'] += record.pallets_received
                
            # Apply adjustments to owner balances
            owner_balances[owner_id]['total_packaging'] += record.adjustment_packaging
            owner_balances[owner_id]['total_units'] += record.adjustment_heads
            owner_balances[owner_id]['total_kilos'] += record.adjustment_kilos
            owner_balances[owner_id]['total_pallets'] += record.adjustment_pallets
    
            updates.append({
                'id': record.id,
                'overall_pallets': running_pallets,
                'overall_kilos': running_kilos,
                'beginning_balance_in_pallets': beginning_pallets,
                'beginning_balance_in_kilos': beginning_kilos,
                'total_balance_in_units': owner_balances[owner_id]['total_units'],
                'total_balance_in_packaging': owner_balances[owner_id]['total_packaging'],
                'total_balance_in_kilos': owner_balances[owner_id]['total_kilos'],
                'total_balance_in_pallets': owner_balances[owner_id]['total_pallets'],
            })
    
        # Batch write all updates
        for update in updates:
            record_id = update.pop('id')
            self.browse(record_id).write(update)

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
        all_records = self.search([], order='start_time asc')
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
        Creates PalletKilosRecordModel records grouped by owner+warehouse
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
        
        # Group quants by owner + warehouse
        grouped_data = {}
        
        for quant in quants:
            if not quant.location_id.warehouse_id:
                _logger.warning(f"Skipping quant {quant.id} - no warehouse found for location {quant.location_id.name}")
                continue
                
            key = (quant.owner_id.id if quant.owner_id else False, quant.location_id.warehouse_id.id)
            
            if key not in grouped_data:
                grouped_data[key] = {
                    'owner_id': quant.owner_id.id if quant.owner_id else False,
                    'warehouse_id': quant.location_id.warehouse_id.id,
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
        
        # Check for duplicates - see if any of these quants were already imported
        all_quant_ids = []
        for data in grouped_data.values():
            all_quant_ids.extend(data['quant_ids'])
        
        # This is a simple check - you might want to implement a more sophisticated tracking system
        # For now, we'll just warn but not block
        
        created_records = []
        
        # Create opening balance records
        for (owner_id, warehouse_id), data in grouped_data.items():
            
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
                'pallets_received': len(data['unique_packages']),
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
                'total_balance_in_pallets': len(data['unique_packages']),
                
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
                'message': f'Successfully created {len(created_records)} opening balance records.',
                'type': 'success',
                'sticky': False,
            }
        }