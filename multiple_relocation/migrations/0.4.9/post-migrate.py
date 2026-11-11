# -*- coding: utf-8 -*-
"""0.4.9: re-fill Transacted Pallet Count on validated pickings.

Since 8b84702 (Aug 2026) helper methods sat between the @api.depends block
and _compute_transacted_pallet_count, so the decorator landed on the helper
and the stored count never recomputed on validation (0 / blank on almost
every RR/WR validated from late July). The decorator is back on the compute;
this recomputes the stored value once for pickings validated since
2026-07-01. Only the list column changes - printed reports and the PKR
ledger compute their own counts. Running it again changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

BATCH = 2000


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking']
    field = Picking._fields['transacted_pallet_count']
    ids = Picking.search([
        ('state', '=', 'done'),
        ('date_done', '>=', '2026-07-01'),
    ]).ids
    for i in range(0, len(ids), BATCH):
        batch = Picking.browse(ids[i:i + BATCH])
        env.add_to_compute(field, batch)
        env.flush_all()
        env.invalidate_all()
    _logger.info("0.4.9: recomputed Transacted Pallet Count on %d pickings", len(ids))
