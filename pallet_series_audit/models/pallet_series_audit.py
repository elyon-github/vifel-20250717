# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
    ('assigned', 'Assigned'),
    ('reassigned', 'Reassigned'),
    ('pushed_to_pool', 'Pushed to Pool'),
    ('pulled_from_pool', 'Pulled from Pool'),
    ('generated_new', 'Generated New'),
    ('recycled', 'Recycled'),
    ('cleared', 'Cleared'),
    ('synced', 'Synced to Pallet'),
    ('restored', 'Restored Original'),
    ('line_deleted', 'Line Deleted'),
    ('pallet_assigned', 'Pallet Changed'),
]

SOURCE_TYPES = [
    ('server_action', 'Assign Pallet Series (SA)'),
    ('wizard', 'Magic Wizard'),
    ('generate_lines', 'Generate Lines'),
    ('write_override', 'Pallet Change'),
    ('ondelete', 'Line Delete Handler'),
    ('regenerate', 'Regenerate Move Lines'),
    ('pool_operation', 'Pool Operation'),
    ('system', 'System'),
]


class PalletSeriesAudit(models.Model):
    _name = 'pallet.series.audit'
    _description = 'Pallet Series Audit'
    _order = 'create_date desc'
    _rec_name = 'picking_id'

    picking_id = fields.Many2one(
        'stock.picking', string='RR Transfer', required=True,
        readonly=True, index=True, ondelete='cascade',
    )
    warehouse_id = fields.Many2one(
        related='picking_id.picking_type_id.warehouse_id', store=True,
        index=True, string='Warehouse',
        help='Warehouse of the audited transfer. Multi-warehouse Phase 1: '
             'enables per-warehouse filtering and the Phase 2 record rule.',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client / Owner', readonly=True, index=True,
    )
    picking_name = fields.Char(
        related='picking_id.name', store=True, string='RR Name',
    )
    picking_state = fields.Selection(
        related='picking_id.state', store=False, string='RR Status',
    )
    line_ids = fields.One2many(
        'pallet.series.audit.line', 'audit_id', string='Event Log', readonly=True,
    )

    event_count = fields.Integer(
        string='Events', compute='_compute_stats', store=True,
    )
    unique_series_count = fields.Integer(
        string='Unique Series', compute='_compute_stats', store=True,
    )
    last_event_date = fields.Datetime(
        string='Last Event', compute='_compute_stats', store=True,
    )
    # --- CURRENT state of the document (not the event log) -------------
    # The counts above summarise the LOG.  These summarise the RR as it
    # stands right now, which is what someone asking "did I lose my
    # series?" actually needs.  COMP-2026-00048: a supervisor read the
    # log-derived "0 Pallets" on an unvalidated RR as data loss and filed
    # a ticket for a document that was already fully re-encoded.
    current_line_count = fields.Integer(
        string='Lines Now', compute='_compute_current_state',
    )
    current_series_count = fields.Integer(
        string='Series Now', compute='_compute_current_state',
    )
    current_pallet_count = fields.Integer(
        string='Pallets Now', compute='_compute_current_state',
    )
    lines_without_series = fields.Integer(
        string='Lines Without Series', compute='_compute_current_state',
        help='Lines on the RR that carry no pallet series at all.  Note that '
             'several lines legitimately SHARE one series (different products '
             'or batches on the same pallet), so a series count lower than the '
             'line count is normal and is not flagged.',
    )
    pallets_pending = fields.Boolean(
        string='Pallets Not Yet Created', compute='_compute_current_state',
        help='True while the RR is not validated.  Pallets (packages) are '
             'only created on validation, so a zero pallet count before '
             'that is expected and says nothing about the pallet series.',
    )

    _sql_constraints = [
        ('picking_uniq', 'unique(picking_id)', 'Only one audit record per RR transfer.'),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('line_ids', 'line_ids.pallet_series_id', 'line_ids.event_date')
    def _compute_stats(self):
        for rec in self:
            events = rec.line_ids
            rec.event_count = len(events)
            rec.unique_series_count = len(set(events.mapped('pallet_series_id')))
            dates = events.mapped('event_date')
            rec.last_event_date = max(dates) if dates else False

    def _compute_current_state(self):
        """Live counts read off the picking, so the dashboard header can show
        what the RR holds now instead of what the log remembers."""
        for rec in self:
            picking = rec.picking_id
            lines = picking.move_line_ids if picking else picking
            rec.current_line_count = len(lines)
            rec.current_series_count = len(set(
                (ml.x_studio_pallet_series_id or '').strip()
                for ml in lines
            ) - {''})
            rec.current_pallet_count = len(set(
                ml.result_package_id.id for ml in lines if ml.result_package_id
            ))
            # Only a BLANK series is a defect.  Lines sharing a series is a
            # normal VIFEL pattern (175 of 1,785 audited RRs do it), so
            # comparing series count to line count would cry wolf.
            rec.lines_without_series = sum(
                1 for ml in lines
                if not (ml.x_studio_pallet_series_id or '').strip()
            )
            rec.pallets_pending = bool(picking) and picking.state != 'done'

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_timeline(self):
        """Open audit events in the custom JS timeline dashboard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'pallet_series_audit.timeline_dashboard',
            'name': 'Visual Timeline – %s' % self.picking_name,
            'params': {
                'audit_id': self.id,
            },
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Scheduled Cleanup
    # ------------------------------------------------------------------
    @api.model
    def _cron_cleanup_old_audits(self, months=3):
        """Delete audit records older than `months` months.

        Called by the ir.cron scheduled action.  Deleting the header
        cascades to all related audit lines automatically.
        """
        cutoff = fields.Datetime.now() - timedelta(days=months * 30)
        old_audits = self.search([
            ('last_event_date', '!=', False),
            ('last_event_date', '<', cutoff),
        ])
        if old_audits:
            count = len(old_audits)
            old_audits.unlink()
            _logger.info(
                "Pallet Series Audit cleanup: removed %d audit records older than %s.",
                count, cutoff,
            )

    # ------------------------------------------------------------------
    # Central logging API
    # ------------------------------------------------------------------
    @api.model
    def log_event(self, picking_id, vals):
        """Create an audit event line for the given picking.

        Auto-creates the audit header record on first call.
        Silently skips if the picking is already validated/cancelled or
        is not an incoming (RR) transfer.
        """
        if not picking_id:
            return
        picking = self.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return
        if picking.state in ('done', 'cancel'):
            return
        if picking.picking_type_code != 'incoming':
            return
        # Skip return RRs
        if picking.return_id:
            return

        audit = self.search([('picking_id', '=', picking_id)], limit=1)
        if not audit:
            try:
                audit = self.sudo().create({
                    'picking_id': picking_id,
                    'partner_id': picking.partner_id.id,
                })
                self.env.cr.flush()
            except Exception:
                # Concurrent creation — re-search
                self.env.cr.rollback()
                audit = self.search([('picking_id', '=', picking_id)], limit=1)
                if not audit:
                    _logger.warning("Could not create/find audit record for picking %s", picking_id)
                    return

        vals['audit_id'] = audit.id
        vals.setdefault('event_date', fields.Datetime.now())
        vals.setdefault('user_id', self.env.uid)

        try:
            self.env['pallet.series.audit.line'].sudo().create(vals)
        except Exception:
            _logger.warning("Failed to create pallet audit event for picking %s", picking_id, exc_info=True)


class PalletSeriesAuditLine(models.Model):
    _name = 'pallet.series.audit.line'
    _description = 'Pallet Series Audit Event'
    _order = 'event_date asc, id asc'

    audit_id = fields.Many2one(
        'pallet.series.audit', string='Audit Record', required=True,
        ondelete='cascade', index=True,
    )
    picking_id = fields.Many2one(
        related='audit_id.picking_id', store=True, string='RR Transfer',
    )
    warehouse_id = fields.Many2one(
        related='audit_id.warehouse_id', store=True, index=True,
        string='Warehouse',
    )
    pallet_series_id = fields.Char(string='Pallet Series', index=True)
    event_type = fields.Selection(EVENT_TYPES, string='Event', required=True)
    source = fields.Selection(SOURCE_TYPES, string='Source', required=True)

    line_number = fields.Integer(string='Line #')
    move_line_id = fields.Integer(string='Move Line DB ID')
    result_package_name = fields.Char(string='Pallet #')

    previous_series = fields.Char(string='Previous Series')
    new_series = fields.Char(string='New Series')

    pool_delta = fields.Char(string='Pool Change')
    pool_size_after = fields.Integer(string='Pool Size After')

    user_id = fields.Many2one('res.users', string='User', readonly=True)
    event_date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    notes = fields.Text(string='Notes')

    kanban_color = fields.Integer(string='Color Index', compute='_compute_kanban_color', store=True)
    event_label = fields.Char(string='Event Label', compute='_compute_event_label')
    series_display = fields.Char(string='Series Change', compute='_compute_series_display')

    @api.depends('event_type')
    def _compute_kanban_color(self):
        color_map = {
            'assigned': 10,         # green
            'pulled_from_pool': 10, # green
            'generated_new': 10,    # green
            'synced': 4,            # light blue
            'restored': 4,          # light blue
            'reassigned': 4,        # light blue
            'recycled': 4,          # light blue
            'pallet_assigned': 3,   # yellow
            'pushed_to_pool': 2,    # orange
            'cleared': 1,           # red
            'line_deleted': 1,      # red
        }
        for rec in self:
            rec.kanban_color = color_map.get(rec.event_type, 0)

    def _compute_event_label(self):
        labels = dict(EVENT_TYPES)
        for rec in self:
            rec.event_label = labels.get(rec.event_type, rec.event_type)

    def _compute_series_display(self):
        for rec in self:
            if rec.previous_series and rec.new_series:
                rec.series_display = '%s → %s' % (rec.previous_series, rec.new_series)
            elif rec.new_series:
                rec.series_display = '→ %s' % rec.new_series
            elif rec.previous_series:
                rec.series_display = '%s → ∅' % rec.previous_series
            else:
                rec.series_display = rec.pallet_series_id or ''
