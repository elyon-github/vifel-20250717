# -*- coding: utf-8 -*-
"""19.0.0.4.25: the manual 17 -> 19 database fixes, as an automatic script.

On the first 19 test (09-30 .. 10-16) these ran by hand as SQL
(_upgrade_db_fixes 01, 03, 05, 06, 07). The Odoo.sh test upgrade of 11-17
started from a fresh live copy without them: RR Summary / Per Pallet failed
with "'stock.picking' object has no attribute 'move_ids_without_package'".
upgrade.odoo.com migrates records but never rewrites code stored in the
database (Studio templates, server actions, Studio computes), and it
switches off VIFEL views it cannot check.

01 Studio views / server actions: move_ids_without_package -> move_ids,
   stock.quant.package -> stock.package (model and table names).
03 stock.picking.date and stock.move.name are gone on 19: Studio reports
   "doc.date" -> "doc.create_date"; old Deviation Report move text.
05 re-enable the VIFEL views the upgrade switched off (by XML id).
06 Studio compute x_studio_exp_warned (move_line_ids_without_package) and
   the "Use Lots on Creation of Product" automation (detailed_type).
07 Auto-Fill Locations (SA 300): ('m2m', '=', '') matches OCCUPIED slots
   on 19; compare with False only.
(02 = 19.0.0.4.24, 04 = 19.0.0.4.22.)
Every step only touches rows that still hold the old text, so running it
again changes nothing.
"""
import logging

_logger = logging.getLogger(__name__)

REENABLE = (
    'studio_customization.odoo_studio_stock_pi_558655e8-d302-48da-a412-6c8ab7382532',
    'multiple_relocation.view_form_stock_picking_inherit_return_package',
    'studio_customization.odoo_studio_stock_qu_d8376b11-c069-45eb-8658-b5a15be0192f',
    'multiple_relocation.view_stock_quant_package_tree_highlighting',
    'studio_customization.odoo_studio_stock_pi_129811a1-9bf9-4c26-97b0-af48c232dc1a',
    'studio_customization.odoo_studio_stock_qu_3584672e-8c54-413b-98f9-10da91374527',
    'studio_customization.odoo_studio_stock_mo_159148a3-eb90-4698-b4fd-adb904791db3',
    'studio_customization.odoo_studio_stock_mo_36de357b-c2b4-4886-90d7-5b2f23980895',
    'studio_customization.odoo_studio_stock_qu_ff51292e-3106-4dd5-beb2-4af5a189db82',
    'multiple_relocation.view_stock_move_line_detailed_operation_tree_inherit',
    'vifel_client_requirements.view_move_line_detailed_op_merge_button',
    'multiple_relocation.view_stock_picking_form_custom',
    'pallet_series_audit.view_picking_form_pallet_audit',
    'vifel_client_requirements.view_picking_form_batch_no',
    'multiple_relocation.view_stock_move_line_adjustment_history_tree',
    'multiple_relocation.view_stock_move_line_relocation_history_tree',
    'studio_customization.odoo_studio_product__862c0b03-e1f3-4a68-b8b2-518cfe6a5e08',
    'studio_customization.odoo_studio_product__c03c8b77-6974-434c-8448-3f047bed1ac8',
    'studio_customization.odoo_studio_stock_lo_d4022610-6ffc-497f-9546-a511866149ab',
    'multiple_relocation.search_stock_quant_filters',
    'multiple_relocation.view_stock_quant_tree_simple_sh_restrict',
)

DEVIATION_OLD_KEY = 'studio_customization.studio_report_docume_6b5647c5-0b65-4075-ac70-c1e07e0fd9fd_document'


def _replace_in_views(cr, label, old, new, extra_where='', params=()):
    """Replace text in every language of ir_ui_view.arch_db (jsonb)."""
    cr.execute(f"""
        UPDATE ir_ui_view v
           SET arch_db = (SELECT jsonb_object_agg(k, replace(val, %s, %s))
                            FROM jsonb_each_text(v.arch_db) AS t(k, val))
         WHERE EXISTS (SELECT 1 FROM jsonb_each_text(v.arch_db) AS t(k, val)
                        WHERE strpos(val, %s) > 0)
           {extra_where}
        RETURNING v.id
    """, (old, new, old) + tuple(params))
    ids = [r[0] for r in cr.fetchall()]
    _logger.info("19.0.0.4.25: %s: %s view(s) %s", label, len(ids), ids)


def _replace_in_actions(cr, label, old, new, extra_where='', params=()):
    cr.execute(f"""
        UPDATE ir_act_server s SET code = replace(code, %s, %s)
         WHERE strpos(code, %s) > 0 {extra_where}
        RETURNING s.id
    """, (old, new, old) + tuple(params))
    ids = [r[0] for r in cr.fetchall()]
    _logger.info("19.0.0.4.25: %s: %s server action(s) %s", label, len(ids), ids)


def migrate(cr, version):
    # 01 removed core names inside database-stored code
    _replace_in_views(cr, '01 views move_ids_without_package', 'move_ids_without_package', 'move_ids')
    _replace_in_actions(cr, '01 actions move_ids_without_package', 'move_ids_without_package', 'move_ids')
    _replace_in_actions(cr, '01 actions stock.quant.package', 'stock.quant.package', 'stock.package')
    _replace_in_actions(cr, '01 actions stock_quant_package', 'stock_quant_package', 'stock_package')

    # 03 stock.picking.date / stock.move.name removed on 19
    _replace_in_views(cr, '03 doc.date', '"doc.date"', '"doc.create_date"', "AND v.type = 'qweb'")
    _replace_in_views(
        cr, '03 deviation (old) move text', 't-esc="o.name"',
        't-esc="o.inventory_name or o.description_picking or o.product_id.display_name"',
        "AND v.key = %s", (DEVIATION_OLD_KEY,))

    # 05 VIFEL views the upgrade switched off
    cr.execute("""
        UPDATE ir_ui_view v SET active = true
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view' AND d.res_id = v.id AND NOT v.active
           AND d.module || '.' || d.name IN %s
        RETURNING d.module || '.' || d.name
    """, (REENABLE,))
    names = [r[0] for r in cr.fetchall()]
    _logger.info("19.0.0.4.25: 05 re-enabled %s view(s): %s", len(names), names)

    # 06 Studio compute + product automation
    cr.execute("""
        UPDATE ir_model_fields
           SET compute = replace(compute, 'move_line_ids_without_package', 'move_line_ids'),
               depends = replace(depends, 'move_line_ids_without_package', 'move_line_ids')
         WHERE strpos(coalesce(compute, ''), 'move_line_ids_without_package') > 0
            OR strpos(coalesce(depends, ''), 'move_line_ids_without_package') > 0
        RETURNING model || '.' || name
    """)
    _logger.info("19.0.0.4.25: 06 computes fixed: %s", [r[0] for r in cr.fetchall()])
    _replace_in_actions(cr, '06 move_line_ids_without_package', 'move_line_ids_without_package', 'move_line_ids')
    _replace_in_actions(
        cr, '06 detailed_type automation', "if record.detailed_type == 'product':",
        "if record.is_storable:  # Odoo 19: detailed_type 'product' -> is_storable")

    # 07 Auto-Fill Locations: ('m2m', '=', '') matches occupied slots on 19
    _replace_in_actions(
        cr, '07 auto-fill locations', '("x_studio_occupied_by_1", "=", ""),',
        '("x_studio_occupied_by_1", "=", False),')

    # leftovers (should all be 0)
    cr.execute("""
        SELECT (SELECT count(*) FROM ir_ui_view WHERE arch_db::text LIKE '%%move_ids_without_package%%'),
               (SELECT count(*) FROM ir_act_server
                 WHERE code ~ 'move_ids_without_package|move_line_ids_without_package|stock\\.quant\\.package|detailed_type'),
               (SELECT count(*) FROM ir_model_fields
                 WHERE compute ~ 'move_line_ids_without_package|\\.detailed_type')
    """)
    _logger.info("19.0.0.4.25: left over (views, server actions, computes): %s", cr.fetchone())
