# -*- coding: utf-8 -*-
"""19.0.0.4.34: Verify Transfer also requires Printed By.

The Verify Transfer button runs server action "X_Verifier Check on Receipt"
(id 348 on live), which lists every empty required header field in one
"Please complete the following required fields" popup (Documentation Staff,
Truck Time, ...). Add Printed By (x_studio_printed_by_name, 19.0.0.4.28) to
that same list, for RR, WR, BFRR and BFWR. The old code is kept as an
attachment on the action. Running it again changes nothing.
"""
import base64
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.34'
MARK = "x_studio_printed_by_name"
ANCHOR = re.compile(
    r'\n(?P<ind>[ \t]*)if missing_fields:\n[ \t]*raise UserError\(\s*'
    r'"Please complete the following required fields')


def _block(ind):
    return (
        "\n{i}# Printed By is required too ({tag})\n"
        "{i}if '{f}' in record._fields and not (record['{f}'] or '').strip():\n"
        "{i}    missing_fields.append(\"\u2022 Printed By - next to NCR-Remarks\")\n"
    ).format(i=ind, tag=TAG, f=MARK)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    actions = env['ir.actions.server'].with_context(active_test=False).search([
        ('model_id.model', '=', 'stock.picking'),
        ('state', '=', 'code'),
        ('code', 'ilike', 'Please complete the following required fields'),
        # Only the Verify Transfer action. The same list also sits in the
        # "Disable Validate if has Discrepancy" automation (on validation),
        # which must not start requiring Printed By (automatic validations).
        ('usage', '=', 'ir_actions_server'),
        ('name', '=', 'X_Verifier Check on Receipt'),
    ])
    for action in actions:
        code = action.code or ''
        if MARK in code:
            _logger.info("%s: action %s already checks Printed By", TAG, action.id)
            continue
        m = ANCHOR.search(code)
        if not m:
            _logger.warning("%s: action %s (%s): anchor not found, left unchanged", TAG, action.id, action.name)
            continue
        new = code[:m.start()] + _block(m.group('ind')) + code[m.start():]
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'server_action_%s_before_%s.py' % (action.id, TAG),
                    'res_model': 'ir.actions.server',
                    'res_id': action.id,
                    'mimetype': 'text/plain',
                    'datas': base64.b64encode(code.encode('utf-8')),
                    'description': '%s: Printed By added to the required fields check' % TAG,
                })
                action.write({'code': new})
        except Exception:
            _logger.warning("%s: action %s left unchanged", TAG, action.id, exc_info=True)
            continue
        _logger.info("%s: action %s (%s): Printed By added to required fields", TAG, action.id, action.name)
