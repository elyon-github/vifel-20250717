# -*- coding: utf-8 -*-
"""0.4.15: Per Pallet reports repeat the item description at the top of
every printed page.

get_grouped_move_lines_for_report() flagged a repeat every 15 lines (RR) or
14 (WR), but the templates paginate on their own (13/12 rows per page, or by
row height), so the repeat drifted: on M/RR/07876 the description printed on
rows 1 and 16 of page 1, row 15 of page 2 and nowhere on page 3.

Python now flags only the first line and item changes. Each Per Pallet view
(RR, BFRR, WR, BFWR and their copies: every QWeb view calling
get_grouped_move_lines_for_report) shows the description when flagged OR when
the row is the first of its printed page (line_data_index == 0 in the page
loop). Views that paginate by row height also count that description in the
height of a page's first row, so the page still fits.

Only exact anchors are touched; running it twice changes nothing; a view
whose anchors are missing is left as it is (warning logged).
"""
import logging

from lxml import etree

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "line_data['show_description'] or line_data_index == 0"
OLD_IF = "line_data['show_description']"

# Height-based pagination: a page's first row now always carries the
# description, so reserve its height there.
HEIGHT_REPLACEMENTS = [
    ('<t t-set="row_px" t-value="[]"/>',
     '<t t-set="row_px" t-value="[]"/>'
     '<t t-set="row_desc_px" t-value="[]"/>'),
    ('<t t-set="_a" t-value="row_px.append(max(24, int(n_lines * desc_font * 1.15) + 2))"/>',
     '<t t-set="_a" t-value="row_px.append(max(24, int(n_lines * desc_font * 1.15) + 2))"/>'
     '<t t-set="_ad" t-value="row_desc_px.append(max(24, int((1 + str(ld[\'item_description\'] '
     'or \'\').count(\'&lt;br\')) * desc_font * 1.15) + 2))"/>'),
    ("<t t-set=\"_d\" t-value=\"pg.update({'px': pg['px'] + row_px[ix]})\"/>",
     "<t t-set=\"_d\" t-value=\"pg.update({'px': pg['px'] + "
     "(row_px[ix] if pg['px'] else row_desc_px[ix])})\"/>"),
]


def patch_per_pallet_arch(arch):
    """Return (new_arch, None), or (None, reason) when nothing is changed."""
    if MARK in arch:
        return None, 'already done'

    # 1. height-based pagination (only when ALL three anchors exist once)
    counts = [arch.count(old) for old, _new in HEIGHT_REPLACEMENTS]
    height_based = counts == [1, 1, 1]
    if any(counts) and not height_based:
        return None, 'height pagination anchors not as expected %s' % counts
    if height_based:
        for old, new in HEIGHT_REPLACEMENTS:
            arch = arch.replace(old, new)

    # 2. description shown on the first row of every printed page
    root = etree.fromstring(arch.encode('utf-8'))
    done = 0
    for el in root.iter():
        if el.get('t-if') != OLD_IF:
            continue
        loop = el.getparent()
        while loop is not None and not (
                loop.get('t-as') == 'line_data'
                and 'start_idx' in (loop.get('t-foreach') or '')):
            loop = loop.getparent()
        if loop is None:
            continue
        el.set('t-if', MARK)
        done += 1
    if done != 1:
        return None, 'page loop description t-if found %s times' % done
    return etree.tostring(root, encoding='unicode'), None


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    views = env['ir.ui.view'].with_context(active_test=False).search([
        ('type', '=', 'qweb'),
        ('arch_db', 'ilike', 'get_grouped_move_lines_for_report'),
    ])
    for view in views:
        new_arch, reason = patch_per_pallet_arch(view.arch_db or '')
        if new_arch is None:
            if reason != 'already done':
                _logger.warning("Per Pallet description: view %s (id %s) not changed: %s",
                                view.key, view.id, reason)
            continue
        view.write({'arch_db': new_arch})
        _logger.info("Per Pallet description: view %s (id %s) patched", view.key, view.id)
