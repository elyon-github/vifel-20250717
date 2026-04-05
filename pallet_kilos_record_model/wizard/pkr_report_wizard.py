import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Map selection key → XML ID of the ir.actions.report
REPORT_MAP = {
    'pallet_monitoring': 'pallet_kilos_record_model.pallet_kilos_inventory',
    'pallet_kilos_billing': 'pallet_kilos_record_model.pallet_kilos_billing_inventory_2',
    'daily_inventory': 'pallet_kilos_record_model.xlsx_daily_inventory',
}


class PkrReportWizard(models.TransientModel):
    _name = 'pallet_kilos_record_model.report.wizard'
    _description = 'Pallet Kilos Record Report Wizard'

    report_type = fields.Selection(
        [
            ('pallet_monitoring', 'Pallet Monitoring XLSX'),
            ('pallet_kilos_billing', 'Pallet Kilos Billing XLSX'),
            ('daily_inventory', 'Daily Inventory XLSX'),
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
    date_from = fields.Date(
        string='Start Date',
        required=True,
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise UserError(_("Start Date must be before End Date."))

    def action_generate_report(self):
        self.ensure_one()

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

        records = self.env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
            domain, order='start_time asc'
        )

        if not records:
            raise UserError(_(
                "No Pallet Kilos records found for the selected criteria "
                "(%s to %s)."
            ) % (self.date_from, self.date_to))

        xml_id = REPORT_MAP.get(self.report_type)
        if not xml_id:
            raise UserError(_("Unknown report type: %s") % self.report_type)

        report_action = self.env.ref(xml_id)
        return report_action.report_action(records)
