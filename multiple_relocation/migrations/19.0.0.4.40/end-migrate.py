# -*- coding: utf-8 -*-
"""19.0.0.4.40: Verify Transfer checks the Printed By dropdown.

The 19.0.0.4.34 check in "X_Verifier Check on Receipt" read the typed text
field, which 19.0.0.4.38 hid behind the dropdown. A name typed there earlier
(M/RR/11316 "noelma") let Verify pass while the dropdown showed empty.
Switch the check to stock.picking.vifel_printed_by_missing() (dropdown).
4.34 now writes this form itself, so a fresh database finds nothing here.
"""
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD = re.compile(
    r"if 'x_studio_printed_by_name' in record\._fields and not "
    r"\(record\['x_studio_printed_by_name'\] or ''\)\.strip\(\):")
NEW = "if record.vifel_printed_by_missing():"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    actions = env['ir.actions.server'].with_context(active_test=False).search([
        ('code', 'ilike', 'Printed By is required too (19.0.0.4.34)')])
    for action in actions:
        new, n = OLD.subn(NEW, action.code or '')
        if n:
            action.write({'code': new})
            _logger.info("19.0.0.4.40: action %s (%s): Printed By check now reads the dropdown", action.id, action.name)
