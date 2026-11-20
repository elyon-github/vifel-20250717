# -*- coding: utf-8 -*-
"""19.0.0.4.22: retire app_common and odoo_calculator_tool after the 17 -> 19 upgrade.

Both third-party modules are installed on live 17 but have no Odoo 19
release, so the 19 code does not ship them. After the upgrade they stay
'installed' / 'to upgrade' in ir_module_module, which makes every update log
"Some modules have inconsistent states ... ['app_common',
'odoo_calculator_tool']" (Odoo.sh: Test Failed), and their leftover views
break screens (Settings: "app_saas_ok field is undefined"; the ir.cron list
xpath on 'active').

This end script runs just before that check (odoo/modules/loading.py STEP
3.5), so the same update is clean:
1. every view owned by the two modules is switched off (kept, not deleted);
2. both modules are marked 'uninstalled'.
Nothing VIFEL depends on them. Their own tables/columns are left in place,
unused. If they were already uninstalled on 17 before the upgrade (the
go-live plan), this script finds nothing and changes nothing.
"""
import logging

_logger = logging.getLogger(__name__)

RETIRED = ('app_common', 'odoo_calculator_tool')


def migrate(cr, version):
    cr.execute("""
        SELECT name, state FROM ir_module_module
         WHERE name IN %s AND state != 'uninstalled'
    """, (RETIRED,))
    modules = cr.fetchall()
    if not modules:
        _logger.info("19.0.0.4.22: app_common / odoo_calculator_tool already uninstalled")
        return

    cr.execute("""
        UPDATE ir_ui_view v SET active = false
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
           AND d.module IN %s AND v.active
        RETURNING v.id
    """, (RETIRED,))
    view_ids = [row[0] for row in cr.fetchall()]
    _logger.info("19.0.0.4.22: switched off %s view(s) of the retired modules: %s",
                 len(view_ids), view_ids)

    cr.execute("""
        UPDATE ir_module_module SET state = 'uninstalled'
         WHERE name IN %s AND state != 'uninstalled'
    """, (RETIRED,))
    for name, state in modules:
        _logger.info("19.0.0.4.22: module %s %s -> uninstalled", name, state)
