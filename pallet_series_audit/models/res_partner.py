# -*- coding: utf-8 -*-

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResPartnerAudit(models.Model):
    _inherit = 'res.partner'

    def push_unused_pallet(self, pallet_series_id):
        """Override to log pool-push events."""
        pool_before = len(self.unused_pallet_series_ids or [])
        res = super().push_unused_pallet(pallet_series_id)
        pool_after = len(self.unused_pallet_series_ids or [])

        picking_id = self.env.context.get('audit_picking_id')
        if picking_id:
            source = self.env.context.get('audit_source', 'system')
            self.env['pallet.series.audit'].log_event(picking_id, {
                'pallet_series_id': pallet_series_id,
                'event_type': 'pushed_to_pool',
                'source': source,
                'pool_delta': f'+1 (size {pool_before}→{pool_after})',
                'pool_size_after': pool_after,
                'notes': f'{pallet_series_id} returned to pool',
            })
        return res

    def get_smallest_pallet_series_ids(self, count):
        """Override to log pool-pull events."""
        pool_before = len(self.unused_pallet_series_ids or [])
        result = super().get_smallest_pallet_series_ids(count)
        pool_after = len(self.unused_pallet_series_ids or [])

        picking_id = self.env.context.get('audit_picking_id')
        if picking_id and result:
            source = self.env.context.get('audit_source', 'system')
            for series in result:
                self.env['pallet.series.audit'].log_event(picking_id, {
                    'pallet_series_id': series,
                    'event_type': 'pulled_from_pool',
                    'source': source,
                    'new_series': series,
                    'pool_delta': f'-{len(result)} (size {pool_before}→{pool_after})',
                    'pool_size_after': pool_after,
                    'notes': f'{series} consumed from pool',
                })
        return result

    def generate_new_pallet_series_id(self):
        """Override to log new-generation events."""
        result = super().generate_new_pallet_series_id()

        picking_id = self.env.context.get('audit_picking_id')
        if picking_id and result:
            source = self.env.context.get('audit_source', 'system')
            self.env['pallet.series.audit'].log_event(picking_id, {
                'pallet_series_id': result,
                'event_type': 'generated_new',
                'source': source,
                'new_series': result,
                'notes': f'{result} generated from counter',
            })
        return result

    def get_pallet_series_by_id(self, pallet_series_id):
        """Override to log targeted pool-pull events."""
        pool_before = len(self.unused_pallet_series_ids or [])
        result = super().get_pallet_series_by_id(pallet_series_id)
        pool_after = len(self.unused_pallet_series_ids or [])

        picking_id = self.env.context.get('audit_picking_id')
        if picking_id and result:
            source = self.env.context.get('audit_source', 'system')
            found = result[0] if result else ''
            was_exact = (found == pallet_series_id) if found else False
            self.env['pallet.series.audit'].log_event(picking_id, {
                'pallet_series_id': found,
                'event_type': 'pulled_from_pool',
                'source': source,
                'new_series': found,
                'pool_delta': f'size {pool_before}→{pool_after}',
                'pool_size_after': pool_after,
                'notes': (
                    f'Restored exact {found} from pool'
                    if was_exact
                    else f'Requested {pallet_series_id}, got {found} (smallest fallback)'
                ),
            })
        return result
