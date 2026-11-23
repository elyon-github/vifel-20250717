# -*- coding: utf-8 -*-
"""19.0.0.4.41: the Printed By dropdown keeps the name that was picked.

19.0.0.4.38 made the dropdown read-only with
    state == 'done' and is_locked and vifel_printed_by_name_id
The rule reads the dropdown itself: on a done transfer with an empty
Printed By, picking a name made the field read-only at once, and Odoo 19
does not send read-only fields when saving, so the name vanished on Save.

Use the same lock as the typed Printed By and the rest of the form:
    state == 'done' and not x_studio_edit_record
(done = read-only, the Unlock button / x_studio_edit_record makes it
editable again) and keep force_save so a picked name is always written.
Old arch kept as an attachment; running it again changes nothing.
"""
import base64
import logging

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.41'
DROPDOWN = 'vifel_printed_by_name_id'
LOCK_FIELD = 'x_studio_edit_record'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    if LOCK_FIELD in env['stock.picking']._fields:
        readonly = "state == 'done' and not %s" % LOCK_FIELD
    else:
        readonly = "state == 'done' and is_locked"
    views = env['ir.ui.view'].with_context(active_test=False).search([
        ('model', '=', 'stock.picking'), ('type', '=', 'form'),
    ]).filtered(lambda v: DROPDOWN in (v.arch_db or ''))
    for view in views:
        arch = view.arch_db or ''
        try:
            tree = etree.fromstring(arch)
        except Exception:
            _logger.warning("%s: view %s could not be parsed, left unchanged", TAG, view.id)
            continue
        changed = False
        for node in tree.xpath(".//field[@name='%s']" % DROPDOWN):
            if node.get('readonly') != readonly:
                node.set('readonly', readonly)
                changed = True
            if node.get('force_save') != '1':
                node.set('force_save', '1')
                changed = True
        if not changed:
            continue
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'view_%s_before_%s.xml' % (view.id, TAG),
                    'res_model': 'ir.ui.view', 'res_id': view.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode(arch.encode('utf-8')),
                    'description': '%s: Printed By dropdown read-only rule corrected' % TAG,
                })
                view.write({'arch_db': etree.tostring(tree, encoding='unicode')})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, view.id, exc_info=True)
            continue
        _logger.info("%s: view %s: Printed By dropdown read-only = %s", TAG, view.id, readonly)
