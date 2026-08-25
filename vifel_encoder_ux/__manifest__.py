# -*- coding: utf-8 -*-
{
    'name': 'VIFEL Encoder Experience',
    'summary': 'Client-first navigation for encoders: Clients hub, Find '
               'Transfer, transfer-type picker and client smart buttons.',
    'description': """
VIFEL Encoder Experience
========================

The screens an encoder actually works in, kept OUT of the operational
modules so they can be installed, upgraded and removed on their own.

Everything here is user interface. It adds no field to a stock document and
changes no algorithm: uninstalling it takes the screens away and leaves
receiving, withdrawal, relocation, voiding and billing exactly as they were.

What it adds
------------
* **Clients hub** - the Inventory app opens on clients rather than on document
  types, because work here starts from a client and a piece of paper.
* **Clients kanban** - counts on a card are buttons that open exactly the
  records they count. Pending work is shown first, badges with nothing to say
  are hidden, and a control-panel toggle sorts by name or by most pending.
* **Find Transfer** - a search-first screen that reaches a document from the
  RR/WR number printed on a returned Tally Sheet, from a Pallet Series ID or
  from a Pallet #. It is also the only menu path to a blast-freeze transfer,
  whose own menu entries are archived.
* **Transfer-type picker** - asks Receiving or Withdrawal before opening a
  client's transfers, showing how much of each is still outstanding, and
  offers to create the new document straight from the dialog.
* **Client smart buttons** - transfers, stocks and occupied locations on the
  Contact form, scoped to the client and reusing the Inventory Overview
  domains so the numbers match those screens.
* **Client Unique Code guard** - the code prefixes every Pallet Series ID, so
  no two contacts may share one.
* **Read-only contact form for Documentation Staff.**
""",
    'author': "Mark Angelo Templanza",
    'website': "https://templanza-portfolio.netlify.app/",
    'category': 'Inventory/Inventory',
    'version': '17.0.1.0.0',
    # multiple_relocation supplies the fields these screens read:
    # stock.picking.documentation_staff_id, stock.picking.type
    # .is_blast_freeze_operation and stock.quant.bf_pallet_char.
    'depends': [
        'base',
        'stock',
        'web',
        'multiple_relocation',
    ],
    # Order matters: client_picking_tree_views defines the tree view that
    # client_menu_views references by ref=.
    'data': [
        'security/ir.model.access.csv',
        'views/client_location_search_views.xml',
        'views/client_picking_tree_views.xml',
        'views/picking_search_views.xml',
        'wizard/client_transfer_type_wizard.xml',
        'wizard/picking_type_state_wizard.xml',
        'views/res_partner_client_buttons.xml',
        'views/client_menu_views.xml',
        'views/picking_type_overview_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'vifel_encoder_ux/static/src/css/transfer_type_picker.scss',
            'vifel_encoder_ux/static/src/css/overview_kanban.scss',
            'vifel_encoder_ux/static/src/js/client_kanban_sort.js',
            'vifel_encoder_ux/static/src/js/client_kanban_sort.xml',
            'vifel_encoder_ux/static/src/js/overview_kanban.js',
            'vifel_encoder_ux/static/src/js/overview_kanban.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
