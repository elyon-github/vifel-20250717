# -*- coding: utf-8 -*-
"""19.0.0.4.35: Print Count next to Last Print Date on RR/WR/BFRR/BFWR.

The 8 Summary / Per Pallet templates (19.0.0.4.29) print
    Last Print Date: <now>
This adds "Print Count: <Transfer's vifel_print_count>" on its own line
right below it (models/print_count.py counts each PDF print). Views found by key, old
arch kept as an attachment, a template already carrying it is skipped.
Existing Transfers start at 0: earlier prints were never counted.
"""
import base64
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.35'
P = 'studio_customization.studio_report_docume_603fbdfc-3014-4b3d-a461-45261cb3aeba_document'
KEYS = [P + s for s in ('', '_copy_1', '_copy_2', '_copy_3', '_copy_2_copy_1',
                        '_copy_3_copy_1', '_copy_2_copy_1_copy_1', '_copy_3_copy_1_copy_1')]
LAST = re.compile(r'(Last Print Date:\s*<t\b[^>]*?t-esc="[^"]*"[^>]*?/>)')
ADD = '<br/>Print Count: <t t-esc="doc.vifel_print_count or 0"/>'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    views = env['ir.ui.view'].with_context(active_test=False).search([('key', 'in', KEYS)])
    for view in views:
        arch = view.arch_db or ''
        if 'vifel_print_count' in arch:
            continue
        new, count = LAST.subn(lambda m: m.group(1) + ADD, arch)
        if not count:
            _logger.warning("%s: view %s (%s): no Last Print Date line, left unchanged", TAG, view.id, view.key)
            continue
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'view_%s_before_%s.xml' % (view.id, TAG),
                    'res_model': 'ir.ui.view', 'res_id': view.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode(arch.encode('utf-8')),
                    'description': '%s: Print Count added after Last Print Date' % TAG,
                })
                view.write({'arch_db': new})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, view.id, exc_info=True)
            continue
        _logger.info("%s: view %s: Print Count added (%d spot(s))", TAG, view.id, count)
