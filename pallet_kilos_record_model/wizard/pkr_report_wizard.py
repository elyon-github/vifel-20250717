import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Map selection key → XML ID of the ir.actions.report
REPORT_MAP = {
    'pallet_monitoring': 'pallet_kilos_record_model.pallet_kilos_inventory',
    'pallet_kilos_billing': 'pallet_kilos_record_model.pallet_kilos_billing_inventory_2',
    'daily_inventory': 'pallet_kilos_record_model.xlsx_daily_inventory',
    'daily_pallet_utilization': 'pallet_kilos_record_model.xlsx_daily_pallet_utilization',
    'outbound_log': 'pallet_kilos_record_model.action_report_outbound_log_xlsx',
}

# Reports that take an as-of-now snapshot and don't need a date range
SNAPSHOT_REPORTS = {'daily_pallet_utilization'}


class PkrReportWizard(models.TransientModel):
    _name = 'pallet_kilos_record_model.report.wizard'
    _description = 'Pallet Kilos Record Report Wizard'

    report_type = fields.Selection(
        [
            ('pallet_monitoring', 'Pallet Monitoring XLSX'),
            ('pallet_kilos_billing', 'Pallet Kilos Billing XLSX'),
            ('daily_inventory', 'Daily Inventory XLSX'),
            ('daily_pallet_utilization', 'Daily Pallet Utilization XLSX'),
            ('outbound_log', 'Outbound Log XLSX'),
        ],
        string='Report Type',
        required=True,
        default='pallet_monitoring',
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string='Clients',
        help='Leave empty to include all clients.',
    )
    building_ids = fields.Many2many(
        'x_warehouse_building',
        'pkr_wizard_building_rel',
        'wizard_id',
        'building_id',
        string='Buildings',
        help='Leave empty to include all buildings.',
    )
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'pkr_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Warehouses',
        help='Leave empty to include all warehouses.',
    )
    date_from = fields.Date(string='Start Date')
    date_to = fields.Date(string='End Date')

    is_snapshot_report = fields.Boolean(
        compute='_compute_is_snapshot_report',
        store=False,
    )

    @api.depends('report_type')
    def _compute_is_snapshot_report(self):
        for rec in self:
            rec.is_snapshot_report = rec.report_type in SNAPSHOT_REPORTS

    @api.constrains('report_type', 'date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.report_type in SNAPSHOT_REPORTS:
                continue
            if not rec.date_from or not rec.date_to:
                raise UserError(_("Start Date and End Date are required for this report."))
            if rec.date_from > rec.date_to:
                raise UserError(_("Start Date must be before End Date."))

    def action_generate_report(self):
        self.ensure_one()

        xml_id = REPORT_MAP.get(self.report_type)
        if not xml_id:
            raise UserError(_("Unknown report type: %s") % self.report_type)
        report_action = self.env.ref(xml_id)

        # As-of-now snapshot reports don't need transaction records — pass the wizard itself
        if self.report_type in SNAPSHOT_REPORTS:
            return report_action.report_action(self)

        # Outbound Log drives on validated WR pickings, not PKR rows
        if self.report_type == 'outbound_log':
            return self._generate_outbound_log(report_action)

        domain = [
            ('start_time', '>=', fields.Datetime.to_string(
                fields.Datetime.to_datetime(self.date_from)
            )),
            ('start_time', '<=', fields.Datetime.to_string(
                fields.Datetime.to_datetime(self.date_to).replace(
                    hour=23, minute=59, second=59,
                )
            )),
        ]
        if self.partner_ids:
            domain.append(('owner_id', 'in', self.partner_ids.ids))
        if self.warehouse_ids:
            domain.append(('warehouse', 'in', self.warehouse_ids.ids))

        records = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
            domain, order='start_time asc'
        )

        if not records:
            raise UserError(_(
                "No Pallet Kilos records found for the selected criteria "
                "(%s to %s)."
            ) % (self.date_from, self.date_to))

        return report_action.report_action(records)

    def _generate_outbound_log(self, report_action):
        """Collect validated, non-void, non-BF withdrawals for the Outbound Log."""
        self.ensure_one()
        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', fields.Datetime.to_datetime(self.date_from)),
            ('date_done', '<=', fields.Datetime.to_datetime(self.date_to).replace(
                hour=23, minute=59, second=59)),
            ('picking_type_id.is_blast_freeze_operation', '!=', True),
            ('is_void_wr', '!=', True),
        ]
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        if self.warehouse_ids:
            domain.append(('picking_type_id.warehouse_id', 'in', self.warehouse_ids.ids))

        pickings = self.env['stock.picking'].search(domain, order='date_done, name')
        # Voided flag is a Studio field — filter in Python so module code never
        # assumes the column exists in a bare DB.
        pickings = pickings.filtered(lambda p: not getattr(p, 'x_studio_voided', False))
        if not pickings:
            raise UserError(_(
                "No validated withdrawals found for the selected criteria "
                "(%s to %s)."
            ) % (self.date_from, self.date_to))

        data = {
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
        }
        return report_action.report_action(pickings, data=data)
