import logging
from datetime import timedelta

from pytz import timezone, utc as pytz_utc

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MANILA_TZ = timezone('Asia/Manila')


class OccupancyReportWizard(models.TransientModel):
    _name = 'stock.quant.history.occupancy.wizard'
    _description = 'Occupancy Report Wizard'

    computation_method = fields.Selection(
        [
            ('snapshot', 'Generate Snapshots'),
            ('sql', 'On-the-fly (SQL)'),
        ],
        string='Computation Method',
        default='snapshot',
        required=True,
        help=(
            "Generate Snapshots: auto-creates and generates snapshots for every "
            "date in the range, then reads them. Accurate but slower and uses storage. "
            "On-the-fly (SQL): computes from nearest snapshot + move-line deltas "
            "without creating any records (fast, zero storage cost)."
        ),
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string='Clients',
        help='Leave empty to include all clients.',
    )
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouses',
        help='Leave empty to include all warehouses.',
    )
    date_from = fields.Date(
        string='Start Date',
        required=True,
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        # Default to yesterday: the latest day with a complete scheduled snapshot
        # (the daily cron stamps end-of-yesterday).
        default=lambda self: fields.Date.context_today(self) - timedelta(days=1),
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_("Start Date must be before End Date."))
            if rec.date_to and rec.date_to > today:
                raise UserError(_(
                    "End Date cannot be in the future - you cannot report on a "
                    "day that has not happened yet."))

    # ─── Snapshot method (auto-generate) ───────────────────────────────
    def _ensure_snapshots_for_range(self):
        """Auto-create and generate snapshots for every date in the range
        that doesn't already have one."""
        from datetime import datetime, timedelta
        from pytz import timezone

        manila_tz = timezone('Asia/Manila')
        SnapshotModel = self.env['stock.quant.history.snapshot'].sudo()

        current_date = self.date_from
        while current_date <= self.date_to:
            day_start_dt = datetime.combine(current_date, datetime.min.time())
            day_end_dt = datetime.combine(current_date, datetime.max.time())

            existing = SnapshotModel.search([
                ('inventory_date', '>=', day_start_dt),
                ('inventory_date', '<=', day_end_dt),
            ], limit=1)

            if not existing:
                local_dt = manila_tz.localize(
                    datetime.combine(current_date, datetime.min.time()).replace(
                        hour=23, minute=59, second=59
                    )
                )
                utc_dt = local_dt.astimezone(timezone('UTC')).replace(tzinfo=None)

                snapshot = SnapshotModel.create({
                    'inventory_date': utc_dt,
                    'state': 'draft',
                })
                _logger.info("Auto-created snapshot for %s (inventory_date=%s)", current_date, utc_dt)
                snapshot._generate_stock_quant_history()
            elif existing.state == 'draft':
                _logger.info("Auto-generating existing draft snapshot for %s", current_date)
                existing._generate_stock_quant_history()

            current_date += timedelta(days=1)

    def _action_report_snapshot(self):
        """Auto-generate missing snapshots, then build report from them."""
        from datetime import datetime

        self._ensure_snapshots_for_range()

        date_from_dt = datetime.combine(self.date_from, datetime.min.time())
        date_to_dt = datetime.combine(self.date_to, datetime.max.time())

        snapshots = self.env['stock.quant.history.snapshot'].search([
            ('state', '=', 'generated'),
            ('inventory_date', '>=', date_from_dt),
            ('inventory_date', '<=', date_to_dt),
        ], order='inventory_date asc')

        if not snapshots:
            raise UserError(_(
                "No generated snapshots found between %s and %s."
            ) % (self.date_from, self.date_to))

        # Keep exactly ONE snapshot per Manila calendar day. A day can carry both
        # a user-manual snapshot and the scheduled 23:59:59 one; feeding both to
        # the report double/triple-counts that day's quants (the report buckets
        # history rows by calendar date). Prefer the scheduled (cron) snapshot,
        # then the latest inventory_date; a manual snapshot is used only when no
        # scheduled one exists for that day.
        best_per_day = {}
        for snap in snapshots:
            day = pytz_utc.localize(snap.inventory_date).astimezone(MANILA_TZ).date()
            current = best_per_day.get(day)
            if current is None or (
                (snap.generated_by_cron and not current.generated_by_cron)
                or (snap.generated_by_cron == current.generated_by_cron
                    and snap.inventory_date > current.inventory_date)
            ):
                best_per_day[day] = snap
        snapshots = self.env['stock.quant.history.snapshot'].browse(
            [snap.id for snap in best_per_day.values()])

        history_domain = [
            ('snapshot_id', 'in', snapshots.ids),
            ('owner_id', '!=', False),
        ]
        if self.partner_ids:
            history_domain.append(('owner_id', 'in', self.partner_ids.ids))
        if self.warehouse_ids:
            history_domain.append(('warehouse_id', 'in', self.warehouse_ids.ids))

        history_records = self.env['stock.quant.history'].search(history_domain)

        if not history_records:
            raise UserError(_("No inventory history records found for the given criteria."))

        data = {
            'method': 'snapshot',
            'snapshot_ids': snapshots.ids,
            'partner_ids': self.partner_ids.ids or [],
            'warehouse_ids': self.warehouse_ids.ids or [],
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
            'history_ids': history_records.ids,
        }

        return self.env.ref(
            'stock_quant_history.action_report_occupancy_xlsx'
        ).report_action(history_records, data=data)

    # ─── SQL on-the-fly method ─────────────────────────────────────────
    def _action_report_sql(self):
        """Generate report using on-the-fly SQL computation."""
        data = {
            'method': 'sql',
            'partner_ids': self.partner_ids.ids or [],
            'warehouse_ids': self.warehouse_ids.ids or [],
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
        }

        # Pass an empty recordset; the report computes everything via SQL
        return self.env.ref(
            'stock_quant_history.action_report_occupancy_xlsx'
        ).report_action(
            self.env['stock.quant.history'].browse([]),
            data=data,
        )

    # ─── Main entry point ─────────────────────────────────────────────
    def action_generate_report(self):
        self.ensure_one()
        if self.computation_method == 'sql':
            return self._action_report_sql()
        return self._action_report_snapshot()
