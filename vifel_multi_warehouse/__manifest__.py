# -*- coding: utf-8 -*-
{
    'name': 'VIFEL Multi-Warehouse Base',
    'version': '17.0.2.0.0',
    'category': 'Inventory',
    'summary': 'Global warehouse record rules driven by the user\'s '
               'Allowed Warehouses, plus contact-per-warehouse guard-rails.',
    'description': """
Multi-Warehouse Security — dead simple
======================================
Assign warehouses on the user (Allowed Warehouses). GLOBAL record rules then
filter every scoped model to those warehouses:
stock.picking, stock.picking.type, stock.quant, stock.move, stock.move.line,
stock.location, stock.warehouse, the pallet-kilos ledger, the pallet-series
audit, quant-history snapshots, and res.partner (clients).

- A user with an EMPTY Allowed Warehouses list has FULL access (admins,
  back-office) — that is also the rollout lever: nothing changes at install
  until you start assigning warehouses.
- Records without any warehouse (vendor/customer locations, non-client
  partners, legacy rows) stay visible to everyone.

Contact-per-warehouse policy guard-rails on res.partner:
  * client contacts must carry x_studio_warehouse
  * the warehouse is immutable once the contact has transaction history
    (Settings administrators may override)
  * contacts from different warehouses cannot be merged

See ai_context/multi_warehouse_PLAN.md for the roadmap.
""",
    'author': 'Elyon Solutions International Inc.',
    # Umbrella security module: it scopes these modules' models with record
    # rules, so it must load after them.
    'depends': [
        'stock',
        'multiple_relocation',
        'pallet_kilos_record_model',
        'pallet_series_audit',
        'stock_quant_history',
    ],
    'data': [
        'security/multi_warehouse_rules.xml',
        'views/res_users_views.xml',
        'views/search_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
