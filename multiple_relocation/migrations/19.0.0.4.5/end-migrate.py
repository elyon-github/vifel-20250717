# -*- coding: utf-8 -*-
"""19.0.0.4.5 (end script): Studio opens again on Transfers (Reports tab "Oops!").

Studio views saved on 17 contain xpaths whose anchor no longer exists in the
Odoo 19 views. With Studio off, web_studio skips such an xpath silently
(_apply_studio_specs), so users never noticed. With Studio on, the same xpath
raises, and Studio cannot open Views/Reports for that model, e.g.:

    Element '<xpath expr="...move_ids']/list[1]/field[@name='display_assign_serial']">'
    cannot be located in parent view

Fix, per active Studio extension view:
1. Known re-anchors (REANCHOR) keep the customization: on 17 the optional
   "ID" column sat after display_assign_serial; on 19 that column is gone from
   the operations list, so it is placed after display_import_lot (its 17
   neighbour) instead.
2. Every other xpath is replayed exactly as Studio does it, on the arch built
   from all views applied before this one. An xpath that still cannot be
   located is removed: it is already skipped for every user today, so the
   screens do not change. The original arch is kept as an attachment
   (res_model ir.ui.view, res_id = view id) and each removal is logged.

Running it again changes nothing: a clean view has nothing to remove.

Why an END script with load_all_views: during -u, ir.ui.view only combines
views of modules already reloaded (_filter_loaded_views), so a post-migrate
sees an incomplete form and would drop live customizations (seen on the 19
test build 11-09: Operation Types' Vifel Operation Type field). End scripts
run after every module is loaded; load_all_views=True includes DB-only views.
A view that cannot be saved (validation fails for an unrelated reason) is
left as is with a WARNING; an ERROR would fail the Odoo.sh build.
"""
import base64
import copy
import logging

from lxml import etree

from odoo import api, SUPERUSER_ID
from odoo.tools.template_inheritance import apply_inheritance_specs

_logger = logging.getLogger(__name__)

TAG = 'VIFEL 19.0.0.4.5 Studio xpath cleanup'

OPS_LIST = "//form[1]/sheet[1]/notebook[1]/page[@name='operations']/field[@name='move_ids']/list[1]"
REANCHOR = [
    (OPS_LIST + "/field[@name='display_assign_serial']",
     OPS_LIST + "/field[@name='display_import_lot']"),
]


def _studio_views(env):
    data = env['ir.model.data'].search([
        ('model', '=', 'ir.ui.view'),
        ('module', '=', 'studio_customization'),
    ])
    views = env['ir.ui.view'].browse(data.mapped('res_id')).exists()
    return views.filtered(lambda v: v.active and v.mode == 'extension' and v.inherit_id)


def _clean(view):
    """Return (new_arch_or_None, removed_specs) for one Studio view."""
    arch_text = view.arch_db or ''
    for old, new in REANCHOR:
        arch_text = arch_text.replace('expr="%s"' % old, 'expr="%s"' % new)

    specs_tree = etree.fromstring(arch_text)
    # All views applied before this one, exactly what Studio builds on.
    source = view.with_context(load_all_views=True,
                               ir_ui_view_tree_cut_off_view=view)._get_combined_arch()

    removed = []
    for spec in list(specs_tree.iterchildren(tag=etree.Element)):
        try:
            source = apply_inheritance_specs(copy.deepcopy(source), copy.deepcopy(spec))
        except ValueError:
            removed.append(etree.tostring(spec, encoding='unicode'))
            specs_tree.remove(spec)

    new_arch = etree.tostring(specs_tree, encoding='unicode')
    if new_arch == etree.tostring(etree.fromstring(view.arch_db), encoding='unicode'):
        return None, removed
    return new_arch, removed


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'load_all_views': True})
    Attachment = env['ir.attachment']
    for view in _studio_views(env):
        try:
            new_arch, removed = _clean(view)
        except Exception:
            _logger.warning("%s: view %s (%s) not checked", TAG, view.id, view.name, exc_info=True)
            continue
        if new_arch is None:
            continue
        try:
            with cr.savepoint():
                Attachment.create({
                    'name': 'view_%s_before_19.0.0.4.5.xml' % view.id,
                    'res_model': 'ir.ui.view',
                    'res_id': view.id,
                    'mimetype': 'application/xml',
                    'datas': base64.b64encode(view.arch_db.encode('utf-8')),
                    'description': '%s\nremoved %d xpath(s):\n%s' % (TAG, len(removed), '\n'.join(removed)),
                })
                view.write({'arch_db': new_arch})
        except Exception:
            _logger.warning("%s: view %s (%s) left unchanged", TAG, view.id, view.name, exc_info=True)
            continue
        _logger.info("%s: view %s (%s) re-anchored/cleaned, %d xpath(s) removed",
                     TAG, view.id, view.name, len(removed))
        for spec in removed:
            _logger.info("%s: view %s removed %s", TAG, view.id, spec)
