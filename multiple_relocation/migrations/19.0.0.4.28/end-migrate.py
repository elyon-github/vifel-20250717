# -*- coding: utf-8 -*-
"""19.0.0.4.28: RR/WR print buttons owned by the module, not by Studio.

Consultant-Test-19, 11-18: the RR and WR print buttons (Receiving / Withdrawal
R. Summary and Per Pallet) disappeared from Transfers after the Transfer form
was saved once in Studio. On 17 the module view put 4 old report buttons in
the header and a Studio view replaced them with the 4 print server actions.
Studio 19 rewrote that Studio view on save and turned the 4 buttons into
<b>/<br> tags, so they no longer showed.

views.xml now calls the 4 print server actions directly. This script:
1. removes, from the Studio views on stock.picking, every xpath that still
   points at the old report buttons or (re)defines the 4 print buttons, so
   nothing fights the module buttons, garbled or not;
2. keeps the "Printed By" field added in Studio on 11-18
   (x_studio_printed_by_name, after First Date/Time Printed), which the next
   restore of the live backup would otherwise drop.

The old arch is kept as an attachment on the view. Running it again changes
nothing.
"""
import base64
import logging
import re

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.28'

STALE = re.compile(
    r"withdrawal_report_co_bcde3da2-155e-480b-a43d-604c0359ca36"
    r"|receiving_report_fin_73786620-334b-443e-8828-5d6872e62187"
    r"|bfwr_final_69f184c6-7101-4113-bf02-559f8e2f89eb"
    r"|bfwr_final_129e37d2-2dc6-4e1d-ac5b-fd830adb4bfc"
    r"|studio_customization\.print_(receiving|withdrawal)_r_(summary|per_pallet)\b"
)

PRINTED_BY = 'x_studio_printed_by_name'
PRINTED_BY_ANCHOR = 'x_studio_first_date_time_printed'
PRINTED_BY_XPATH = (
    '<xpath expr="//field[@name=\'%s\']" position="after">'
    '<field name="%s" placeholder="Place indicate your name when printing RR/WR"/>'
    '</xpath>' % (PRINTED_BY_ANCHOR, PRINTED_BY)
)


def _backup(env, view, why):
    env['ir.attachment'].create({
        'name': 'view_%s_before_%s.xml' % (view.id, TAG),
        'res_model': 'ir.ui.view',
        'res_id': view.id,
        'mimetype': 'application/xml',
        'datas': base64.b64encode((view.arch_db or '').encode('utf-8')),
        'description': '%s: %s' % (TAG, why),
    })


def _studio_picking_views(env):
    data = env['ir.model.data'].search([
        ('model', '=', 'ir.ui.view'), ('module', '=', 'studio_customization')])
    return env['ir.ui.view'].with_context(active_test=False).browse(
        data.mapped('res_id')).exists().filtered(
        lambda v: v.model == 'stock.picking' and v.type == 'form' and v.mode == 'extension')


def _drop_stale_xpaths(env, cr):
    for view in _studio_picking_views(env):
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
                _backup(env, view, 'removed %d xpath(s):\n%s' % (len(removed), '\n'.join(removed)))
                view.write({'arch_db': etree.tostring(tree, encoding='unicode')})
        except Exception:
            _logger.warning("%s: view %s left unchanged", TAG, view.id, exc_info=True)
            continue
        _logger.info("%s: view %s: %d old print-button xpath(s) removed", TAG, view.id, len(removed))


def _printed_by(env, cr):
    Fields = env['ir.model.fields']
    if not Fields.search([('model', '=', 'stock.picking'), ('name', '=', PRINTED_BY)]):
        Fields.create({
            'name': PRINTED_BY,
            'model_id': env['ir.model']._get_id('stock.picking'),
            'field_description': 'Printed By',
            'ttype': 'char',
            'state': 'manual',
            'copied': False,
        })
        _logger.info("%s: field stock.picking.%s created", TAG, PRINTED_BY)

    # load_all_views: during -u Odoo leaves DB-only (Studio) views out of the
    # combined arch, and the anchor field lives in the Studio view.
    combined = env['stock.picking'].with_context(load_all_views=True).get_view(view_type='form')['arch']
    if ('name="%s"' % PRINTED_BY) in combined:
        return
    if ('name="%s"' % PRINTED_BY_ANCHOR) not in combined:
        _logger.warning("%s: %s not on the Transfer form; Printed By not placed", TAG, PRINTED_BY_ANCHOR)
        return
    views = _studio_picking_views(env).filtered('active').sorted('priority')
    if not views:
        _logger.warning("%s: no Studio Transfer form view; Printed By not placed", TAG)
        return
    view = views[-1]
    tree = etree.fromstring(view.arch_db)
    tree.append(etree.fromstring(PRINTED_BY_XPATH))
    try:
        with cr.savepoint():
            _backup(env, view, 'added Printed By field')
            view.write({'arch_db': etree.tostring(tree, encoding='unicode')})
    except Exception:
        _logger.warning("%s: Printed By not placed on view %s", TAG, view.id, exc_info=True)
        return
    _logger.info("%s: Printed By placed on view %s", TAG, view.id)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    _drop_stale_xpaths(env, cr)
    _printed_by(env, cr)
