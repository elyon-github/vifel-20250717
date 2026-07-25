import logging

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MANILA_TZ = 'Asia/Manila'

# Map selection key → XML ID of the ir.actions.report
REPORT_MAP = {
    'pallet_monitoring': 'pallet_kilos_record_model.pallet_kilos_inventory',
    'pallet_kilos_billing': 'pallet_kilos_record_model.pallet_kilos_billing_inventory_2',
    'daily_inventory': 'pallet_kilos_record_model.xlsx_daily_inventory',
    'daily_pallet_utilization': 'pallet_kilos_record_model.xlsx_daily_pallet_utilization',
    'outbound_log': 'pallet_kilos_record_model.action_report_outbound_log_xlsx',
    'inbound_log': 'pallet_kilos_record_model.action_report_inbound_log_xlsx',
}

# Reports that take an as-of-now snapshot and don't need a date range
SNAPSHOT_REPORTS = {'daily_pallet_utilization'}

# Reports that deliberately ignore the date range and always cover ALL history.
#
# The Inbound Log lists one row per physical pallet with its LIVE available
# balance. Filtering its rows by receiving date would hide pallets received
# before the window that are still holding stock today — the report would look
# like an inventory picture while silently omitting stock. The client's own
# reference workbook likewise spans the client's full history.
FULL_HISTORY_REPORTS = {'inbound_log'}

# Reports where the date range is a genuine filter but optional (blank = all).
OPTIONAL_RANGE_REPORTS = {'outbound_log'}


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
            ('inbound_log', 'Inbound Log XLSX'),
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
    @api.model
    def _default_date_to(self):
        """Today on the warehouse floor (Manila, UTC+8).

        The server works in UTC, so late in the PH day fields.Date.today()
        still reads as yesterday locally and the user silently loses the
        current day's transactions. The user's own tz is preferred when set,
        but it is often blank on these accounts — hence the Manila fallback
        rather than letting it degrade to UTC.
        """
        tz = pytz.timezone(self.env.user.tz or MANILA_TZ)
        return pytz.utc.localize(fields.Datetime.now()).astimezone(tz).date()

    date_from = fields.Date(string='Start Date')
    date_to = fields.Date(string='End Date', default=_default_date_to)

    is_snapshot_report = fields.Boolean(
        compute='_compute_is_snapshot_report',
        store=False,
    )
    # True when the report ignores the date range entirely (hides the group)
    is_full_history_report = fields.Boolean(
        compute='_compute_is_snapshot_report',
        store=False,
    )

    @api.depends('report_type')
    def _compute_is_snapshot_report(self):
        for rec in self:
            rec.is_snapshot_report = rec.report_type in SNAPSHOT_REPORTS
            rec.is_full_history_report = rec.report_type in FULL_HISTORY_REPORTS

    @api.constrains('report_type', 'date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.report_type in SNAPSHOT_REPORTS or \
                    rec.report_type in FULL_HISTORY_REPORTS:
                continue
            if rec.report_type in OPTIONAL_RANGE_REPORTS:
                # blank = all history; only order matters when both are given
                if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                    raise UserError(_("Start Date must be before End Date."))
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

        # Outbound / Inbound Log drive on validated pickings, not PKR rows
        if self.report_type == 'outbound_log':
            return self._generate_outbound_log(report_action)
        if self.report_type == 'inbound_log':
            return self._generate_inbound_log(report_action)

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

    def _partner_label(self):
        """Totals-row label mirroring the reference workbook's client cell."""
        if not self.partner_ids:
            return 'All Clients'
        if len(self.partner_ids) == 1:
            return self.partner_ids.name
        return '%d Clients' % len(self.partner_ids)

    def _range_label(self):
        """" (2026-01-01 to 2026-07-25)" — empty when no range was given."""
        if self.date_from and self.date_to:
            return _(" (%s to %s)") % (self.date_from, self.date_to)
        if self.date_from:
            return _(" (from %s)") % self.date_from
        if self.date_to:
            return _(" (up to %s)") % self.date_to
        return ''

    def _generate_outbound_log(self, report_action):
        """Collect validated, non-void, non-BF withdrawals for the Outbound Log."""
        self.ensure_one()
        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('picking_type_id.is_blast_freeze_operation', '!=', True),
            ('is_void_wr', '!=', True),
        ]
        # Date range is OPTIONAL here: blank means the client's full history,
        # like the reference workbook's Outbound sheet.
        if self.date_from:
            domain.append(
                ('date_done', '>=', fields.Datetime.to_datetime(self.date_from)))
        if self.date_to:
            domain.append(
                ('date_done', '<=', fields.Datetime.to_datetime(self.date_to).replace(
                    hour=23, minute=59, second=59)))
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
                "No validated withdrawals found for the selected criteria%s."
            ) % self._range_label())

        data = {
            'date_from': str(self.date_from or ''),
            'date_to': str(self.date_to or ''),
            'partner_label': self._partner_label(),
            'range_label': (self._range_label() or ' All history').strip(' ()'),
        }
        return report_action.report_action(pickings, data=data)

    def _generate_inbound_log(self, report_action):
        """Collect validated, non-void, non-BF, NON-return receipts for the
        Inbound Log.

        NO DATE FILTER — deliberately. Each row is a physical pallet shown with
        its LIVE available balance, so restricting rows by receiving date would
        drop pallets received earlier that still hold stock today: the report
        would read as an inventory picture while omitting real stock. Returns
        are likewise excluded as rows; their effect appears in AVAILABLE. The
        report then dedupes the lines to one row per physical pallet.
        """
        self.ensure_one()
        Quant = self.env['stock.quant']

        # The report is driven by OWNER, not by the picking selection: a client
        # can hold stock that has no receiving document at all (opening-balance
        # imports, or pallets whose only receipts belong to a previous client),
        # and that stock must still be reported.
        if self.partner_ids:
            owner_ids = self.partner_ids.ids
        else:
            owner_ids = [g['owner_id'][0] for g in Quant.read_group(
                [('owner_id', '!=', False), ('quantity', '>', 0)],
                ['owner_id'], ['owner_id']) if g.get('owner_id')]

        domain = [
            ('picking_type_id.code', '=', 'incoming'),
            ('state', '=', 'done'),
            ('picking_type_id.is_blast_freeze_operation', '!=', True),
            ('return_id', '=', False),
        ]
        if owner_ids:
            domain.append(('move_line_ids.owner_id', 'in', owner_ids))
        if self.warehouse_ids:
            domain.append(('picking_type_id.warehouse_id', 'in', self.warehouse_ids.ids))

        pickings = self.env['stock.picking'].search(domain, order='date_done, name')
        pickings = pickings.filtered(lambda p: not getattr(p, 'x_studio_voided', False))

        # Only abort when there is nothing at all to say — neither receipts nor
        # stock. Receipts alone are not the test any more.
        has_stock = bool(owner_ids) and Quant.search_count([
            ('owner_id', 'in', owner_ids), ('quantity', '>', 0)])
        if not pickings and not has_stock:
            raise UserError(_(
                "The selected clients have no receipts and no stock on hand."))

        data = {
            'partner_label': self._partner_label(),
            'owner_ids': owner_ids,
        }
        return report_action.report_action(pickings, data=data)
