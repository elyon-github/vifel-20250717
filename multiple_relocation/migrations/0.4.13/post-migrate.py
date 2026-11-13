# -*- coding: utf-8 -*-
"""0.4.13: WR Per Pallet report KG totals round half-up.

The Withdrawal Report - Per Pallet (Studio views, stored in the database) adds
the line weights inside the template and prints them with '{:,.2f}'.format(),
which rounds the binary float: M/WR/10648 summed to 6531.165 (stored as
6531.16499...) and printed Grand Total 6,531.16, while the Picklist, the WR
Summary and the Pallet Breakdown print 6,531.17.

Each weight that the template formats is wrapped in
doc.round_report_kg(...) (half-up, 2 or 3 decimals like the template's own
choice). Only Per Pallet WR views (..._document_copy_3_copy_1*) are touched,
only the exact expressions are replaced, so running this twice changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PREFIX = ('studio_customization.studio_report_docume_'
          '603fbdfc-3014-4b3d-a461-45261cb3aeba_document_copy_3_copy_1')
REPLACEMENTS = [
    (".format(line_data['weight'] if line_data['weight'] is not None else 0)",
     ".format(doc.round_report_kg(line_data['weight']))"),
    (".format(uom_total[1] if uom_total[1] is not None else 0)",
     ".format(doc.round_report_kg(uom_total[1]))"),
    (".format(uom_weights.get(current_uom, 0))",
     ".format(doc.round_report_kg(uom_weights.get(current_uom, 0)))"),
    (".format(total_weight)",
     ".format(doc.round_report_kg(total_weight))"),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    View = env['ir.ui.view'].with_context(active_test=False)
    views = View.search([('key', '=like', PREFIX + '%'), ('type', '=', 'qweb')])
    for view in views:
        arch = view.arch_db or ''
        total = 0
        for old, new in REPLACEMENTS:
            n = arch.count(old)
            if n:
                arch = arch.replace(old, new)
                total += n
        if total:
            view.write({'arch_db': arch})
        _logger.info("WR per pallet KG rounding: %s (id %s) %s spot(s) replaced",
                     view.key, view.id, total)
