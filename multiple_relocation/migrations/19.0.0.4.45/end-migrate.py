# -*- coding: utf-8 -*-
"""19.0.0.4.45: give repeated Pallet Breakdown # their own number.

Until 4.44 a duplicated line kept the # of the line it was copied from
(M/RR/11450: five pallets copied from line 31 all showed 31). In every
transfer, the earliest line with a # keeps it; each later line repeating
that # (or with no #) gets the next free number after the transfer's
highest, in the order it was created - the same as 4.44 now does for a
new copy. Lines that were not repeated keep their number.
Only the # changes. Old numbers are kept as a CSV attachment; running it
again finds nothing to do.
"""
import base64
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.45'


def migrate(cr, version):
    cr.execute("""
        WITH ranked AS (
            SELECT id, picking_id, NULLIF(x_studio_, 0) AS no,
                   ROW_NUMBER() OVER (PARTITION BY picking_id, NULLIF(x_studio_, 0)
                                      ORDER BY id) AS occ
              FROM stock_move_line
             WHERE picking_id IS NOT NULL
        ), extra AS (
            SELECT id, picking_id, no FROM ranked
             WHERE no IS NULL OR occ > 1
        ), top AS (
            SELECT picking_id, COALESCE(MAX(x_studio_), 0) AS top_no
              FROM stock_move_line
             WHERE picking_id IN (SELECT picking_id FROM extra)
             GROUP BY picking_id
        )
        SELECT e.id, sp.name, e.no,
               t.top_no + ROW_NUMBER() OVER (PARTITION BY e.picking_id ORDER BY e.id)
          FROM extra e
          JOIN top t ON t.picking_id = e.picking_id
          JOIN stock_picking sp ON sp.id = e.picking_id
         ORDER BY sp.name, e.id
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info("%s: no repeated # found", TAG)
        return

    csv = 'move_line_id,transfer,old_no,new_no\n' + ''.join(
        '%s,%s,%s,%s\n' % (r[0], r[1], r[2] or '', r[3]) for r in rows)
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    env['ir.attachment'].create({
        'name': '%s backup Pallet Breakdown numbers.csv' % TAG,
        'datas': base64.b64encode(csv.encode('utf-8')),
        'mimetype': 'text/csv',
    })

    cr.execute("CREATE TEMP TABLE vifel_renum (id int PRIMARY KEY, new_no int) ON COMMIT DROP")
    cr.executemany("INSERT INTO vifel_renum VALUES (%s, %s)",
                   [(r[0], r[3]) for r in rows])
    cr.execute("""
        UPDATE stock_move_line ml SET x_studio_ = r.new_no
          FROM vifel_renum r WHERE r.id = ml.id
    """)
    _logger.info("%s: renumbered %s lines on %s transfers", TAG, cr.rowcount,
                 len({r[1] for r in rows}))
