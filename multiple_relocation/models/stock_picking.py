# -*- coding: utf-8 -*-


from ast import literal_eval
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


class picking_type(models.Model):
    _inherit = 'stock.picking.type'

    is_blast_freeze_operation = fields.Boolean(
        string="Is a Blast Freeze Operation?")


class transfer_locations(models.Model):
    _inherit = 'stock.picking'

    is_void_wr = fields.Boolean(string="Is Void WR", default=False, copy=False,
                                help="Marks this WR as auto-created by voiding an RR. Will auto-void after validation.")
    void_source_picking_id = fields.Many2one('stock.picking', string="Void Source Picking",
                                             copy=False, readonly=True, help="The original RR that was voided to create this WR.")
    is_void_return = fields.Boolean(string="Is Void Return", default=False, copy=False,
                                    help="Marks this return RR as auto-created by voiding a WR. Will auto-void after validation.")

    # Void equivalent smart button fields
    void_equivalent_count = fields.Integer(
        string="Void Equivalent Count", compute="_compute_void_equivalent")
    void_equivalent_label = fields.Char(
        string="Void Equivalent Label", compute="_compute_void_equivalent")

    # Non-void return count (excludes returns with return_reason='Void Transfer')
    non_void_return_count = fields.Integer(
        string="Non-Void Returns", compute="_compute_non_void_return_count")

    # Unvalidated void child banner
    has_unvalidated_void_child = fields.Boolean(
        string="Has Unvalidated Void Child",
        compute="_compute_has_unvalidated_void_child",
        store=False,
    )

    next_step_status = fields.Char(
        compute="_compute_next_step_status", default=lambda self: self._default_next_step_status())

    location_id = fields.Many2one(
        'stock.location', "Source Location",
        store=True,  readonly=False,
        check_company=True, required=True, domain="[('id', 'in', allowed_value_ids)]")

    next_operation_source_document = fields.Many2one(
        'stock.picking', compute="_compute_next_operation_source_document")

    def _compute_next_operation_source_document(self):
        for record in self:
            next_picking = self.env['stock.picking'].search([
                ('x_studio_last_operation_source_document', '=', record.id)
            ], limit=1)
            record.next_operation_source_document = next_picking.id if next_picking else False

    def _default_next_step_status(self):
        # Get picking_type_id from context
        picking_type_id = self.env.context.get('default_picking_type_id')

        if picking_type_id:
            # Search for the record
            picking_type = self.env['stock.picking.type'].browse(
                picking_type_id)
            is_blast_freeze, is_receiving = self.operation_type_checker(
                picking_type)

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

            is_blast_freeze, is_receiving = record.operation_type_checker(
                record.picking_type_id)

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
                active_returns = record.return_ids.filtered(
                    lambda r: r.state != 'cancel')
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

    total_quantity = fields.Float(
        string="Total Quantity", compute="_compute_totals", store=True)
    total_weight = fields.Float(
        string="Total Weight (KG)", compute="_compute_totals", store=True, digits='Product Unit of Measure')
    transacted_pallet_count = fields.Integer(
        string="Transacted Pallet Count", compute="_compute_transacted_pallet_count", store=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        related='picking_type_id.warehouse_id', store=True, readonly=True)

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
    allowed_product_ids = fields.Many2many(
        'product.product', compute="_compute_allowed_product_ids", string="Allowed Products")
    allowed_value_ids = fields.Many2many(
        'stock.location', compute="_compute_allowed_value_ids", string="Allowed Locations"
    )

    gentle_reminder = fields.Char(string="Reminder")

    quant_count = fields.Integer(
        string="Quants", compute="_compute_quant_count")

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

    other_reasons = fields.Char(
        string="Specific Reason for Return", readonly=True, copy=False)

    return_id_already_done = fields.Boolean(
        string="Return Already Validated", compute="_compute_return_id_already_validated", store=True)

    @api.depends('return_ids.state', 'return_ids.x_studio_voided')
    def _compute_return_id_already_validated(self):
        for record in self:
            already_done = False
            if record.return_ids:
                for rr_return_id in record.return_ids:
                    if rr_return_id.state == 'done' and not rr_return_id.x_studio_voided:
                        already_done = True
                        break
            record.return_id_already_done = already_done

    show_return_alert = fields.Boolean(
        compute="_compute_show_return_alert",
        store=False
    )

    validated_on = fields.Datetime(
        string="Validated On",
        readonly=True,
        copy=False,
        help="Date and time when this record was validated (UTC)"
    )

    documentation_staff_id = fields.Many2one(
        'res.partner',
        string="Documentation Staff",
        domain="[('category_id.name', 'ilike', 'documentation staff')]",
        copy=False,
        tracking=True,
        help="Documentation staff responsible for processing this picking. Can be set after validation to track who handled the documentation."
    )

    @api.depends("return_ids.state", "return_ids.return_reason")
    def _compute_show_return_alert(self):
        for rec in self:
            # True if at least one return_id is in draft or assigned and is NOT a void transfer
            rec.show_return_alert = any(
                r.state in (
                    "draft", "assigned") and r.return_reason != 'Void Transfer'
                for r in rec.return_ids
            )

    def _compute_void_equivalent(self):
        """Compute the void equivalent record(s) count and label for the smart button."""
        for record in self:
            void_records = self.env['stock.picking']

            if record.is_void_wr:
                # This IS a void WR → parent is the source RR
                if record.void_source_picking_id:
                    void_records = record.void_source_picking_id
                record.void_equivalent_label = "Void Parent Equivalent Record"
            elif record.is_void_return:
                # This IS a void return RR → parent is the WR
                if record.return_id:
                    void_records = record.return_id
                record.void_equivalent_label = "Void Parent Equivalent Record"
            elif record.x_studio_voided:
                is_blast_freeze, is_receiving = record.operation_type_checker(
                    record.picking_type_id)
                if is_receiving:
                    # Voided RR → find the void WR created from it
                    void_records = self.env['stock.picking'].search([
                        ('void_source_picking_id', '=', record.id),
                    ])
                else:
                    # Voided WR → find the void return RR created from it
                    void_records = record.return_ids.filtered(
                        lambda r: r.is_void_return)
                record.void_equivalent_label = "Void Equivalent Record"
            else:
                record.void_equivalent_label = "Void Equivalent Record"

            record.void_equivalent_count = len(void_records)

    def _compute_non_void_return_count(self):
        """Compute the count of returns excluding those with return_reason='Void Transfer'."""
        for record in self:
            non_void_returns = record.return_ids.filtered(
                lambda r: r.return_reason != 'Void Transfer'
            )
            record.non_void_return_count = len(non_void_returns)

    def _compute_has_unvalidated_void_child(self):
        """Check if this voided parent has a void child record that is not yet validated."""
        for record in self:
            if not record.x_studio_voided or record.state != 'done':
                record.has_unvalidated_void_child = False
                continue

            is_blast_freeze, is_receiving = record.operation_type_checker(
                record.picking_type_id)

            if is_receiving:
                # Voided RR/BFRR → check for unvalidated void WR
                void_wr = self.env['stock.picking'].search([
                    ('void_source_picking_id', '=', record.id),
                    ('is_void_wr', '=', True),
                    ('state', 'not in', ['done', 'cancel']),
                ], limit=1)
                record.has_unvalidated_void_child = bool(void_wr)
            else:
                # Voided WR/BFWR → check for unvalidated void return RR
                void_return = record.return_ids.filtered(
                    lambda r: r.is_void_return and r.state not in (
                        'done', 'cancel')
                )
                record.has_unvalidated_void_child = bool(void_return)

    def action_see_void_equivalent(self):
        """Navigate to the void equivalent record(s)."""
        self.ensure_one()
        void_records = self.env['stock.picking']

        if self.is_void_wr:
            # This IS a void WR → navigate to source RR
            if self.void_source_picking_id:
                void_records = self.void_source_picking_id
        elif self.is_void_return:
            # This IS a void return RR → navigate to parent WR
            if self.return_id:
                void_records = self.return_id
        elif self.x_studio_voided:
            is_blast_freeze, is_receiving = self.operation_type_checker(
                self.picking_type_id)
            if is_receiving:
                # Voided RR → find void WR
                void_records = self.env['stock.picking'].search([
                    ('void_source_picking_id', '=', self.id),
                ])
            else:
                # Voided WR → find void return RR
                void_records = self.return_ids.filtered(
                    lambda r: r.is_void_return)

        if len(void_records) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'views': [[False, 'form']],
                'res_id': void_records.id,
            }
        elif len(void_records) > 1:
            return {
                'name': _('Void Equivalent Records'),
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'views': [[False, 'tree'], [False, 'form']],
                'domain': [('id', 'in', void_records.ids)],
            }

    def action_see_returns(self):
        """Override to exclude returns with return_reason='Void Transfer'."""
        self.ensure_one()
        non_void_returns = self.return_ids.filtered(
            lambda r: r.return_reason != 'Void Transfer'
        )
        if len(non_void_returns) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'views': [[False, 'form']],
                'res_id': non_void_returns.id,
            }
        return {
            'name': _('Returns'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'views': [[False, 'tree'], [False, 'form']],
            'domain': [('id', 'in', non_void_returns.ids)],
        }

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

    # @api.constrains('x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time')
    # def _check_date_not_too_old(self):
    #     """
    #     Constraint to ensure truck_time, start_time, and end_time are not older
    #     than the configured maximum days back
    #     """
    #     max_days_back = self._get_max_days_back_config()
    #     cutoff_datetime = datetime.now() - timedelta(days=max_days_back)

    #     for record in self:
    #         # Check truck_time
    #         if record.x_studio_truck_time and record.x_studio_truck_time < cutoff_datetime:
    #             raise ValidationError(
    #                 f"Truck Time cannot be more than {int(max_days_back)} days ago. "
    #                 f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
    #             )

    #         # Check start_time
    #         if record.x_studio_start_time and record.x_studio_start_time < cutoff_datetime:
    #             raise ValidationError(
    #                 f"Start Time cannot be more than {int(max_days_back)} days ago. "
    #                 f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
    #             )

    #         # Check end_time
    #         if record.x_studio_end_time and record.x_studio_end_time < cutoff_datetime:
    #             raise ValidationError(
    #                 f"End Time cannot be more than {int(max_days_back)} days ago. "
    #                 f"The earliest allowed date is {cutoff_datetime.strftime('%m/%d/%Y %H:%M:%S')}"
    #             )

    def operation_type_checker(self, operation_type_record):
        is_receiving = operation_type_record.code == 'incoming'
        return operation_type_record.is_blast_freeze_operation, is_receiving

    @api.depends('picking_type_id')
    def _comupute_vifel_type_of_operation(self):
        for record in self:
            is_blast_freeze, is_receiving = record.operation_type_checker(
                record.picking_type_id)

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

    @api.depends(
        'state',
    )
    def _compute_transacted_pallet_count(self):
        # Count unique pallets transacted on this picking. Only validated
        # ('done') pickings contribute; mirrors the dedupe logic in
        # pallet_kilos_record_model._populate_operations_data.
        for record in self:
            if record.state != 'done':
                record.transacted_pallet_count = 0
                continue

            pallets = set()
            is_bf = record.x_studio_is_a_blast_freezer
            is_outgoing = record.picking_type_id.code == 'outgoing'

            for ml in record.move_line_ids:
                if is_bf:
                    if ml.bf_pallet_char:
                        pallets.add(ml.bf_pallet_char)
                elif is_outgoing:
                    if ml.package_id and ml.reserved_quantity_on_validation == 0:
                        pallets.add(ml.package_id.id)
                else:
                    if ml.result_package_id:
                        pallets.add(ml.result_package_id.id)

            record.transacted_pallet_count = len(pallets)

    def _refresh_pallet_kilos_on_lock(self):
        """Refresh the pallet kilos record when locking/unlocking a done picking.
        Re-syncs start_time, end_time, and all data from the effective document."""
        PalletKilos = self.env['pallet_kilos_record_model.pallet_kilos_record_model']
        pallet_record = PalletKilos.search([
            '|',
            ('record_reference', '=', self.id),
            ('readjustment_document', '=', self.id),
            ('active', '=', True),
        ], limit=1)

        if pallet_record:
            old_start_time = pallet_record.start_time
            # Re-populate all data from effective document
            pallet_record._populate_vehicle_data()
            pallet_record._populate_operations_data()
            pallet_record._populate_returns_data()

            # Recalculate running balances from the earlier of old or new start_time
            new_start_time = pallet_record.start_time
            if old_start_time and new_start_time:
                earliest = min(old_start_time, new_start_time)
            else:
                earliest = new_start_time or old_start_time

            if earliest and pallet_record.warehouse:
                pallet_record._recalculate_running_balances(
                    pallet_record.warehouse.id,
                    pallet_record.is_blast_freezer,
                    earliest,
                )
                _logger.info(
                    "Refreshed pallet kilos record for %s on lock/unlock (start_time: %s -> %s)",
                    self.name, old_start_time, new_start_time,
                )

    def _void_archive_pallet_kilos_record(self, record):
        """Archive the pallet kilos record associated with a picking and recalculate balances."""
        pallet_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
            [('effective_document', '=', record.id), ('active', '=', True)],
            order='create_date desc',
            limit=1
        )

        if pallet_record:
            warehouse_id = pallet_record.warehouse.id
            is_blast_freezer = pallet_record.is_blast_freezer
            start_time = pallet_record.start_time

            if pallet_record.readjustment_document and pallet_record.readjustment_document.id == record.id:
                pallet_record.readjustment_document = False
            pallet_record.active = False

            _logger.info("Deactivated pallet kilos record: %s",
                         pallet_record.effective_document.name)

            previous_record = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search([
                ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', is_blast_freezer),
                ('start_time', '<', start_time),
                ('active', '=', True)
            ], order='start_time desc', limit=1)

            if previous_record:
                recalc_from_time = previous_record.start_time
            else:
                recalc_from_time = None

            pallet_record._recalculate_running_balances(
                warehouse_id,
                is_blast_freezer,
                recalc_from_time
            )

            _logger.info(
                "Voided transfer and archived Pallet Kilos Log: %s", record.name)
        else:
            _logger.warning(
                "No pallet kilos record found for transfer: %s", record.name)

    def _create_void_wr_from_rr(self, record):
        """
        Create an outgoing (WR) picking to reverse the inventory from a voided RR/BFRR.
        Automatically checks out the same stock quants that were received.
        Returns the created WR picking record.
        """
        is_blast_freeze, is_receiving = record.operation_type_checker(
            record.picking_type_id)

        if not is_receiving:
            return False

        # === REUSE EXISTING VOID WR IF AVAILABLE ===
        existing_void_wr = self.env['stock.picking'].search([
            ('void_source_picking_id', '=', record.id),
            ('is_void_wr', '=', True),
            ('state', 'not in', ['done', 'cancel']),
        ], limit=1)

        if existing_void_wr:
            _logger.info("Reusing existing void WR %s for voided RR %s",
                         existing_void_wr.name, record.name)
            # Clear old moves and re-populate from current quants
            existing_void_wr.move_ids_without_package.unlink()
            existing_void_wr.x_studio_voided = False

            # Re-populate stock moves from current quants
            rr_pallet_series_ids = record.move_line_ids.mapped(
                'x_studio_pallet_series_id')
            rr_pallet_series_ids = [p for p in rr_pallet_series_ids if p]
            package_ids = record.move_line_ids.mapped(
                'result_package_id')
            
            if rr_pallet_series_ids:
                child_location_ids = self.env['stock.location'].search([
                    ('id', 'child_of', existing_void_wr.location_id.id)
                ]).ids
                quant_domain = [
                    ('location_id', 'in', child_location_ids),
                    ('x_studio_pallet_series_id', 'in', rr_pallet_series_ids),
                    ('package_id', 'in', package_ids.ids),
                    ('quantity', '!=', 0),
                ]
                if record.partner_id:
                    quant_domain.append(
                        ('owner_id', '=', record.partner_id.id))
                quants_to_checkout = self.env['stock.quant'].search(
                    quant_domain)
                if quants_to_checkout:
                    self._checkout_quants_to_picking(
                        existing_void_wr, quants_to_checkout)
                    _logger.info("Re-checked out %d quants into reused void WR %s",
                                 len(quants_to_checkout), existing_void_wr.name)

            return existing_void_wr
        # === END REUSE ===

        warehouse_id = record.picking_type_id.warehouse_id.id

        # Find the matching outgoing picking type
        outgoing_picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('is_blast_freeze_operation', '=', is_blast_freeze),
            ('warehouse_id', '=', warehouse_id)
        ], limit=1)

        if not outgoing_picking_type:
            raise UserError(
                _("No matching outgoing operation type found for warehouse. Cannot create void WR."))

        # Source = where the stock currently sits after the RR. Walk the RR move
        # lines and use the first building's preset_location we find (same
        # algorithm as the return wizard's _compute_location_and_packages).
        # Fall back to the RR's own destination location, then id 7, if nothing
        # resolves.
        wr_source_location = False
        for ml in record.move_line_ids:
            building = ml.location_dest_id.x_studio_building
            if building and building.x_studio_preset_location:
                wr_source_location = building.x_studio_preset_location.id
                break
        if not wr_source_location:
            wr_source_location = record.location_dest_id.id or 7

        wr_dest_location = 5  # Customer location — semantically correct for outgoing

        # Create the WR picking
        wr_picking = record.copy({
            'picking_type_id': outgoing_picking_type.id,
            'location_id': wr_source_location,
            'location_dest_id': wr_dest_location,
            'x_studio_last_operation_source_document': record.id,
            'state': 'draft',
            'is_void_wr': True,
            'void_source_picking_id': record.id,
            'x_studio_voided': False,
            'x_studio_loading_dock_no': 'N/A',
            'truck_type': record.truck_type,
            'x_studio_trucks_plate_': record.x_studio_trucks_plate_,
            'x_studio_driver': record.x_studio_driver,
            'x_studio_client_reference': record.x_studio_client_reference,
            'x_studio_start_time': record.x_studio_end_time,
            'x_studio_truck_time': record.x_studio_end_time,
            'x_studio_validated_by': False,
            'x_studio_checked_by': False,
            'x_studio_approved_by': False,
            'x_studio_gate_pass': record.x_studio_gate_pass,
            'x_studio_source': 'VOIDED',
            'x_studio_remarks': f'Auto-created from voided {record.name}',
            'x_studio_manual_document_': 'VOIDED',
        })

        # Remove copied moves - we'll create fresh ones from quants
        wr_picking.move_ids_without_package.unlink()

        _logger.info("Created void WR %s from voided RR %s",
                     wr_picking.name, record.name)

        # Find the stock quants that were received by this RR
        # These are quants at the RR's destination location, owned by the same partner,
        # with pallet_series_ids matching the RR's move lines
        rr_pallet_series_ids = record.move_line_ids.mapped(
            'x_studio_pallet_series_id')
        # Filter out empty strings
        rr_pallet_series_ids = [p for p in rr_pallet_series_ids if p]
        package_ids = record.move_line_ids.mapped(
                'result_package_id')
        
        if not rr_pallet_series_ids:
            _logger.warning(
                "No pallet series IDs found on voided RR %s, cannot auto-checkout quants", record.name)
            return wr_picking

        # Get child locations of the RR destination (where goods landed)
        child_location_ids = self.env['stock.location'].search([
            ('id', 'child_of', wr_source_location)
        ]).ids

        # Find quants with matching pallet series in those locations (include negative qty)
        quant_domain = [
            ('location_id', 'in', child_location_ids),
            ('x_studio_pallet_series_id', 'in', rr_pallet_series_ids),
            ('package_id', 'in', package_ids.ids),
            ('quantity', '!=', 0),
        ]

        if record.partner_id:
            quant_domain.append(('owner_id', '=', record.partner_id.id))

        quants_to_checkout = self.env['stock.quant'].search(quant_domain)

        if not quants_to_checkout:
            _logger.warning("No quants found for voided RR %s at location %s",
                            record.name, record.location_dest_id.name)
            return wr_picking

        # Use create_transfer_stock_move logic to checkout quants into the WR
        self._checkout_quants_to_picking(wr_picking, quants_to_checkout)

        _logger.info("Auto-checked out %d quants into void WR %s",
                     len(quants_to_checkout), wr_picking.name)

        return wr_picking

    def _checkout_quants_to_picking(self, picking, quants):
        """
        Checkout stock quants into a picking by creating stock.move and stock.move.line records.
        This replicates the logic from create_transfer_stock_move() on stock.quant.
        """
        StockMove = self.env['stock.move']
        StockMoveLine = self.env['stock.move.line']

        grouped_data = {}

        for quant in quants:
            product = quant.product_id
            prod_id = product.id

            if not quant.quantity:
                continue

            # Merge key matches the pattern used in create_transfer_stock_move
            merge_key = (
                prod_id,
                quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
                quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False
            )

            if merge_key not in grouped_data:
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
                    'picking_type_id': picking.picking_type_id.id,
                }

                grouped_data[merge_key] = {
                    'move_vals': move_vals,
                    'total_qty': 0.0,
                    'quant_ids': [],
                    'move_line_vals': [],
                }

            grouped_data[merge_key]['total_qty'] += abs(quant.quantity)
            grouped_data[merge_key]['quant_ids'].append(quant.id)

            move_line_vals = {
                'move_id': False,  # Updated after move creation
                'picking_id': picking.id,
                'product_id': prod_id,
                'product_uom_id': quant.product_uom_id.id,
                'quantity': abs(quant.quantity),
                'location_id': quant.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'lot_id': quant.lot_id.id if quant.lot_id else False,
                'package_id': quant.package_id.id if quant.package_id else False,
                'result_package_id': False,
                'owner_id': quant.owner_id.id if quant.owner_id else False,
            }
            grouped_data[merge_key]['move_line_vals'].append(move_line_vals)

        # Create moves and move lines
        all_move_lines = []
        for merge_key, data in grouped_data.items():
            data['move_vals']['product_uom_qty'] = data['total_qty']
            move = StockMove.create(data['move_vals'])

            move.write({'quant_ids_picked': [(4, q_id)
                       for q_id in data['quant_ids']]})

            for ml_vals in data['move_line_vals']:
                ml_vals['move_id'] = move.id
            all_move_lines.extend(data['move_line_vals'])

        if all_move_lines:
            StockMoveLine.create(all_move_lines)

    def _create_return_rr_from_wr(self, record):
        """
        Create a return RR from a voided WR by programmatically invoking the
        Return Packages wizard (action_return_packages) with all items selected
        and return reason set to 'Void Transfer'.
        If an existing void return RR already exists (from a previous void), the
        wizard will automatically find it and reuse it via _append_to_existing_return.
        Returns the wizard's action result (navigation to the RR).
        """
        # Verify this is an outgoing operation
        is_blast_freeze, is_receiving = record.operation_type_checker(
            record.picking_type_id)
        if is_receiving:
            _logger.warning(
                "_create_return_rr_from_wr called on incoming operation %s - skipping", record.name)
            return False

        # Check for existing void return RR that can be reused
        existing_void_return = record.return_ids.filtered(
            lambda r: r.is_void_return and r.state not in ('done', 'cancel')
        )
        if existing_void_return:
            _logger.info(
                "Existing void return RR %s found for WR %s — wizard will reuse it via _append_to_existing_return",
                existing_void_return[0].name, record.name
            )

        # Build wizard lines manually (replicating _compute_location_and_packages logic)
        lines = []
        for move_line in record.move_line_ids:
            location_dest_id = False
            pallet_result_id = False
            if not move_line.location_id.x_studio_is_reserved:
                occupying_owners = move_line.location_id.x_studio_occupied_by_1.ids
                package_occupying_owners = (move_line.package_id.quant_ids.mapped(
                    'x_studio_pallet_series_id') if move_line.package_id else [])
                if move_line.owner_id.id in occupying_owners or not move_line.location_id.x_studio_occupied_by_1.ids:
                    location_dest_id = move_line.location_id.id
            else:
                package_occupying_owners = []
            if (move_line.package_id.location_id.id == location_dest_id and move_line.x_studio_pallet_series_id in package_occupying_owners) or not move_line.package_id.location_id.id:
                pallet_result_id = move_line.package_id.id

            if move_line.location_id.x_studio_is_an_aisle:
                location_dest_id = move_line.location_id.id

            # Fallback: if location_dest_id is still blank (source bin is
            # reserved or occupied by a different owner), drop the line into an
            # aisle. Prefer one in the same building so the stock at least
            # lands in the right zone; fall back to any aisle if that fails.
            # Same algorithm as ReturnPackageWizard._compute_location_and_packages.
            if not location_dest_id and move_line.location_id:
                building = move_line.location_id.x_studio_building
                if building:
                    aisle_location = self.env['stock.location'].search([
                        ('x_studio_is_an_aisle', '=', True),
                        ('x_studio_building', '=', building.id),
                    ], limit=1)
                    if aisle_location:
                        location_dest_id = aisle_location.id
                if not location_dest_id:
                    aisle_location = self.env['stock.location'].search([
                        ('x_studio_is_an_aisle', '=', True),
                    ], limit=1)
                    if aisle_location:
                        location_dest_id = aisle_location.id

            lines.append((0, 0, {
                'select_package': True,  # Auto-select all
                'result_package_id': pallet_result_id,
                'location_dest_id': location_dest_id,
                'pallet_series_id': move_line.x_studio_pallet_series_id,
                'bf_pallet_char': move_line.bf_pallet_char,
                'product_id': move_line.product_id.id,
                'expiration_date': move_line.x_studio_expiration_date,
                'x_studio_building_dropped': move_line.x_studio_building_dropped,
                'original_record_reference': move_line.original_record_reference.id if move_line.original_record_reference else False,
                'production_date': move_line.x_studio_production_date,
                'lot_id': move_line.lot_id.id,
                'stock_move_line': move_line.id,
                'return_counter': move_line.x_studio_return_count,
                'container_number': move_line.x_studio_container_number,
                'pack_uom_unit': move_line.x_studio_affected_2nd_uom,
                'min_uom_unit': move_line.x_studio_withdraw_units,
                'quantity': move_line.quantity,
                'pack_uom': move_line.x_studio_quantity_uom_delivery.id if move_line.x_studio_quantity_uom_delivery else False,
                'min_uom': move_line.x_studio_min_quantity_uom.id if move_line.x_studio_min_quantity_uom else False,
                'actual_pack_uom_unit': move_line.x_studio_affected_2nd_uom,
                'actual_min_uom_unit': move_line.x_studio_withdraw_units,
                'actual_quantity': move_line.quantity,
                'location_id': record.location_id.id,
            }))

        # Destination = where the stock should land back. Walk the WR move
        # lines and use the first building's preset_location we find (same
        # algorithm as the return wizard's _compute_location_and_packages).
        # Fall back to the WR's own source location if nothing resolves.
        rr_dest_location = False
        for ml in record.move_line_ids:
            building = ml.location_id.x_studio_building
            if building and building.x_studio_preset_location:
                rr_dest_location = building.x_studio_preset_location.id
                break
        if not rr_dest_location:
            rr_dest_location = record.location_id.id

        # Create the wizard with all lines pre-built and selected
        wizard = self.env['return.package.wizard'].with_context(
            default_picking_id=record.id,
            voided=True,
            default_warehouse_id=record.picking_type_id.warehouse_id.id,
        ).create({
            'picking_id': record.id,
            'return_reason': 'Void Transfer',
            'warehouse_id': record.picking_type_id.warehouse_id.id,
            'location_id': rr_dest_location,
            'select_all': True,
            'lines_computed': True,
            'package_line_ids': lines,
        })

        # Process the return (creates the RR and returns navigation action)
        result = wizard.action_process_return()

        # If a return was created, mark it as a void return so it auto-voids after validation
        if result and result.get('res_id'):
            return_picking = self.env['stock.picking'].browse(result['res_id'])
            return_picking.is_void_return = True
            return_picking.x_studio_manual_document_ = 'VOIDED'
            _logger.info(
                "Marked return RR %s as void_return with VOIDED tag, will auto-void after validation", return_picking.name)

        _logger.info(
            "Created return RR from voided WR %s via Return Packages wizard", record.name)
        return result

    def void_transfer(self):
        """Mark transfer as voided and deactivate the latest associated pallet kilos record.
        For incoming (RR/BFRR) transfers, creates a WR to reverse the inventory.
        For outgoing (WR/BFWR) transfers, creates a return RR to reverse the withdrawal."""
        for record in self:
            if not self.env.user.has_group('__custom__.inventory_supervisor'):
                raise UserError(
                    _("You do not have permission to void transfers."))

            # Determine operation type early for guard rail checks
            is_blast_freeze, is_receiving = record.operation_type_checker(
                record.picking_type_id)

            # === GUARD RAILS ===
            if is_receiving:
                # RR/BFRR Guard Rail: Check if stock quants with pallet series still exist at destination
                pallet_series_ids = record.move_line_ids.mapped(
                    'x_studio_pallet_series_id')
                # Filter out empty strings
                pallet_series_ids = [p for p in pallet_series_ids if p]

                if pallet_series_ids:
                    child_location_ids = self.env['stock.location'].search([
                        ('id', 'child_of', record.location_dest_id.id)
                    ]).ids

                    # Exclude the parent WR if this RR is a return (avoids circular guard rail)
                    excluded_picking_ids = [record.id]
                    if record.return_id:
                        excluded_picking_ids.append(record.return_id.id)

                    missing_pallets = []
                    used_in_wr_pallets = []
                    for pallet_series in pallet_series_ids:
                        quant = self.env['stock.quant'].search([
                            ('x_studio_pallet_series_id', '=', pallet_series),
                            # ('location_id', 'in', child_location_ids),
                            ('quantity', '!=', 0),
                        ], limit=1)
                        if not quant:
                            # Quant is missing - check if it was used in a done WR
                            used_in_wr = self.env['stock.move.line'].search([
                                ('x_studio_pallet_series_id', '=', pallet_series),
                                ('picking_id', 'not in', excluded_picking_ids),
                                ('picking_id.picking_type_id.code', '=', 'outgoing'),
                                ('picking_id.x_studio_voided', '=', False),
                                ('state', '=', 'done'),
                            ], limit=1)
                            if used_in_wr:
                                used_in_wr_pallets.append(
                                    (pallet_series, used_in_wr.picking_id.name))
                            else:
                                missing_pallets.append(pallet_series)

                    if used_in_wr_pallets:
                        details = '\n'.join(
                            [f"  - Pallet {pallet} → used in {wr}" for pallet, wr in used_in_wr_pallets])
                        raise UserError(_(
                            "Cannot void this receiving record.\n\n"
                            "The following pallet(s) have been used in withdrawal record(s) that are still active:\n"
                            "%(details)s\n\n"
                            "Please void those withdrawal record(s) first before voiding this receiving record.",
                            details=details,
                        ))

                    if missing_pallets:
                        raise UserError(_(
                            "Cannot void this receiving record.\n\n"
                            "The following pallet(s) no longer have available stock at the destination location:\n"
                            "%(pallet_names)s\n\n"
                            "This stock may have been moved or consumed. "
                            "Please check and resolve any dependent transactions first.",
                            pallet_names=', '.join(missing_pallets),
                        ))
            else:
                # WR/BFWR: Check if there are completed (non-voided) return pickings
                active_returns = record.return_ids.filtered(
                    lambda r: r.state == 'done' and not r.x_studio_voided
                )
                if active_returns:
                    return_names = ', '.join(active_returns.mapped('name'))
                    raise UserError(_(
                        "Cannot void this withdrawal record.\n\n"
                        "The following return record(s) are still active:\n"
                        "%(return_names)s\n\n"
                        "Please void those return record(s) first before voiding this withdrawal record.",
                        return_names=return_names,
                    ))

                # Check if any of this WR's return RRs are voided and have unvalidated void children
                # e.g., WR → RR (voided) → child void WR (still draft) = block voiding the original WR
                voided_returns = record.return_ids.filtered(
                    lambda r: r.x_studio_voided and r.state == 'done'
                )
                if voided_returns:
                    # Look for unvalidated void WR children of these voided returns
                    unvalidated_void_children = self.env['stock.picking'].search([
                        ('void_source_picking_id', 'in', voided_returns.ids),
                        ('is_void_wr', '=', True),
                        ('state', 'in', ('draft', 'assigned')),
                    ])
                    if unvalidated_void_children:
                        void_names = ', '.join(
                            unvalidated_void_children.mapped('name'))
                        parent_names = ', '.join(
                            unvalidated_void_children.mapped('void_source_picking_id.name'))
                        raise UserError(_(
                            "Cannot void this withdrawal record.\n\n"
                            "The following return(s) have been voided but their void child record(s) are still unvalidated:\n"
                            "%(void_names)s (from voided return %(parent_names)s)\n\n"
                            "Please complete validation of the void child record(s) first.",
                            void_names=void_names,
                            parent_names=parent_names,
                        ))

            # === END GUARD RAILS ===

            record.x_studio_voided = True

            # Archive pallet kilos record and recalculate balances
            record._void_archive_pallet_kilos_record(record)

            if is_receiving:
                # Incoming (RR/BFRR): Create a WR to reverse the received inventory
                void_wr = record._create_void_wr_from_rr(record)

                if void_wr:
                    _logger.info(
                        "Void WR %s created for voided RR %s - navigating user to WR", void_wr.name, record.name)

                    return {
                        'type': 'ir.actions.act_window',
                        'name': 'Void Withdrawal',
                        'res_model': 'stock.picking',
                        'view_mode': 'form',
                        'res_id': void_wr.id,
                        'target': 'current',
                    }
            else:
                # Outgoing (WR/BFWR): Create a return RR via Return Packages wizard
                result = record._create_return_rr_from_wr(record)

                if result:
                    _logger.info(
                        "Return RR created for voided WR %s - navigating user to RR", record.name)
                    return result

            _logger.info("Voided transfer: %s", record.name)

    def void_transfer_simple(self):
        """Simple void: marks as voided and archives PKR only. No next operation created."""
        for record in self:
            if not self.env.user.has_group('__custom__.inventory_supervisor'):
                raise UserError(
                    _("You do not have permission to void transfers."))
            record.x_studio_voided = True
            record._void_archive_pallet_kilos_record(record)
            _logger.info("Simple-voided transfer: %s", record.name)

    def unvoid_transfer(self):
        """Reverse the void operation: unmark transfer as voided and reactivate the associated pallet kilos record."""
        for record in self:
            if not self.env.user.has_group('multiple_relocation.inventory_super_admin'):
                raise UserError(
                    _("You do not have permission to unvoid transfers."))

            # Check if the record is actually voided
            if not record.x_studio_voided:
                _logger.warning(
                    "Transfer %s is not voided, cannot unvoid.", record.name)
                continue

            # If the void created an equivalent Void WR/RR that's already been
            # validated, the void is permanent. Letting an unvoid through here
            # would leave the validated child as an orphan inventory move.
            void_child = self.env['stock.picking'].search([
                ('void_source_picking_id', '=', record.id),
                '|', ('is_void_wr', '=', True), ('is_void_return', '=', True),
            ], limit=1)
            if void_child and void_child.state == 'done':
                raise UserError(_(
                    "Cannot unvoid %(record_name)s: its equivalent void %(kind)s "
                    "%(child_name)s has already been validated. This void is "
                    "permanent. To restore the inventory, please create a new "
                    "transaction instead.",
                    record_name=record.name,
                    kind="WR" if void_child.is_void_wr else "RR",
                    child_name=void_child.name,
                ))

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
                    _logger.info(
                        "Reactivated pallet kilos record with main reference: %s", record.name)

                elif pallet_record.readjustment_document and pallet_record.readjustment_document.id == record.id:
                    # This record was a readjustment - restore the readjustment link
                    pallet_record.active = True
                    # readjustment_document should already be set to record.id
                    _logger.info(
                        "Reactivated pallet kilos record with readjustment reference: %s", record.name)

                else:
                    # Fallback: set as readjustment document and activate
                    pallet_record.readjustment_document = record.id
                    pallet_record.active = True
                    _logger.info(
                        "Set as readjustment document and activated pallet kilos record: %s", record.name)

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

                _logger.info(
                    "Successfully unvoided transfer and restored Pallet Kilos Log: %s", record.name)
            else:
                _logger.error(
                    "No pallet kilos record found for transfer: %s. Cannot complete unvoid operation.", record.name)
                raise UserError(
                    _("No associated pallet kilos record found for transfer %s. Cannot unvoid.") % record.name)

    def button_validate(self):
        """Override button_validate to auto-void WR pickings created from voided RRs after validation."""
        result = super(transfer_locations, self).button_validate()

        # After validation, check if any of these pickings are void WRs or void returns
        for record in self:
            if record.state == 'done':
                # Set validated_on timestamp when record is validated
                if not record.validated_on:
                    record.validated_on = fields.Datetime.now()

                # Auto-void WRs created from voiding RRs
                if record.is_void_wr:
                    _logger.info(
                        "Auto-voiding void WR %s after validation", record.name)
                    record.x_studio_voided = True
                    record._void_archive_pallet_kilos_record(record)
                    _logger.info(
                        "Successfully auto-voided void WR %s", record.name)

                # Auto-void return RRs created from voiding WRs
                elif record.is_void_return:
                    _logger.info(
                        "Auto-voiding void return RR %s after validation", record.name)
                    record.x_studio_voided = True
                    record._void_archive_pallet_kilos_record(record)
                    _logger.info(
                        "Successfully auto-voided void return RR %s", record.name)

        return result
        
    def get_picklist_page_boundaries(self):
        """
        Pre-compute page boundaries for picklist using pixel-based height budgeting.
        Returns list of (start_idx, end_idx) tuples into sorted_move_lines.

        Pixel budget per page:
          Page height:                           1060px
          Header (company/dates/shipping):       ~230px
          Table header row:                       ~40px
          Footer (sigs + dist, no remarks):      ~186px
          ─────────────────────────────────────────────
          Available for item rows:               ~604px
          MAX_PIXEL_HEIGHT (with safety buffer):  590px

        If pages still overflow lower MAX_PIXEL_HEIGHT.
        If there is still too much empty space raise it.
        """
        MAX_PIXEL_HEIGHT = 700

        sorted_lines = list(self.get_picklist_sorted_move_line_ids())
        n = len(sorted_lines)

        if not n:
            return [(0, 0)]

        boundaries = []
        page_start = 0
        px_used = 0
        last_product_id = None
        last_prod_date = None
        last_exp_date = None

        for idx in range(n):
            line = sorted_lines[idx]
            next_line = sorted_lines[idx + 1] if idx + 1 < n else None

            show_product = (
                line.product_id.id != last_product_id
                or line.x_studio_production_date != last_prod_date
                or line.x_studio_expiration_date != last_exp_date
            )

            current_container = line.x_studio_container_number or ''
            next_container = (next_line.x_studio_container_number or '') if next_line else ''
            is_last = next_line is None
            next_move_id = next_line.move_id.id if next_line else None

            container_changed = is_last or bool(
                next_container and current_container and current_container != next_container
            )
            move_changed = is_last or (line.move_id.id != next_move_id)

            row_px = self._picklist_row_pixels(
                line, show_product, current_container,
                container_changed, move_changed, is_last
            )

            # Flush current page if this item would exceed budget
            if px_used + row_px > MAX_PIXEL_HEIGHT and idx > page_start:
                boundaries.append((page_start, idx))
                page_start = idx
                px_used = 0
                last_product_id = None
                last_prod_date = None
                last_exp_date = None
                # Recount for new page — product always shows at top of new page
                row_px = self._picklist_row_pixels(
                    line, True, current_container,
                    container_changed, move_changed, is_last
                )

            px_used += row_px
            last_product_id = line.product_id.id
            last_prod_date = line.x_studio_production_date
            last_exp_date = line.x_studio_expiration_date

        boundaries.append((page_start, n))
        return boundaries

    def _picklist_row_pixels(self, line, show_product, current_container,
                              container_changed, move_changed, is_last):
        """
        Estimate pixel height one move line consumes in the picklist table.

        Pixel breakdown:
          24px  base data row (min-height)
          +15px product name wraps (name > 38 chars in the description column)
          +15px date range line inside td   (if show_product and has dates)
          +15px container line inside td    (if container_changed and has container)
          +30px separate Total Request <tr> (if move_changed and total_request set)
          +12px spacing <tr> between container groups (not on last item)
        """
        px = 24  # base data row

        if show_product:
            # Long product names wrap inside the td, adding an extra line
            product_name = line.product_id.name or ''
            if len(product_name) > 38:
                px += 15  # wrapping line
            if line.x_studio_production_date or line.x_studio_expiration_date:
                px += 15  # date range line
            if container_changed and current_container:
                px += 15  # container shown on first product row
        else:
            if container_changed and current_container:
                px += 15  # container shown on non-product row

        if move_changed and line.move_id.x_studio_total_request:
            px += 30  # separate Total Request <tr>

        if container_changed and current_container and not is_last:
            px += 12  # spacing <tr> between container groups

        return px

    
    def get_grouped_move_lines_for_report(self):
            """
            Preprocess move lines for report rendering.
            Groups lines by item description key and marks which ones should display the description.
    
            Returns:
                tuple: (processed_lines, grand_total_by_uom, grand_packs_by_uom)
                - processed_lines: List of dictionaries with processed move line data
                - grand_total_by_uom: Dictionary with UOM quantity totals for grand total
                - grand_packs_by_uom: Dictionary with UOM packs totals for grand total
    
            total_units field mapping by operation type:
                RR (incoming):          x_studio_total_units
                WR (outgoing) normal:   x_studio_withdraw_units
                WR (outgoing) special:  x_studio_actual_min
            """
            all_move_lines = []
    
            # Collect all move lines
            for move in self.move_ids:
                for line in move.move_line_ids:
                    all_move_lines.append(line)
    
            # Sort by description key (product|container|prod_date|exp_date) first,
            # then by pallet series ID (groups items with same description together)
            def get_sort_key(line):
                product_name = line.product_id.name if line.product_id else ''
                container_number = line.x_studio_container_number or ''
    
                production_date = ''
                if line.x_studio_production_date:
                    production_date = line.x_studio_production_date.strftime('%b%d.%Y').upper()
    
                expiration_date = ''
                if line.x_studio_expiration_date:
                    expiration_date = line.x_studio_expiration_date.strftime('%b%d.%Y').upper()
    
                description_key = f"{product_name}|{container_number}|{production_date}|{expiration_date}"
                pallet_id = line.x_studio_pallet_series_id or ''
    
                return (description_key, pallet_id)
    
            sorted_move_lines = sorted(all_move_lines, key=get_sort_key)
    
            processed_lines = []
            seen_descriptions = set()
            grand_total_by_uom = {}
            grand_packs_by_uom = {}
    
            # Determine operation type and special partner flag once, used for total_units mapping
            is_outgoing = self.picking_type_id.code == 'outgoing'
            is_special = self.partner_id.x_studio_special_no_rr_return_needed
    
            # First pass: determine unique descriptions
            unique_descriptions = set()
            for line in sorted_move_lines:
                move = line
                product_name = line.product_id.name if line.product_id else ''
                container_number = move.x_studio_container_number or ''
    
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
            seen_descriptions_current_page = set()
            items_per_page = 15  # Should match your XML template
    
            for line_index, line in enumerate(sorted_move_lines):
                move = line
    
                product_name = line.product_id.name if line.product_id else ''
                container_number = move.x_studio_container_number or ''
    
                production_date = ''
                if move.x_studio_production_date:
                    production_date = move.x_studio_production_date.strftime('%b%d.%Y').upper()
    
                expiration_date = ''
                if move.x_studio_expiration_date:
                    expiration_date = move.x_studio_expiration_date.strftime('%b%d.%Y').upper()
    
                description_key = f"{product_name}|{container_number}|{production_date}|{expiration_date}"
    
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
    
                is_new_page = line_index > 0 and line_index % items_per_page == 0
    
                if is_new_page:
                    seen_descriptions_current_page = set()
    
                show_description = False
                if description_key not in seen_descriptions_current_page or is_new_page:
                    show_description = True
                    seen_descriptions_current_page.add(description_key)
    
                uom = move.x_studio_quantity_uom.name if move and move.x_studio_quantity_uom else move.x_studio_quantity_uom_delivery.name
                quantity = 0
                weight = 0
    
                if is_special and move.x_studio_affected_2nd_uom:
                    quantity = line.x_studio_actual_packaging
                else:
                    quantity = line.x_studio_2nd_uom or move.x_studio_affected_2nd_uom
    
                if is_special and line.x_studio_actual_kg:
                    weight = line.x_studio_actual_kg
                else:
                    weight = line.quantity or 0
    
                # total_units field mapping based on operation type:
                # RR (incoming):         x_studio_total_units
                # WR (outgoing) normal:  x_studio_withdraw_units
                # WR (outgoing) special: x_studio_actual_min
                if is_outgoing:
                    total_units = float(line.x_studio_actual_min or 0) if is_special else float(line.x_studio_withdraw_units or 0)
                else:
                    total_units = float(line.x_studio_total_units or 0)
    
                # Accumulate grand totals
                if uom:
                    if uom not in grand_total_by_uom:
                        grand_total_by_uom[uom] = 0
                    grand_total_by_uom[uom] += quantity
    
                if uom and total_units:
                    if uom not in grand_packs_by_uom:
                        grand_packs_by_uom[uom] = 0
                    grand_packs_by_uom[uom] += total_units
    
                # Build pallet number with fallback logic
                if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                    pallet_no = f"{line.package_id.name}"
                elif line.picking_id.x_studio_is_a_blast_freezer:
                    pallet_no = line.bf_pallet_char
                else:
                    pallet_no = line.result_package_id.name if line.result_package_id else ''
    
                processed_lines.append({
                    'pallet_no': pallet_no,
                    'item_description': formatted_description,
                    'show_description': show_description,
                    'description_key': description_key,
                    'quantity': quantity,
                    'uom': uom,
                    'weight': weight,
                    'weight_uom': line.product_uom_id.name if line.product_uom_id else '',
                    'total_units': total_units,
                    'original_line': line,
                    'is_new_page': is_new_page
                })
    
            # Add "***Nothing Follows***" as a separate trailing line
            if processed_lines:
                last_line = processed_lines[-1].copy()
                nothing_follows_line = last_line.copy()
                nothing_follows_line['item_description'] = '***Nothing Follows***'
                nothing_follows_line['show_description'] = True
                nothing_follows_line['description_key'] = 'nothing_follows'
                nothing_follows_line['pallet_no'] = ''
                nothing_follows_line['quantity'] = 0
                nothing_follows_line['weight'] = 0
                nothing_follows_line['total_units'] = 0
                nothing_follows_line['uom'] = ''
                nothing_follows_line['weight_uom'] = ''
    
                processed_lines.append(nothing_follows_line)
    
            return processed_lines, grand_total_by_uom, grand_packs_by_uom

    def get_uom_totals_for_page(self, processed_lines, start_idx, end_idx):
        """
        Calculate UOM quantity totals for a specific page range.
 
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
 
        Returns:
            dict: Dictionary with UOM quantity totals for the page
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
        Calculate weight totals by UOM for a specific page range.
 
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
 
        Returns:
            dict: Dictionary with UOM weight totals for the page
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


    def get_packs_totals_for_page(self, processed_lines, start_idx, end_idx):
        """
        Calculate x_studio_total_units (PACKS) totals by UOM for a specific page range.
 
        Args:
            processed_lines: List of processed line data
            start_idx: Start index for page
            end_idx: End index for page
 
        Returns:
            dict: Dictionary with UOM packs totals for the page
        """
        page_packs_by_uom = {}
 
        for line_data in processed_lines[start_idx:end_idx]:
            uom = line_data['uom']
            packs = line_data.get('total_units', 0)
 
            if uom and packs:
                if uom not in page_packs_by_uom:
                    page_packs_by_uom[uom] = 0
                page_packs_by_uom[uom] += packs
 
        return page_packs_by_uom
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
        # Build a map of which line index each pallet first appears at
        first_occurrence = {}
 
        for idx, line_data in enumerate(processed_lines):
            line = line_data['original_line']
            pallet_id = None
 
            if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('package', line.package_id.id)
            elif line.result_package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('result_package', line.result_package_id.id)
            elif line.bf_pallet_char and line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('bf_pallet', line.bf_pallet_char)
 
            if pallet_id and pallet_id not in first_occurrence:
                first_occurrence[pallet_id] = idx
 
        # Count pallets that first appear in this page range
        page_pallet_count = 0
 
        for line_idx in range(start_idx, min(end_idx, len(processed_lines))):
            line_data = processed_lines[line_idx]
            line = line_data['original_line']
            same_quant_stocks_picked = self.env['stock.move.line'].search([
                ('lot_id', '=', line.lot_id.id),
                ('state', '!=', 'done'),
                ('picking_id.id', '!=', line.picking_id.id),
                ('picking_id.picking_type_code', '=', 'outgoing')
            ])
 
            if line.package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('package', line.package_id.id)
                if first_occurrence.get(pallet_id) == line_idx:
                    page_pallet_count += 1 if line.reserved_quantity_on_validation == 0 or not same_quant_stocks_picked else 0
            elif line.result_package_id and not line.picking_id.x_studio_is_a_blast_freezer:
                pallet_id = ('result_package', line.result_package_id.id)
                if first_occurrence.get(pallet_id) == line_idx:
                    page_pallet_count += 1 if line.reserved_quantity_on_validation == 0 or not same_quant_stocks_picked else 0
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
            'heads_demand': 0,
            'heads_actual': 0,
            'heads_uom': 0,
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
                prod_date = move_line.x_studio_production_date if hasattr(
                    move_line, 'x_studio_production_date') else None
                exp_date = move_line.x_studio_expiration_date if hasattr(
                    move_line, 'x_studio_expiration_date') else None
                cont_number = move_line.x_studio_container_number if hasattr(
                    move_line, 'x_studio_container_number') else None

                # Convert dates to string for consistent grouping
                prod_date_str = prod_date.strftime(
                    '%Y-%m-%d') if prod_date else 'No Prod Date'
                exp_date_str = exp_date.strftime(
                    '%Y-%m-%d') if exp_date else 'No Exp Date'

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
                        date_info.append(
                            f"{prod_date.strftime('%b').upper()}.{prod_date.day}.{prod_date.year}")

                    if exp_date:
                        date_info.append(
                            f"- {exp_date.strftime('%b').upper()}.{exp_date.day}.{exp_date.year}")

                    if date_info:
                        if cont_number:
                            grouped_moves[key][
                                'product_name'] = f"{base_name} <br/>{cont_number} <br/>{' '.join(date_info)} "
                        else:
                            grouped_moves[key][
                                'product_name'] = f"{base_name} <br/>{', '.join(date_info)} "
                    else:
                        grouped_moves[key]['product_name'] = base_name

                    grouped_moves[key]['production_date'] = prod_date
                    grouped_moves[key]['expiration_date'] = exp_date
                    grouped_moves[key]['container_number'] = cont_number
                    grouped_moves[key]['uom_name'] = move.x_studio_packaging_unit.name if hasattr(
                        move, 'x_studio_packaging_unit') and move.x_studio_packaging_unit else ''
                    grouped_moves[key]['packaging_unit_name'] = move.x_studio_packaging_unit.name if hasattr(
                        move, 'x_studio_packaging_unit') and move.x_studio_packaging_unit else ''

                # Add move-level quantities (documented/demand) only ONCE per move globally
                # This ensures same product quantities are not duplicated across different date groups
                if move.id not in globally_processed_moves:
                    # grouped_moves[key]['qty_actual'] += move.x_studio_actual_packaging_demand if hasattr(move, 'x_studio_actual_packaging_demand') else 0
                    grouped_moves[key]['qty_demand'] += move.x_studio_demand_packaging if hasattr(
                        move, 'x_studio_demand_packaging') else 0
                    grouped_moves[key]['weight_demand'] += move.product_uom_qty if hasattr(
                        move, 'product_uom_qty') else 0
                    grouped_moves[key]['heads_demand'] += move.x_studio_min_uom if hasattr(
                        move, 'x_studio_min_uom') else 0
                    globally_processed_moves.add(move.id)

                pack_qty = 0
                weight_actual = 0
                qty_actual = 0
                if move_line.x_studio_2nd_uom:
                    pack_qty = move_line.x_studio_2nd_uom
                else:
                    pack_qty = move_line.x_studio_affected_2nd_uom
                    if self.partner_id.x_studio_special_no_rr_return_needed and move_line.x_studio_actual_packaging:
                        pack_qty = move_line.x_studio_actual_packaging

                if hasattr(move_line, 'quantity'):
                    weight_actual = move_line.quantity
                    if self.partner_id.x_studio_special_no_rr_return_needed and move_line.x_studio_actual_kg:
                        weight_actual = move_line.x_studio_actual_kg
                else:
                    weight_actual = 0

                if hasattr(move_line, 'quantity'):
                    qty_actual = move_line.quantity
                    if self.partner_id.x_studio_special_no_rr_return_needed and move_line.x_studio_actual_kg:
                        qty_actual = move_line.x_studio_actual_kg

                else:
                    qty_actual = 0

                # Add move line specific quantities (actual quantities)
                # These are added for each move line since they're line-specific
                grouped_moves[key]['qty_actual'] += qty_actual
                grouped_moves[key]['weight_actual'] += weight_actual
                grouped_moves[key]['packaging_qty'] += pack_qty
                grouped_moves[key]['heads_actual'] += move_line.x_studio_total_units if move_line.x_studio_total_units else move_line.x_studio_withdraw_units

                same_quant_stocks_picked = self.env['stock.move.line'].search([
                    ('lot_id', '=', move_line.lot_id.id),
                    ('state', '!=', 'done'),
                    ('picking_id.id', '!=', move_line.picking_id.id),
                    ('picking_id.picking_type_code', '=', 'outgoing')
                ])
                # Track unique packages for pallet count
                if move_line.package_id and not move_line.picking_id.x_studio_is_a_blast_freezer:
                    grouped_moves[key]['package_ids'].add(
                        move_line.package_id.id)
                    if move_line.package_id.id not in package_ids:
                        package_ids.add(move_line.package_id.id)
                        grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 and not same_quant_stocks_picked else 0

                elif move_line.bf_pallet_char and move_line.picking_id.x_studio_is_a_blast_freezer:

                    grouped_moves[key]['package_ids'].add(
                        move_line.bf_pallet_char)
                    if move_line.bf_pallet_char not in package_ids:
                        package_ids.add(move_line.bf_pallet_char)
                        grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 and not same_quant_stocks_picked else 0

                elif move_line.result_package_id:
                    grouped_moves[key]['package_ids'].add(
                        move_line.result_package_id.id)
                    if move_line.result_package_id.id not in package_ids:
                        package_ids.add(move_line.result_package_id.id)
                        grouped_moves[key]['pallet_count'] += 1 if move_line.reserved_quantity_on_validation == 0 and not same_quant_stocks_picked else 0

        # Convert to list and calculate final pallet counts
        processed_moves = []
        for key, data in grouped_moves.items():
            # Remove set as it's not needed in template
            del data['package_ids']
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
        uom_total_actual_heads = defaultdict(float)
        uom_total_demand_heads = defaultdict(float)

        for move in moves:
            uom = move['uom_name'] or 'Units'
            uom_totals[uom] += move['qty_actual']
            uom_totals_demand[uom] += move['qty_demand']
            uom_totals_actual[uom] += move['packaging_qty']
            uom_demand = move['uom_name'] or 'Units'
            uom_total_actual_kg[uom] += move['qty_actual']
            uom_total_demand_kg[uom] += move['weight_demand']
            uom_total_actual_heads[uom] += move['heads_actual']
            uom_total_demand_heads[uom] += move['heads_demand']

        # Format the grouped quantities and UOMs separately
        qty_parts = []
        uom_parts = []
        qty_demand_parts = []
        qty_actual_parts = []

        kg_demand_parts = []
        kg_actual_parts = []
        heads_demand_parts = []
        heads_actual_parts = []
        uom_digit = 2 if not self.partner_id.x_studio_special_3_digit_decimal_pdf_report else 3

        for uom, qty in uom_totals.items():
            qty_parts.append(f"{qty:,.2f}")
            uom_parts.append(uom)

        for uom, qty in uom_totals_demand.items():
            qty_demand_parts.append(f"{qty:,.2f}")
        for uom, qty in uom_totals_actual.items():
            qty_actual_parts.append(f"{qty:,.2f}")
        for uom, kg in uom_total_actual_kg.items():
            kg_actual_parts.append(f"{kg:,.{uom_digit}f}")
        for uom, kg in uom_total_demand_kg.items():
            kg_demand_parts.append(f"{kg:,.{uom_digit}f}")
        for uom, heads in uom_total_actual_heads.items():
            heads_actual_parts.append(f"{heads:,.2f}")
        for uom, heads in uom_total_demand_heads.items():
            heads_demand_parts.append(f"{heads:,.2f}")

        return {
            'qty_formatted': "<br/>".join(qty_parts) if qty_parts else "0",
            'uom_formatted': "<br/>".join(uom_parts) if uom_parts else "",
            'qty_demand_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.0f}" for part in qty_demand_parts]) if qty_demand_parts else "0.00",
            'qty_actual_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.0f}" for part in qty_actual_parts]) if qty_actual_parts else "0.00",
            'kg_actual_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.{uom_digit}f}" for part in kg_actual_parts]) if kg_actual_parts else "0.00",
            'kg_demand_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.{uom_digit}f}" for part in kg_demand_parts]) if kg_demand_parts else "0.00",
            'heads_actual_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.0f}" for part in heads_actual_parts]) if heads_actual_parts else "0.00",
            'heads_demand_formatted': "<br/>".join([f"{float(str(part).replace(',', '')):,.0f}" for part in heads_demand_parts]) if heads_demand_parts else "0.00"
        }

    def calculate_page_data(self, processed_moves, page_size=9):
        """
        Calculate pagination data for the processed moves
        """
        total_items = len(processed_moves)
        pages_count = (total_items + page_size -
                       1) // page_size if total_items > 0 else 1

        page_data = []
        for page_num in range(pages_count):
            start_idx = page_num * page_size
            end_idx = min(start_idx + page_size, total_items)

            page_moves = processed_moves[start_idx:end_idx]

            # Calculate page totals
            uom_data = self.group_quantities_by_uom(page_moves)
            if not self.partner_id.x_studio_special_no_rr_return_needed:
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
                    'heads_actual': sum(move['heads_actual'] for move in page_moves),
                    'heads_demand': sum(move['heads_demand'] for move in page_moves),
                    'heads_actual_formatted': uom_data['heads_actual_formatted'],
                    'heads_demand_formatted': uom_data['heads_demand_formatted'],
                }
            else:
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
                    'heads_actual': sum(move['heads_actual'] for move in page_moves),
                    'heads_demand': sum(move['heads_demand'] for move in page_moves),
                    'heads_actual_formatted': uom_data['heads_actual_formatted'],
                    'heads_demand_formatted': uom_data['heads_demand_formatted'],
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
            'heads_actual': sum(move['heads_actual'] for move in processed_moves),
            'heads_demand': sum(move['heads_demand'] for move in processed_moves),
            'heads_actual_formatted': grand_uom_data['heads_actual_formatted'],
            'heads_demand_formatted': grand_uom_data['heads_demand_formatted'],
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
    def get_picklist_page_totals_by_uom(self, page_start_index, page_end_index, sorted_move_lines=None):
        """
        Calculate page totals grouped by UOM for picklist
        Returns dictionary with UOM as key and totals as values
        """
        page_totals = {}
    
        # Use sorted_move_lines if provided, otherwise fall back to self.move_line_ids
        lines = sorted_move_lines if sorted_move_lines is not None else self.move_line_ids
    
        for i in range(page_start_index, min(page_end_index, len(lines))):
            move_line = lines[i]
            uom_name = move_line.x_studio_quantity_uom_delivery.name if move_line.x_studio_quantity_uom_delivery else 'Unknown'
            if uom_name not in page_totals:
                page_totals[uom_name] = {
                    'qty': 0,
                    'packs': 0,
                    'kg': 0,
                    'uom': move_line.x_studio_quantity_uom_delivery
                }
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

    # def get_picklist_sorted_move_line_ids(self):
    #     """
    #     Returns move lines sorted by container number to keep the same containers grouped together in the picklist.
    #     Sorting order: product name -> container_number -> pallet_series_id
    #     Returns: Sorted recordset of move.line ordered by container grouping
    #     """
    #     move_lines = self.move_line_ids

    #     # Sort by product name, then container number, then pallet series for deterministic grouping
    #     def get_sort_key(line):
    #         product_name = line.product_id.name if line.product_id else ''
    #         container = line.x_studio_container_number or ''
    #         pallet_id = line.x_studio_pallet_series_id or ''
    #         return (product_name, container, pallet_id)

    #     sorted_lines = sorted(move_lines, key=get_sort_key)
    #     return self.env['stock.move.line'].browse([l.id for l in sorted_lines])

    def get_picklist_sorted_move_line_ids(self):
        """
        Returns move lines sorted by container number to keep the same containers grouped together in the picklist.
        Sorting order: product name -> container_number -> pallet_series_id
        Returns: Sorted recordset of move.line ordered by container grouping
        """
        move_lines = self.move_line_ids

        # Sort by product name → production date → expiration date → container → pallet series
        def get_sort_key(line):
            product_name = line.product_id.name if line.product_id else ''
            prod_date = str(
                line.x_studio_production_date) if line.x_studio_production_date else ''
            exp_date = str(
                line.x_studio_expiration_date) if line.x_studio_expiration_date else ''
            container = line.x_studio_container_number or ''
            pallet_id = line.x_studio_pallet_series_id or ''
            return (product_name, prod_date, exp_date, container, pallet_id)

        sorted_lines = sorted(move_lines, key=get_sort_key)
        return self.env['stock.move.line'].browse([l.id for l in sorted_lines])

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
        counter = 1
        for record in self:
            record.action_confirm()

            for move in record.move_ids_without_package:
                try:
                    if move.exists():
                        counter = move.regenerate_move_lines(counter)
                        successful_count += 1
                except Exception as e:
                    failed_count += 1
                    _logger.error(
                        f"Error processing stock move {move.id}: {str(e)}")
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
        # Capture old x_studio_edit_record values before super write
        old_edit_record_vals = {}
        if 'x_studio_edit_record' in vals:
            for record in self:
                old_edit_record_vals[record.id] = {
                    'old_val': record.x_studio_edit_record if hasattr(record, 'x_studio_edit_record') else None,
                    'state': record.state,
                }

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

            # Refresh pallet kilos record on lock/unlock (x_studio_edit_record toggle)
            if record.id in old_edit_record_vals and record.state == 'done':
                old_info = old_edit_record_vals[record.id]
                new_val = record.x_studio_edit_record if hasattr(
                    record, 'x_studio_edit_record') else None
                if old_info['old_val'] != new_val:
                    record._refresh_pallet_kilos_on_lock()

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
            lot_ids = picking.move_line_ids.mapped(
                'lot_id.id')  # Get lot/serial numbers

            domain = []
            is_blast_freeze, is_receiving = picking.operation_type_checker(
                picking.picking_type_id)

            if not is_receiving and picking.state == 'done':
                picking.quant_count = False
                return
            if picking.picking_type_id.code == 'incoming':
                domain = [('lot_id', 'in', lot_ids), ('package_id',
                                                      '!=', False),  ('quantity', '!=', 0)]
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
                    # Get all child locations, including self
                    ('location_id', 'in', child_location_ids),
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
                    # Get all child locations, including self
                    ('location_id', 'in', child_location_ids),
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
        is_blast_freeze, is_receiving = self.operation_type_checker(
            self.picking_type_id)
        if self.picking_type_id.code == 'incoming':
            domain = [('lot_id', 'in', lot_ids), ('package_id',
                                                  '!=', False), ('quantity', '!=', 0)]
        elif self.picking_type_id.code == 'outgoing' and not is_blast_freeze:
            child_location_ids = self.env['stock.location'].search([
                ('id', 'child_of', self.location_id.id)
            ]).ids
            domain = [
                # Get all child locations, including self
                ('location_id', 'in', child_location_ids),
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
                # Get all child locations, including self
                ('location_id', 'in', child_location_ids),
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
            # Specify the editable tree view
            'view_id': self.env.ref('multiple_relocation.view_stock_quant_tree_custom_2').id,
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
                child_locations = self.env['stock.location'].search(
                    [('id', 'child_of', record.location_id.id)])

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
                record.allowed_product_ids = self.env['product.product'].search(
                    [('sale_ok', '!=', False)])

    def action_return_packages(self):
        if self.partner_id.x_studio_special_no_rr_return_needed:
            raise UserError(
                "You cannot create a return for Special No RR Return Needed customers. Please contact your Inventory Supervisor if you really think you need to create a return for this customer.")
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
                'voided': self.x_studio_voided,
                'is_a_blast_freeze': self.x_studio_is_a_blast_freezer,
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
        view_id = self.env.ref(
            'stock.view_stock_move_line_detailed_operation_tree').id
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
                        conflicting_pallets[line.result_package_id.name] = [
                            data['display_name']]

                    # Add the current product to the conflict list if it's not already added
                    if line.product_id.display_name not in conflicting_pallets[line.result_package_id.name]:
                        conflicting_pallets[line.result_package_id.name].append(
                            line.product_id.display_name)

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
                conflict_messages.append(
                    f"• Pallet: '{pallet}' contains multiple products: {product_list}")

            # Use \n to create line breaks
            self.gentle_reminder = "Reminder:\n" + \
                "\n".join(conflict_messages) + \
                "\n\nAre you sure you want to insert each line of multiple products into a single pallet?"
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

                    record.allowed_value_ids = self.env['stock.location'].browse(
                        locations_with_partner_quants)
                else:
                    allowed_locations = self.env["stock.location"].search([
                        "&",    # first AND
                        "&",    # second AND (for warehouse + new condition)
                        "|", "|", "|", "|",
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1",
                         "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1",
                         "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.x_studio_occupied_by_1",
                         "in", record.partner_id.id),
                        ("child_ids.child_ids.x_studio_occupied_by_1",
                         "in", record.partner_id.id),
                        ("child_ids.child_ids.child_ids.child_ids.child_ids.child_ids.x_studio_occupied_by_1",
                         "in", record.partner_id.id),
                        ("warehouse_id.code", "=", record.x_studio_warehouse_sh),
                        ("child_ids.child_ids.x_studio_is_a_blast_freezer", "=", False)
                    ])

                    record.allowed_value_ids = allowed_locations

            elif record.picking_type_code == 'incoming':
                if record.x_studio_is_a_blast_freezer:
                    record.allowed_value_ids = self.env['stock.location'].search(['|', ('x_studio_is_a_blast_freezer', '=', True), (
                        'name', '=', 'BF'), ('warehouse_id.id', '=', record.partner_id.x_studio_warehouse.id)])
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
                            '|',  # Main OR: either the location itself OR its children
                            # Include preferred locations themselves
                            ('id', 'in', record.x_studio_preferred_locations.ids),
                            '|',
                            ('location_id', 'in',
                             record.x_studio_preferred_locations.ids),
                            '|',
                            ('location_id.location_id', 'in',
                             record.x_studio_preferred_locations.ids),
                            ('location_id.location_id.location_id', 'in',
                             record.x_studio_preferred_locations.ids),
                        ]

                    # Perform the search with the updated domain
                    record.allowed_value_ids = self.env['stock.location'].search(
                        domain)

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
                        # Replace <br> tags with newlines
                        cleaned_content = re.sub(
                            r'<br\s*/?>', '\n', div_content)
                        # Remove extra whitespace around newlines
                        cleaned_content = re.sub(
                            r'\s*\n\s*', '\n', cleaned_content).strip()
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
        fields = ['old_value_text', 'old_value_integer',
                  'old_value_float', 'old_value_datetime', 'old_value_char']
        new_fields = ['new_value_text', 'new_value_integer',
                      'new_value_float', 'new_value_datetime', 'new_value_char']

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
            adjustment_form_series = self.env['ir.sequence'].search(
                [('code', '=', 'adjustment.form.series')], limit=1)
            if not adjustment_form_series:
                raise UserError("Adjustment Form Series sequence not found.")

            # Get and increment the next number in the sequence
            next_number = adjustment_form_series.next_by_id()
            self.x_studio_set_adjustment_series = next_number

        return Values
