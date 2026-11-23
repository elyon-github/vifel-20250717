# -*- coding: utf-8 -*-
"""19.0.0.4.38: Printed By becomes a dropdown.

In the Studio Transfer form, next to the typed Printed By
(x_studio_printed_by_name, placed by 19.0.0.4.28), add the dropdown
vifel_printed_by_name_id (models/printed_by_name.py) and hide the typed one.
Picking a name fills the text field, so reports, the print check, Verify
Transfer and the print history keep reading it. The dropdown is read-only
once the transfer is done; Unlock (x_studio_edit_record) makes it editable.
Old arch kept as an attachment; a view that already has the dropdown is
skipped; no anchor = warning, form untouched.
"""
import base64
import logging

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.38'
TEXT = 'x_studio_printed_by_name'
DROPDOWN = 'vifel_printed_by_name_id'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    data = env['ir.model.data'].search([
        ('model', '=', 'ir.ui.view'), ('module', '=', 'studio_customization')])
    views = env['ir.ui.view'].with_context(active_test=False).browse(
        data.mapped('res_id')).exists().filtered(
        lambda v: v.model == 'stock.picking' and v.type == 'form'
        and v.mode == 'extension' and TEXT in (v.arch_db or ''))
    placed = False
    for view in views:
        arch = view.arch_db or ''
        tree = etree.fromstring(arch)
        if tree.xpath(".//field[@name='%s']" % DROPDOWN):
            placed = True
            continue
        nodes = tree.xpath(".//field[@name='%s']" % TEXT)
        if not nodes:
            continue
        for node in nodes:
            node.set('invisible', '1')
        new = etree.Element('field', {
            'name': DROPDOWN,
            'string': 'Printed By',
            'options': "{'no_create': True, 'no_open': True}",
            # Same lock as the typed field: done = read-only until Unlock
            # (x_studio_edit_record). 19.0.0.4.41 corrects databases where
            # this ran with the older, self-referencing rule.
            'readonly': "state == 'done' and not x_studio_edit_record",
            'force_save': '1',
        })
        nodes[0].addnext(new)
        try:
            with cr.savepoint():
                env['ir.attachment'].create({
                    'name': 'view_%s_before_%s.xml' % (view.id, TAG),
                    'res_model': 'ir.ui.view', 'res_id': view.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode(arch.encode('utf-8')),
                    'description': '%s: Printed By dropdown added, typed field hidden' % TAG,
                })
                view.write({'arch_db': etree.tostring(tree, encoding='unicode')})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, view.id, exc_info=True)
            continue
        placed = True
        _logger.info("%s: view %s: Printed By dropdown placed", TAG, view.id)
    if not placed:
        _logger.warning("%s: typed Printed By not found on any Studio Transfer form; dropdown not placed", TAG)
