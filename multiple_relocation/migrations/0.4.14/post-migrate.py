# -*- coding: utf-8 -*-
"""0.4.14: RR Summary prints PACKS when the RR has packs.

The Receiving Report (Final) summary (Studio view, stored in the database)
had only QTY and WEIGHT(KG) under ACTUAL QUANTITY, so packs encoded in the
Pallet Breakdown (e.g. M/RR/07884, WONDER MEATS (FG): 3,700) showed only on
the Per Pallet report. prepare_report_data() already carries them
(heads_actual / heads_actual_main / special_rows['heads'] /
heads_actual_formatted); this adds a PACKS column after the actual QTY, the
same rule as the WR Summary: shown only when the document has packs, so RRs
without packs keep their old layout.

The template is edited structurally (lxml), so whitespace differences between
databases do not matter. If any anchor is missing the view is left untouched
and a warning is logged. Running it twice changes nothing.
"""
import logging

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KEY = ('studio_customization.studio_report_docume_'
       '603fbdfc-3014-4b3d-a461-45261cb3aeba_document_copy_2')
FLAG = 'vifel_rr_packs'
PACKS_FMT = "'{:,.0f}'.format(%s)"


def _el(tag, attrs, text=None):
    el = etree.Element(tag)
    for k, v in attrs.items():
        el.set(k, v)
    if text:
        el.text = text
    return el


def _td_containing(root, needle, attr='t-esc'):
    """The <td> that holds an element whose `attr` contains `needle`."""
    for el in root.iter():
        if needle in (el.get(attr) or ''):
            td = el
            while td is not None and td.tag != 'td':
                td = td.getparent()
            if td is not None:
                return td
    return None


def _insert_after(ref, new):
    new.tail = ref.tail
    ref.addnext(new)


def add_rr_summary_packs(arch):
    """Return (new_arch, None), or (None, reason) when nothing is changed."""
    if FLAG in arch:
        return None, 'already done'
    root = etree.fromstring(arch.encode('utf-8'))

    # 0. flag: does this RR have packs at all?
    pag = next((el for el in root.iter('t')
                if el.get('t-set') == 'pagination_data'), None)
    if pag is None:
        return None, 'pagination_data t-set not found'
    _insert_after(pag, _el('t', {
        't-set': FLAG,
        't-value': "bool(pagination_data['grand_totals'].get('heads_actual'))",
    }))

    # 1. ACTUAL QUANTITY header spans one more column
    actual = next((th for th in root.iter('th')
                   if (th.text or '').strip() == 'ACTUAL QUANTITY'), None)
    if actual is None:
        return None, 'ACTUAL QUANTITY header not found'
    actual.attrib.pop('colspan', None)
    actual.set('t-att-colspan', "3 if %s else 2" % FLAG)

    # 2. sub-header: QTY | WEIGHT | QTY | [PACKS] | WEIGHT
    sub = actual.getparent().getnext()
    ths = list(sub.iter('th')) if sub is not None else []
    if len(ths) != 4 or (ths[2].text or '').strip() != 'QTY':
        return None, 'sub-header QTY/WEIGHT row not as expected'
    _insert_after(ths[2], _el('th', {
        't-if': FLAG, 'style': ths[2].get('style', '')}, 'PACKS'))

    # 3. full-width cells span one more column
    for td in root.iter('td'):
        if td.get('colspan') == '6':
            td.attrib.pop('colspan')
            td.set('t-att-colspan', "7 if %s else 6" % FLAG)

    cell = {'style': 'padding: 1px; text-align: right;'}
    total_cell = {'style': 'text-align: right; padding: 2px;'}

    # 4. item row
    td = _td_containing(root, "move['packaging_qty_main']")
    if td is None:
        return None, 'item row actual QTY cell not found'
    new = _el('td', dict(cell, **{'t-if': FLAG}))
    new.append(_el('t', {'t-esc': PACKS_FMT % "move['heads_actual_main']",
                         't-if': "move['heads_actual_main']"}))
    _insert_after(td, new)

    # 5. special-pallet sub-rows
    td = _td_containing(root, "sr['packs']")
    if td is not None:
        new = _el('td', dict(cell, **{'t-if': FLAG}))
        new.append(_el('t', {'t-esc': PACKS_FMT % "sr['heads']",
                             't-if': "sr['heads']"}))
        _insert_after(td, new)

    # 6. ***NOTHING FOLLOWS*** row: one more empty cell
    for tr in list(root.iter('tr')):
        tds = [c for c in tr if c.tag == 'td']
        if len(tds) == 6 and any('NOTHING FOLLOWS' in (c.text or '') for c in tds):
            _insert_after(tds[4], _el('td', {'t-if': FLAG, 'style': 'padding: 1px;'}))

    # 7. page subtotal + 8. grand total (per-UOM formatted totals)
    for src in ("page_info['totals']['qty_actual_formatted']",
                "pagination_data['grand_totals']['qty_actual_formatted']"):
        td = _td_containing(root, src, attr='t-raw')
        if td is None:
            return None, '%s cell not found' % src
        new = _el('td', dict(total_cell, **{'t-if': FLAG}))
        new.append(_el('span', {'t-raw': src.replace('qty_actual_formatted',
                                                     'heads_actual_formatted')}))
        _insert_after(td, new)

    # 9. underline row under the totals (2 blank + 4 underlined cells)
    for tr in list(root.iter('tr')):
        tds = [c for c in tr if c.tag == 'td']
        if (len(tds) == 6 and tds[0].get('style') == 'border: none;'
                and all('border-bottom' in (c.get('style') or '') for c in tds[2:])):
            _insert_after(tds[4], _el('td', {
                't-if': FLAG, 'style': 'border-bottom: 1px solid black'}))

    # 10. final combined totals row
    td = _td_containing(root, "total_actual_qty + move['packaging_qty']", attr='t-value')
    if td is None:
        return None, 'final total actual QTY cell not found'
    new = _el('td', dict(total_cell, **{'t-if': FLAG}))
    new.append(_el('span', {
        't-esc': PACKS_FMT % "(pagination_data['grand_totals'].get('heads_actual') or 0)"}))
    _insert_after(td, new)

    return etree.tostring(root, encoding='unicode'), None


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    view = env['ir.ui.view'].with_context(active_test=False).search(
        [('key', '=', KEY), ('type', '=', 'qweb')], limit=1)
    if not view:
        _logger.warning("RR Summary packs: view %s not found", KEY)
        return
    new_arch, reason = add_rr_summary_packs(view.arch_db or '')
    if new_arch is None:
        _logger.warning("RR Summary packs: view %s (id %s) not changed: %s",
                        view.key, view.id, reason)
        return
    view.write({'arch_db': new_arch})
    _logger.info("RR Summary packs: PACKS column added to view id %s", view.id)
