# -*- coding: utf-8 -*-
"""19.0.0.4.23: unwrap translated values the 17 -> 19 upgrade wrapped twice.

Found on the Odoo.sh test upgrade (11-17): every product.product.name came
back as {'en_US': '...'} instead of text, so the RR Summary crashed in
_wrap_text ("'dict' object has no attribute 'split'") and product names
showed as "{'en_US': 'X'}". The stored jsonb was {"en_US": {"en_US": "X"}}.
product.product.name is redefined here as a stored compute; it keeps the
template field's translate=True, and the upgrade wrapped it a second time.

Generic repair, so any other column hit the same way is fixed too: for every
stored char/text/html field whose column is jsonb, while a language key holds
an object instead of text, replace that key with the inner value for the same
language (or 'en_US', or the first inner text). Loops until clean (max 5).
Rows already correct are not touched; running it again changes nothing.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT DISTINCT m.model, f.name, c.table_name
          FROM ir_model_fields f
          JOIN ir_model m ON m.id = f.model_id
          JOIN information_schema.columns c
            ON c.table_name = replace(m.model, '.', '_')
           AND c.column_name = f.name
           AND c.data_type = 'jsonb'
           AND c.table_schema = current_schema()
          JOIN information_schema.tables t
            ON t.table_name = c.table_name
           AND t.table_schema = c.table_schema
           AND t.table_type = 'BASE TABLE'
         WHERE f.store AND f.ttype IN ('char', 'text', 'html')
    """)
    targets = cr.fetchall()
    total = 0
    for model, field, table in targets:
        fixed = 0
        for _round in range(5):
            cr.execute(f"""
                UPDATE "{table}" t
                   SET "{field}" = (
                       SELECT jsonb_object_agg(
                                  e.key,
                                  CASE WHEN jsonb_typeof(e.value) = 'object'
                                       THEN COALESCE(
                                                e.value -> e.key,
                                                e.value -> 'en_US',
                                                (SELECT i.value FROM jsonb_each(e.value) i LIMIT 1))
                                       ELSE e.value END)
                         FROM jsonb_each(t."{field}") e)
                 WHERE jsonb_typeof(t."{field}") = 'object'
                   AND EXISTS (SELECT 1 FROM jsonb_each(t."{field}") x
                                WHERE jsonb_typeof(x.value) = 'object')
            """)
            if not cr.rowcount:
                break
            fixed += cr.rowcount
        if fixed:
            total += fixed
            _logger.info("19.0.0.4.23: %s.%s: unwrapped double-wrapped translations on %s row(s)",
                         model, field, fixed)
    _logger.info("19.0.0.4.23: checked %s translated jsonb column(s), %s row update(s)",
                 len(targets), total)
