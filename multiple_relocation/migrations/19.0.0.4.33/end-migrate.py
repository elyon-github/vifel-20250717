# -*- coding: utf-8 -*-
"""19.0.0.4.33: Picklist KG follows the client's 3-decimal flag.

The RR/WR/BFRR/BFWR prints already show KG with 3 decimals for clients with
"Special 3 Digit Decimal PDF Report" ticked (0.4.3 / 19.0.0.4.4), but the
Picklist (Studio report view, key below) kept a fixed precision 2 on the line
weight, the page subtotal and the grand total (M/WR/16801). Make those three
follow the flag. Only t-options whose t-esc is a KG value are touched; qty and
packs keep their own precision. The old arch is kept as an attachment on the
view. Running it again changes nothing.
"""
import base64
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.33'
KEY = 'studio_customization.studio_report_docume_1127fe43-e7e7-4f7d-9b4b-abcd95f913ee_document'
DIGITS = '(3 if doc.partner_id.x_studio_special_3_digit_decimal_pdf_report else 2)'
# <t t-esc="...x_studio_actual_kg" t-options="{... &quot;precision&quot;: 2 ...}"
# and <t t-esc="..._totals_by_uom[uom_name]['kg']" t-options="{... 2 ...}"
KG_TAG = re.compile(
    r'''(<t\b[^>]*\bt-esc="[^"]*(?:x_studio_actual_kg|\[(?:'|&apos;)kg(?:'|&apos;)\])"[^>]*?'''
    r'''\bt-options="[^"]*?(?:&quot;|")precision(?:&quot;|")\s*:\s*)2\b''')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    view = env['ir.ui.view'].with_context(active_test=False).search([('key', '=', KEY)])
    for v in view:
        arch = v.arch_db or ''
        new, count = KG_TAG.subn(lambda m: m.group(1) + DIGITS, arch)
        if not count:
            _logger.info("%s: view %s already follows the flag", TAG, v.id)
            continue
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'view_%s_before_%s.xml' % (v.id, TAG),
                    'res_model': 'ir.ui.view',
                    'res_id': v.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode(arch.encode('utf-8')),
                    'description': '%s: %d KG precision(s) 2 -> client flag' % (TAG, count),
                })
                v.write({'arch_db': new})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, v.id, exc_info=True)
            continue
        _logger.info("%s: view %s: %d KG precision(s) now follow the 3-decimal flag", TAG, v.id, count)
