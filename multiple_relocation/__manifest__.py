# -*- coding: utf-8 -*-
{
    'name': "VIFEL Warehouse Operations & Quant Corrections",

    'summary': "Core cold-storage WMS operations: pallet relocation, quant "
               "corrections with approval workflow, returns, fast RR "
               "encoding, and inventory reports",

    'description': """
VIFEL Warehouse Operations & Quant Corrections
==============================================
The operational backbone of the VIFEL cold-storage WMS on top of Odoo
Inventory. Every receiving (RR), withdrawal (WR), relocation, return,
correction and void in the warehouse runs through this module.

Pallet relocation
-----------------
* Batch relocation wizard: move any number of pallets/quants between
  bins and buildings in one operation, with building-aware allowed-
  destination filtering (leaf bins only, occupancy- and BF-aware) and a
  relocation reason trail.
* Leaf-location guard: stock can only LAND on a specific pallet position
  (e.g. .../R07/L6/P1) — validating onto an aisle/building/parent
  location is blocked, so parent locations can never become reservable
  stock spots.

Quant corrections & approval workflow
-------------------------------------
* Correct Quants wizard: controlled corrections of Weight (KG), quantity
  (2nd UOM), packs, Pallet #, product, owner, lot, production/expiration
  dates and container # — applied immediately (Inventory Supervisors) or
  routed through an adjustment request with per-line approve/reject,
  batch numbers, conflict detection and mail-thread tracking.
* Every applied correction — both flows — is stored as an approved
  adjustment line linked to its Pallet Kilos Record row, with the
  correction stock-move reference recoverable per line.
* Pallet-count integrity legs posted automatically at correction time:
  adjust-to-0 releases the pallet and posts -1; a pallet SPLIT (stock
  moved to a new pallet # while the source keeps stock) posts +1; a
  MERGE posts -1; plain renumbers stay net 0.

Withdrawals, returns & voiding
------------------------------
* Return Packages wizard for partial-withdraw returns, wired to the
  return-RR counting rules; original lot preserved (is_return lines are
  skipped by the RR lot assigner) so restored stock merges back into the
  same quant.
* Void / Unvoid transfer flows: voiding an RR creates a reversing void
  WR; voiding a WR creates a void return RR. Void returns land
  PSI-remainder-first: if the pallet series still has stock, the
  restored quantity goes back to that exact pallet # and location so
  KG / quantity / packs merge into one quant.
* Special "No RR Return Needed" client handling: partial withdrawals
  straight off the pallet without forced returns.
* Transacted Pallet Count on every picking, using the warehouse counting
  rule (a pallet counts as withdrawn only when it leaves at 0 KG),
  recomputed automatically when the reserved-at-validation stamp lands.

Encoding & productivity tools
-----------------------------
* Fast Encode RR ("Magic Wizard"): rapid line entry for receipts with
  pallet-series snapshots and destination-bin recommendation.
* Select Quant wizard for multi-pallet withdrawal picking.
* Custom list/form keyboard shortcuts (validate, generate lines, etc.).

Reports
-------
* RR / WR Summary and Per-Pallet PDF reports (regular and blast-freeze
  variants) sharing the ledger's pallet counting rule.
* Client Inventory Summary and Count Sheet XLSX reports.

Foundation fields used across the VIFEL system: pallet series ID (PSI),
reserved_quantity_on_validation, adjustment batch #, original record
reference, is_return / is_relocation flags, warehouseman, and the
Fix Pallet Duplicates support fields for physical-inventory imports.
    """,

    'author': "Mark Angelo Templanza",
    'company': "Elyon Solutions International Inc.",
    'maintainer': "Elyon Solutions International Inc.",
    'website': "https://templanza-portfolio.netlify.app/",

    'category': 'Inventory/Inventory',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'web', 'report_xlsx', 'pallet_kilos_record_model'],

    'post_init_hook': 'post_init_hook',

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/search_views.xml',
        'views/action_views.xml',
        # 'views/templates.xml',
        'wizard/ReturnPackageWizard.xml',
        'wizard/SelectQuantWizard.xml',
        'wizard/SmallWizards.xml',
        'wizard/stock_quant_correction.xml',
        'wizard/FastEncodeRR.xml',
        'wizard/client_transfer_type_wizard.xml',
        'reports/inventory_summary_view.xml',
        'reports/count_sheet_view.xml',
        'data/data.xml',
        'data/picking_server_actions.xml',
        # after data.xml: the quant-detail actions reference the
        # inventory_super_admin group defined there
        'views/stock_quant_views.xml',
        'views/client_location_search_views.xml',
        'views/res_partner_client_buttons.xml',
        'views/quant_report_button_views.xml',

    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',

        
    ],
    'assets': {
        'web.assets_backend': [
            'multiple_relocation/static/src/images/logo_1.jpg',
            'multiple_relocation/static/src/css/custom_css.scss',
            'multiple_relocation/static/src/css/transfer_type_picker.scss',
            'multiple_relocation/static/src/js/test.js',
            'multiple_relocation/static/src/js/test2.js',
            'multiple_relocation/static/src/js/list_controller_custom_keybinds.js',
            # 'multiple_relocation/static/src/js/list_controller_custom_2.js',
            'multiple_relocation/static/src/js/form_controller_custom_keybinds.js',
            'multiple_relocation/static/src/views/templates.xml',
            'multiple_relocation/static/src/js/many2many_tags_field.js',
            'multiple_relocation/static/src/js/fast_encode_rr_list_controller.js',
            'multiple_relocation/static/src/js/fast_encode_rr_list_view_template.xml',
            'multiple_relocation/static/src/js/magic_wizard_list_controller.js',
            'multiple_relocation/static/src/js/magic_wizard_list_view_template.xml',
            'multiple_relocation/static/src/js/quant_report_button.js',
            'multiple_relocation/static/src/js/quant_report_button.xml',
        ],
    },
    'license': 'LGPL-3',
}

