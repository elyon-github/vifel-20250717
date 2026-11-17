# -*- coding: utf-8 -*-
"""19.0.0.4.24: plain-text columns for fields that are no longer translated on 19.

Found on the Odoo.sh test upgrade (11-17): product.product.name (redefined
here as a stored compute) is translatable on 17, so its column is jsonb
{"en_US": "X"}. On 19 the same field is NOT translated, but the column stayed
jsonb, so every variant name reads back as the raw {'en_US': 'X'}:
- RR Summary crashed in _wrap_text ("'dict' object has no attribute 'split'");
- searching products by name failed ("invalid input syntax for type json").
(19.0.0.4.23 looked for double-wrapped values; there were none.)

With all modules loaded, for every stored char/text/html field whose 19
definition is not translated but whose column is still jsonb, convert the
column back to text with Odoo's own helper (keeps the en_US value) and clear
the stale 'translate' flag in ir_model_fields. Columns already right are
left alone; running it again changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID
from odoo.tools import sql

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    fixed = []
    for model_name in list(env.registry):
        model = env[model_name]
        if model._abstract or not model._auto or model._table_query:
            continue
        for field in model._fields.values():
            if (not field.store or field.translate
                    or field.type not in ('char', 'text', 'html')
                    or field.inherited):
                continue
            cr.execute("""
                SELECT udt_name FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = %s AND column_name = %s
            """, (model._table, field.name))
            row = cr.fetchone()
            if not row or row[0] != 'jsonb':
                continue
            sql.convert_column_translatable(cr, model._table, field.name, field.column_type[1])
            cr.execute("""
                UPDATE ir_model_fields SET translate = NULL
                 WHERE model = %s AND name = %s
            """, (model_name, field.name))
            fixed.append(f"{model_name}.{field.name}")
            _logger.info("19.0.0.4.24: %s.%s jsonb -> %s (not translated on 19)",
                         model_name, field.name, field.column_type[1])
    if fixed:
        env.invalidate_all()
    _logger.info("19.0.0.4.24: %s column(s) converted: %s", len(fixed), fixed)
