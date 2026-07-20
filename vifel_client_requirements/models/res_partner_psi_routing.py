# -*- coding: utf-8 -*-
"""Prefix-aware PSI routing (Client-Specific Requirement Enhancement).

Every path that frees or re-serves a pallet series funnels through
``push_unused_pallet`` / ``get_pallet_series_by_id`` on res.partner, so both
are hardened HERE rather than at each of the callers (FastEncodeRR recycle,
the stock_move write intercept, the merge wizard).

Two rules are enforced:

1. **Never recycle a series that is still on stocked quants.** Re-issuing it
   would mint a duplicate of live stock — the split-PSI corruption the
   identity doctrine exists to prevent.
2. **Special-type numbers never enter the client's normal pool.** The normal
   pool stores bare integers and re-issues them under the client's unique
   code, so an ``SDMG-`` number dropped in there would come back out as a
   duplicate normal series.

Both overrides are additive: when neither rule applies, the call falls
through to the core implementation untouched, keeping the pallet_series_audit
super() chain intact.
"""
from odoo import api, models


class ResPartnerPsiRouting(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _vifel_series_is_stocked(self, pallet_series_id):
        """The series is still physically on stock on the floor.

        Internal locations only — quants at customer locations are history,
        not stock.
        """
        if not pallet_series_id:
            return False
        return bool(self.env['stock.quant'].search_count([
            ('x_studio_pallet_series_id', '=', pallet_series_id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]))

    def _vifel_audit_type_recycle(self, ptype, pallet_series_id):
        """Log a special-type recycle to the pallet series audit trail.

        This module's override sits OUTSIDE pallet_series_audit's wrapper in
        the MRO (its module depends on that one, so it loads later and wraps
        it). A type-pool recycle returns before ``super()``, so the audit
        wrapper never sees it — yet it is a real recycle, on the newest and
        least-exercised path in the system. Log it here rather than let it
        vanish: unaudited recycling is how split-PSI corruption goes
        untraceable.
        """
        picking_id = self.env.context.get('audit_picking_id')
        if not picking_id:
            return
        pool_size = len(ptype.number_pool or [])
        self.env['pallet.series.audit'].log_event(picking_id, {
            'pallet_series_id': pallet_series_id,
            'event_type': 'pushed_to_pool',
            'source': self.env.context.get('audit_source', 'system'),
            'pool_delta': '+1 (%s pool size %d)' % (ptype.prefix, pool_size),
            'pool_size_after': pool_size,
            'notes': '%s returned to the %s type pool (special series — kept '
                     'out of the client\'s normal numbers)'
                     % (pallet_series_id, ptype.prefix),
        })

    def push_unused_pallet(self, pallet_series_id):
        """Route a freed series to the right home, or refuse it outright."""
        # Still on the floor: recycling it would duplicate live stock.
        if self._vifel_series_is_stocked(pallet_series_id):
            return

        # Special PSI types own their prefix — the number goes back to that
        # type's own recyclable numbers, never the client's normal ones.
        ptype = self.env['vifel.psi.type']._type_for_series(
            self, pallet_series_id)
        if ptype:
            if ptype.give_back(pallet_series_id):
                self._vifel_audit_type_recycle(ptype, pallet_series_id)
            return

        prefix = (pallet_series_id or '').rpartition('-')[0]
        code = (self.x_studio_client_unique_code_1 or '').strip()
        if code and prefix and prefix != code:
            # A foreign prefix with no matching type: drop it rather than
            # pollute the normal pool with a number that would re-issue
            # under the wrong code.
            return

        return super().push_unused_pallet(pallet_series_id)

    def get_pallet_series_by_id(self, pallet_series_id):
        """Serve a specific series, from its own type when it has one."""
        ptype = self.env['vifel.psi.type']._type_for_series(
            self, pallet_series_id)
        if ptype:
            # pool first, then that type's counter — never the normal pool
            return [ptype.take_number(pallet_series_id)]
        return super().get_pallet_series_by_id(pallet_series_id)
