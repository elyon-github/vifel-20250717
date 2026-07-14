# -*- coding: utf-8 -*-
{
    'name': "Pallet Kilos Record Log",

    'summary': "Per-client running ledger of pallets, kilos, quantity and "
               "packs per RR/WR, with re-sync tools and monitoring/billing "
               "XLSX reports",

    'description': """
Pallet Kilos Record Log
=======================
The per-client storage ledger of the VIFEL cold-storage WMS: every
validated Receiving Report and Withdrawal Report becomes one row in a
running-balance ledger partitioned by (client, warehouse, blast-freezer).
Billing, monitoring and client statements are all derived from it.

The ledger & counting rules
---------------------------
* Row creation is automatic on RR/WR validation (via the DB automation
  "Pallet Kilos Record - Create Record Per Move"); vehicle, gate pass and
  timing details are pulled from the document.
* Pallet counting rule: RECEIVED = one count per unique pallet per RR;
  WITHDRAWN = one count per unique pallet per WR only when the pallet
  really leaves at 0 KG (reserved-at-validation stamp = 0) — partial
  withdrawals count zero until the pallet is emptied. Blast-freeze
  pallets count by their BF pallet text instead of a package.
* Running balances per row for pallets, Weight (KG), quantity
  (packaging) and packs:
      total = beginning + received - withdrawn + adjustment
  recalculated warehouse-wide in chronological order
  (start_time, then id) whenever history changes.
* Return RRs (partial-withdraw returns) carry their own rows so returned
  pallets/kilos flow back into the balance.

Adjustments & audit trail
-------------------------
* Approved quant-correction lines are LINKED to the ledger row they were
  posted against — the row's Adjustment Information page shows each
  correction with PSI, old/new pallet #, old/new quantities, reason and
  the correction stock-move reference.
* A human-readable HTML explanation table (plus a plain-text copy in
  remarks for the XLSX reports) justifies every adjustment: corrections,
  re-sync events (e.g. "PSI X adjusted to 0 quantity - batch N") and
  residuals with an exact per-pallet cause breakdown (pallet splits,
  undocumented re-entries, opening-balance drift, mass imports).

Maintenance actions (Actions menu on the ledger)
------------------------------------------------
* Re-sync Pallet Counts: rebuilds pallets received/withdrawn from the
  documents, re-links the correction history (with dead-quant recovery
  via correction-move references), derives events for pallets whose
  documented ins/outs are unbalanced, and anchors any untraceable
  residual on the opening-balance row — guaranteeing ledger == physical
  distinct pallets per client, idempotently.
* Recompute Balances: rebuild the running-balance series only.
* Get Unsynced: read-only ledger-vs-physical discrepancy report.

Reports (XLSX)
--------------
* Pallet Monitoring: day-by-day client statement (RR/WR/return columns,
  net movement, remaining balances; adjustment columns built and
  feature-flagged for deployment).
* Billing: per-day pallet/kilo balances for invoicing.
* Daily Inventory and Daily Pallet Utilization.
* Report wizard with client/date filtering and a list-view report button.
    """,

    'author': "Mark Angelo Templanza",
    'company': "Elyon Solutions International Inc.",
    'maintainer': "Elyon Solutions International Inc.",
    'website': "https://templanza-portfolio.netlify.app/",

    'category': 'Inventory/Inventory',
    'version': '17.0.1.0.0',

    # any module necessary for this one to work correctly
    'depends': ['report_xlsx', 'stock'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'wizard/pkr_report_wizard.xml',
        'views/views.xml',
        'reports/pallet_kilos_xlsx_report.xml',
        'data/pkr_server_actions.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pallet_kilos_record_model/static/src/js/pkr_report_button.js',
            'pallet_kilos_record_model/static/src/js/pkr_report_button.xml',
        ],
    },
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'license': 'LGPL-3',
}

