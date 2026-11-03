# -*- coding: utf-8 -*-
"""0.4.2: copy every adjustment change text into vifel_correction_note.

The text was stored only in stock_move_line.reference. Odoo 19 no longer
stores that column, so it must be copied into our own field BEFORE the
17 -> 19 upgrade (VIF-130). Rows already filled are left alone, so running
this twice changes nothing.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'stock_move_line' AND column_name = 'reference'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE stock_move_line
           SET vifel_correction_note = reference
         WHERE vifel_correction_note IS NULL
           AND reference LIKE '%%CORRECTION (%%'
    """)
    _logger.info("VIF-130: copied %s adjustment change texts into "
                 "vifel_correction_note", cr.rowcount)
