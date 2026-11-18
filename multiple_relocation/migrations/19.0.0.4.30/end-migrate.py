# -*- coding: utf-8 -*-
"""19.0.0.4.30: variance tolerances 0 on the Consultant-Test-19 rehearsal.

On 11-18 the three "... Variance Acceptable Threshold" settings
(Inventory > Configuration > Inventory Static Variable Settings) were set
to 0 on Consultant-Test-19, so any difference between demand and actual
(e.g. M/RR/11083: +0.5 kg, -1 kg) flags the transfer and shows Print
Deviation Report. Each push to Consultant-Test-19 restores the live backup
(1 / 5 / 5), so this step sets them to 0 again.

!! REMOVE THIS STEP BEFORE THE REAL LIVE UPGRADE unless the client has
!! agreed to 0 tolerance on live: it would override live's values.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

NAMES = (
    'Quantity Variance Acceptable Threshold',
    'Weight (KG) Variance Acceptable Threshold',
    'Packs Variance Acceptable Threshold',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    if 'x_inventory_static_var' not in env:
        _logger.warning("19.0.0.4.30: x_inventory_static_var missing; tolerances not changed")
        return
    rows = env['x_inventory_static_var'].search([
        ('x_name', 'in', NAMES),
        ('x_studio_use_case', '=', 'Threshold Constraint'),
    ])
    changed = rows.filtered(lambda r: r.x_studio_float_value != 0)
    for row in changed:
        _logger.info("19.0.0.4.30: %s (%s) %s -> 0", row.x_name,
                     row.x_studio_warehouse.display_name, row.x_studio_float_value)
    changed.write({'x_studio_float_value': 0.0})
    _logger.info("19.0.0.4.30: %d of %d variance tolerances set to 0", len(changed), len(rows))
