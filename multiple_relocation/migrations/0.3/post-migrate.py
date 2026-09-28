# -*- coding: utf-8 -*-
"""0.3: Noted By moves from a contact (res.partner, vifel_noted_by_id) to a
typed name (vifel.noted.by.name, vifel_noted_by_name_id).

A transfer that already has the old contact-based Noted By keeps the same
name: the contact's name is added to the Noted By list and linked. The old
column is left in place, untouched.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'stock_picking' AND column_name = 'vifel_noted_by_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO vifel_noted_by_name (name, sequence, active,
                                         create_uid, write_uid, create_date, write_date)
        SELECT DISTINCT trim(p.name), 10, true, 1, 1,
               now() at time zone 'UTC', now() at time zone 'UTC'
          FROM stock_picking sp
          JOIN res_partner p ON p.id = sp.vifel_noted_by_id
         WHERE coalesce(trim(p.name), '') <> ''
        ON CONFLICT (name) DO NOTHING
    """)
    cr.execute("""
        UPDATE stock_picking sp
           SET vifel_noted_by_name_id = n.id
          FROM res_partner p, vifel_noted_by_name n
         WHERE p.id = sp.vifel_noted_by_id
           AND n.name = trim(p.name)
           AND sp.vifel_noted_by_name_id IS NULL
    """)
