# -*- coding: utf-8 -*-
"""19.0.0.4.31: BF print buttons owned by the module (Printed By check).

All 8 RR/WR/BFRR/BFWR Summary / Per Pallet buttons now live in
views/views.xml and call methods that require "Printed By" first
(models/stock_picking_print_guard.py). The Studio Transfer form still
carried its own copies of the two BF Per Pallet buttons, anchored on the BF
Withdrawal R. Summary button, which now has a new name. Remove every Studio
xpath that still refers to the old BF print buttons so they are not shown
twice or left pointing at nothing. The old arch is kept as an attachment on
the view. Running it again changes nothing.
"""
import base64
import logging
import re

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.31'
STALE = re.compile(
    r"studio_customization\.print_bf_(receiving|withdrawal)_r_(summary|per_pallet)\b")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    data = env['ir.model.data'].search([
        ('model', '=', 'ir.ui.view'), ('module', '=', 'studio_customization')])
    views = env['ir.ui.view'].with_context(active_test=False).browse(
        data.mapped('res_id')).exists().filtered(
        lambda v: v.model == 'stock.picking' and v.type == 'form' and v.mode == 'extension')
    for view in views:
        tree = etree.fromstring(view.arch_db)
        removed = []
        for spec in list(tree.iterchildren(tag=etree.Element)):
            text = etree.tostring(spec, encoding='unicode')
            if STALE.search(text):
                removed.append(text)
                tree.remove(spec)
        if not removed:
            continue
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'view_%s_before_%s.xml' % (view.id, TAG),
                    'res_model': 'ir.ui.view',
                    'res_id': view.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode((view.arch_db or '').encode('utf-8')),
                    'description': '%s: removed %d xpath(s):\n%s' % (TAG, len(removed), '\n'.join(removed)),
                })
                view.write({'arch_db': etree.tostring(tree, encoding='unicode')})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, view.id, exc_info=True)
            continue
        _logger.info("%s: view %s: %d old BF print-button xpath(s) removed", TAG, view.id, len(removed))
