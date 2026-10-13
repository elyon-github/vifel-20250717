# -*- coding: utf-8 -*-

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


def _safe_line_number(rec):
    """Safely read x_studio_ (line #) — returns 0 if field missing."""
    try:
        return rec.x_studio_ or 0
    except Exception:
        return 0


class StockMoveLineAudit(models.Model):
    _inherit = 'stock.move.line'

    # ------------------------------------------------------------------
    # write — detect series & pallet changes after full write chain
    # ------------------------------------------------------------------
    def write(self, vals):
        series_change = 'x_studio_pallet_series_id' in vals
        package_change = 'result_package_id' in vals

        # Fast exit: nothing we audit
        if not series_change and not package_change:
            return super().write(vals)

        # Only audit incoming, non-done, non-return RR lines
        to_audit = self.filtered(
            lambda r: r.picking_id
            and r.picking_id.picking_type_code == 'incoming'
            and r.picking_id.state not in ('done', 'cancel')
            and not r.picking_id.return_id
        )
        if not to_audit:
            return super().write(vals)

        # Snapshot old values for the lines we care about
        old_series = {r.id: r.x_studio_pallet_series_id or '' for r in to_audit}
        old_packages = {
            r.id: (r.result_package_id.id if r.result_package_id else False,
                   r.result_package_id.name if r.result_package_id else '')
            for r in to_audit
        }

        # Inject audit context so pool methods inside can log
        picking_id = to_audit[0].picking_id.id
        ctx = {'audit_picking_id': picking_id}
        source = self.env.context.get('audit_source')
        if not source:
            if self.env.context.get('skip_pallet_series_sync'):
                source = 'wizard'
            elif 'result_package_id' in vals:
                source = 'write_override'
            else:
                source = 'system'
            ctx['audit_source'] = source

        res = super(StockMoveLineAudit, self.with_context(**ctx)).write(vals)

        # --- Compare after full write chain has completed ---
        Audit = self.env['pallet.series.audit']
        for rec in to_audit:
            line_num = _safe_line_number(rec)
            pkg_name = rec.result_package_id.name if rec.result_package_id else ''

            # ── Series change detection ──
            old_s = old_series.get(rec.id, '')
            new_s = rec.x_studio_pallet_series_id or ''
            if old_s != new_s:
                if not old_s and new_s:
                    event_type = 'assigned'
                elif old_s and not new_s:
                    event_type = 'cleared'
                else:
                    old_pkg_id = old_packages.get(rec.id, (False, ''))[0]
                    new_pkg_id = rec.result_package_id.id if rec.result_package_id else False
                    if old_pkg_id != new_pkg_id:
                        event_type = 'synced'
                    elif rec.original_pallet_series_id and new_s == rec.original_pallet_series_id:
                        event_type = 'restored'
                    else:
                        event_type = 'reassigned'

                Audit.log_event(rec.picking_id.id, {
                    'pallet_series_id': new_s or old_s,
                    'event_type': event_type,
                    'source': source,
                    'line_number': line_num,
                    'move_line_id': rec.id,
                    'result_package_name': pkg_name,
                    'previous_series': old_s,
                    'new_series': new_s,
                    'notes': f'{old_s or "(empty)"} → {new_s or "(empty)"}',
                })

            # ── Pallet (result_package) change detection ──
            old_pkg_id, old_pkg_name = old_packages.get(rec.id, (False, ''))
            new_pkg_id = rec.result_package_id.id if rec.result_package_id else False
            if old_pkg_id != new_pkg_id:
                current_series = rec.x_studio_pallet_series_id or ''
                if not old_pkg_id and new_pkg_id:
                    pallet_note = f'Assigned to pallet {pkg_name}'
                elif old_pkg_id and not new_pkg_id:
                    pallet_note = f'Removed from pallet {old_pkg_name}'
                else:
                    pallet_note = f'Pallet changed: {old_pkg_name} → {pkg_name}'
                Audit.log_event(rec.picking_id.id, {
                    'pallet_series_id': current_series,
                    'event_type': 'pallet_assigned',
                    'source': source,
                    'line_number': line_num,
                    'move_line_id': rec.id,
                    'result_package_name': pkg_name,
                    'previous_series': old_pkg_name,
                    'new_series': pkg_name,
                    'notes': pallet_note,
                })

        return res

    # ------------------------------------------------------------------
    # unlink — log deletions of lines that carry a pallet series
    # ------------------------------------------------------------------
    def unlink(self):
        Audit = self.env['pallet.series.audit']

        for rec in self:
            if (
                rec.x_studio_pallet_series_id
                and rec.picking_id
                and rec.picking_id.picking_type_code == 'incoming'
                and rec.picking_id.state not in ('done', 'cancel')
                and not rec.picking_id.return_id
            ):
                source = self.env.context.get('audit_source', 'ondelete')
                line_num = _safe_line_number(rec)
                Audit.log_event(rec.picking_id.id, {
                    'pallet_series_id': rec.x_studio_pallet_series_id,
                    'event_type': 'line_deleted',
                    'source': source,
                    'line_number': line_num,
                    'move_line_id': rec.id,
                    'result_package_name': rec.result_package_id.name if rec.result_package_id else '',
                    'previous_series': rec.x_studio_pallet_series_id,
                    'new_series': '',
                    'notes': f'Line #{line_num} deleted — series {rec.x_studio_pallet_series_id} removed',
                })

        # Inject context for pool operations in ondelete handlers
        ctx = {}
        picking = self[:1].picking_id if self else False
        if picking and picking.picking_type_code == 'incoming' and picking.state not in ('done', 'cancel'):
            ctx['audit_picking_id'] = picking.id
            ctx['audit_source'] = self.env.context.get('audit_source', 'ondelete')

        return super(StockMoveLineAudit, self.with_context(**ctx)).unlink()
