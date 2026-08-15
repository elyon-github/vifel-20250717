# -*- coding: utf-8 -*-
{
    'name': "VIFEL Client-Specific Requirements",

    'summary': "Per-client pallet merging, special PSI types and client "
               "Lot No. — installable and removable without disturbing the "
               "pallet/kilos ledger.",

    'description': """
Client-Specific Requirement Enhancement
=======================================

Adds the per-client capabilities agreed with VIFEL:

* **VIFEL Configuration** tab on the Contact form: a checkbox cascade that
  turns pallet merging on for a client, in one of two exclusive modes.
  *Fixed* offers one pinned pallet and PSI forever (Wonder Meats).
  *Multiple* offers special PSI types, each with its own prefix, counter and
  recyclable numbers (Consistent: MDGM, BOC, TDMG, SDMG).

* **Merge Pallet**, a per-line action in the Pallet Breakdown and in the Magic
  Wizard, lands an incoming line on a pallet already stocked on the floor. The
  line adopts the target's Pallet Series ID and location, and the ledger does
  not count a new pallet for it; Weight, Quantity and Packs still count in full.

* **Client Lot No.**: the client's own lot number on transfer lines, stamped
  onto stock when the transfer validates.

Design note
-----------
Everything this feature owns lives in this module. ``multiple_relocation`` and
``pallet_kilos_record_model`` keep only five generic extension hooks, because
the behaviour they gate sits inside methods of ~300 and ~990 lines that an
add-on cannot re-implement without duplicating them and drifting from core.

The fields lived in ``multiple_relocation`` until 2026-07-23, so that
uninstalling could not drop them and inflate historical pallet counts. The
module is installed once and never uninstalled, so that risk cannot occur and
the fields now sit with the rest of the feature. If that ever changes, move
them back to core first: dropping ``is_pallet_merge`` silently inflates pallet
counts, and a wrong pallet count is a wrong invoice.
    """,

    'author': "Mark Angelo Templanza",
    'company': "Elyon Solutions International Inc.",
    'maintainer': "Elyon Solutions International Inc.",
    'website': "https://templanza-portfolio.netlify.app/",

    'category': 'Inventory/Inventory',
    'version': '17.0.1.0.0',
    'license': 'LGPL-3',

    # pallet_series_audit is NOT cosmetic: it and this module both extend
    # push_unused_pallet. Two siblings that merely share a parent have no
    # guaranteed MRO order, so declaring it forces the prefix routing here to
    # compose AFTER the audit wrapper instead of racing it — otherwise the
    # audit trail can silently stop logging routed recycles.
    'depends': [
        'multiple_relocation',
        'pallet_series_audit',
        # transitive through multiple_relocation, but declared explicitly:
        # this module overrides its counting hooks.
        'pallet_kilos_record_model',
    ],

    'data': [
        'security/ir.model.access.csv',
        'wizard/pallet_merge_wizard.xml',
        'views/res_partner_views.xml',
        'views/stock_move_line_views.xml',
        'views/fast_encode_views.xml',
        'views/stock_quant_views.xml',
    ],

    # Loads after multiple_relocation's own backend assets (this module depends
    # on it), so the patch below lands on an already-defined controller.
    'assets': {
        'web.assets_backend': [
            'vifel_client_requirements/static/src/js/hide_print_pallet_breakdown.js',
            'vifel_client_requirements/static/src/js/merge_wizard_back_on_close.js',
            'vifel_client_requirements/static/src/js/merge_target_toggle.js',
        ],
    },

    'installable': True,
    'application': False,
    'auto_install': False,
}
