# -*- coding: utf-8 -*-
"""0.4.11: WR Summary prints the building of every pallet on the WR.

The Withdrawal Summary headers (Studio views, stored in the database) printed
only the FIRST line's building:
    doc.move_line_ids[0].location_id.x_studio_building.x_name
while the picklist printed the WR's own source location, which is always 'M'
(MAIN) in Meycauayan. M/WR/10648 therefore showed EXPANSION on the summary and
MAIN on the picklist, although its pallets came from EXPANSION and ANNEX.

Both now use stock.picking.get_branch_from_location('WR'), which lists every
building on the lines ('EXPANSION / ANNEX'). Only WR Summary views
(..._document_copy_3*) are touched and only the exact expression is replaced,
so running this twice changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PREFIX = ('studio_customization.studio_report_docume_'
          '603fbdfc-3014-4b3d-a461-45261cb3aeba_document_copy_3')
OLD = 'doc.move_line_ids[0].location_id.x_studio_building.x_name'
NEW = "doc.get_branch_from_location('WR')"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    View = env['ir.ui.view'].with_context(active_test=False)
    views = View.search([('key', '=like', PREFIX + '%'), ('type', '=', 'qweb')])
    for view in views:
        arch = view.arch_db or ''
        count = arch.count(OLD)
        if count:
            view.write({'arch_db': arch.replace(OLD, NEW)})
        _logger.info("WR building: %s (id %s) %s spot(s) replaced",
                     view.key, view.id, count)
