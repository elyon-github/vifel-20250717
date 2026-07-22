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

Deliberate design note
----------------------
The ``is_pallet_merge`` and ``client_lot_no`` FIELDS live in
``multiple_relocation``, not here. They are ledger evidence: uninstalling this
module must never drop the columns that tell the pallet count why a merged
line was not counted, or every merged line would silently recount as a
received pallet on the next Re-sync. This module owns the configuration, the
routing and the user interface — never the record of what already happened.
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
    ],

    'data': [
        'security/ir.model.access.csv',
        'wizard/pallet_merge_wizard.xml',
        'views/res_partner_views.xml',
        'views/stock_move_line_views.xml',
        'views/fast_encode_views.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}
