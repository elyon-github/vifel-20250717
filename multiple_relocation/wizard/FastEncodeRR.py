from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

logger = logging.getLogger(__name__)

class FastEncodeRRWizard(models.TransientModel):
    _name = 'stock.move.line.fast_encode_rr'
    _description = 'Stock Move Line Fast Encode RR'
        
    transfer_id = fields.Integer(string="Transfer ID")
    line_ids = fields.One2many(
        'stock.move.line.fast_encode_rr.line', 'wizard_id', string="Pallet Lines", readonly=False
    )
    
    def action_confirm(self):
        """Apply wizard changes back to stock.move.line"""
        
        # Check if this is a blast freeze operation
        is_blast_freeze = self.env.context.get('is_blast_freeze', False)
        
        if is_blast_freeze:
            # Simple write for blast freeze - no pallet series grouping or reservations
            for line in self.line_ids:
                if line.stock_move_line:
                    move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                    move_line.write({
                        'result_package_id': line.result_package_id.id if line.result_package_id else False,
                        'bf_pallet_char': line.bf_pallet_char,
                        'x_studio_2nd_uom': line.quantity,
                        'x_studio_total_units': line.min_uom_unit,
                        'quantity': line.kilogram,
                        'x_studio_container_number': line.container_number or '',
                        'x_studio_production_date': line.production_date,
                        'x_studio_expiration_date': line.expiration_date,
                        'x_studio_quantity_uom': line.quantity_uom.id if line.quantity_uom else False,
                        'x_studio_min_quantity_uom': line.packs_uom.id if line.packs_uom else False,
                    })
            return {'type': 'ir.actions.act_window_close'}
        
        # Normal logic for non-blast-freeze operations
        # Get all move lines for this transfer to track pallet and location changes
        if not self.line_ids:
            return {'type': 'ir.actions.act_window_close'}
        
        transfer_id = self.line_ids[0].transfer_id
        
        # Track pallets and locations that were previously used (before wizard changes)
        previous_pallets = set()
        previous_locations = set()
        for line in self.line_ids:
            if line.stock_move_line:
                move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                if move_line.result_package_id:
                    previous_pallets.add(move_line.result_package_id.id)
                if move_line.location_dest_id:
                    previous_locations.add(move_line.location_dest_id.id)
        
        # First pass: Build mappings of pallet_id -> first pallet_series_id and first location
        pallet_to_first_series = {}
        pallet_to_first_location = {}
        current_pallets = set()  # Track pallets being used after wizard changes
        current_locations = set()  # Track locations being used after wizard changes
        
        # Group lines by pallet, then pick the smallest original_pallet_series_id
        # as the winning series for each pallet (consistent with wizard multi-edit logic).
        pallet_lines = {}  # pallet_id -> list of wizard lines
        for line in self.line_ids:
            if line.result_package_id:
                pallet_id = line.result_package_id.id
                current_pallets.add(pallet_id)
                pallet_lines.setdefault(pallet_id, []).append(line)
            
            if line.location_dest_id:
                current_locations.add(line.location_dest_id.id)
        
        for pallet_id, lines in pallet_lines.items():
            # Sort by original_pallet_series_id — smallest wins
            sorted_lines = sorted(lines, key=lambda l: l.original_pallet_series_id or l.pallet_series_id or '')
            winner = sorted_lines[0]
            pallet_to_first_series[pallet_id] = winner.pallet_series_id
            pallet_to_first_location[pallet_id] = winner.location_dest_id.id if winner.location_dest_id else False
            if winner.location_dest_id:
                current_locations.add(winner.location_dest_id.id)
        
        # Second pass: Check if pallets are already used by OTHER existing move lines
        # If so, prioritize their existing series and location
        for pallet_id, wizard_series in list(pallet_to_first_series.items()):
            existing_line = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('result_package_id', '=', pallet_id),
                ('x_studio_pallet_series_id', '!=', False),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            if existing_line:
                pallet_to_first_series[pallet_id] = existing_line.x_studio_pallet_series_id
                pallet_to_first_location[pallet_id] = existing_line.location_dest_id.id if existing_line.location_dest_id else False
        
        # ── Comparison pass: determine which pre_wizard series are freed ──
        # Build the set of series that will be used in the FINAL state (excluding NEW placeholders).
        final_series_set = set()
        new_lines = []  # Lines that need a fresh series from pool/counter
        
        for line in self.line_ids:
            if line.needs_new_pallet_series:
                new_lines.append(line)
                continue
            
            if line.result_package_id:
                final = pallet_to_first_series.get(line.result_package_id.id, line.pallet_series_id)
            else:
                final = line.pallet_series_id
            if final:
                final_series_set.add(final)
        
        # Also include series from external move lines (not in wizard) — they must not be recycled.
        external_ml_ids = self.line_ids.mapped('stock_move_line')
        external_lines = self.env['stock.move.line'].search([
            ('picking_id', '=', transfer_id),
            ('id', 'not in', external_ml_ids),
            ('x_studio_pallet_series_id', '!=', False),
        ])
        for ml in external_lines:
            final_series_set.add(ml.x_studio_pallet_series_id)
        
        # A pre_wizard series gets recycled if it's NOT in any final line's resolved series.
        wizard_series_to_recycle = set()
        for line in self.line_ids:
            pre_wizard = line.pre_wizard_pallet_series_id
            if pre_wizard and pre_wizard not in final_series_set:
                wizard_series_to_recycle.add(pre_wizard)
        
        # ── Recycle pass: push freed series back to owner's pool BEFORE pulling new ones ──
        owner = None
        for wl in self.line_ids:
            if wl.stock_move_line:
                ml = self.env['stock.move.line'].browse(wl.stock_move_line)
                if ml.owner_id:
                    owner = ml.owner_id
                    break
        
        if owner and wizard_series_to_recycle:
            for series_id in wizard_series_to_recycle:
                owner.push_unused_pallet(series_id)
        
        # ── Restore originals pass: consume originals from pool for unique/cleared lines ──
        # Only applies to lines that are NOT part of a multi-line pallet group.
        # Grouped lines get their series from pallet_to_first_series, not from the pool.
        if owner:
            # Build set of pallet IDs that have multiple lines (grouped pallets)
            grouped_pallets = set()
            for pid, lines in pallet_lines.items():
                if len(lines) > 1:
                    grouped_pallets.add(pid)
            
            for line in self.line_ids:
                if line.needs_new_pallet_series:
                    continue
                # Skip lines that are in a multi-line pallet group
                if line.result_package_id and line.result_package_id.id in grouped_pallets:
                    continue
                if line.pallet_series_id and line.pallet_series_id != line.pre_wizard_pallet_series_id:
                    # This line is restoring its original — consume it from the pool
                    owner.get_pallet_series_by_id(line.pallet_series_id)
        
        # ── Resolve NEW pass: pull real series for lines flagged needs_new_pallet_series ──
        if owner and new_lines:
            for line in new_lines:
                new_series = owner.get_smallest_pallet_series_ids(1)
                if new_series:
                    resolved = new_series[0]
                else:
                    resolved = owner.generate_new_pallet_series_id()
                
                # Update the wizard line with the resolved series
                super(FastEncodeRRWizardLine, line).write({
                    'pallet_series_id': resolved,
                    'needs_new_pallet_series': False,
                })
                
                # Update pallet mapping if this line has a pallet
                if line.result_package_id and line.result_package_id.id in pallet_to_first_series:
                    pallet_to_first_series[line.result_package_id.id] = resolved
        
        # ── Third pass: Apply changes to stock.move.line ──
        for line in self.line_ids:
            if line.stock_move_line:
                move_line = self.env['stock.move.line'].browse(line.stock_move_line)
                
                # Determine which pallet_series_id and location_dest_id to use
                pallet_series_to_use = line.pallet_series_id
                location_dest_to_use = line.location_dest_id.id if line.location_dest_id else False
                
                if line.result_package_id:
                    # Use the determined series and location for this pallet
                    pallet_series_to_use = pallet_to_first_series.get(line.result_package_id.id, line.pallet_series_id)
                    location_dest_to_use = pallet_to_first_location.get(line.result_package_id.id, location_dest_to_use)
                
                # Build the values to write
                write_vals = {
                    'result_package_id': line.result_package_id.id if line.result_package_id else False,
                    'bf_pallet_char': line.bf_pallet_char,
                    'x_studio_2nd_uom': line.quantity,
                    'x_studio_total_units': line.min_uom_unit,
                    'quantity': line.kilogram,
                    'x_studio_pallet_series_id': pallet_series_to_use,
                    'x_studio_container_number': line.container_number or '',
                    'x_studio_production_date': line.production_date,
                    'x_studio_expiration_date': line.expiration_date,
                    'x_studio_quantity_uom': line.quantity_uom.id if line.quantity_uom else False,
                    'x_studio_min_quantity_uom': line.packs_uom.id if line.packs_uom else False,
                }
                
                # Only write location_dest_id if we have a valid value
                if location_dest_to_use:
                    write_vals['location_dest_id'] = location_dest_to_use
                
                # Write all the values — skip the stock.move.line write override
                # since action_confirm already handles all pallet series logic.
                move_line.with_context(skip_pallet_series_sync=True).write(write_vals)
                
                # Reserve the pallet if it's not already reserved
                if line.result_package_id and not line.result_package_id.x_studio_is_reserved:
                    line.result_package_id.write({
                        'x_studio_is_reserved': True, 
                        'x_studio_receiving_report_id': transfer_id
                    })
                
                # Reserve the location if it's not already reserved
                if location_dest_to_use:
                    location = self.env['stock.location'].browse(location_dest_to_use)
                    if location.exists() and not location.x_studio_is_reserved:
                        location.write({
                            'x_studio_is_reserved': True,
                            'x_studio_receiving_report_id': transfer_id
                        })
        
        # Fourth pass: Remove reservations for pallets that are no longer being used
        removed_pallets = previous_pallets - current_pallets
        for pallet_id in removed_pallets:
            # Check if this pallet is still used by other move lines in the same transfer
            other_usage = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('result_package_id', '=', pallet_id),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            # Only remove reservation if no other lines are using it
            if not other_usage:
                pallet = self.env['stock.quant.package'].browse(pallet_id)
                if pallet.exists():
                    pallet.remove_reservation()
        
        # Fifth pass: Remove reservations for locations that are no longer being used
        removed_locations = previous_locations - current_locations
        for location_id in removed_locations:
            # Check if this location is still used by other move lines in the same transfer
            other_usage = self.env['stock.move.line'].search([
                ('picking_id', '=', transfer_id),
                ('location_dest_id', '=', location_id),
                ('id', 'not in', self.line_ids.mapped('stock_move_line'))
            ], limit=1)
            
            # Only remove reservation if no other lines are using it
            if not other_usage:
                location = self.env['stock.location'].browse(location_id)
                if location.exists():
                    location.remove_reservation()
        
        return {'type': 'ir.actions.act_window_close'}
    
    def _recycle_unused_pallet_series(self, series_to_recycle):
        """Push unused pallet series back to the owner's pool"""
        if not series_to_recycle:
            return
        
        # Get the picking to find the owner
        if not self.line_ids:
            return
        
        picking = self.env['stock.picking'].browse(self.line_ids[0].transfer_id)
        if not picking:
            return
        
        # For each series that needs recycling, verify it's not being used anywhere
        for series_id in series_to_recycle:
            # Check if this series is actually being used in the final move lines
            series_in_use = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', series_id)
            ], limit=1)
            
            # Only push back if it's truly unused
            if not series_in_use:
                # Find the owner from any move line in this picking
                move_line_with_owner = self.env['stock.move.line'].search([
                    ('picking_id', '=', picking.id),
                    ('owner_id', '!=', False)
                ], limit=1)
                
                if move_line_with_owner and move_line_with_owner.owner_id:
                    move_line_with_owner.owner_id.push_unused_pallet(series_id)
    



class FastEncodeRRWizardLine(models.TransientModel):
    _name = 'stock.move.line.fast_encode_rr.line'
    _description = 'Stock Move Line Fast Encode RR Line'
    _order = 'pallet_series_id asc'
    
    wizard_id = fields.Many2one('stock.move.line.fast_encode_rr', string="Wizard", ondelete='cascade')
    transfer_id = fields.Integer(string="Transfer ID", related='wizard_id.transfer_id', store=True)
    stock_move_line = fields.Integer(string="Move Line ID")
    x_studio_ = fields.Integer(string="#", readonly=True, group_operator=False)
    
    product_id = fields.Many2one('product.product', string="Products", readonly="1")
    pallet_series_id = fields.Char(string='Pallet Series ID', readonly="1")
    result_package_id = fields.Many2one('stock.quant.package', string='RR Pallet #')
    pallet_number = fields.Many2one('stock.quant.package', string='BFRR Pallet #')
    bf_pallet_char = fields.Char(string="Pallet # - Text")
    quantity = fields.Float(string="Quantity")
    min_uom_unit = fields.Float(string="Packs")
    kilogram = fields.Float(string="Weight (KG)")
    location_dest_id = fields.Many2one('stock.location', string='Destination Location')
    container_number = fields.Char(string='Container #')
    production_date = fields.Date(string='Production Date')
    expiration_date = fields.Date(string='Expiration Date')
    quantity_uom = fields.Many2one('uom.uom', string='Quantity UOM')
    packs_uom = fields.Many2one('uom.uom', string='Packs UOM')
    
    # Snapshot of the pallet series from the DB when wizard opened — NEVER changes during wizard session.
    # Used at confirm time to compare with the final pallet_series_id and determine what needs recycling.
    pre_wizard_pallet_series_id = fields.Char(string='Pre-Wizard Pallet Series ID', readonly=True)
    
    # Hidden fallback fields - stores the original values before auto-sync
    original_pallet_series_id = fields.Char(string='Original Pallet Series ID', readonly=True)
    original_location_dest_id = fields.Many2one('stock.location', string='Original Location', readonly=True)
    original_container_number = fields.Char(string='Original Container #', readonly=True)
    original_production_date = fields.Date(string='Original Production Date', readonly=True)
    original_expiration_date = fields.Date(string='Original Expiration Date', readonly=True)
    original_quantity_uom = fields.Many2one('uom.uom', string='Original Quantity UOM', readonly=True)
    original_packs_uom = fields.Many2one('uom.uom', string='Original Packs UOM', readonly=True)
    
    # Flag: if True, this line needs a NEW pallet series pulled from pool/counter at confirm time.
    # Displayed with green text in the wizard to indicate a pending new assignment.
    needs_new_pallet_series = fields.Boolean(string='Needs New Pallet Series', default=False)

    # Pending re-sync: stores the pallet the user tried to select that would cause a re-sync.
    # The JS confirmation dialog reads this to ask the user before applying.
    pending_resync_pallet_id = fields.Many2one('stock.quant.package', string='Pending Resync Pallet')
    pending_resync_old_series = fields.Char(string='Pending Resync Old Series')
    pending_resync_new_series = fields.Char(string='Pending Resync New Series')
    
    has_duplicate_pallet = fields.Boolean(
        string='Has Duplicate Pallet',
        compute='_compute_has_duplicate_pallet',
        store=False
    )
    
    @api.depends('result_package_id', 'wizard_id.line_ids.result_package_id')
    def _compute_has_duplicate_pallet(self):
        """Check if this line's pallet is used by other lines in the wizard"""
        for record in self:
            if not record.result_package_id:
                record.has_duplicate_pallet = False
                continue
            
            # Count how many lines in this wizard have the same pallet
            duplicate_count = self.search_count([
                ('wizard_id', '=', record.wizard_id.id),
                ('result_package_id', '=', record.result_package_id.id)
            ])
            
            # If more than 1, then this pallet is duplicated
            record.has_duplicate_pallet = duplicate_count > 1

    def _get_wizard_owner(self):
        """Return the res.partner owner from any move line in this wizard, or None."""
        for wl in self.wizard_id.line_ids:
            if wl.stock_move_line:
                ml = self.env['stock.move.line'].browse(wl.stock_move_line)
                if ml.owner_id:
                    return ml.owner_id
        return None

    def _resolve_series_for_unique_line(self):
        """Determine what pallet series ID to DISPLAY for a line being made unique.
        
        Logic:
        1. If original_pallet_series_id is claimed as the WINNING series for any
           other pallet group in this wizard, it's taken → preview new.
        2. If original_pallet_series_id is in the owner's unused pool, it can be
           restored → return it directly.
        3. If original equals the line's pre_wizard (current DB) series, it's
           still assigned to this line → return it directly.
        4. Otherwise the original was consumed elsewhere → preview new.
        
        Returns:
            tuple: (series_id_string, needs_new_bool)
        """
        self.ensure_one()
        if not self.original_pallet_series_id:
            # No original at all — get a preview of new series
            series, _ = self._preview_next_series()
            return (series, True)  # Always new when no original
        
        # Build pallet groups and determine the TRUE winner per group using smallest
        # original_pallet_series_id (mirrors action_confirm first-pass logic).
        # Using line.pallet_series_id would be wrong after a multi-edit grouped all
        # lines to the same series — it would falsely claim the winner's original.
        pallet_groups = {}  # pallet_id -> list of original_pallet_series_id
        exclude_ids = {self.id}
        if hasattr(self, '_origin') and self._origin:
            exclude_ids.add(self._origin.id)
        
        for line in self.wizard_id.line_ids:
            if line.id in exclude_ids:
                continue
            if line.result_package_id:
                pid = line.result_package_id.id
                orig = line.original_pallet_series_id or line.pallet_series_id or ''
                if pid not in pallet_groups:
                    pallet_groups[pid] = []
                pallet_groups[pid].append(orig)
        
        # Determine actual winner for each pallet group (smallest original wins)
        pallet_winner_series = set()
        for pid, originals in pallet_groups.items():
            if originals:
                pallet_winner_series.add(min(originals))
        
        # If our original is claimed as the winner for ANY pallet group, it's taken → need new
        if self.original_pallet_series_id in pallet_winner_series:
            series, _ = self._preview_next_series()
            return (series, True)  # Always new when original is taken
        
        # If the original is what the line currently has in DB, it's still ours → restore it
        if self.original_pallet_series_id == self.pre_wizard_pallet_series_id:
            return (self.original_pallet_series_id, False)  # Not new, restore original
        
        # Check if the original is available in the owner's unused pool → restore it
        owner = self._get_wizard_owner()
        if owner:
            pool = owner.unused_pallet_series_ids or []
            try:
                orig_int = int(self.original_pallet_series_id.split('-')[-1])
                if orig_int in pool:
                    return (self.original_pallet_series_id, False)  # Not new, restore from pool
            except (ValueError, IndexError):
                pass
        
        # Original was consumed elsewhere → need a new one (from pool or counter)
        series, _ = self._preview_next_series()
        return (series, True)  # Always new when original was consumed

    def _preview_next_series(self):
        """Peek at the owner's unused pool + counter to preview the next series ID
        that would be assigned — WITHOUT consuming anything.
        
        Also accounts for how many other wizard lines already need_new before this one.
        
        Returns:
            tuple: (preview_series_string, True)
        """
        self.ensure_one()
        owner = self._get_wizard_owner()
        if not owner or not owner.x_studio_client_unique_code_1:
            return ('NEW', True)
        
        prefix = owner.x_studio_client_unique_code_1
        
        # Build a simulated pool from the actual unused pool only.
        # Do NOT add "freed" series here — those depend on confirm-time logic
        # and could collide with series still in use by other pallet groups.
        sim_pool = sorted(list(owner.unused_pallet_series_ids or []))
        
        # Remove pool entries that are reserved by "restore" lines — either already
        # resolved (pallet_series != pre_wizard) OR about to be resolved (original is in pool).
        for line in self.wizard_id.line_ids:
            if line.id == self.id:
                continue
            
            # Case 1: Line already resolved — its pallet_series differs from pre_wizard
            if not line.needs_new_pallet_series and line.pallet_series_id and line.pallet_series_id != line.pre_wizard_pallet_series_id:
                try:
                    restore_int = int(line.pallet_series_id.split('-')[-1])
                    if restore_int in sim_pool:
                        sim_pool.remove(restore_int)
                except (ValueError, IndexError):
                    pass
            
            # Case 2: Line not yet resolved — but its original IS in pool, so it WILL claim it
            if line.original_pallet_series_id and line.original_pallet_series_id != line.pallet_series_id:
                try:
                    orig_int = int(line.original_pallet_series_id.split('-')[-1])
                    if orig_int in sim_pool:
                        sim_pool.remove(orig_int)
                except (ValueError, IndexError):
                    pass
        
        # Simulated counter
        sim_counter = int(owner.x_studio_pallet_series_id or 0)
        
        # Count how many NEW lines come BEFORE this line in wizard order
        # (they would consume from the pool first)
        lines_before = 0
        for line in self.wizard_id.line_ids:
            if line.id == self.id:
                break
            if line.needs_new_pallet_series:
                lines_before += 1
        
        # Simulate pulling `lines_before + 1` series
        from_counter = False
        for i in range(lines_before + 1):
            if sim_pool:
                picked = sim_pool.pop(0)
                from_counter = False
            else:
                picked = sim_counter
                sim_counter += 1
                from_counter = True
        
        preview = f"{prefix}-{str(picked).zfill(6)}"
        return (preview, from_counter)

    def _sync_pallet_series_and_location(self, result_package_id):
        """Core sync logic: find the PSI, location, and other fields for a given pallet.
        
        Used by both onchange (single edit) and write (multi-edit).
        Returns dict with synced field values if found, or None if no sync needed.
        """
        if not result_package_id:
            return None
        
        # Search sibling lines in the same wizard with the same pallet
        sibling_lines = self.wizard_id.line_ids.filtered(
            lambda l: l.result_package_id.id == result_package_id
                      and l.id != self.id
                      and l.pallet_series_id
        )
        
        if sibling_lines:
            source_line = sibling_lines[0]
            return {
                'pallet_series_id': source_line.pallet_series_id,
                'location_dest_id': source_line.location_dest_id.id if source_line.location_dest_id else False,
            }
        
        # No sibling found in wizard - check actual stock.move.line records
        # Exclude ALL wizard lines' ML IDs — wizard state takes priority over DB
        all_wizard_ml_ids = self.wizard_id.line_ids.mapped('stock_move_line')
        existing_move_line = self.env['stock.move.line'].search([
            ('picking_id', '=', self.transfer_id),
            ('result_package_id', '=', result_package_id),
            ('x_studio_pallet_series_id', '!=', False),
            ('id', 'not in', all_wizard_ml_ids),
        ], limit=1)
        
        if existing_move_line:
            return {
                'pallet_series_id': existing_move_line.x_studio_pallet_series_id,
                'location_dest_id': existing_move_line.location_dest_id.id if existing_move_line.location_dest_id else False,
            }
        
        return None

    @api.onchange('result_package_id')
    def _onchange_result_package_id_sync(self):
        """Auto-sync PSI and location when user changes Pallet# to match another row.
        
        Mirrors the behavior of assign_pallet_series_on_already_used_pallets 
        in stock.move.line but operates within the wizard context.
        """
        for record in self:
            if not record.result_package_id:
                # Pallet cleared — try to restore original, or flag for NEW
                series, needs_new = record._resolve_series_for_unique_line()
                record.pallet_series_id = series
                record.needs_new_pallet_series = needs_new
                record.pending_resync_pallet_id = False
                record.pending_resync_old_series = False
                record.pending_resync_new_series = False
                
                # Restore original location (skip if current is an aisle and original has children)
                if record.original_location_dest_id:
                    if not (record.location_dest_id.x_studio_is_an_aisle and record.original_location_dest_id.child_ids):
                        record.location_dest_id = record.original_location_dest_id
                continue
            
            sync_vals = record._sync_pallet_series_and_location(record.result_package_id.id)
            if sync_vals:
                old_series = record.pallet_series_id
                new_series = sync_vals['pallet_series_id']
                # If series will change (recycled), defer to JS confirmation
                if old_series and new_series and old_series != new_series:
                    pending_pallet = record.result_package_id
                    # Revert pallet selection — don't apply yet
                    record.result_package_id = record._origin.result_package_id if record._origin else False
                    record.pending_resync_pallet_id = pending_pallet
                    record.pending_resync_old_series = old_series
                    record.pending_resync_new_series = new_series
                else:
                    # Same series or no old series — apply directly
                    record.pallet_series_id = new_series
                    record.needs_new_pallet_series = False
                    record.location_dest_id = sync_vals['location_dest_id']
                    record.pending_resync_pallet_id = False
                    record.pending_resync_old_series = False
                    record.pending_resync_new_series = False
            else:
                # No match anywhere — this pallet is unique
                # Try to restore original, or flag for NEW
                series, needs_new = record._resolve_series_for_unique_line()
                record.pallet_series_id = series
                record.needs_new_pallet_series = needs_new
                record.pending_resync_pallet_id = False
                record.pending_resync_old_series = False
                record.pending_resync_new_series = False
                
                # Restore original location (skip if current is an aisle and original has children)
                if record.original_location_dest_id:
                    if not (record.location_dest_id.x_studio_is_an_aisle and record.original_location_dest_id.child_ids):
                        record.location_dest_id = record.original_location_dest_id

    def action_apply_resync(self, pallet_id):
        """Called from JS when user confirms the re-sync dialog.
        
        Args:
            pallet_id: ID of the pallet to apply (passed from JS since
                       onchange values aren't persisted to DB).
        """
        self.ensure_one()
        if not pallet_id:
            return
        # First set the pallet so sibling detection works
        super(FastEncodeRRWizardLine, self).write({
            'result_package_id': pallet_id,
            'pending_resync_pallet_id': False,
            'pending_resync_old_series': False,
            'pending_resync_new_series': False,
        })
        # Now sync series and location from sibling/existing line
        sync_vals = self._sync_pallet_series_and_location(pallet_id)
        if sync_vals:
            sync_vals['needs_new_pallet_series'] = False
            super(FastEncodeRRWizardLine, self).write(sync_vals)

    def action_cancel_resync(self):
        """Called from JS when user declines the re-sync dialog."""
        for record in self:
            super(FastEncodeRRWizardLine, record).write({
                'pending_resync_pallet_id': False,
                'pending_resync_old_series': False,
                'pending_resync_new_series': False,
            })

    def write(self, vals):
        """Override write to handle multi-edit sync (onchange is bypassed during multi-edit)."""
        # Capture old pallet/series before super changes them
        old_vals_by_id = {}
        if 'result_package_id' in vals:
            for record in self:
                old_vals_by_id[record.id] = {
                    'result_package_id': record.result_package_id.id if record.result_package_id else False,
                    'pallet_series_id': record.pallet_series_id,
                }

        res = super().write(vals)
        
        if 'result_package_id' in vals:
            new_pallet_id = vals.get('result_package_id')
            
            if not new_pallet_id:
                # Pallet cleared — use _resolve which checks:
                # 1. Is original claimed by another pallet group? → needs_new
                # 2. Is original == pre_wizard (still ours in DB)? → restore directly
                # 3. Is original in the unused pool? → restore directly
                # 4. Otherwise consumed → needs_new
                for record in self:
                    series, needs_new = record._resolve_series_for_unique_line()
                    update_vals = {
                        'pallet_series_id': series,
                        'needs_new_pallet_series': needs_new,
                    }
                    # Skip restore if current is an aisle and original has children
                    if record.original_location_dest_id:
                        if not (record.location_dest_id.x_studio_is_an_aisle and record.original_location_dest_id.child_ids):
                            update_vals['location_dest_id'] = record.original_location_dest_id.id
                    super(FastEncodeRRWizardLine, record).write(update_vals)
            
            elif len(self) > 1:
                # Multi-edit: determine the winning series UPFRONT before per-record mutations
                any_record = self[0]
                
                # 1. Check for existing move line (outside wizard) already using this pallet
                # Exclude ALL wizard lines' ML IDs — wizard state takes priority over DB
                all_wizard_ml_ids = any_record.wizard_id.line_ids.mapped('stock_move_line')
                existing_move_line = self.env['stock.move.line'].search([
                    ('picking_id', '=', any_record.transfer_id),
                    ('result_package_id', '=', new_pallet_id),
                    ('x_studio_pallet_series_id', '!=', False),
                    ('id', 'not in', all_wizard_ml_ids),
                ], limit=1)

                # Determine sync series from existing move line or sibling
                sync_series = None
                sync_location = None
                if existing_move_line:
                    sync_series = existing_move_line.x_studio_pallet_series_id
                    sync_location = existing_move_line.location_dest_id.id if existing_move_line.location_dest_id else False
                else:
                    sibling = any_record.wizard_id.line_ids.filtered(
                        lambda l: l.result_package_id.id == new_pallet_id
                                  and l.id not in self.ids
                                  and l.pallet_series_id
                    )
                    if sibling:
                        sync_series = sibling[0].pallet_series_id
                        sync_location = sibling[0].location_dest_id.id if sibling[0].location_dest_id else False

                if sync_series:
                    # Check if any line would have its series changed (re-sync)
                    needs_confirm = any(
                        old_vals_by_id.get(r.id, {}).get('pallet_series_id')
                        and old_vals_by_id[r.id]['pallet_series_id'] != sync_series
                        for r in self
                    )
                    if needs_confirm:
                        # Defer to JS confirmation — revert all lines
                        first_old = old_vals_by_id.get(self[0].id, {}).get('pallet_series_id', '?')
                        for record in self:
                            old = old_vals_by_id.get(record.id, {})
                            super(FastEncodeRRWizardLine, record).write({
                                'result_package_id': old.get('result_package_id', False),
                                'pending_resync_pallet_id': new_pallet_id,
                                'pending_resync_old_series': old.get('pallet_series_id', '?'),
                                'pending_resync_new_series': sync_series,
                            })
                    else:
                        sync_vals = {
                            'pallet_series_id': sync_series,
                            'needs_new_pallet_series': False,
                            'location_dest_id': sync_location,
                        }
                        for record in self:
                            super(FastEncodeRRWizardLine, record).write(sync_vals)
                else:
                    # No external match — pick the lowest original_pallet_series_id as winner
                    sorted_lines = sorted(self, key=lambda l: l.original_pallet_series_id or l.pallet_series_id or '')
                    winner = sorted_lines[0]
                    
                    series, needs_new = winner._resolve_series_for_unique_line()
                    
                    winning_vals = {
                        'pallet_series_id': series,
                        'needs_new_pallet_series': needs_new,
                    }
                    for record in self:
                        record_vals = dict(winning_vals)
                        if winner.original_location_dest_id:
                            if not (record.location_dest_id.x_studio_is_an_aisle and winner.original_location_dest_id.child_ids):
                                record_vals['location_dest_id'] = winner.original_location_dest_id.id
                        super(FastEncodeRRWizardLine, record).write(record_vals)
            
            else:
                # Single edit — check for re-sync scenario
                for record in self:
                    old = old_vals_by_id.get(record.id, {})
                    sync_vals = record._sync_pallet_series_and_location(new_pallet_id)
                    if sync_vals:
                        old_series = old.get('pallet_series_id', '')
                        new_series = sync_vals.get('pallet_series_id')
                        old_pallet = old.get('result_package_id', False)
                        if old_series and new_series and old_series != new_series:
                            # Re-sync detected — defer to JS confirmation
                            super(FastEncodeRRWizardLine, record).write({
                                'result_package_id': old_pallet,
                                'pending_resync_pallet_id': new_pallet_id,
                                'pending_resync_old_series': old_series,
                                'pending_resync_new_series': new_series,
                            })
                        else:
                            sync_vals['needs_new_pallet_series'] = False
                            super(FastEncodeRRWizardLine, record).write(sync_vals)
                    else:
                        # No match — this pallet is unique
                        series, needs_new = record._resolve_series_for_unique_line()
                        update_vals = {
                            'pallet_series_id': series,
                            'needs_new_pallet_series': needs_new,
                        }
                        if record.original_location_dest_id:
                            if not (record.location_dest_id.x_studio_is_an_aisle and record.original_location_dest_id.child_ids):
                                update_vals['location_dest_id'] = record.original_location_dest_id.id
                        super(FastEncodeRRWizardLine, record).write(update_vals)
        
        return res