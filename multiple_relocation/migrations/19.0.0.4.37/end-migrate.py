# -*- coding: utf-8 -*-
"""19.0.0.4.37: Print Count on its own line below Last Print Date.

The first 19.0.0.4.35 put it on the Last Print Date line
("Last Print Date: ... | Print Count: N"). Move it to its own line, like
Printed By and Last Print Date. 4.35 now writes the separate line itself, so
on a database that never ran the old 4.35 this finds nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

P = 'studio_customization.studio_report_docume_603fbdfc-3014-4b3d-a461-45261cb3aeba_document'
KEYS = [P + s for s in ('', '_copy_1', '_copy_2', '_copy_3', '_copy_2_copy_1',
                        '_copy_3_copy_1', '_copy_2_copy_1_copy_1', '_copy_3_copy_1_copy_1')]
OLD = ' | Print Count: <t t-esc="doc.vifel_print_count or 0"/>'
NEW = '<br/>Print Count: <t t-esc="doc.vifel_print_count or 0"/>'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    for view in env['ir.ui.view'].with_context(active_test=False).search([('key', 'in', KEYS)]):
        arch = view.arch_db or ''
        if OLD in arch:
            view.write({'arch_db': arch.replace(OLD, NEW)})
            _logger.info("19.0.0.4.37: view %s: Print Count moved to its own line", view.id)
