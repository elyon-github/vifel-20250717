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
}

# Reports that take an as-of-now snapshot and don't need a date range
SNAPSHOT_REPORTS = {'daily_pallet_utilization'}

# Reports that must NOT show blast-freeze documents (BFRR / BFWR). Scoped to
# Pallet Monitoring only - billing and the daily reports still account for BF
# stock, so silently dropping it there would understate what the client owes.
BLAST_FREEZE_EXCLUDED_REPORTS = {'pallet_monitoring'}


class PkrReportWizard(models.TransientModel):
    _name = 'pallet_kilos_record_model.report.wizard'
    _description = 'Pallet Kilos Record Report Wizard'

    report_type = fields.Selection(
        [
            ('pallet_monitoring', 'Pallet Monitoring XLSX'),
            ('pallet_kilos_billing', 'Pallet Kilos Billing XLSX'),
            ('daily_inventory', 'Daily Inventory XLSX'),
            ('daily_pallet_utilization', 'Daily Pallet Utilization XLSX'),
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
        if self.report_type in BLAST_FREEZE_EXCLUDED_REPORTS:
            # Keep blast-freeze documents off the Pallet Monitoring statement:
            # they live in their own running-balance partition, so their
            # Beginning/Remaining figures belong to a different series. The
            # report itself filters too (it is reachable from the list view
            # without this wizard); excluding them here as well keeps the
            # "no records found" message below honest.
            # '!=' True, never '=' False: older rows have the flag as NULL and
            # must still be included.
            domain.append(('is_blast_freezer', '!=', True))

        records = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
            domain, order='start_time asc'
        )

        if not records:
            raise UserError(_(
                "No Pallet Kilos records found for the selected criteria "
                "(%s to %s)."
            ) % (self.date_from, self.date_to))

        return report_action.report_action(records)
