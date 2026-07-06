# -*- coding: utf-8 -*-
{
    'name': "Pallet Series Audit",
    'summary': "Audit trail for pallet series ID (PSI) operations on RR "
               "transfers: assignments, changes, pool events and deletions",
    'description': """
Pallet Series Audit
===================
Forensic audit trail for pallet series IDs (PSI) — the client-facing
pallet identity of the VIFEL cold-storage WMS. Every PSI is generated
from the client's unique code (e.g. AL-002966) and follows the physical
pallet through receipts, withdrawals, corrections and pallet swaps; this
module records everything that happens to those identifiers.

What is recorded
----------------
* A chronological event log per Receiving Report line: PSI assigned,
  changed, cleared/deleted, taken from or returned to the client's
  series pool — each event with before/after values, the responsible
  user, timestamp, and the source mechanism (manual edit, auto-assign,
  pool recycling, wizard).
* Per-picking and per-line audit views with search/grouping by client,
  warehouse, event type and date; an audit smart button on the RR form
  opens the transfer's full PSI history.
* Warehouse dimension on audit records for multi-warehouse filtering.

Why it exists
-------------
* Built to catch and diagnose pallet-series pool defects — most notably
  the "disappearing series" bug where reservation (_action_assign)
  silently dropped assigned PSIs from RR lines — and to prove, for any
  disputed pallet, who changed which PSI, when, and from what value.
* Doubles as the compliance trail for client-facing pallet identity:
  the PSI printed on RR/WR documents can always be traced back to its
  assignment history.

Housekeeping
------------
* Scheduled cron trims aged audit entries to keep the log lean.
* Access rules restrict audit visibility to inventory users; records
  are system-generated and read-only in the UI.
    """,
    'author': "Mark Angelo Templanza",
    'company': "Elyon Solutions International Inc.",
    'maintainer': "Elyon Solutions International Inc.",
    'website': "https://templanza-portfolio.netlify.app/",
    'category': 'Inventory/Inventory',
    'version': '17.0.1.1.0',
    'depends': ['multiple_relocation'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/audit_views.xml',
        'views/stock_picking_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pallet_series_audit/static/src/js/**/*',
            'pallet_series_audit/static/src/xml/**/*',
            'pallet_series_audit/static/src/scss/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
