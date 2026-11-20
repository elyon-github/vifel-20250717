# -*- coding: utf-8 -*-
"""19.0.0.4.36: undo the 19.0.0.4.34 Printed By check on validation.

The first 4.34 also patched the "Disable Validate if has Discrepancy"
automation (base_automation code action), which shares the required-fields
list with Verify Transfer. Printed By must only be required by Verify
Transfer, so remove the inserted block from any automation action. 4.34 now
only touches the Verify Transfer action, so on a database that never ran the
old 4.34 this finds nothing.
"""
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

BLOCK = re.compile(
    r"\n[ \t]*# Printed By is required too \(19\.0\.0\.4\.34\)\n"
    r"[ \t]*if 'x_studio_printed_by_name' in record\._fields[^\n]*\n"
    r"[ \t]*missing_fields\.append\([^\n]*\)\n")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    actions = env['ir.actions.server'].with_context(active_test=False).search([
        ('usage', '!=', 'ir_actions_server'),
        ('code', 'ilike', 'Printed By is required too (19.0.0.4.34)'),
    ])
    for action in actions:
        new, n = BLOCK.subn('\n', action.code or '')
        if n:
            action.write({'code': new})
            _logger.info("19.0.0.4.36: action %s (%s): Printed By check removed", action.id, action.name)
