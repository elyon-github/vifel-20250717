# models/stock_quant_correction_wizard.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
import json
import logging
_logger = logging.getLogger(__name__)


class StockQuantCorrectionWizard(models.TransientModel):
    _name = 'stock.quant.correction.wizard'
    _description = 'Stock Quant Correction Wizard'

    line_ids = fields.One2many('stock.quant.correction.line', 'wizard_id', string='Quant Corrections')
    reason_for_adjustment = fields.Char(string="Reason for Adjustment", required=True)
    skip_approval = fields.Boolean(
        string="Apply Immediately (Skip Approval)",
        default=False,
        help="If checked, changes will be applied immediately without approval workflow. Only available for Stock Managers."
    )

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
    
        quant_ids = self.env.context.get('active_ids', [])
        quants = self.env['stock.quant'].browse(quant_ids)
        
        # Check 1: Reserved quantities
        reserved_quants = quants.filtered(lambda q: q.reserved_quantity > 0)
        if reserved_quants:
            raise UserError(_("Cannot modify Pallet details with reserved quantities. "
                              "\nPlease unreserve the following Pallets first:\n• %s") %
                            '\n• '.join(reserved_quants.mapped('x_studio_pallet_series_id')))
        
        # Check 2: Active pending adjustment requests
        pallet_series_ids = quants.mapped('x_studio_pallet_series_id')
        
        # Search for any pending adjustment lines for these pallet series
        pending_lines = self.env['stock.quant.adjustment.line'].search([
            ('quant_id.x_studio_pallet_series_id', 'in', pallet_series_ids),
            ('line_state', 'in', ['pending', 'draft']),
            ('request_id.state', 'in', ['draft', 'pending', 'partial'])
        ])
        
        if pending_lines:
            # Group by pallet series for clear error message
            pallets_with_requests = {}
            for line in pending_lines:
                series_id = line.quant_id.x_studio_pallet_series_id
                request_name = line.request_id.name
                
                if series_id not in pallets_with_requests:
                    pallets_with_requests[series_id] = []
                if request_name not in pallets_with_requests[series_id]:
                    pallets_with_requests[series_id].append(request_name)
            
            # Build error message
            error_lines = []
            for series_id, request_names in pallets_with_requests.items():
                requests_str = ', '.join(request_names)
                error_lines.append(f"• {series_id} (Request: {requests_str})")
            
            raise UserError(_(
                "Cannot modify Pallet details with active pending adjustment requests.\n"
                "The following Pallets have pending adjustments:\n\n%s\n\n"
                "Please wait for approval or cancel the existing requests first."
            ) % '\n'.join(error_lines))

        
        line_vals = []
        for quant in quants:
            line_vals.append({
                'quant_id': quant.id,
                'package_id': quant.package_id.id,
                'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
                'product_id': quant.product_id.id,
                'x_studio_production_date': quant.x_studio_production_date,
                'x_studio_expiration_date': quant.x_studio_expiration_date,
                'x_studio_loading_dock_no': quant.x_studio_loading_dock_no,
                'x_studio_source': quant.x_studio_source,
                'x_studio_gate_pass': quant.x_studio_gate_pass,
                'x_studio_truck_time': quant.x_studio_truck_time,
                'x_studio_start_time': quant.x_studio_start_time,
                'x_studio_end_time': quant.x_studio_end_time,
                'x_studio_truck_number': quant.x_studio_truck_number,
                'x_studio_2nd_uom': quant.x_studio_2nd_uom,
                'x_studio_quantity_uom': quant.x_studio_quantity_uom.id,
                'x_studio_total_units': quant.x_studio_total_units,
                'x_studio_min_quantity_uom': quant.x_studio_min_quantity_uom.id,
                'x_studio_container_number': quant.x_studio_container_number,
                'x_studio_building_dropped': quant.x_studio_building_dropped,
                'quantity': quant.quantity,
                'lot_id': quant.lot_id.id,
                'owner_id': quant.owner_id.id,
                'x_studio_return_count': quant.x_studio_return_count,
            })
        
        res['line_ids'] = [(0, 0, vals) for vals in line_vals]
        
        is_manager = self.env.user.has_group('stock.group_stock_manager')
        if not is_manager:
            res['skip_approval'] = False
        
        return res
    
    def action_confirm_corrections(self):
        """Main action: Either create approval request OR apply directly"""
        self.ensure_one()
        
        if self.skip_approval and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_("Only Stock Managers can skip the approval workflow."))
        
        if self.skip_approval:
            return self._apply_corrections_immediately()
        else:
            return self._create_adjustment_request()
    
    def _create_adjustment_request(self):
        """Create an adjustment request with all lines for approval workflow"""
        self.ensure_one()
        
        lines_with_changes = self.line_ids.filtered(lambda l: l._get_changes())
        if not lines_with_changes:
            raise UserError(_("No changes detected. Please modify at least one field."))
        
        restricted_pallets = {}
        for line in lines_with_changes:
            changes = line._get_changes()
            if changes and 'product_id' in changes and line.quant_id.x_studio_return_count > 0:
                series_id = line.quant_id.x_studio_pallet_series_id
                if series_id not in restricted_pallets:
                    restricted_pallets[series_id] = []
                restricted_pallets[series_id].append(line.quant_id.x_studio_record_reference or f"Quant {line.quant_id.id}")
        
        if restricted_pallets:
            error_msg = "You cannot change product of Pallets already with return count history:\n\n"
            for series_id, pallet_refs in restricted_pallets.items():
                error_msg += f"Series ID: {series_id}\n"
            raise UserError(error_msg)
        
        request_vals = {
            'reason_for_adjustment': self.reason_for_adjustment,
            'requested_by': self.env.user.id,
            'requested_date': fields.Datetime.now(),
        }
        
        request = self.env['stock.quant.adjustment.request'].create(request_vals)
        
        for wizard_line in lines_with_changes:
            self._create_adjustment_line(request, wizard_line)
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Adjustment Request Created'),
            'res_model': 'stock.quant.adjustment.request',
            'res_id': request.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'form_view_initial_mode': 'edit'},
        }
    
    def _create_adjustment_line(self, request, wizard_line):
        """Create an adjustment line from a wizard line"""
        quant = wizard_line.quant_id
        
        snapshot_data = {
            'quantity': quant.quantity,
            'reserved_quantity': quant.reserved_quantity,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': quant.package_id.id if quant.package_id else False,
            'owner_id': quant.owner_id.id if quant.owner_id else False,
            'location_id': quant.location_id.id,
            'write_date': str(quant.write_date),
            'x_studio_2nd_uom': quant.x_studio_2nd_uom,
            'x_studio_total_units': quant.x_studio_total_units,
        }
        
        line_vals = {
            'request_id': request.id,
            'quant_id': quant.id,
            'quant_snapshot': json.dumps(snapshot_data, sort_keys=True),
            'line_state': 'draft',
            'old_package_id': quant.package_id.id if quant.package_id else False,
            'old_product_id': quant.product_id.id,
            'old_quantity': quant.quantity,
            'old_lot_id': quant.lot_id.id if quant.lot_id else False,
            'old_owner_id': quant.owner_id.id if quant.owner_id else False,
            'old_x_studio_production_date': quant.x_studio_production_date,
            'old_x_studio_expiration_date': quant.x_studio_expiration_date,
            'old_x_studio_2nd_uom': quant.x_studio_2nd_uom,
            'old_x_studio_total_units': quant.x_studio_total_units,
            'old_x_studio_quantity_uom': quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
            'old_x_studio_min_quantity_uom': quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False,
            'new_package_id': wizard_line.package_id.id if wizard_line.package_id else False,
            'new_product_id': wizard_line.product_id.id,
            'new_quantity': wizard_line.quantity,
            'new_lot_id': wizard_line.lot_id.id if wizard_line.lot_id else False,
            'new_owner_id': wizard_line.owner_id.id if wizard_line.owner_id else False,
            'new_x_studio_production_date': wizard_line.x_studio_production_date,
            'new_x_studio_expiration_date': wizard_line.x_studio_expiration_date,
            'new_x_studio_2nd_uom': wizard_line.x_studio_2nd_uom,
            'new_x_studio_total_units': wizard_line.x_studio_total_units,
            'new_x_studio_quantity_uom': wizard_line.x_studio_quantity_uom.id if wizard_line.x_studio_quantity_uom else False,
            'new_x_studio_min_quantity_uom': wizard_line.x_studio_min_quantity_uom.id if wizard_line.x_studio_min_quantity_uom else False,
        }
        
        return self.env['stock.quant.adjustment.line'].create(line_vals)
    
    def _apply_corrections_immediately(self):
        """OLD BEHAVIOR: Apply corrections immediately (when skip_approval is checked)"""
        adjustment_form_series = self.env['ir.sequence'].search([('code', '=', 'adjustment.form.series')], limit=1)
        batch_number = adjustment_form_series.next_by_id()
        
        restricted_pallets = {}
        for line in self.line_ids:
            changes = line._get_changes()
            if changes and 'product_id' in changes and line.quant_id.x_studio_return_count > 0:
                series_id = line.quant_id.x_studio_pallet_series_id
                if series_id not in restricted_pallets:
                    restricted_pallets[series_id] = []
                restricted_pallets[series_id].append(line.quant_id.x_studio_record_reference or f"Quant {line.quant_id.id}")
        
        if restricted_pallets:
            error_msg = "You cannot change product of Pallets already with return count history:\n\n"
            for series_id, pallet_refs in restricted_pallets.items():
                error_msg += f"Series ID: {series_id}\n"
            raise UserError(error_msg)
        
        for line in self.line_ids:
            changes = line._get_changes()
            if changes:
                original_state = line._capture_original_state()
                
                if 'quantity' in changes:
                    self._handle_quantity_adjustment(line, changes['quantity'][0], changes['quantity'][1], batch_number)
                
                line._apply_changes(changes)
                
                non_quantity_changes = {k: v for k, v in changes.items() if k != 'quantity'}
                if non_quantity_changes:
                    self._create_correction_move(line, non_quantity_changes, original_state, batch_number, line.quant_id.x_studio_record_reference)
                
                self._update_pallet_kilos_record(line, changes, batch_number)
        
        return {'type': 'ir.actions.act_window_close'}

    def _handle_quantity_adjustment(self, line, old_quantity, new_quantity, batch_number):
        """Handle quantity adjustments with proper inventory moves"""
        quant = line.quant_id
        quantity_diff = new_quantity - old_quantity
        
        inventory_location = self.env.ref('stock.location_inventory', raise_if_not_found=False)
        if not inventory_location:
            inventory_location = self.env['stock.location'].search([('usage', '=', 'inventory')], limit=1)
            if not inventory_location:
                raise UserError(_("Inventory location not found. Please configure inventory adjustments."))
        
        if abs(quantity_diff) < 0.001:
            return
        
        if quantity_diff > 0:
            source_location = inventory_location
            dest_location = quant.location_id
            move_quantity = quantity_diff
            source_package = False
            dest_package = quant.package_id.id if quant.package_id else False
            move_name = f'Inventory Adjustment: +{quantity_diff} {quant.product_id.name}'
        else:
            source_location = quant.location_id
            dest_location = inventory_location
            move_quantity = abs(quantity_diff)
            source_package = quant.package_id.id if quant.package_id else False
            dest_package = False
            move_name = f'Inventory Adjustment: -{abs(quantity_diff)} {quant.product_id.name}'
        
        move_vals = {
            'name': move_name,
            'product_id': quant.product_id.id,
            'product_uom': quant.product_id.uom_id.id,
            'product_uom_qty': move_quantity,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'origin': f'Quantity Adjustment - {self.reason_for_adjustment}',
            'date': fields.Datetime.now(),
            'state': 'done',
        }
        
        move = self.env['stock.move'].create(move_vals)
        
        move_line_vals = {
            'move_id': move.id,
            'product_id': quant.product_id.id,
            'product_uom_id': quant.product_id.uom_id.id,
            'quantity': move_quantity,
            'adjusted_quantity': new_quantity,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': source_package,
            'result_package_id': dest_package,
            'owner_id': quant.owner_id.id if quant.owner_id else False,
            'state': 'done',
            'adjustment_batch_number': batch_number,
            'adjustment_reference_id': quant.x_studio_record_reference.id if quant.x_studio_record_reference else False,
            'is_quant_detail_adjusted': True,
            'reference': self._format_quantity_change_reference(old_quantity, new_quantity),
            'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
            'x_studio_production_date': quant.x_studio_production_date,
            'x_studio_expiration_date': quant.x_studio_expiration_date,
            'x_studio_loading_dock_no': quant.x_studio_loading_dock_no,
            'x_studio_source': quant.x_studio_source,
            'x_studio_gate_pass': quant.x_studio_gate_pass,
            'x_studio_truck_time': quant.x_studio_truck_time,
            'x_studio_start_time': quant.x_studio_start_time,
            'x_studio_end_time': quant.x_studio_end_time,
            'x_studio_truck_number': quant.x_studio_truck_number,
            'x_studio_2nd_uom': quant.x_studio_2nd_uom,
            'x_studio_quantity_uom': quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
            'x_studio_total_units': quant.x_studio_total_units,
            'x_studio_min_quantity_uom': quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False,
            'x_studio_return_count': quant.x_studio_return_count,
            'x_studio_container_number': quant.x_studio_container_number,
        }
        
        self.env['stock.move.line'].sudo().create(move_line_vals)

    def _create_correction_move(self, line, changes, original_state, batch_number, picking_id):
        """Create stock move to track the correction in history"""
        quant = line.quant_id
        
        inventory_location = self.env.ref('stock.location_inventory', raise_if_not_found=False)
        if not inventory_location:
            inventory_location = self.env['stock.location'].search([('usage', '=', 'inventory')], limit=1)
            if not inventory_location:
                raise UserError(_("Inventory location not found. Please configure inventory adjustments."))
        
        correction_description = self._format_changes_description(changes)
        
        move_vals = {
            'name': f'Correction: {original_state["product_name"]} - {correction_description}',
            'product_id': quant.product_id.id,
            'product_uom': quant.product_id.uom_id.id,
            'product_uom_qty': 0,
            'location_id': inventory_location.id,
            'location_dest_id': quant.location_id.id,
            'reason_for_adjustment': f'{self.reason_for_adjustment}',
            'date': fields.Datetime.now(),
            'state': 'done',
        }
        
        move = self.env['stock.move'].create(move_vals)


        move_line_vals = {
            'move_id': move.id,
            'product_id': quant.product_id.id,
            'product_uom_id': quant.product_id.uom_id.id,
            'quantity': 0,
            'location_id': inventory_location.id,
            'location_dest_id': quant.location_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': original_state.get('package_id') if original_state.get('package_id') else None,
            'result_package_id': quant.package_id.id if quant.package_id else False,
            'reference': self._format_changes_reference(changes, original_state),
            'x_studio_reason_for_adjustment': self.reason_for_adjustment,
            'is_quant_detail_adjusted': True,
            'owner_id': quant.owner_id.id if quant.owner_id else False,
            'state': 'done',
            'adjustment_batch_number': batch_number,
            'adjustment_reference_id': quant.x_studio_record_reference.id if quant.x_studio_record_reference else False,
            'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
            'x_studio_production_date': quant.x_studio_production_date,
            'x_studio_expiration_date': quant.x_studio_expiration_date,
            'x_studio_loading_dock_no': quant.x_studio_loading_dock_no,
            'x_studio_source': quant.x_studio_source,
            'x_studio_gate_pass': quant.x_studio_gate_pass,
            'x_studio_truck_time': quant.x_studio_truck_time,
            'x_studio_start_time': quant.x_studio_start_time,
            'x_studio_end_time': quant.x_studio_end_time,
            'x_studio_truck_number': quant.x_studio_truck_number,
            'x_studio_2nd_uom': quant.x_studio_2nd_uom,
            'x_studio_quantity_uom': quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
            'x_studio_total_units': quant.x_studio_total_units,
            'x_studio_min_quantity_uom': quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False,
            'x_studio_return_count': quant.x_studio_return_count if quant.x_studio_return_count else 0,
            'x_studio_container_number': quant.x_studio_container_number,
        }
        
        for field_name in changes.keys():
            if hasattr(self.env['stock.move.line'], field_name):
                current_value = getattr(quant, field_name, False)
                if isinstance(current_value, models.Model):
                    current_value = current_value.id
                if field_name in ['x_studio_production_date', 'x_studio_expiration_date']:
                    move_line_vals[field_name] = current_value
                elif field_name.startswith('x_studio_'):
                    move_line_vals[field_name] = current_value

        move_line = self.env['stock.move.line'].sudo().create(move_line_vals)
        return move

    def _format_changes_description(self, changes):
        """Format changes for move name"""
        if len(changes) == 1:
            field, (old_val, new_val) = list(changes.items())[0]
            return f"{field} updated"
        else:
            return f"{len(changes)} fields updated"
    
    def _format_quantity_change_reference(self, old_quantity, new_quantity):
        """Format quantity change reference"""
        from datetime import datetime, timezone, timedelta
        utc_plus_8 = timezone(timedelta(hours=8))
        timestamp = datetime.now(utc_plus_8).strftime('%m/%d/%y %H:%M:%S')
        user = self.env.user.name
        field_label = self._get_field_label('product_uom_qty')
        old_display = self._format_value_for_display(old_quantity)
        new_display = self._format_value_for_display(new_quantity)
        return f"CORRECTION ({timestamp} by {user}): [{field_label}: {old_display} → {new_display}]"
    
    def _format_changes_reference(self, changes, original_state):
        """Format changes for reference field"""
        change_list = []
        for field, (old_val, new_val) in changes.items():
            old_display = new_display = None

            # Handle special relational fields
            if field == 'package_id':
                old_pkg = self.env['stock.quant.package'].browse(old_val) if old_val else False
                new_pkg = self.env['stock.quant.package'].browse(new_val) if new_val else False
                old_display = old_pkg.name if old_pkg else 'None'
                new_display = new_pkg.name if new_pkg else 'None'
    
            elif field == 'x_studio_quantity_uom':
                old_uom = self.env['uom.uom'].browse(old_val) if old_val else False
                new_uom = self.env['uom.uom'].browse(new_val) if new_val else False
                old_display = old_uom.name if old_uom else 'None'
                new_display = new_uom.name if new_uom else 'None'
    
            elif field == 'product_id':
                old_display = original_state.get('product_name', 'Unknown')
                new_display = original_state.get('new_product_name', str(new_val))
    
            else:
                # fallback to generic formatter
                old_display = self._format_value_for_display(old_val)
                new_display = self._format_value_for_display(new_val)
    
            field_label = self._get_field_label(field)
            change_list.append(f"[{field_label}: {old_display} → {new_display}]")
    
        # Compose reference text
        from datetime import datetime, timezone, timedelta
        utc_plus_8 = timezone(timedelta(hours=8))
        timestamp = datetime.now(utc_plus_8).strftime('%m/%d/%y %H:%M:%S')
        user = self.env.user.name
        return f"CORRECTION ({timestamp} by {user}): " + " ".join(change_list)

    
    def _get_field_label(self, field_name):
        """Get field label"""

        Quant = self.env['stock.quant']
        if field_name == 'package_id':
            return 'Pallet #'
        if field_name in Quant._fields:
            return Quant._fields[field_name].string or field_name
        if field_name == 'product_uom_qty':
            return 'Weight (KG)'
        return field_name.replace('x_studio_', '').replace('_', ' ').title()
        
    def _format_value_for_display(self, value):
        """Format value for display"""
        if value is False or value is None:
            return "Empty"
        elif isinstance(value, (int, float)) and str(value).endswith('.0'):
            return str(int(value))
        else:
            return str(value)

    def _update_pallet_kilos_record(self, line, changes, batch_number):
        """Update pallet kilos record"""
        quant = line.quant_id
        
        if not quant.original_record_reference:
            _logger.warning(f"Quant {quant.id} has no original_record_reference, skipping pallet kilos update")
            return
        
        pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search([
            ('effective_document', '=', quant.original_record_reference.id)
        ], limit=1)
        
        if not pallet_record:
            _logger.warning(f"No pallet kilos record found for effective_document {quant.original_record_reference.id}")
            return
        
        adjustment_values = self._calculate_adjustment_values(line, changes)
        
        if not adjustment_values:
            return
        
        update_vals = {}
        
        if 'kilos' in adjustment_values:
            update_vals['adjustment_kilos'] = (pallet_record.adjustment_kilos or 0) + adjustment_values['kilos']
        
        if 'packaging' in adjustment_values:
            update_vals['adjustment_packaging'] = (pallet_record.adjustment_packaging or 0) + adjustment_values['packaging']
        
        if 'units' in adjustment_values:
            update_vals['adjustment_heads'] = (pallet_record.adjustment_heads or 0) + adjustment_values['units']
        
        if 'pallets' in adjustment_values:
            update_vals['adjustment_pallets'] = (pallet_record.adjustment_pallets or 0) + adjustment_values['pallets']
        
        if update_vals:
            pallet_record.write(update_vals)
            pallet_record._recalculate_running_balances(
                pallet_record.warehouse.id,
                pallet_record.is_blast_freezer,
                pallet_record.start_time
            )
            _logger.info(f"Updated pallet kilos record {pallet_record.id} with adjustments: {update_vals}")
    
    def _calculate_adjustment_values(self, line, changes):
        """Calculate adjustment values"""
        adjustments = {}
        
        if 'quantity' in changes:
            old_qty, new_qty = changes['quantity']
            qty_diff = new_qty - old_qty
            adjustments['kilos'] = qty_diff
        
        if 'x_studio_2nd_uom' in changes:
            old_packaging, new_packaging = changes['x_studio_2nd_uom']
            packaging_diff = new_packaging - old_packaging
            adjustments['packaging'] = packaging_diff
        
        if 'x_studio_total_units' in changes:
            old_units, new_units = changes['x_studio_total_units']
            units_diff = new_units - old_units
            adjustments['units'] = units_diff
        
        return adjustments


class StockQuantCorrectionLine(models.TransientModel):
    _name = 'stock.quant.correction.line'
    _description = 'Stock Quant Correction Line'

    wizard_id = fields.Many2one('stock.quant.correction.wizard', required=True, ondelete='cascade')
    quant_id = fields.Many2one('stock.quant', string='Original Quant', required=True)
    package_id = fields.Many2one('stock.quant.package', string='Pallet #')
    x_studio_pallet_series_id = fields.Char(string='Placeholder')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    x_studio_production_date = fields.Date(string='Production Date')
    x_studio_expiration_date = fields.Date(string='Expiration Date')
    x_studio_loading_dock_no = fields.Char(string='Loading Dock No')
    x_studio_source = fields.Char(string='Source')
    x_studio_gate_pass = fields.Char(string='Gate Pass')
    x_studio_truck_time = fields.Datetime(string='Truck Time')
    x_studio_start_time = fields.Datetime(string='Start Time')
    x_studio_end_time = fields.Datetime(string='End Time')
    x_studio_truck_number = fields.Char(string='Truck Number')
    x_studio_2nd_uom = fields.Float(string='Total Quantity')
    x_studio_quantity_uom = fields.Many2one('uom.uom', string='Quantity UOM')
    x_studio_total_units = fields.Float(string='Total Heads')
    x_studio_min_quantity_uom = fields.Many2one('uom.uom', string='Heads UOM')
    owner_id = fields.Many2one('res.partner', string="Owner")
    quantity = fields.Float(string='Quantity')
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial', readonly=True)
    x_studio_return_count = fields.Integer(string="Return Count")
    x_studio_container_number = fields.Char(string="Container #")
    x_studio_building_dropped = fields.Char(string="Building RR")
    display_pallet_series_id = fields.Char(string='Pallet Series ID', compute="_compute_display_payllet_series_id")


    def _compute_display_payllet_series_id(self):
        for record in self:
            record['display_pallet_series_id'] = record.x_studio_pallet_series_id
    
    @api.onchange('select_all')
    def _onchange_select_all(self):
        for line in self.line_ids:
            line.selected = self.select_all
            
    def _capture_original_state(self):
        """Capture original quant state"""
        self.ensure_one()
        quant = self.quant_id
        
        original_state = {
            'product_name': quant.product_id.name,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': quant.package_id.id if quant.package_id else False,
        }
        
        if hasattr(self, 'product_id') and self.product_id != quant.product_id:
            original_state['new_product_name'] = self.product_id.name
        
        return original_state

    def _check_dates(self):
        for line in self:
            if (line.x_studio_production_date and line.x_studio_expiration_date and 
                line.x_studio_production_date > line.x_studio_expiration_date):
                raise ValidationError(_("Production date cannot be later than expiration date."))

    def _get_changes(self):
        """Compare current values with original quant and return changes"""
        self.ensure_one()
        quant = self.quant_id
        
        changes = {}
        field_mapping = {
            'package_id': ('package_id', lambda x: x.id if x else False),
            'x_studio_pallet_series_id': ('x_studio_pallet_series_id', str),
            'product_id': ('product_id', lambda x: x.id),
            'x_studio_2nd_uom': ('x_studio_2nd_uom', float),
            'x_studio_quantity_uom': ('x_studio_quantity_uom', lambda x: x.id if x else False),
            'x_studio_total_units': ('x_studio_total_units', float),
            'x_studio_min_quantity_uom': ('x_studio_min_quantity_uom', lambda x: x.id if x else False),
            'owner_id': ('owner_id', lambda x: x.id if x else False),
            'quantity': ('quantity', float),
            'x_studio_return_count': ('x_studio_return_count', int),
        }
        
        for wizard_field, (quant_field, converter) in field_mapping.items():
            old_value = getattr(quant, quant_field)
            new_value = getattr(self, wizard_field)
            
            try:
                old_converted = converter(old_value) if old_value not in [False, None] else old_value
                new_converted = converter(new_value) if new_value not in [False, None] else new_value
            except (ValueError, TypeError):
                old_converted = old_value
                new_converted = new_value
            
            if old_converted != new_converted:
                changes[quant_field] = (old_converted, new_converted)
        
        return changes

    def _apply_changes(self, changes):
        """Apply changes to the original quant"""
        self.ensure_one()
        quant = self.quant_id
        
        update_vals = {}
        for field, (old_val, new_val) in changes.items():
            update_vals[field] = new_val
        
        if 'product_id' in changes and quant.lot_id:
            try:
                existing_move_lines = self.env['stock.move.line'].search([
                    ('lot_id', '=', quant.lot_id.id)
                ])
                
                existing_moves = existing_move_lines.mapped('move_id')
                moves_to_restore = existing_moves.filtered(lambda m: m.state == 'done')
                
                if existing_moves:
                    existing_moves.sudo().write({'state': 'draft'})
                
                if existing_move_lines:
                    existing_move_lines.sudo().write({'product_id': update_vals['product_id']})
                
                if existing_moves:
                    existing_moves.sudo().write({'product_id': update_vals['product_id']})
                
                quant.lot_id.sudo()._write({'product_id': update_vals['product_id']})
                
                if hasattr(quant.lot_id, '_cr'):
                    try:
                        quant.lot_id._cr.execute(
                            "UPDATE stock_lot SET product_id = %s WHERE id = %s",
                            (update_vals['product_id'], quant.lot_id.id)
                        )
                        quant.lot_id._cr.commit()
                        quant.lot_id.invalidate_recordset(['product_id'])
                    except Exception:
                        pass
                
                if moves_to_restore:
                    moves_to_restore.sudo().write({'state': 'done'})
                
            except Exception as e:
                raise UserError(_("Failed to force update lot product (keeping same lot_id): %s") % str(e))
        
        if update_vals:
            quant.write(update_vals)



# models/stock_quant_adjustment_request.py
# models/stock_quant_adjustment_request.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import json
import logging

_logger = logging.getLogger(__name__)


class StockQuantAdjustmentRequest(models.Model):
    _name = 'stock.quant.adjustment.request'
    _description = 'Stock Quant Adjustment Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Adjustment Number', required=True, copy=False, readonly=True, default='New')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('partial', 'Partially Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True, compute='_compute_state', store=True)
    
    reason_for_adjustment = fields.Char(string='Reason for Adjustment', required=True, tracking=True)
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user, readonly=True, required=True)
    requested_date = fields.Datetime(string='Request Date', default=fields.Datetime.now, readonly=True, required=True)
    approved_by = fields.Many2one('res.users', string='Approved/Rejected By', readonly=True, tracking=True)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, tracking=True)
    rejection_reason = fields.Text(string='Rejection Reason', tracking=True)
    batch_number = fields.Char(string='Batch Number', readonly=True, help='Batch number assigned when approved')
    line_ids = fields.One2many('stock.quant.adjustment.line', 'request_id', string='Adjustment Lines')
    line_count = fields.Integer(string='Lines', compute='_compute_line_count')
    approved_line_count = fields.Integer(string='Approved', compute='_compute_line_count')
    rejected_line_count = fields.Integer(string='Rejected', compute='_compute_line_count')
    pending_line_count = fields.Integer(string='Pending', compute='_compute_line_count')
    selected_line_count = fields.Integer(string='Selected', compute='_compute_line_count')
    has_conflicts = fields.Boolean(string='Has Conflicts', compute='_compute_has_conflicts', store=True)
    conflict_count = fields.Integer(string='Conflicts', compute='_compute_has_conflicts', store=True)

    @api.depends('line_ids', 'line_ids.line_state')
    def _compute_state(self):
        for record in self:
            if not record.line_ids:
                record.state = 'draft'
                continue
            
            line_states = record.line_ids.mapped('line_state')
            
            if 'draft' in line_states:
                record.state = 'draft'
            elif 'pending' in line_states and 'draft' not in line_states:
                record.state = 'pending'
            elif set(line_states) == {'approved'}:
                record.state = 'approved'
            elif set(line_states) == {'rejected'}:
                record.state = 'rejected'
            elif 'approved' in line_states and 'rejected' in line_states:
                record.state = 'partial'
            elif 'cancelled' in line_states:
                record.state = 'cancelled'
            else:
                record.state = 'pending'

    @api.depends('line_ids', 'line_ids.line_state', 'line_ids.selected')
    def _compute_line_count(self):
        for record in self:
            record.line_count = len(record.line_ids)
            record.approved_line_count = len(record.line_ids.filtered(lambda l: l.line_state == 'approved'))
            record.rejected_line_count = len(record.line_ids.filtered(lambda l: l.line_state == 'rejected'))
            record.pending_line_count = len(record.line_ids.filtered(lambda l: l.line_state == 'pending'))
            record.selected_line_count = len(record.line_ids.filtered(lambda l: l.selected))
    
    @api.depends('line_ids.conflict_status')
    def _compute_has_conflicts(self):
        for record in self:
            conflicted_lines = record.line_ids.filtered(lambda l: l.conflict_status in ['changed', 'reserved', 'deleted'])
            record.has_conflicts = len(conflicted_lines) > 0
            record.conflict_count = len(conflicted_lines)
    
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('stock.quant.adjustment.request') or 'New'
        return super().create(vals)
    
    def action_submit_for_approval(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Cannot submit request without adjustment lines."))
        
        lines_without_changes = self.line_ids.filtered(lambda l: not l.has_changes)
        if lines_without_changes:
            raise UserError(_("Some lines have no changes. Please remove them or modify values."))
        
        draft_lines = self.line_ids.filtered(lambda l: l.line_state == 'draft')
        draft_lines.write({'line_state': 'pending'})
        self._notify_approvers()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
        
    def action_select_all_pending(self):
        """Select all pending lines without conflicts"""
        self.ensure_one()
        pending_lines = self.line_ids.filtered(lambda l: l.line_state == 'pending' and l.conflict_status == 'ok')
        pending_lines.write({'selected': True})
        
        # Unselect others
        other_lines = self.line_ids - pending_lines
        other_lines.write({'selected': False})
        
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': _('Lines Selected'),
        #         'message': _('%s pending line(s) selected.') % len(pending_lines),
        #         'type': 'info',
        #         'sticky': False,
        #     }
        # }
    
    def action_deselect_all(self):
        """Deselect all lines"""
        self.ensure_one()
        self.line_ids.write({'selected': False})
        return True
        
    def action_approve_selected(self):
        """Approve selected lines"""
        self.ensure_one()
        
        selected_lines = self.line_ids.filtered(lambda l: l.selected and l.line_state == 'pending' and l.conflict_status == 'ok')
                
        if not selected_lines:
            raise UserError(_(
                "No valid lines were selected.\n\n"
                "Please ensure that the lines you are selecting are pending and have no conflicts — "
                "conflicts typically occur when Pallets are reserved in another pending Picklist or have been successfully delivered out."
            ))

        
        if not self.batch_number:
            adjustment_form_series = self.env['ir.sequence'].search([('code', '=', 'adjustment.form.series')], limit=1)
            self.batch_number = adjustment_form_series.next_by_id() if adjustment_form_series else self.env['ir.sequence'].next_by_code('adjustment.form.series')
        
        for line in selected_lines:
            line.action_approve_line(self.batch_number, self.reason_for_adjustment)
        
        # Deselect approved lines
        selected_lines.write({'selected': False})
        
        if not self.approved_by:
            self.write({'approved_by': self.env.user.id, 'approved_date': fields.Datetime.now()})
        
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': _('Lines Approved'),
        #         'message': _('%s line(s) approved successfully.') % len(selected_lines),
        #         'type': 'success',
        #         'sticky': False,
        #     }
        # }
    
    def action_reject_selected(self):
        """Reject selected lines"""
        self.ensure_one()
        
        selected_lines = self.line_ids.filtered(lambda l: l.selected and l.line_state == 'pending')
        
        if not selected_lines:
            raise UserError(_("No valid lines selected. Please select pending lines."))
        
        return {
            'name': _('Reject Selected Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
                'default_line_ids': [(6, 0, selected_lines.ids)]
            }
        }
        
    def action_approve_all_pending(self):
        """Approve all pending lines without conflicts"""
        self.ensure_one()
        pending_lines = self.line_ids.filtered(lambda l: l.line_state == 'pending' and l.conflict_status == 'ok')
        
        if not pending_lines:
            raise UserError(_(
                "There are no pending lines available for approval.\n\n"
                "Please ensure that all conflicts have been resolved — "
                "conflicts typically occur when Pallets are reserved in another pending Picklist  or have been successfully delivered out."
            ))
        
        if not self.batch_number:
            adjustment_form_series = self.env['ir.sequence'].search([('code', '=', 'adjustment.form.series')], limit=1)
            self.batch_number = (
                adjustment_form_series.next_by_id()
                if adjustment_form_series
                else self.env['ir.sequence'].next_by_code('adjustment.form.series')
            )
        
        for line in pending_lines:
            line.action_approve_line(self.batch_number, self.reason_for_adjustment)
        
        if not self.approved_by:
            self.write({
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now()
            })

        
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': _('All Lines Approved'),
        #         'message': _('%s line(s) approved successfully.') % len(pending_lines),
        #         'type': 'success',
        #         'sticky': False,
        #     }
        # }
    
    def action_cancel(self):
        self.ensure_one()
        if self.state not in ['draft', 'pending', 'partial']:
            raise UserError(_("Only draft, pending or partial requests can be cancelled."))
        if self.state in ['pending', 'partial'] and self.requested_by != self.env.user:
            raise UserError(_("Only the requester can cancel a pending request."))
        self.line_ids.filtered(lambda l: l.line_state != 'approved').write({'line_state': 'cancelled'})
        return True
    
    def action_set_to_draft(self):
        self.ensure_one()
        if self.state != 'cancelled':
            raise UserError(_("Only cancelled requests can be reset to draft."))
        self.line_ids.write({'line_state': 'draft'})
        return True
    
    def action_check_conflicts(self):
        self.ensure_one()
        self.line_ids._check_quant_conflicts()
        # if self.has_conflicts:
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'display_notification',
        #         'params': {
        #             'title': _('Conflicts Detected'),
        #             'message': _('%s line(s) have conflicts. Please review.') % self.conflict_count,
        #             'type': 'warning',
        #             'sticky': False,
        #         }
        #     }
        # else:
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'display_notification',
        #         'params': {
        #             'title': _('No Conflicts'),
        #             'message': _('All lines are ready for approval.'),
        #             'type': 'success',
        #             'sticky': False,
        #         }
        #     }
    
    def _notify_approvers(self):
        approval_group = self.env.ref('stock.group_stock_manager', raise_if_not_found=False)
        if approval_group:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=approval_group.users[1].id if approval_group.users else self.env.user.id,
                summary=_('Stock Adjustment Approval Required'),
                note=_('Request %s submitted by %s requires approval.\nReason: %s\nLines: %s') % (
                    self.name, self.requested_by.name, self.reason_for_adjustment, self.line_count
                )
            )


class StockQuantAdjustmentLine(models.Model):
    _name = 'stock.quant.adjustment.line'
    _description = 'Stock Quant Adjustment Line'
    _order = 'id'

    request_id = fields.Many2one('stock.quant.adjustment.request', string='Adjustment Request', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Select', default=False, help='Select this line for batch approval/rejection')
    line_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Line Status', default='draft', required=True, tracking=True)
    
    rejection_reason = fields.Text(string='Rejection Reason')
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approved Date', readonly=True)
    quant_id = fields.Many2one('stock.quant', string='Pallet Quant Details', required=True)
    quant_snapshot = fields.Text(string='Quant Snapshot', readonly=True, help='JSON snapshot of quant state when request was created')
    conflict_status = fields.Selection([
        ('ok', 'OK'),
        ('changed', 'Pallet Changed'),
        ('reserved', 'Pallet Reserved'),
        ('deleted', 'Pallet Deleted / Delivered')
    ], string='Conflict Status', default='ok', compute='_compute_conflict_status', store=True)
    
    has_changes = fields.Boolean(string='Has Changes', compute='_compute_has_changes', store=True)
    display_pallet_series = fields.Char(string='Pallet Series', related='quant_id.x_studio_pallet_series_id', readonly=True)
    display_location = fields.Char(string='Location', related='quant_id.location_id.complete_name', readonly=True)
    
    # OLD VALUES
    old_package_id = fields.Many2one('stock.quant.package', string='Old Pallet #', readonly=True)
    old_product_id = fields.Many2one('product.product', string='Old Product', readonly=True)
    old_quantity = fields.Float(string='Old Quantity', readonly=True)
    old_lot_id = fields.Many2one('stock.lot', string='Old Lot', readonly=True)
    old_owner_id = fields.Many2one('res.partner', string='Old Owner', readonly=True)
    old_x_studio_production_date = fields.Date(string='Old Production Date', readonly=True)
    old_x_studio_expiration_date = fields.Date(string='Old Expiration Date', readonly=True)
    old_x_studio_2nd_uom = fields.Float(string='Old Total Quantity', readonly=True)
    old_x_studio_total_units = fields.Float(string='Old Total Heads', readonly=True)
    old_x_studio_quantity_uom = fields.Many2one('uom.uom', string='Old Quantity UOM', readonly=True)
    old_x_studio_min_quantity_uom = fields.Many2one('uom.uom', string='Old Heads UOM', readonly=True)
    
    # NEW VALUES
    new_package_id = fields.Many2one('stock.quant.package', string='New Pallet #')
    new_product_id = fields.Many2one('product.product', string='New Product')
    new_quantity = fields.Float(string='New Quantity')
    new_lot_id = fields.Many2one('stock.lot', string='New Lot')
    new_owner_id = fields.Many2one('res.partner', string='New Owner')
    new_x_studio_production_date = fields.Date(string='New Production Date')
    new_x_studio_expiration_date = fields.Date(string='New Expiration Date')
    new_x_studio_2nd_uom = fields.Float(string='New Total Quantity')
    new_x_studio_total_units = fields.Float(string='New Total Heads')
    new_x_studio_quantity_uom = fields.Many2one('uom.uom', string='New Quantity UOM')
    new_x_studio_min_quantity_uom = fields.Many2one('uom.uom', string='New Heads UOM')


    changed_fields_display = fields.Html(string='Changes', compute='_compute_changed_fields_display')
    
    @api.depends('old_package_id', 'new_package_id', 'old_product_id', 'new_product_id', 
                 'old_quantity', 'new_quantity', 'old_x_studio_2nd_uom', 'new_x_studio_2nd_uom',
                 'old_x_studio_total_units', 'new_x_studio_total_units',
                 'old_x_studio_quantity_uom', 'new_x_studio_quantity_uom',
                 'old_x_studio_min_quantity_uom', 'new_x_studio_min_quantity_uom',
                 'old_owner_id', 'new_owner_id')
    def _compute_changed_fields_display(self):
        """Compute HTML display of only the fields that changed"""
        for line in self:
            changes = line._get_changes()
            if not changes:
                line.changed_fields_display = '<span class="text-muted">No changes detected</span>'
                continue
            
            html_parts = []
            field_labels = {
                'package_id': 'Pallet #',
                'product_id': 'Product',
                'quantity': 'Weight (KG)',
                'owner_id': 'Owner',
                'x_studio_2nd_uom': 'Total Quantity',
                'x_studio_quantity_uom': 'Quantity UOM',
                'x_studio_total_units': 'Total Heads',
                'x_studio_min_quantity_uom': 'Heads UOM',
            }
            
            for field_name, (old_val, new_val) in changes.items():
                label = field_labels.get(field_name, field_name.replace('_', ' ').title())
                old_display = line._format_field_value(field_name, old_val)
                new_display = line._format_field_value(field_name, new_val)
                
                html_parts.append(
                    f'<div style="margin-bottom: 5px;">'
                    f'<strong>{label}:</strong> '
                    f'<span style="color: #dc3545; text-decoration: line-through;">{old_display}</span> '
                    f'<i class="fa fa-long-arrow-right" style="margin: 0 8px; color: #6c757d;"></i> '
                    f'<span style="color: #28a745; font-weight: bold;">{new_display}</span>'
                    f'</div>'
                )
            
            line.changed_fields_display = ''.join(html_parts) if html_parts else '<span class="text-muted">No changes</span>'
    
    def _format_field_value(self, field_name, value):
        """Format field value for display"""
        if value is False or value is None:
            return '<em style="color: #6c757d;">Empty</em>'
        
        # Handle Many2one fields
        if field_name in ['package_id', 'product_id', 'owner_id', 'x_studio_quantity_uom', 'x_studio_min_quantity_uom']:
            if isinstance(value, int):
                model_map = {
                    'package_id': 'stock.quant.package',
                    'product_id': 'product.product',
                    'owner_id': 'res.partner',
                    'x_studio_quantity_uom': 'uom.uom',
                    'x_studio_min_quantity_uom': 'uom.uom',
                }
                model_name = model_map.get(field_name)
                if model_name:
                    try:
                        record = self.env[model_name].browse(value)
                        if record.exists():
                            return record.display_name or str(value)
                    except:
                        pass
                return str(value)
        
        # Handle float fields with formatting
        if field_name in ['quantity', 'x_studio_2nd_uom', 'x_studio_total_units']:
            try:
                return f'{float(value):,.2f}'
            except:
                return str(value)
        
        return str(value)

    def action_view_line_details(self):
        """Open form view of the adjustment line"""
        self.ensure_one()
        return {
            'name': _('Adjustment Line Details'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant.adjustment.line',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
    
    @api.depends('old_package_id', 'new_package_id', 'old_product_id', 'new_product_id', 'old_quantity', 'new_quantity', 
                 'old_lot_id', 'new_lot_id', 'old_owner_id', 'new_owner_id', 'old_x_studio_2nd_uom', 'new_x_studio_2nd_uom',
                 'old_x_studio_total_units', 'new_x_studio_total_units')
    def _compute_has_changes(self):
        for line in self:
            changes = line._get_changes()
            line.has_changes = bool(changes)
    
    @api.depends('quant_id', 'quant_snapshot', 'quant_id.reserved_quantity')
    def _compute_conflict_status(self):
        for line in self:
            line._check_quant_conflicts()
    
    def _check_quant_conflicts(self):
        for line in self:
            
            quant = line.quant_id
            
            if line.line_state in ['approved', 'rejected', 'cancelled'] and quant.reserved_quantity == 0 and not quant.quantity == 0:
                line.conflict_status = 'ok'
                continue

            if quant.quantity == 0:
                line.conflict_status = 'deleted'
                continue
                
            if not line.quant_id.exists():
                line.conflict_status = 'deleted'
                continue
            
            if quant.reserved_quantity > 0:
                line.conflict_status = 'reserved'
                continue
            
            if line.quant_snapshot:
                current_snapshot = line._create_quant_snapshot(quant)
                if current_snapshot != line.quant_snapshot:
                    line.conflict_status = 'changed'
                    continue
            
            line.conflict_status = 'ok'

    def _create_quant_snapshot(self, quant):
        snapshot_data = {
            'quantity': quant.quantity,
            'reserved_quantity': quant.reserved_quantity,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': quant.package_id.id if quant.package_id else False,
            'owner_id': quant.owner_id.id if quant.owner_id else False,
            'location_id': quant.location_id.id,
            'write_date': str(quant.write_date),
            'x_studio_2nd_uom': quant.x_studio_2nd_uom,
            'x_studio_total_units': quant.x_studio_total_units,
        }
        return json.dumps(snapshot_data, sort_keys=True)
    
    def _get_changes(self):
        self.ensure_one()
        changes = {}
        
        field_mapping = {
            'package_id': ('package_id', lambda x: x.id if x else False),
            'product_id': ('product_id', lambda x: x.id),
            'quantity': ('quantity', float),
            'owner_id': ('owner_id', lambda x: x.id if x else False),
            'x_studio_2nd_uom': ('x_studio_2nd_uom', float),
            'x_studio_total_units': ('x_studio_total_units', float),
            'x_studio_quantity_uom': ('x_studio_quantity_uom', lambda x: x.id if x else False),
            'x_studio_min_quantity_uom': ('x_studio_min_quantity_uom', lambda x: x.id if x else False),
        }
        
        for base_field, (field_name, converter) in field_mapping.items():
            old_value = getattr(self, f'old_{base_field}')
            new_value = getattr(self, f'new_{base_field}')
            
            try:
                old_converted = converter(old_value) if old_value not in [False, None] else old_value
                new_converted = converter(new_value) if new_value not in [False, None] else new_value
            except (ValueError, TypeError):
                old_converted = old_value
                new_converted = new_value
            
            if old_converted != new_converted:
                changes[field_name] = (old_converted, new_converted)
        
        return changes
    
    def action_approve_line(self, batch_number, reason):
        self.ensure_one()

        # self._check_quant_conflicts()
        
        if self.line_state != 'pending':
            raise UserError(_("Only pending lines can be approved."))
        
        if self.conflict_status != 'ok':
            raise UserError(_("Cannot approve line with conflicts: %s") % self.conflict_status)
        
        self._apply_adjustment(batch_number, reason)
        
        self.write({
            'line_state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now()
        })
    
    def action_reject_line(self, rejection_reason):
        self.ensure_one()
        
        if self.line_state != 'pending':
            raise UserError(_("Only pending lines can be rejected."))
        
        self.write({
            'line_state': 'rejected',
            'rejection_reason': rejection_reason,
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now()
        })
    
    def _apply_adjustment(self, batch_number, reason):
        # Same implementation as before - this part doesn't change
        self.ensure_one()
        
        quant = self.quant_id
        changes = self._get_changes()
        
        if not changes:
            return
        
        wizard = self.env['stock.quant.correction.wizard'].create({'reason_for_adjustment': reason})
        
        line_vals = {
            'wizard_id': wizard.id,
            'quant_id': quant.id,
            'package_id': self.new_package_id.id if self.new_package_id else quant.package_id.id,
            'product_id': self.new_product_id.id if self.new_product_id else quant.product_id.id,
            'quantity': self.new_quantity if self.new_quantity else quant.quantity,
            'owner_id': self.new_owner_id.id if self.new_owner_id else (quant.owner_id.id if quant.owner_id else False),
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'x_studio_2nd_uom': self.new_x_studio_2nd_uom if self.new_x_studio_2nd_uom else quant.x_studio_2nd_uom,
            'x_studio_total_units': self.new_x_studio_total_units if self.new_x_studio_total_units else quant.x_studio_total_units,
            'x_studio_quantity_uom': self.new_x_studio_quantity_uom.id if self.new_x_studio_quantity_uom else (quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False),
            'x_studio_min_quantity_uom': self.new_x_studio_min_quantity_uom.id if self.new_x_studio_min_quantity_uom else (quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False),
        }
        
        correction_line = self.env['stock.quant.correction.line'].create(line_vals)
        original_state = correction_line._capture_original_state()
        
        if 'quantity' in changes:
            wizard._handle_quantity_adjustment(correction_line, changes['quantity'][0], changes['quantity'][1], batch_number)
        
        correction_line._apply_changes(changes)
        
        non_quantity_changes = {k: v for k, v in changes.items() if k != 'quantity'}
        if non_quantity_changes:
            wizard._create_correction_move(correction_line, non_quantity_changes, original_state, batch_number, quant.x_studio_record_reference)
        
        wizard._update_pallet_kilos_record(correction_line, changes, batch_number)



# models/stock_quant_adjustment_reject_wizard.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockQuantAdjustmentRejectWizard(models.TransientModel):
    _name = 'stock.quant.reject.wizard'
    _description = 'Stock Quant Adjustment Reject Wizard'

    request_id = fields.Many2one('stock.quant.adjustment.request', string='Request', required=True, readonly=True)
    line_ids = fields.Many2many('stock.quant.adjustment.line', string='Lines to Reject', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', required=True, help='Please provide a reason for rejecting these adjustment line(s)')
    line_count = fields.Integer(string='Number of Lines', compute='_compute_line_count')
    
    @api.depends('line_ids')
    def _compute_line_count(self):
        for record in self:
            record.line_count = len(record.line_ids)

    def action_confirm_reject(self):
        self.ensure_one()
        
        if not self.rejection_reason:
            raise UserError(_("Please provide a rejection reason."))
        
        if not self.line_ids:
            raise UserError(_("No lines to reject."))
        
        for line in self.line_ids:
            line.action_reject_line(self.rejection_reason)
        
        self.request_id.message_post(
            body=_('%s line(s) rejected by %s<br/>Reason: %s') % (
                len(self.line_ids),
                self.env.user.name,
                self.rejection_reason
            ),
            subject=_('Adjustment Lines Rejected'),
            message_type='notification',
            subtype_xmlid='mail.mt_comment'
        )
        
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': _('Lines Rejected'),
        #         'message': _('%s line(s) rejected successfully.') % len(self.line_ids),
        #         'type': 'info',
        #         'sticky': False,
        #     }
        # }