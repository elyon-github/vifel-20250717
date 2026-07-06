# -*- coding: utf-8 -*-
"""Create global warehouse rules for STUDIO models.

Studio models (x_inventory_static_var, x_warehouse_building) exist only in the
database — their ir.model xmlids are per-DB UUIDs, so the rules cannot be
declared in module XML. This hook creates them by model-name lookup, only when
the model (and its x_studio_warehouse field) actually exists. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)

STUDIO_RULES = [
    ('x_inventory_static_var', 'Inventory Static Var: user\'s allowed warehouses'),
    ('x_warehouse_building', 'Warehouse Building: user\'s allowed warehouses'),
]

DOMAIN = ("['|', ('x_studio_warehouse', 'in', user.allowed_warehouse_ids.ids),"
          " ('x_studio_warehouse', '=', False)]"
          " if user.allowed_warehouse_ids else [(1, '=', 1)]")


def post_init_hook(env):
    Rule = env['ir.rule']
    Fields = env['ir.model.fields']
    for model_name, rule_name in STUDIO_RULES:
        model = env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            _logger.info("Studio model %s not present; skipping its rule", model_name)
            continue
        if not Fields.search_count([('model', '=', model_name),
                                    ('name', '=', 'x_studio_warehouse')], limit=1):
            _logger.warning("Studio model %s has no x_studio_warehouse; skipping",
                            model_name)
            continue
        if Rule.with_context(active_test=False).search_count(
                [('name', '=', rule_name), ('model_id', '=', model.id)], limit=1):
            continue
        Rule.create({
            'name': rule_name,
            'model_id': model.id,
            'domain_force': DOMAIN,
            # no groups -> global rule, same as security/multi_warehouse_rules.xml
        })
        _logger.info("Created global warehouse rule for %s", model_name)
