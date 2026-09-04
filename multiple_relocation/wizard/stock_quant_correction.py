# models/stock_quant_correction_wizard.py

from odoo.exceptions import UserError
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape
from datetime import datetime
import json
import logging
_logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Writing a correction back onto the receiving document
#
# A correction fixes the QUANT, but the pallet line on the RR that received
# that pallet -- the "Pallet Breakdown" the encoders read and print -- kept
# whatever was typed at receiving, so a corrected pallet still showed the
# wrong weight/quantity/date there forever (COMP-2026-00055).
#
# These are the fields an applied correction now also writes onto that line.
# Keys are the quant's field names, values the move line's field of the same
# meaning (the two models name Remarks differently).
VIFEL_BREAKDOWN_SYNC_FIELDS = {
    'quantity': 'quantity',
    'x_studio_2nd_uom': 'x_studio_2nd_uom',
    'x_studio_total_units': 'x_studio_total_units',
    'x_studio_quantity_uom': 'x_studio_quantity_uom',
    'x_studio_min_quantity_uom': 'x_studio_min_quantity_uom',
    'x_studio_production_date': 'x_studio_production_date',
    'x_studio_expiration_date': 'x_studio_expiration_date',
    'x_studio_container_number': 'x_studio_container_number',
    'x_studio_remarks': 'vifel_remarks',
}

# Deliberately NOT in the map above:
#   package_id / bf_pallet_char -- pallet IDENTITY. The Pallet Kilos Record
#     counts pallets off those two columns and the correction already posts
#     its own pallet leg (_package_change_pallet_delta); rewriting them on
#     the RR would make the same pallet move twice in the ledger, and the
#     pallet-number reuse guard reads the document lines as history.
#   owner_id / location_id -- they decide WHICH PKR partition a line belongs
#     to, so changing them on the receipt would move the receipt itself.
#   product_id / lot_id -- already carried onto the document line by the
#     product branch of _apply_changes below.
#
# Three of the synced fields (quantity, 2nd UOM, total units) are quantities
# the Pallet Kilos Record sums off the document in _populate_operations_data,
# so once the document line carries the corrected figure they must NOT also
# be posted into the adjustment bucket -- see _update_pallet_kilos_record.


class StockQuantCorrectionWizard(models.TransientModel):
    _name = 'stock.quant.correction.wizard'
    _description = 'Stock Quant Correction Wizard'

    line_ids = fields.One2many(
        'stock.quant.correction.line', 'wizard_id', string='Quant Corrections')
    reason_for_adjustment = fields.Char(
        string="Reason for Adjustment", required=True)
    skip_approval = fields.Boolean(
        string="Apply Immediately (Skip Approval)",
        default=False,
        help="If checked, changes will be applied immediately without approval workflow. Only available for Stock Managers."
    )
    is_blast_freeze = fields.Boolean(
        string="Is Blast Freeze",
        help="True when all selected quants are blast-freeze pallets (identified by BF Pallet #, no pallet series / package). Drives which columns the wizard shows."
    )
    psi_cascade_notice = fields.Text(
        string="Pallet Series Group Notice",
        compute='_compute_psi_cascade_notice',
        help="Live warning shown when a Pallet # change affects a pallet "
             "series shared by other quants: those siblings automatically "
             "follow to the same Pallet # on confirm. Blank for blast-freeze "
             "adjustments (no pallet series)."
    )

    @api.model
    def _pallet_label(self, quant):
        """Human-facing identity of a quant regardless of pallet type.

        Regular pallets are identified by their pallet series ID (PSI); blast-freeze
        pallets have no PSI/package and are identified by the free-text bf_pallet_char.
        Falls back to the quant id so user-facing messages never crash on blank values.
        """
        if quant.location_is_bf:
            return quant.bf_pallet_char or f"BF Quant #{quant.id}"
        return quant.x_studio_pallet_series_id or f"Quant #{quant.id}"

    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        quant_ids = self.env.context.get('active_ids', [])
        quants = self.env['stock.quant'].browse(quant_ids)

        # Block mixing blast-freeze and regular pallets in a single correction.
        # They use different identity models (PSI/package vs bf_pallet_char) and the
        # wizard shows a different column set for each, so they must be adjusted apart.
        bf_quants = quants.filtered(lambda q: q.location_is_bf)
        if bf_quants and (quants - bf_quants):
            raise UserError(_(
                "You selected both Blast Freeze pallets and regular pallets.\n\n"
                "Please adjust Blast Freeze pallets separately from regular "
                "(pallet-series) pallets."))
        is_bf = bool(bf_quants)
        res['is_blast_freeze'] = is_bf

        # Check 1: Reserved quantities
        reserved_quants = quants.filtered(lambda q: q.reserved_quantity > 0)
        if reserved_quants:
            raise UserError(_("Cannot modify Pallet details with reserved quantities. "
                              "\nPlease unreserve the following Pallets first:\n• %s") %
                            '\n• '.join(self._pallet_label(q) for q in reserved_quants))

        # Check 2: Active pending adjustment requests.
        # Regular pallets are matched by pallet series (PSI) across requests; blast-freeze
        # pallets have no PSI, so they are matched by lot_id (unique per quant in this DB).
        if is_bf:
            lot_ids = quants.mapped('lot_id').ids
            pending_lines = self.env['stock.quant.adjustment.line'].search([
                ('quant_id.lot_id', 'in', lot_ids),
                ('line_state', 'in', ['pending', 'draft']),
                ('request_id.state', 'in', ['draft', 'pending', 'partial'])
            ]) if lot_ids else self.env['stock.quant.adjustment.line']
        else:
            pallet_series_ids = quants.mapped('x_studio_pallet_series_id')
            pending_lines = self.env['stock.quant.adjustment.line'].search([
                ('quant_id.x_studio_pallet_series_id', 'in', pallet_series_ids),
                ('line_state', 'in', ['pending', 'draft']),
                ('request_id.state', 'in', ['draft', 'pending', 'partial'])
            ])

        if pending_lines:
            # Group by pallet label for a clear error message
            pallets_with_requests = {}
            for line in pending_lines:
                label = self._pallet_label(line.quant_id)
                request_name = line.request_id.name

                if label not in pallets_with_requests:
                    pallets_with_requests[label] = []
                if request_name not in pallets_with_requests[label]:
                    pallets_with_requests[label].append(request_name)

            # Build error message
            error_lines = []
            for label, request_names in pallets_with_requests.items():
                requests_str = ', '.join(request_names)
                error_lines.append(f"• {label} (Request: {requests_str})")

            raise UserError(_(
                "Cannot modify Pallet details with active pending adjustment requests.\n"
                "The following Pallets have pending adjustments:\n\n%s\n\n"
                "Please wait for approval or cancel the existing requests first."
            ) % '\n'.join(error_lines))

        line_vals = [self._correction_line_vals(quant) for quant in quants]

        res['line_ids'] = [(0, 0, vals) for vals in line_vals]

        is_manager = self.env.user.has_group('stock.group_stock_manager')
        if not is_manager:
            res['skip_approval'] = False

        return res

    @api.model
    def _correction_line_vals(self, quant):
        """Wizard-line values mirroring the quant's current state (the wizard
        opens with zero changes; user edits against these are what
        _get_changes later detects)."""
        return {
            'quant_id': quant.id,
            'package_id': quant.package_id.id,
            'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
            'bf_pallet_char': quant.bf_pallet_char,
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
            'x_studio_remarks': quant.x_studio_remarks,
            'x_studio_building_dropped': quant.x_studio_building_dropped,
            'quantity': quant.quantity,
            'lot_id': quant.lot_id.id,
            'owner_id': quant.owner_id.id,
            'x_studio_return_count': quant.x_studio_return_count,
        }

    def _psi_cascade_plan(self):
        """Group-move plan enforcing pallet-series integrity.

        A pallet series (PSI) identifies ONE physical pallet, so when a
        line changes its Pallet # (package) every other stocked quant
        sharing that owner + PSI must follow to the same package —
        otherwise the series ends up split across two pallet numbers.

        Returns one plan dict per affected PSI:
          psi / new_package    the series and its target pallet
          moving_lines         wizard lines the user explicitly changed
          lines_to_sync        sibling lines already in the wizard whose
                               Pallet # will be auto-retargeted
          quants_to_add        stocked sibling quants NOT in the wizard,
                               to be auto-added as package-change lines
        Raises UserError when one series is given two different targets.
        Blast-freeze wizards return [] — BF pallets have no PSI.
        """
        self.ensure_one()
        if self.is_blast_freeze:
            return []

        plans = {}
        for line in self.line_ids:
            quant = line.quant_id
            if not quant:
                continue
            psi = quant.x_studio_pallet_series_id
            new_pkg = line.package_id
            old_pkg_id = quant.package_id.id if quant.package_id else False
            if (not psi or not quant.owner_id or not new_pkg
                    or new_pkg.id == old_pkg_id):
                continue
            key = (quant.owner_id.id, psi)
            plan = plans.get(key)
            if plan and plan['new_package'] != new_pkg:
                raise UserError(_(
                    "Pallet series %(psi)s is being moved to two different "
                    "Pallet #s (%(pkg_a)s and %(pkg_b)s).\n\n"
                    "A pallet series identifies one physical pallet and must "
                    "always move as one group — set the same target Pallet # "
                    "on all of its lines.",
                    psi=psi, pkg_a=plan['new_package'].name,
                    pkg_b=new_pkg.name))
            if not plan:
                plan = plans[key] = {
                    'owner_id': quant.owner_id.id,
                    'psi': psi,
                    'new_package': new_pkg,
                    'moving_lines': self.env['stock.quant.correction.line'],
                    'lines_to_sync': self.env['stock.quant.correction.line'],
                    'quants_to_add': self.env['stock.quant'],
                }
            plan['moving_lines'] |= line

        if not plans:
            return []

        wizard_quant_ids = self.line_ids.mapped('quant_id').ids
        Quant = self.env['stock.quant']
        for plan in plans.values():
            # sibling lines already in the wizard, still pointing elsewhere
            # (contradictory explicit targets were already caught above)
            for line in self.line_ids - plan['moving_lines']:
                quant = line.quant_id
                if (quant and quant.owner_id.id == plan['owner_id']
                        and quant.x_studio_pallet_series_id == plan['psi']
                        and (line.package_id.id if line.package_id else False)
                        != plan['new_package'].id):
                    plan['lines_to_sync'] |= line
            # stocked siblings not in the wizard at all ('|' leaf: Odoo's
            # '!=' excludes NULL packages, but a released same-PSI quant
            # still belongs to the group)
            plan['quants_to_add'] = Quant.search([
                ('owner_id', '=', plan['owner_id']),
                ('x_studio_pallet_series_id', '=', plan['psi']),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
                ('id', 'not in', wizard_quant_ids),
                '|', ('package_id', '=', False),
                     ('package_id', '!=', plan['new_package'].id),
            ])
        return list(plans.values())

    @api.depends('line_ids.package_id', 'line_ids.quant_id',
                 'is_blast_freeze')
    def _compute_psi_cascade_notice(self):
        for wizard in self:
            try:
                plans = wizard._psi_cascade_plan()
            except UserError as err:
                wizard.psi_cascade_notice = str(err.args[0]) if err.args else str(err)
                continue
            notes = []
            for plan in plans:
                extra = len(plan['quants_to_add']) + len(plan['lines_to_sync'])
                if not extra:
                    continue
                notes.append(_(
                    "Series %(psi)s → Pallet %(pkg)s: %(extra)d other pallet "
                    "quant(s) share this series and will AUTOMATICALLY follow "
                    "to the same Pallet # on confirm (%(added)d auto-included "
                    "in this adjustment, %(synced)d retargeted in the list "
                    "below). A pallet series always moves as one group.",
                    psi=plan['psi'], pkg=plan['new_package'].name,
                    extra=extra, added=len(plan['quants_to_add']),
                    synced=len(plan['lines_to_sync'])))
            wizard.psi_cascade_notice = '\n'.join(notes) if notes else False

    def _expand_psi_package_cascade(self):
        """Apply the PSI group-move plan at confirm time: retarget sibling
        lines already in the wizard and auto-add the missing sibling quants
        as package-change-only lines, so both the approval request and the
        immediate flow always carry the WHOLE series."""
        self.ensure_one()
        plans = self._psi_cascade_plan()   # raises on contradictory targets
        Line = self.env['stock.quant.correction.line']
        added = Line
        for plan in plans:
            reserved = plan['quants_to_add'].filtered(
                lambda q: q.reserved_quantity > 0)
            if reserved:
                raise UserError(_(
                    "Cannot move pallet series %(psi)s to Pallet %(pkg)s.\n\n"
                    "The series must move as one group, but the following "
                    "sibling stock is reserved (typically in an active "
                    "Picklist) and cannot be adjusted:\n• %(pallets)s\n\n"
                    "Please unreserve it first, then retry.",
                    psi=plan['psi'], pkg=plan['new_package'].name,
                    pallets='\n• '.join(
                        '%s (%s)' % (self._pallet_label(q),
                                     q.location_id.complete_name)
                        for q in reserved)))
            if plan['lines_to_sync']:
                plan['lines_to_sync'].write(
                    {'package_id': plan['new_package'].id})
            for quant in plan['quants_to_add']:
                vals = self._correction_line_vals(quant)
                vals.update({
                    'wizard_id': self.id,
                    'package_id': plan['new_package'].id,
                })
                added |= Line.create(vals)
            if plan['quants_to_add'] or plan['lines_to_sync']:
                _logger.info(
                    "PSI cascade on %s: series %s -> pallet %s (%d line(s) "
                    "auto-added, %d retargeted)", self.id, plan['psi'],
                    plan['new_package'].name, len(plan['quants_to_add']),
                    len(plan['lines_to_sync']))
        if added:
            self.invalidate_recordset(['line_ids'])
        return added

    def action_confirm_corrections(self):
        """Main action: Either create approval request OR apply directly"""
        self.ensure_one()

        if self.skip_approval and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(
                _("Only Stock Managers can skip the approval workflow."))

        # PSI integrity: a pallet series moves as one group — pull the
        # sibling quants of any repackaged series into this correction.
        self._expand_psi_package_cascade()

        if self.skip_approval:
            return self._apply_corrections_immediately()
        else:
            return self._create_adjustment_request()

    def _create_adjustment_request(self):
        """Create an adjustment request with all lines for approval workflow"""
        self.ensure_one()

        lines_with_changes = self.line_ids.filtered(lambda l: l._get_changes())
        if not lines_with_changes:
            raise UserError(
                _("No changes detected. Please modify at least one field."))

        restricted_pallets = {}
        for line in lines_with_changes:
            changes = line._get_changes()
            if changes and 'product_id' in changes and line.quant_id.x_studio_return_count > 0:
                label = self._pallet_label(line.quant_id)
                if label not in restricted_pallets:
                    restricted_pallets[label] = []
                restricted_pallets[label].append(
                    line.quant_id.x_studio_record_reference or f"Quant {line.quant_id.id}")

        if restricted_pallets:
            error_msg = "You cannot change product of Pallets already with return count history:\n\n"
            for label, pallet_refs in restricted_pallets.items():
                error_msg += f"Pallet: {label}\n"
            raise UserError(error_msg)

        request_vals = {
            'reason_for_adjustment': self.reason_for_adjustment,
            'requested_by': self.env.user.id,
            'requested_date': fields.Datetime.now(),
            'is_blast_freeze': self.is_blast_freeze,
        }

        request = self.env['stock.quant.adjustment.request'].create(
            request_vals)

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
            'bf_pallet_char': quant.bf_pallet_char,
        }

        line_vals = {
            'request_id': request.id,
            'quant_id': quant.id,
            'quant_snapshot': json.dumps(snapshot_data, sort_keys=True),
            'line_state': 'draft',
            'is_blast_freeze': quant.location_is_bf,
            'old_bf_pallet_char': quant.bf_pallet_char,
            'new_bf_pallet_char': wizard_line.bf_pallet_char,
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
            'old_x_studio_container_number': quant.x_studio_container_number,
            'old_x_studio_remarks': quant.x_studio_remarks,
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
            'new_x_studio_container_number': wizard_line.x_studio_container_number,
            'new_x_studio_remarks': wizard_line.x_studio_remarks,
            'display_pallet_series': quant.x_studio_pallet_series_id or '',
            'display_location': quant.location_id.complete_name or '',
        }

        return self.env['stock.quant.adjustment.line'].create(line_vals)

    def _apply_corrections_immediately(self):
        """OLD BEHAVIOR: Apply corrections immediately (when skip_approval is checked)"""
        adjustment_form_series = self.env['ir.sequence'].search(
            [('code', '=', 'adjustment.form.series')], limit=1)
        batch_number = adjustment_form_series.next_by_id()

        restricted_pallets = {}
        for line in self.line_ids:
            changes = line._get_changes()
            if changes and 'product_id' in changes and line.quant_id.x_studio_return_count > 0:
                label = self._pallet_label(line.quant_id)
                if label not in restricted_pallets:
                    restricted_pallets[label] = []
                restricted_pallets[label].append(
                    line.quant_id.x_studio_record_reference or f"Quant {line.quant_id.id}")

        if restricted_pallets:
            error_msg = "You cannot change product of Pallets already with return count history:\n\n"
            for label, pallet_refs in restricted_pallets.items():
                error_msg += f"Pallet: {label}\n"
            raise UserError(error_msg)

        # Even skip-approval corrections leave the SAME persistent audit
        # trail as the approval flow: one request + one approved line per
        # change, each linked to the PKR row it was posted against — so
        # EVERY correction (quantity, pallet #, product, owner, ...) is
        # referenced on the Pallet Kilos Record.
        request = self.env['stock.quant.adjustment.request'].create({
            'reason_for_adjustment': (self.reason_for_adjustment or
                                      'Correction') + ' (applied immediately)',
            'requested_by': self.env.user.id,
            'requested_date': fields.Datetime.now(),
            'is_blast_freeze': self.is_blast_freeze,
            'batch_number': batch_number,
        })

        for line in self.line_ids:
            changes = line._get_changes()
            if changes:
                # snapshot BEFORE applying: the audit line stores old values
                adj_line = self._create_adjustment_line(request, line)

                original_state = line._capture_original_state()

                if 'quantity' in changes:
                    self._handle_quantity_adjustment(
                        line, changes['quantity'][0], changes['quantity'][1], batch_number)

                line._apply_changes(changes)

                non_quantity_changes = {
                    k: v for k, v in changes.items() if k != 'quantity'}
                if non_quantity_changes:
                    self._create_correction_move(
                        line, non_quantity_changes, original_state, batch_number, line.quant_id.x_studio_record_reference)

                pallet_record = self._update_pallet_kilos_record(
                    line, changes, batch_number)

                adj_line.write({
                    'line_state': 'approved',
                    'approved_by': self.env.user.id,
                    'approved_date': fields.Datetime.now(),
                    'pallet_kilos_record_id': (pallet_record.id
                                               if pallet_record else False),
                })
                adj_line._vifel_stamp_applied_to_document(
                    line, pallet_record)

                self._release_pallet_if_emptied(line, changes)

                # dead quant (all zeros): remove it right away instead of
                # leaving it to float until the next zero-quant sweep
                self._gc_quant_if_emptied(line.quant_id)

        if not request.line_ids:
            request.unlink()

        return {'type': 'ir.actions.act_window_close'}

    def _handle_quantity_adjustment(self, line, old_quantity, new_quantity, batch_number):
        """Handle quantity adjustments with proper inventory moves"""
        quant = line.quant_id
        quantity_diff = new_quantity - old_quantity

        inventory_location = self.env.ref(
            'stock.location_inventory', raise_if_not_found=False)
        if not inventory_location:
            inventory_location = self.env['stock.location'].search(
                [('usage', '=', 'inventory')], limit=1)
            if not inventory_location:
                raise UserError(
                    _("Inventory location not found. Please configure inventory adjustments."))

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
            'bf_pallet_char': quant.bf_pallet_char,
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
            # Named differently on the two models (quant: x_studio_remarks,
            # move line: vifel_remarks), which is exactly why the dynamic
            # x_studio_ loop in _create_correction_move cannot pick it up.
            'vifel_remarks': quant.x_studio_remarks,
            **self._vifel_correction_line_extra_vals(quant),
        }

        self.env['stock.move.line'].sudo().create(move_line_vals)

    def _vifel_correction_line_extra_vals(self, quant):
        """Hook: extra move-line vals for a correction history line, read off
        the quant being corrected.

        Empty in core. An optional add-on returns the fields it owns, so the
        adjustment audit trail is as complete as the receiving line was. Core
        must not name an add-on's fields (see the plug-and-play suite), hence a
        hook rather than more entries in the dicts above.
        """
        return {}

    def _release_pallet_if_emptied(self, line, changes):
        """Free the package of a pallet that this adjustment emptied.

        Called LAST (after the correction move and the PKR posting) so the
        correction move still records the pallet via result_package_id and the
        pallet leg in _calculate_adjustment_values still sees the package.
        """
        if self._is_pallet_emptied_by_adjustment(line, changes):
            quant = line.quant_id
            pallet_name = quant.package_id.name
            quant.sudo().write({'package_id': False})
            _logger.info(
                "Correction emptied pallet %s (quant %s): package released "
                "and -1 pallet adjustment posted.", pallet_name, quant.id)

    def _create_correction_move(self, line, changes, original_state, batch_number, picking_id):
        """Create stock move to track the correction in history"""
        quant = line.quant_id

        inventory_location = self.env.ref(
            'stock.location_inventory', raise_if_not_found=False)
        if not inventory_location:
            inventory_location = self.env['stock.location'].search(
                [('usage', '=', 'inventory')], limit=1)
            if not inventory_location:
                raise UserError(
                    _("Inventory location not found. Please configure inventory adjustments."))

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
            # NOTE: source here is the Inventory virtual location, which never
            # physically holds the pallet. Carrying a source package_id makes Odoo
            # register a 0-qty package quant at that virtual location (the empty
            # records seen in the Quants view). Leave it False -- mirrors how the
            # KG/quantity path behaves (no package at the inventory side). The
            # package is still preserved for audit/history/snapshots via
            # result_package_id below (stock_quant_history reads result_package_id).
            'package_id': False,
            'result_package_id': quant.package_id.id if quant.package_id else False,
            'reference': self._format_changes_reference(changes, original_state) + (
                ' | Pallet %s released (adjusted to 0)' % quant.package_id.name
                if self._is_pallet_emptied_by_adjustment(line, changes) else ''),
            'x_studio_reason_for_adjustment': self.reason_for_adjustment,
            'is_quant_detail_adjusted': True,
            'owner_id': quant.owner_id.id if quant.owner_id else False,
            'state': 'done',
            'adjustment_batch_number': batch_number,
            'adjustment_reference_id': quant.x_studio_record_reference.id if quant.x_studio_record_reference else False,
            'x_studio_pallet_series_id': quant.x_studio_pallet_series_id,
            'bf_pallet_char': quant.bf_pallet_char,
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
            # See the note in _handle_quantity_adjustment: the name differs on
            # the two models, so the loop below cannot carry it.
            'vifel_remarks': quant.x_studio_remarks,
            **self._vifel_correction_line_extra_vals(quant),
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
                old_pkg = self.env['stock.quant.package'].browse(
                    old_val) if old_val else False
                new_pkg = self.env['stock.quant.package'].browse(
                    new_val) if new_val else False
                old_display = old_pkg.name if old_pkg else 'None'
                new_display = new_pkg.name if new_pkg else 'None'

            elif field == 'x_studio_quantity_uom':
                old_uom = self.env['uom.uom'].browse(
                    old_val) if old_val else False
                new_uom = self.env['uom.uom'].browse(
                    new_val) if new_val else False
                old_display = old_uom.name if old_uom else 'None'
                new_display = new_uom.name if new_uom else 'None'

            elif field == 'product_id':
                old_display = original_state.get('product_name', 'Unknown')
                new_display = original_state.get(
                    'new_product_name', str(new_val))

            else:
                # fallback to generic formatter
                old_display = self._format_value_for_display(old_val)
                new_display = self._format_value_for_display(new_val)

            field_label = self._get_field_label(field)
            change_list.append(
                f"[{field_label}: {old_display} → {new_display}]")

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

        PKR = self.env['pallet_kilos_record_model.pallet_kilos_record_model']

        if quant.original_record_reference:
            pallet_record = PKR.search([
                ('effective_document', '=', quant.original_record_reference.id)
            ], limit=1)
            if not pallet_record:
                _logger.warning(
                    f"No pallet kilos record found for effective_document "
                    f"{quant.original_record_reference.id}, falling back to oldest in partition")
        else:
            pallet_record = None

        if not pallet_record:
            if not quant.owner_id:
                _logger.warning(
                    f"Quant {quant.id} has no original_record_reference and no owner_id, "
                    f"skipping pallet kilos update")
                return
            # Fallback: post the adjustment to the OPENING-BALANCE record of
            # the quant's own (owner, warehouse, blast-freeze) partition —
            # the row with no stock.picking reference. Quants without a
            # record reference are almost always opening-balance/import
            # stock, and the PKR re-sync anchors its residuals on the same
            # row, so corrections and explanations stay together. Falls back
            # to the oldest row when no opening-balance row exists.
            fallback_domain = [('owner_id', '=', quant.owner_id.id)]
            if quant.location_id.warehouse_id:
                fallback_domain.append(
                    ('warehouse', '=', quant.location_id.warehouse_id.id))
            fallback_domain.append(
                ('is_blast_freezer', '=', bool(getattr(quant, 'location_is_bf', False))))
            pallet_record = PKR.search(
                fallback_domain + [('effective_document', '=', False)],
                order='start_time asc, id asc', limit=1) or PKR.search(
                fallback_domain, order='start_time asc, id asc', limit=1)
            if not pallet_record:
                _logger.warning(
                    f"No pallet kilos record found for owner {quant.owner_id.name} "
                    f"(quant {quant.id}) in its warehouse/BF partition, "
                    f"skipping pallet kilos update")
                return
            _logger.info(
                f"Quant {quant.id} has no original_record_reference; "
                f"using oldest pallet kilos record {pallet_record.id} in the quant's "
                f"partition for owner {quant.owner_id.name}"
            )

        adjustment_values = self._calculate_adjustment_values(line, changes)

        if not adjustment_values:
            return pallet_record

        update_vals = {}

        # Where the quantity legs go depends on whether the correction was
        # written back onto this row's own document. If it was, the row's
        # RECEIVED figures are what changed -- the ledger reads them straight
        # off those document lines -- so the delta belongs there and posting
        # it into the adjustment bucket as well would count it twice. Only
        # this row's own document qualifies; a correction written onto some
        # other RR keeps the old adjustment-bucket behaviour.
        synced_line = line.vifel_synced_line_id
        posts_to_received = bool(synced_line) and \
            synced_line.picking_id == pallet_record.effective_document
        leg_to_field = {
            'kilos': ('kilos_received', 'adjustment_kilos'),
            'packaging': ('packaging_received', 'adjustment_packaging'),
            'units': ('units_received', 'adjustment_heads'),
        }
        for leg, (received_field, adjustment_field) in leg_to_field.items():
            if leg not in adjustment_values:
                continue
            target = received_field if posts_to_received else adjustment_field
            update_vals[target] = (
                pallet_record[target] or 0) + adjustment_values[leg]

        if 'pallets' in adjustment_values:
            update_vals['adjustment_pallets'] = (
                pallet_record.adjustment_pallets or 0) + adjustment_values['pallets']

        if update_vals:
            pallet_record.write(update_vals)
            # explain a pallet-count change right on the PKR row, in the
            # same HTML explanation block the re-sync maintains
            pallet_delta = adjustment_values.get('pallets')
            if pallet_delta:
                if pallet_delta < 0 and self._is_pallet_emptied_by_adjustment(line, changes):
                    why = 'adjusted to 0 quantity — the pallet left without a WR'
                elif pallet_delta > 0:
                    why = ('pallet split: stock was moved onto a new pallet '
                           'number by this correction, creating a pallet no '
                           'RR ever counted in')
                else:
                    why = ('pallet merge/removal: this correction emptied '
                           'the pallet into another one, removing a pallet '
                           'no WR ever counted out')
                entry = (
                    '<p><b>%+g pallet(s)</b> — batch %s, PSI %s: %s</p>'
                    % (pallet_delta,
                       html_escape(str(batch_number or '')),
                       html_escape(str(self._pallet_label(quant))),
                       html_escape(why)))
                pallet_record.write({
                    'adjustment_reason_html':
                        (pallet_record.adjustment_reason_html or '') + entry})
            if posts_to_received:
                # a received figure moving AFTER validation is surprising on
                # its own, so say on the row why it did
                moved = ' / '.join(
                    '%+g %s' % (adjustment_values[leg], label)
                    for leg, label in (('kilos', 'kg'), ('packaging', 'pkg'),
                                       ('units', 'pcs'))
                    if leg in adjustment_values)
                pallet_record.write({
                    'adjustment_reason_html':
                        (pallet_record.adjustment_reason_html or '')
                        + ('<p><b>%s</b> — batch %s, PSI %s: correction '
                           'written back onto %s, so the received figures '
                           'follow the document instead of being posted as '
                           'an adjustment.</p>'
                           % (html_escape(moved),
                              html_escape(str(batch_number or '')),
                              html_escape(str(self._pallet_label(quant))),
                              html_escape(synced_line.picking_id.name or '')))})
            pallet_record._recalculate_running_balances(
                pallet_record.warehouse.id,
                pallet_record.is_blast_freezer,
                pallet_record.start_time
            )
            _logger.info(
                f"Updated pallet kilos record {pallet_record.id} with adjustments: {update_vals}")
        return pallet_record

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

        # Pallet leg: an adjustment that EMPTIES a regular pallet (KG and
        # packaging both end at 0) counts the pallet out of the ledger.
        # The picking-based tally can never see this exit (no WR is created),
        # which was proven to cause pallet-balance drift (e.g. NB 5817).
        # Guards: fires only when this adjustment did the emptying (old had
        # stock), only for regular pallets (a package, not BF), never twice
        # (re-adjusting an already-empty quant has old values of 0).
        if self._is_pallet_emptied_by_adjustment(line, changes):
            adjustments['pallets'] = -1

        # Pallet split/merge leg: a "Pallet #: A -> B" change either CREATES
        # a physical pallet (split: the source pallet keeps stock and the
        # destination was empty => +1), REMOVES one (merge: the source is
        # emptied into an already-stocked destination => -1), or is a plain
        # renumber/transfer between two live pallets (net 0). Without this,
        # split-off pallets get counted -1 by their eventual WR while their
        # birth was never counted (+2 drift proven on Mommy Loida NP 2134).
        split_delta = self._package_change_pallet_delta(line, changes)
        if split_delta:
            adjustments['pallets'] = (
                adjustments.get('pallets', 0) + split_delta)

        return adjustments

    def _package_change_pallet_delta(self, line, changes):
        """Pallet-count effect of a package change, owner-scoped, evaluated
        AFTER _apply_changes (the quant already sits on the new package)."""
        quant = line.quant_id
        if ('package_id' not in changes or line.is_blast_freeze
                or not quant or not quant.owner_id):
            return 0
        old_id, new_id = changes['package_id']
        if not old_id or not new_id or old_id == new_id:
            return 0
        Quant = self.env['stock.quant']
        source_has_stock = bool(Quant.search_count([
            ('package_id', '=', old_id), ('quantity', '>', 0),
            ('owner_id', '=', quant.owner_id.id),
            ('location_id.usage', '=', 'internal')]))
        dest_other_stock = bool(Quant.search_count([
            ('package_id', '=', new_id), ('quantity', '>', 0),
            ('owner_id', '=', quant.owner_id.id),
            ('location_id.usage', '=', 'internal'),
            ('id', '!=', quant.id)]))
        if source_has_stock and not dest_other_stock:
            return 1    # split: new pallet born without a receiving document
        if not source_has_stock and dest_other_stock:
            return -1   # merge: a counted pallet vanished without a WR
        return 0        # renumber or transfer between two live pallets

    def _gc_quant_if_emptied(self, quant):
        """Immediately delete a quant the adjustment fully emptied (KG,
        packaging and packs all zero, nothing reserved) instead of leaving
        the dead record to float until the next opportunistic core sweep
        (stock.quant._unlink_zero_quants, which runs after validations).

        Safe by construction: the persistent audit line's quant_id is
        ON DELETE SET NULL (trail survives, display fields are stored
        chars), the transient wizard line cascades away, and the pallet
        release + PKR posting have already run by the time this is called.
        Stale inventory-count leftovers (inventory_quantity / user_id) are
        cleared first — a pending count on a quant the adjustment just
        explicitly zeroed is stale by definition, and it is exactly what
        makes the core GC skip such records forever.
        """
        if not quant or not quant.exists():
            return False
        if (round(quant.quantity or 0, 6) != 0
                or round(quant.reserved_quantity or 0, 6) != 0
                or round(quant.x_studio_2nd_uom or 0, 3) != 0
                or round(quant.x_studio_total_units or 0, 3) != 0):
            return False
        stale_vals = {}
        if quant.inventory_quantity:
            stale_vals['inventory_quantity'] = 0
        if quant.inventory_diff_quantity:
            stale_vals['inventory_diff_quantity'] = 0
        if quant.user_id:
            stale_vals['user_id'] = False
        if stale_vals:
            quant.sudo().write(stale_vals)
        _logger.info(
            "Adjustment emptied quant %s (owner %s, pallet %s) — deleting "
            "immediately instead of awaiting the zero-quant sweep",
            quant.id, quant.owner_id.display_name,
            quant.x_studio_pallet_series_id or quant.bf_pallet_char or '-')
        quant.sudo().unlink()
        return True

    def _is_pallet_emptied_by_adjustment(self, line, changes):
        """True when this adjustment set both KG and packaging to zero on a
        stocked, regular (packaged) pallet. Evaluated AFTER _apply_changes,
        so the quant already carries the final values."""
        quant = line.quant_id
        if not quant or not quant.package_id or line.is_blast_freeze:
            return False
        if 'quantity' not in changes:
            return False
        old_qty, new_qty = changes['quantity']
        if (new_qty or 0) != 0:
            return False
        final_packaging = quant.x_studio_2nd_uom or 0
        if final_packaging != 0:
            return False
        old_packaging = changes.get(
            'x_studio_2nd_uom', (quant.x_studio_2nd_uom, 0))[0] or 0
        return (old_qty or 0) > 0 or old_packaging > 0


class StockQuantCorrectionLine(models.TransientModel):
    _name = 'stock.quant.correction.line'
    _description = 'Stock Quant Correction Line'

    wizard_id = fields.Many2one(
        'stock.quant.correction.wizard', required=True, ondelete='cascade')
    quant_id = fields.Many2one(
        'stock.quant', string='Original Quant', required=True)
    package_id = fields.Many2one('stock.quant.package', string='Pallet #')
    x_studio_pallet_series_id = fields.Char(string='Placeholder')
    is_blast_freeze = fields.Boolean(
        related='quant_id.location_is_bf', string="Is Blast Freeze")
    bf_pallet_char = fields.Char(string="BF Pallet #")
    product_id = fields.Many2one(
        'product.product', string='Product', required=True)
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
    quantity = fields.Float(
        string='Quantity', digits='Product Unit of Measure')
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial', readonly=True)
    x_studio_return_count = fields.Integer(string="Return Count")
    x_studio_container_number = fields.Char(string="Container #")
    # Remarks is correctable here because it is read-only everywhere else once
    # the receipt is validated (the RR column locks at done, the quant lists are
    # read-only), so this is the only sanctioned way to fix one.
    x_studio_remarks = fields.Char(string="Remarks")
    x_studio_building_dropped = fields.Char(string="Building RR")
    display_pallet_series_id = fields.Char(
        string='Pallet Series ID', compute="_compute_display_payllet_series_id", store=True)
    # The receiving-document pallet line this correction was written back
    # onto, set by _apply_changes. Read afterwards by the caller so the same
    # figures are not ALSO posted into the Pallet Kilos Record's adjustment
    # bucket. Empty when no single source line could be identified.
    vifel_synced_line_id = fields.Many2one(
        'stock.move.line', string='Synced Breakdown Line', readonly=True)

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
                raise ValidationError(
                    _("Production date cannot be later than expiration date."))

    def _get_changes(self):
        """Compare current values with original quant and return changes"""
        self.ensure_one()
        quant = self.quant_id

        changes = {}
        field_mapping = {
            'package_id': ('package_id', lambda x: x.id if x else False),
            'x_studio_pallet_series_id': ('x_studio_pallet_series_id', str),
            'bf_pallet_char': ('bf_pallet_char', str),
            'product_id': ('product_id', lambda x: x.id),
            'x_studio_2nd_uom': ('x_studio_2nd_uom', float),
            'x_studio_quantity_uom': ('x_studio_quantity_uom', lambda x: x.id if x else False),
            'x_studio_total_units': ('x_studio_total_units', float),
            'x_studio_min_quantity_uom': ('x_studio_min_quantity_uom', lambda x: x.id if x else False),
            'owner_id': ('owner_id', lambda x: x.id if x else False),
            'quantity': ('quantity', float),
            'x_studio_return_count': ('x_studio_return_count', int),
            'x_studio_production_date': ('x_studio_production_date', str),
            'x_studio_expiration_date': ('x_studio_expiration_date', str),
            'x_studio_container_number': ('x_studio_container_number', str),
            'x_studio_remarks': ('x_studio_remarks', str),
        }

        for wizard_field, (quant_field, converter) in field_mapping.items():
            old_value = getattr(quant, quant_field)
            new_value = getattr(self, wizard_field)

            try:
                old_converted = converter(old_value) if old_value not in [
                    False, None] else old_value
                new_converted = converter(new_value) if new_value not in [
                    False, None] else new_value
            except (ValueError, TypeError):
                old_converted = old_value
                new_converted = new_value

            # Treat blank values uniformly: '' (empty string the web client sends
            # for a cleared Char like Container #), None and False all mean "no
            # value", so they must compare equal and never register a phantom change.
            if old_converted in ('', None):
                old_converted = False
            if new_converted in ('', None):
                new_converted = False

            if old_converted != new_converted:
                changes[quant_field] = (old_converted, new_converted)

        return changes

    def _vifel_breakdown_line(self):
        """The single pallet line on the receiving document that brought this
        quant in -- the row the encoders see in the RR's Pallet Breakdown.

        Must be called BEFORE the quant is written, because the pallet
        identity it matches on (package / BF pallet #) is part of what a
        correction can change. Returns an empty recordset unless exactly one
        line matches: an ambiguous match is never guessed at, the correction
        just leaves the document alone as it always did.
        """
        self.ensure_one()
        MoveLine = self.env['stock.move.line']
        quant = self.quant_id
        picking = quant.original_record_reference or \
            quant.x_studio_record_reference
        if not picking or picking.state != 'done':
            return MoveLine
        if picking.picking_type_id.code != 'incoming':
            return MoveLine
        lines = picking.move_line_ids.filtered(
            lambda ml: ml.state == 'done'
            and ml.product_id == quant.product_id
            and ml.lot_id == quant.lot_id)
        if quant.package_id:
            lines = lines.filtered(
                lambda ml: ml.result_package_id == quant.package_id)
        elif quant.bf_pallet_char:
            lines = lines.filtered(
                lambda ml: ml.bf_pallet_char == quant.bf_pallet_char)
        else:
            # no pallet identity to key on (opening-balance stock): the
            # document cannot be pinpointed, so it is left untouched
            return MoveLine
        return lines if len(lines) == 1 else MoveLine

    def _vifel_is_departure_not_correction(self, changes):
        """True when this correction zeroes a pallet that held stock.

        The warehouse uses adjust-to-0 to record that a pallet LEFT without a
        withdrawal (that is what the -1 pallet leg below is for), NOT to say
        the receipt over-stated what arrived. Rewriting the receipt to 0 in
        that case would deny a delivery that really happened and wipe the
        handling kilos it is billed on, so the document is left alone and the
        departure keeps posting into the adjustment bucket as it always has.

        Evaluated BEFORE the quant is written, so the quant still holds the
        pre-correction values.
        """
        self.ensure_one()
        quant = self.quant_id
        if 'quantity' not in changes:
            return False
        old_qty, new_qty = changes['quantity']
        if (new_qty or 0) != 0:
            return False
        old_packaging, new_packaging = changes.get(
            'x_studio_2nd_uom',
            (quant.x_studio_2nd_uom, quant.x_studio_2nd_uom))
        if (new_packaging or 0) != 0:
            return False
        return (old_qty or 0) > 0 or (old_packaging or 0) > 0

    def _vifel_sync_breakdown_line(self, line, changes):
        """Write the corrected values onto the receiving document's pallet
        line, so the RR's Pallet Breakdown stops showing the value the
        correction replaced."""
        self.ensure_one()
        move_line_vals = {}
        for quant_field, ml_field in VIFEL_BREAKDOWN_SYNC_FIELDS.items():
            if quant_field in changes:
                move_line_vals[ml_field] = changes[quant_field][1]
        if not move_line_vals:
            return self.env['stock.move.line']

        # _write() and not write(): on a DONE line the ORM's write undoes and
        # re-applies the line's quant movement, which would apply this same
        # correction to stock a SECOND time (the quant was just corrected
        # above). The document is being brought into line with stock that is
        # already right, so only the columns are written -- the same reason
        # the product branch below uses _write().
        line.sudo()._write(move_line_vals)
        line.invalidate_recordset(list(move_line_vals))
        # stock.move.quantity is a stored compute over the lines' quantity and
        # _write() does not trigger it; the RR header total and the Deviation
        # Report both read it.
        line.modified(list(move_line_vals))
        self.vifel_synced_line_id = line.id
        _logger.info(
            "Correction on quant %s written back to %s line %s: %s",
            self.quant_id.id, line.picking_id.name, line.id, move_line_vals)
        return line

    def _apply_changes(self, changes):
        """Apply changes to the original quant"""
        self.ensure_one()
        quant = self.quant_id

        # both resolved before the quant moves: the match keys on pallet
        # identity, and the test reads the pre-correction quantities
        breakdown_line = self._vifel_breakdown_line()
        is_departure = self._vifel_is_departure_not_correction(changes)

        update_vals = {}
        for field, (old_val, new_val) in changes.items():
            update_vals[field] = new_val

        if 'product_id' in changes and quant.lot_id:
            new_product_id = update_vals['product_id']
            old_lot = quant.lot_id
            new_lot = self.env['stock.lot'].sudo().create({
                'name': old_lot.name,
                'product_id': new_product_id,
                'company_id': old_lot.company_id.id,
            })
            source_picking = quant.x_studio_record_reference
            if source_picking:
                target_move_lines = source_picking.move_line_ids.filtered(
                    lambda ml: ml.lot_id == old_lot
                    and ml.location_dest_id == quant.location_id
                    and ml.result_package_id == quant.package_id
                )
                if target_move_lines:
                    # _write() bypasses the stock.move.line.write() guard that
                    # blocks product_id changes on done moves, while remaining
                    # within the current transaction (no mid-op commit needed).
                    target_move_lines.sudo()._write({
                        'lot_id': new_lot.id,
                        'product_id': new_product_id,
                    })
                    target_move_lines.invalidate_recordset(
                        ['lot_id', 'product_id'])
            update_vals['lot_id'] = new_lot.id

        if update_vals:
            quant.write(update_vals)

        if breakdown_line and not is_departure:
            self._vifel_sync_breakdown_line(breakdown_line, changes)


# models/stock_quant_adjustment_request.py
# models/stock_quant_adjustment_request.py

_logger = logging.getLogger(__name__)


class StockQuantAdjustmentRequest(models.Model):
    _name = 'stock.quant.adjustment.request'
    _description = 'Stock Quant Adjustment Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Adjustment Number', required=True,
                       copy=False, readonly=True, default='New')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('partial', 'Partially Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True, compute='_compute_state', store=True)

    reason_for_adjustment = fields.Char(
        string='Reason for Adjustment', required=True, tracking=True)
    requested_by = fields.Many2one('res.users', string='Requested By',
                                   default=lambda self: self.env.user, readonly=True, required=True)
    requested_date = fields.Datetime(
        string='Request Date', default=fields.Datetime.now, readonly=True, required=True)
    approved_by = fields.Many2one(
        'res.users', string='Approved/Rejected By', readonly=True, tracking=True)
    approved_date = fields.Datetime(
        string='Approval Date', readonly=True, tracking=True)
    rejection_reason = fields.Text(string='Rejection Reason', tracking=True)
    batch_number = fields.Char(
        string='Batch Number', readonly=True, help='Batch number assigned when approved')
    is_blast_freeze = fields.Boolean(
        string='Is Blast Freeze', readonly=True,
        help='True when this request adjusts blast-freeze pallets (BF Pallet #) instead of pallet-series pallets.')
    line_ids = fields.One2many(
        'stock.quant.adjustment.line', 'request_id', string='Adjustment Lines')
    line_count = fields.Integer(string='Lines', compute='_compute_line_count')
    approved_line_count = fields.Integer(
        string='Approved', compute='_compute_line_count')
    rejected_line_count = fields.Integer(
        string='Rejected', compute='_compute_line_count')
    pending_line_count = fields.Integer(
        string='Pending', compute='_compute_line_count')
    selected_line_count = fields.Integer(
        string='Selected', compute='_compute_line_count')
    has_conflicts = fields.Boolean(
        string='Has Conflicts', compute='_compute_has_conflicts', store=True)
    conflict_count = fields.Integer(
        string='Conflicts', compute='_compute_has_conflicts', store=True)

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
            record.approved_line_count = len(
                record.line_ids.filtered(lambda l: l.line_state == 'approved'))
            record.rejected_line_count = len(
                record.line_ids.filtered(lambda l: l.line_state == 'rejected'))
            record.pending_line_count = len(
                record.line_ids.filtered(lambda l: l.line_state == 'pending'))
            record.selected_line_count = len(
                record.line_ids.filtered(lambda l: l.selected))

    @api.depends('line_ids.conflict_status')
    def _compute_has_conflicts(self):
        for record in self:
            conflicted_lines = record.line_ids.filtered(lambda l: l.conflict_status in [
                                                        'changed', 'reserved', 'deleted'])
            record.has_conflicts = len(conflicted_lines) > 0
            record.conflict_count = len(conflicted_lines)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'stock.quant.adjustment.request') or 'New'
        return super().create(vals)

    def action_submit_for_approval(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(
                _("Cannot submit request without adjustment lines."))

        lines_without_changes = self.line_ids.filtered(
            lambda l: not l.has_changes)
        if lines_without_changes:
            raise UserError(
                _("Some lines have no changes. Please remove them or modify values."))

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
        pending_lines = self.line_ids.filtered(
            lambda l: l.line_state == 'pending' and l.conflict_status == 'ok')
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

    def _psi_group_guard(self, acting_lines, action='approve'):
        """All-or-nothing per pallet series (anti-split guard).

        The wizard cascade guarantees a request carries EVERY quant of a
        pallet series whose Pallet # changes — but an approver acting on a
        SUBSET of those lines would move part of the series and leave the
        rest behind: the same one-series-on-two-pallets split the cascade
        exists to prevent. So package-change lines of one series must be
        approved together, and rejected together. Blocks with an itemized
        message naming the sibling lines that must be included.
        """
        self.ensure_one()
        group_lines = self.line_ids.filtered(
            lambda l: not l.is_blast_freeze and l.display_pallet_series
            and l.new_package_id and l.new_package_id != l.old_package_id)
        problems = []
        for psi in sorted(set(group_lines.mapped('display_pallet_series'))):
            group = group_lines.filtered(
                lambda l: l.display_pallet_series == psi)
            acting = group & acting_lines
            if not acting:
                continue  # this action doesn't touch the series
            left_behind = (group - acting).filtered(
                lambda l: l.line_state == 'pending')
            if action == 'approve':
                # a sibling already rejected/cancelled can never follow the
                # group — approving the rest would split the series for good
                contradicting = (group - acting).filtered(
                    lambda l: l.line_state in ('rejected', 'cancelled'))
            else:
                # rejecting a subset while a sibling was already applied
                # (or stays approvable) splits the series just the same
                contradicting = (group - acting).filtered(
                    lambda l: l.line_state == 'approved')
            if left_behind or contradicting:
                details = []
                for line in (left_behind | contradicting):
                    details.append('%s → %s (%s%s)' % (
                        line.old_package_id.name or _('no pallet'),
                        line.new_package_id.name,
                        dict(line._fields['line_state'].selection).get(
                            line.line_state, line.line_state),
                        _(', conflict: %s') % line.conflict_status
                        if line.conflict_status != 'ok' else ''))
                problems.append('%s:\n  • %s' % (psi, '\n  • '.join(details)))
        if problems:
            raise UserError(_(
                "Pallet series must be %(verb)s as ONE group.\n\n"
                "Your selection covers only part of the Pallet # change for "
                "the series below — acting on a subset would leave one "
                "series split across two pallets. Please include these "
                "sibling line(s) as well (or act on the whole series):\n\n"
                "%(details)s\n\n"
                "Tip: \"Approve All Pending\" always covers whole groups. "
                "A sibling shown with a conflict must be resolved (or the "
                "request cancelled and re-created) before the series can "
                "move.",
                verb=_('approved') if action == 'approve' else _('rejected'),
                details='\n'.join(problems)))

    def action_approve_selected(self):
        """Approve selected lines"""
        self.ensure_one()

        selected_lines = self.line_ids.filtered(
            lambda l: l.selected and l.line_state == 'pending' and l.conflict_status == 'ok')

        if not selected_lines:
            raise UserError(_(
                "No valid lines were selected.\n\n"
                "Please ensure that the lines you are selecting are pending and have no conflicts — "
                "conflicts typically occur when Pallets are reserved in another pending Picklist or have been successfully delivered out."
            ))

        self._psi_group_guard(selected_lines, action='approve')

        if not self.batch_number:
            adjustment_form_series = self.env['ir.sequence'].search(
                [('code', '=', 'adjustment.form.series')], limit=1)
            self.batch_number = adjustment_form_series.next_by_id(
            ) if adjustment_form_series else self.env['ir.sequence'].next_by_code('adjustment.form.series')

        for line in selected_lines:
            line.action_approve_line(
                self.batch_number, self.reason_for_adjustment)

        # Deselect approved lines
        selected_lines.write({'selected': False})

        if not self.approved_by:
            self.write({'approved_by': self.env.user.id,
                       'approved_date': fields.Datetime.now()})

        # Mark approval activities as done
        self._mark_approval_activities_done()

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

        selected_lines = self.line_ids.filtered(
            lambda l: l.selected and l.line_state == 'pending')

        if not selected_lines:
            raise UserError(
                _("No valid lines selected. Please select pending lines."))

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
        pending_lines = self.line_ids.filtered(
            lambda l: l.line_state == 'pending' and l.conflict_status == 'ok')

        if not pending_lines:
            raise UserError(_(
                "There are no pending lines available for approval.\n\n"
                "Please ensure that all conflicts have been resolved — "
                "conflicts typically occur when Pallets are reserved in another pending Picklist  or have been successfully delivered out."
            ))

        # a conflicted sibling silently excluded from pending_lines would
        # otherwise let "approve all" move only part of a series
        self._psi_group_guard(pending_lines, action='approve')

        if not self.batch_number:
            adjustment_form_series = self.env['ir.sequence'].search(
                [('code', '=', 'adjustment.form.series')], limit=1)
            self.batch_number = (
                adjustment_form_series.next_by_id()
                if adjustment_form_series
                else self.env['ir.sequence'].next_by_code('adjustment.form.series')
            )

        for line in pending_lines:
            line.action_approve_line(
                self.batch_number, self.reason_for_adjustment)

        if not self.approved_by:
            self.write({
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now()
            })

        # Mark approval activities as done
        self._mark_approval_activities_done()

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
            raise UserError(
                _("Only draft, pending or partial requests can be cancelled."))
        if self.state in ['pending', 'partial'] and self.requested_by != self.env.user:
            raise UserError(
                _("Only the requester can cancel a pending request."))
        self.line_ids.filtered(lambda l: l.line_state != 'approved').write(
            {'line_state': 'cancelled'})
        return True

    def action_set_to_draft(self):
        self.ensure_one()
        if self.state != 'cancelled':
            raise UserError(
                _("Only cancelled requests can be reset to draft."))
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

    def _get_adjustment_approvers(self):
        """Users who approve adjustment requests: the members of the
        Adjustment Approvers group. Falls back to the first Stock Manager
        (the closest thing to the old behavior) when the group is missing
        or empty, so submission never goes unnotified."""
        group = self.env.ref(
            'multiple_relocation.group_adjustment_approver',
            raise_if_not_found=False)
        approvers = group.users.filtered('active') if group else self.env['res.users']
        if not approvers:
            legacy = self.env.ref(
                'stock.group_stock_manager', raise_if_not_found=False)
            approvers = legacy.users.filtered('active')[:1] if legacy else self.env['res.users']
        return approvers or self.env.user

    def _notify_approvers(self):
        """Schedule an approval to-do for EVERY adjustment approver (the
        old code notified a single arbitrary Stock Manager)."""
        note = _('Request %s submitted by %s requires approval.\nReason: %s\nLines: %s') % (
            self.name, self.requested_by.name,
            self.reason_for_adjustment, self.line_count)
        for user in self._get_adjustment_approvers():
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=_('Stock Adjustment Approval Required'),
                note=note,
            )

    def _mark_approval_activities_done(self):
        """Mark all pending approval activities as done."""
        activities = self.env['mail.activity'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
        ])
        if activities:
            activities.action_done()

    def action_print_move_lines(self):
        """Print the Product Moves report for all done stock.move.line records matching this request's batch number."""
        self.ensure_one()
        if not self.batch_number:
            raise UserError(
                _("No batch number has been assigned to this request yet."))

        move_lines = self.env['stock.move.line'].search([
            ('state', '=', 'done'),
            ('adjustment_batch_number', '=', self.batch_number),
        ])

        if not move_lines:
            raise UserError(
                _("No completed move lines found for batch number %s.") % self.batch_number)

        report = self.env.ref(
            'studio_customization.product_moves_stock__a6544825-9fe6-4d28-abca-85579916c823')
        return report.report_action(move_lines)


class StockQuantAdjustmentLine(models.Model):
    _name = 'stock.quant.adjustment.line'
    _description = 'Stock Quant Adjustment Line'
    _order = 'id'

    request_id = fields.Many2one('stock.quant.adjustment.request',
                                 string='Adjustment Request', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Select', default=False,
                              help='Select this line for batch approval/rejection')
    line_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Line Status', default='draft', required=True, tracking=True)

    rejection_reason = fields.Text(string='Rejection Reason')
    # Set when applying this line also rewrote the pallet line on the
    # receiving document. Its quantity deltas then live in that document's
    # own received figures, so the Pallet Kilos Record re-sync must leave
    # them out when it rebuilds the adjustment buckets from these lines --
    # otherwise the re-sync would add the same kilos back a second time.
    # False on every line approved before this behaviour existed, so old
    # requests keep re-syncing exactly as they always did.
    applied_to_document = fields.Boolean(
        string='Written Back to Document', readonly=True, copy=False,
        help="The corrected values were written onto the receiving "
             "document's pallet line, so this line's quantity change is "
             "already counted there and is not posted as an adjustment.")
    applied_document_id = fields.Many2one(
        'stock.picking', string='Corrected Document', readonly=True,
        copy=False, ondelete='set null')
    approved_by = fields.Many2one(
        'res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approved Date', readonly=True)
    # PKR row this adjustment was posted to (set on approval; re-linked by
    # the PKR "Re-sync Pallet Counts" action). The approved lines shown on
    # the PKR form ARE the adjustment audit trail — no shadow log model.
    pallet_kilos_record_id = fields.Many2one(
        'pallet_kilos_record_model.pallet_kilos_record_model',
        string='Pallet Kilos Record', index=True, copy=False, readonly=True)
    reason_for_adjustment = fields.Char(
        related='request_id.reason_for_adjustment',
        string='Reason', readonly=True)
    correction_move_reference = fields.Text(
        string='Stock Move Reference',
        compute='_compute_correction_move_reference',
        help='Reference of the CORRECTION stock move line(s) created when '
             'this adjustment was applied (found via the batch number).')

    def _compute_correction_move_reference(self):
        MoveLine = self.env['stock.move.line']
        for line in self:
            refs = []
            batch = line.request_id.batch_number
            if batch and line.line_state == 'approved':
                dom = [('adjustment_batch_number', '=', batch),
                       ('state', '=', 'done')]
                pkgs = [p.id for p in (line.old_package_id,
                                       line.new_package_id) if p]
                if pkgs:
                    dom += ['|', ('package_id', 'in', pkgs),
                            ('result_package_id', 'in', pkgs)]
                elif line.display_pallet_series:
                    dom.append(('x_studio_pallet_series_id', '=',
                                line.display_pallet_series))
                elif line.old_bf_pallet_char:
                    dom.append(('bf_pallet_char', '=',
                                line.old_bf_pallet_char))
                for ml in MoveLine.search(dom, limit=5):
                    if ml.reference and ml.reference not in refs:
                        refs.append(ml.reference)
            line.correction_move_reference = '\n'.join(refs) or False
    quant_id = fields.Many2one('stock.quant', string='Pallet Quant Details')
    quant_snapshot = fields.Text(string='Quant Snapshot', readonly=True,
                                 help='JSON snapshot of quant state when request was created')
    conflict_status = fields.Selection([
        ('ok', 'OK'),
        ('changed', 'Pallet Changed'),
        ('reserved', 'Pallet Reserved'),
        ('deleted', 'Pallet Deleted / Delivered')
    ], string='Conflict Status', default='ok', compute='_compute_conflict_status', store=True)

    has_changes = fields.Boolean(
        string='Has Changes', compute='_compute_has_changes', store=True)
    display_pallet_series = fields.Char(
        string='Pallet Series', readonly=True)
    display_location = fields.Char(
        string='Location', readonly=True)
    is_blast_freeze = fields.Boolean(
        string='Is Blast Freeze', readonly=True)

    # OLD VALUES
    old_package_id = fields.Many2one(
        'stock.quant.package', string='Old Pallet #', readonly=True)
    old_product_id = fields.Many2one(
        'product.product', string='Old Product', readonly=True)
    old_quantity = fields.Float(
        string='Old Quantity', readonly=True, digits='Product Unit of Measure')
    old_lot_id = fields.Many2one('stock.lot', string='Old Lot', readonly=True)
    old_owner_id = fields.Many2one(
        'res.partner', string='Old Owner', readonly=True)
    old_x_studio_production_date = fields.Date(
        string='Old Production Date', readonly=True)
    old_x_studio_expiration_date = fields.Date(
        string='Old Expiration Date', readonly=True)
    old_x_studio_2nd_uom = fields.Float(
        string='Old Total Quantity', readonly=True, digits='Product Unit of Measure')
    old_x_studio_total_units = fields.Float(
        string='Old Total Heads', readonly=True, digits='Product Unit of Measure')
    old_x_studio_quantity_uom = fields.Many2one(
        'uom.uom', string='Old Quantity UOM', readonly=True)
    old_x_studio_min_quantity_uom = fields.Many2one(
        'uom.uom', string='Old Heads UOM', readonly=True)
    old_x_studio_container_number = fields.Char(
        string='Old Container #', readonly=True)
    old_x_studio_remarks = fields.Char(
        string='Old Remarks', readonly=True)
    old_bf_pallet_char = fields.Char(
        string='Old BF Pallet #', readonly=True)

    # NEW VALUES
    new_package_id = fields.Many2one(
        'stock.quant.package', string='New Pallet #')
    new_product_id = fields.Many2one('product.product', string='New Product')
    new_quantity = fields.Float(
        string='New Quantity', digits='Product Unit of Measure')
    new_lot_id = fields.Many2one('stock.lot', string='New Lot')
    new_owner_id = fields.Many2one('res.partner', string='New Owner')
    new_x_studio_production_date = fields.Date(string='New Production Date')
    new_x_studio_expiration_date = fields.Date(string='New Expiration Date')
    new_x_studio_2nd_uom = fields.Float(
        string='New Total Quantity', digits='Product Unit of Measure')
    new_x_studio_total_units = fields.Float(
        string='New Total Heads', digits='Product Unit of Measure')
    new_x_studio_quantity_uom = fields.Many2one(
        'uom.uom', string='New Quantity UOM')
    new_x_studio_min_quantity_uom = fields.Many2one(
        'uom.uom', string='New Heads UOM')
    new_x_studio_container_number = fields.Char(string='New Container #')
    new_x_studio_remarks = fields.Char(string='New Remarks')
    new_bf_pallet_char = fields.Char(string='New BF Pallet #')

    changed_fields_display = fields.Html(
        string='Changes', compute='_compute_changed_fields_display')

    @api.depends('old_package_id', 'new_package_id', 'old_product_id', 'new_product_id',
                 'old_quantity', 'new_quantity', 'old_x_studio_2nd_uom', 'new_x_studio_2nd_uom',
                 'old_x_studio_total_units', 'new_x_studio_total_units',
                 'old_x_studio_quantity_uom', 'new_x_studio_quantity_uom',
                 'old_x_studio_min_quantity_uom', 'new_x_studio_min_quantity_uom',
                 'old_owner_id', 'new_owner_id',
                 'old_x_studio_production_date', 'new_x_studio_production_date',
                 'old_x_studio_expiration_date', 'new_x_studio_expiration_date',
                 'old_x_studio_container_number', 'new_x_studio_container_number',
                 'old_x_studio_remarks', 'new_x_studio_remarks',
                 'old_bf_pallet_char', 'new_bf_pallet_char')
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
                'x_studio_production_date': 'Production Date',
                'x_studio_expiration_date': 'Expiration Date',
                'x_studio_container_number': 'Container #',
                'x_studio_remarks': 'Remarks',
                'bf_pallet_char': 'BF Pallet #',
            }

            for field_name, (old_val, new_val) in changes.items():
                label = field_labels.get(
                    field_name, field_name.replace('_', ' ').title())
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

            line.changed_fields_display = ''.join(
                html_parts) if html_parts else '<span class="text-muted">No changes</span>'

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
                            return html_escape(
                                record.display_name or str(value))
                    except:
                        pass
                return html_escape(str(value))

        # Handle float fields with formatting
        if field_name in ['quantity', 'x_studio_2nd_uom', 'x_studio_total_units']:
            try:
                return f'{float(value):,.2f}'
            except:
                return html_escape(str(value))

        # Free text (Remarks, Container #, BF Pallet #) is interpolated straight
        # into the HTML diff below, which renders on the approver's screen, so a
        # value like <img src=x onerror=...> would execute. Escape it here. The
        # "Empty" marker above is deliberate markup and stays unescaped.
        return html_escape(str(value))

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
            'bf_pallet_char': quant.bf_pallet_char,
        }
        return json.dumps(snapshot_data, sort_keys=True)

    def _get_changes(self):
        self.ensure_one()
        changes = {}

        field_mapping = {
            'package_id': ('package_id', lambda x: x.id if x else False),
            'bf_pallet_char': ('bf_pallet_char', str),
            'product_id': ('product_id', lambda x: x.id),
            'quantity': ('quantity', float),
            'owner_id': ('owner_id', lambda x: x.id if x else False),
            'x_studio_2nd_uom': ('x_studio_2nd_uom', float),
            'x_studio_total_units': ('x_studio_total_units', float),
            'x_studio_quantity_uom': ('x_studio_quantity_uom', lambda x: x.id if x else False),
            'x_studio_min_quantity_uom': ('x_studio_min_quantity_uom', lambda x: x.id if x else False),
            'x_studio_production_date': ('x_studio_production_date', str),
            'x_studio_expiration_date': ('x_studio_expiration_date', str),
            'x_studio_container_number': ('x_studio_container_number', str),
            'x_studio_remarks': ('x_studio_remarks', str),
        }

        for base_field, (field_name, converter) in field_mapping.items():
            old_value = getattr(self, f'old_{base_field}')
            new_value = getattr(self, f'new_{base_field}')

            try:
                old_converted = converter(old_value) if old_value not in [
                    False, None] else old_value
                new_converted = converter(new_value) if new_value not in [
                    False, None] else new_value
            except (ValueError, TypeError):
                old_converted = old_value
                new_converted = new_value

            # Treat blank values uniformly: '' (empty string the web client sends
            # for a cleared Char like Container #), None and False all mean "no
            # value", so they must compare equal and never register a phantom change.
            if old_converted in ('', None):
                old_converted = False
            if new_converted in ('', None):
                new_converted = False

            if old_converted != new_converted:
                changes[field_name] = (old_converted, new_converted)

        return changes

    def _check_approver_rights(self):
        """Approval/rejection is reserved for the Adjustment Approvers
        group (legacy supervisor groups keep working so nothing breaks)."""
        user = self.env.user
        if not (user.has_group('multiple_relocation.group_adjustment_approver')
                or user.has_group('multiple_relocation.inventory_super_admin')
                or user.has_group('__custom__.inventory_supervisor')):
            raise UserError(_(
                "Only Adjustment Approvers can approve or reject "
                "adjustment lines."))

    def action_approve_line(self, batch_number, reason):
        self.ensure_one()

        self._check_approver_rights()

        # self._check_quant_conflicts()

        if self.line_state != 'pending':
            raise UserError(_("Only pending lines can be approved."))

        if self.conflict_status != 'ok':
            raise UserError(
                _("Cannot approve line with conflicts: %s") % self.conflict_status)

        self._apply_adjustment(batch_number, reason)

        self.write({
            'line_state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now()
        })

    def action_reject_line(self, rejection_reason):
        self.ensure_one()

        self._check_approver_rights()

        if self.line_state != 'pending':
            raise UserError(_("Only pending lines can be rejected."))

        self.write({
            'line_state': 'rejected',
            'rejection_reason': rejection_reason,
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now()
        })

    def _vifel_stamp_applied_to_document(self, correction_line, pallet_record):
        """Record on the audit line that its figures were written onto the
        receiving document, so the PKR re-sync knows not to post them again.

        Only counts when the corrected document is the one the PKR row is
        built from — that is the row whose received figures absorbed the
        change.
        """
        self.ensure_one()
        synced_line = correction_line.vifel_synced_line_id
        if not synced_line or not pallet_record:
            return
        if synced_line.picking_id != pallet_record.effective_document:
            return
        self.write({
            'applied_to_document': True,
            'applied_document_id': synced_line.picking_id.id,
        })

    def _apply_adjustment(self, batch_number, reason):
        # Same implementation as before - this part doesn't change
        self.ensure_one()

        quant = self.quant_id
        changes = self._get_changes()

        if not changes:
            return

        wizard = self.env['stock.quant.correction.wizard'].create(
            {'reason_for_adjustment': reason})

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
            'bf_pallet_char': self.new_bf_pallet_char if self.new_bf_pallet_char else quant.bf_pallet_char,
            'x_studio_return_count': quant.x_studio_return_count if quant.x_studio_return_count else 0,
        }

        correction_line = self.env['stock.quant.correction.line'].create(
            line_vals)
        original_state = correction_line._capture_original_state()

        if 'quantity' in changes:
            wizard._handle_quantity_adjustment(
                correction_line, changes['quantity'][0], changes['quantity'][1], batch_number)

        correction_line._apply_changes(changes)

        non_quantity_changes = {k: v for k,
                                v in changes.items() if k != 'quantity'}
        if non_quantity_changes:
            wizard._create_correction_move(
                correction_line, non_quantity_changes, original_state, batch_number, quant.x_studio_record_reference)

        pallet_record = wizard._update_pallet_kilos_record(
            correction_line, changes, batch_number)
        if pallet_record:
            # link the approved line to the PKR row it was posted to — the
            # approved lines are the PKR's adjustment audit trail
            self.pallet_kilos_record_id = pallet_record.id

        self._vifel_stamp_applied_to_document(correction_line, pallet_record)

        wizard._release_pallet_if_emptied(correction_line, changes)

        # dead quant (all zeros): remove it right away instead of leaving
        # it to float until the next zero-quant sweep (the audit line's
        # quant_id is ON DELETE SET NULL — the trail survives)
        wizard._gc_quant_if_emptied(quant)


# models/stock_quant_adjustment_reject_wizard.py


class StockQuantAdjustmentRejectWizard(models.TransientModel):
    _name = 'stock.quant.reject.wizard'
    _description = 'Stock Quant Adjustment Reject Wizard'

    request_id = fields.Many2one(
        'stock.quant.adjustment.request', string='Request', required=True, readonly=True)
    line_ids = fields.Many2many(
        'stock.quant.adjustment.line', string='Lines to Reject', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', required=True,
                                   help='Please provide a reason for rejecting these adjustment line(s)')
    line_count = fields.Integer(
        string='Number of Lines', compute='_compute_line_count')

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

        # rejecting part of a series' Pallet # change while the rest stays
        # approvable would split the series exactly like a partial approval
        self.request_id._psi_group_guard(self.line_ids, action='reject')

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


class PalletKilosRecordAdjustmentTrail(models.Model):
    """Expose the approved adjustment-request lines posted to a PKR row as
    its adjustment audit trail (native records, no shadow log model)."""
    _inherit = 'pallet_kilos_record_model.pallet_kilos_record_model'

    adjustment_line_ids = fields.One2many(
        'stock.quant.adjustment.line', 'pallet_kilos_record_id',
        string='Adjustment Lines', readonly=True,
        domain=[('line_state', '=', 'approved')])
