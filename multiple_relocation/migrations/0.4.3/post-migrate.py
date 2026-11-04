# -*- coding: utf-8 -*-
"""0.4.3: KG weights follow the client's 3-decimal checkbox on every report.

res.partner.x_studio_special_3_digit_decimal_pdf_report ("Special 3 Digit
Decimal PDF Report") already switched RR/WR line weights to 3 decimals, but
BFRR/BFWR ignored it and some totals rows (e.g. the second RR Summary total)
were hard-coded to 2 decimals.

The report templates are Studio views stored in the database, so they are
patched here by key: every '{:,.2f}'.format( / '{:.2f}'.format( outside an
XML comment becomes conditional on the checkbox. Heads/packs counts are not
weights and are left alone. Converted spots no longer match, so running this
twice changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PREFIX = ('studio_customization.studio_report_docume_'
          '603fbdfc-3014-4b3d-a461-45261cb3aeba_document')
SUFFIXES = [
    '',                          # BFWR (Final)
    '_copy_1',                   # BFRR (Final)
    '_copy_2',                   # Receiving Report (Final) - RR Summary
    '_copy_3',                   # Withdrawal Report - Consolidated (Final)
    '_copy_2_copy_1',            # Receiving Report (Final) (Per Pallet)
    '_copy_3_copy_1',            # Withdrawal Report - Per Pallet (Final)
    '_copy_2_copy_1_copy_1',     # BFRR (Final) (Per Pallet)
    '_copy_3_copy_1_copy_1',     # BFWR - Per Pallet (Final)
]
FLAG = 'doc.partner_id.x_studio_special_3_digit_decimal_pdf_report'
PAIRS = [
    ("'{:,.2f}'.format(", "('{:,.3f}' if %s else '{:,.2f}').format(" % FLAG),
    ("'{:.2f}'.format(", "('{:.3f}' if %s else '{:.2f}').format(" % FLAG),
]


def _patch_arch(arch):
    """Return (new_arch, spots_changed); XML comments are left untouched."""
    out = []
    changed = 0
    chunks = arch.split('<!--')
    for i, chunk in enumerate(chunks):
        comment, live = '', chunk
        if i:
            if '-->' in chunk:
                body, live = chunk.split('-->', 1)
                comment = '<!--' + body + '-->'
            else:
                comment, live = '<!--' + chunk, ''
        for old, new in PAIRS:
            parts = live.split(old)
            rebuilt = parts[0]
            for part in parts[1:]:
                if 'heads' in part[:40]:
                    rebuilt += old + part
                else:
                    rebuilt += new + part
                    changed += 1
            live = rebuilt
        out.append(comment + live)
    return ''.join(out), changed


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'x_studio_special_3_digit_decimal_pdf_report' not in env['res.partner']._fields:
        _logger.warning("3-decimal reports: partner checkbox missing, skipped")
        return
    View = env['ir.ui.view'].with_context(active_test=False)
    for suffix in SUFFIXES:
        view = View.search([('key', '=', PREFIX + suffix), ('type', '=', 'qweb')], limit=1)
        if not view:
            _logger.warning("3-decimal reports: view %s not found", PREFIX + suffix)
            continue
        arch, changed = _patch_arch(view.arch_db)
        if changed:
            view.write({'arch_db': arch})
        _logger.info("3-decimal reports: %s (id %s) %s spot(s) converted",
                     view.name, view.id, changed)
