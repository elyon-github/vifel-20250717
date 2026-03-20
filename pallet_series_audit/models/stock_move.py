# -*- coding: utf-8 -*-

from odoo import models
import logging

_logger = logging.getLogger(__name__)


class StockMoveAudit(models.Model):
    _inherit = 'stock.move'

    def regenerate_move_lines(self, counter):
        """Override to inject audit context so pool push/delete events are logged."""
        picking = self.picking_id
        if (
            picking
            and picking.picking_type_code == 'incoming'
            and picking.state not in ('done', 'cancel')
            and not picking.return_id
        ):
            # Log a summary event for the regeneration action
            series_on_lines = [
                ml.x_studio_pallet_series_id
                for ml in self.move_line_ids
                if ml.x_studio_pallet_series_id
            ]
            if series_on_lines:
                self.env['pallet.series.audit'].log_event(picking.id, {
                    'pallet_series_id': ', '.join(series_on_lines[:5]) + ('...' if len(series_on_lines) > 5 else ''),
                    'event_type': 'cleared',
                    'source': 'regenerate',
                    'notes': (
                        f'Regenerating {len(self.move_line_ids)} lines on move {self.id}. '
                        f'Series being cleared: {", ".join(series_on_lines)}'
                    ),
                })

            # Call super with audit context so push_unused_pallet & unlink are logged
            return super(
                StockMoveAudit,
                self.with_context(
                    audit_picking_id=picking.id,
                    audit_source='regenerate',
                ),
            ).regenerate_move_lines(counter)

        return super().regenerate_move_lines(counter)
