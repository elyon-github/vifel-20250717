# -*- coding: utf-8 -*-
"""0.4.5 (end): refresh the pallet details on OPEN withdrawal lines once.

The 0.4.4 / 0.4.5 changes fix the formulas, but the values are stored on the
lines and only refresh when a dependency changes. M/WR/15388 and M/WR/15624
would keep their blank Pallet Series ID / Container # / Prod. Date /
Exp. Date and negative Original Weight until someone re-checked them.

This end script (runs after every module is loaded, so the new formulas are
active) recomputes those fields on outgoing lines that are not done or
cancelled. Done lines are history and are left alone.

Replayed read-only on consultant-test (prod copy 11-09), 865 such lines:
only the 4 affected pallets change (R 7795, NB 10463, NB 10688 on
M/WR/15388; NB 531 on M/WR/15624). Running it again recomputes the same
values, which changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

FIELDS = [
    'x_studio_pallet_series_id',
    'x_studio_container_number',
    'x_studio_building_dropped',
    'original_record_reference',
    'x_studio_production_date',
    'x_studio_expiration_date',
    'x_studio_return_count',
    'x_studio_special_holding',
    'x_studio_sh_reason',
    'x_studio_min_quantity_uom',
    'x_studio_quantity_uom_delivery',
    'x_studio_max_quant',
    'x_studio_max_2nd_uom',
    'x_studio_max_total_units',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    MoveLine = env['stock.move.line']
    lines = MoveLine.search([
        ('picking_id.picking_type_id.code', '=', 'outgoing'),
        ('state', 'not in', ('done', 'cancel')),
        ('location_id.usage', '=', 'internal'),
    ])
    if not lines:
        return
    names = [f for f in FIELDS if f in MoveLine._fields and MoveLine._fields[f].compute]
    snapshot = {l.id: [l[f] for f in names] for l in lines}
    for name in names:
        env.add_to_compute(MoveLine._fields[name], lines)
    env.flush_all()
    changed = 0
    for l in lines:
        after = [l[f] for f in names]
        if after != snapshot[l.id]:
            changed += 1
            _logger.info("0.4.5: refreshed %s line %s (pallet %s)",
                         l.picking_id.name, l.id, l.package_id.name or '-')
    _logger.info("0.4.5: refreshed pallet details on %d open withdrawal lines, %d changed",
                 len(lines), changed)
