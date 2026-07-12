# -*- coding: utf-8 -*-
{
    'name': 'VIFEL Health Monitor',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Scheduled invariant checks over the VIFEL pallet/ledger system',
    'description': """
VIFEL Health Monitor
====================
Runs 19 invariant checks over the pallet ledger, pallet identity, stock
records, operational processes and the automation layer, on a weekly cron
(plus on demand). Findings live in a persistent list with an automatic
lifecycle (new -> open -> resolved) and an Ignore flag for accepted known
issues. When NEW non-ignored findings appear, every member of the
Adjustment Approvers group receives a to-do activity.

Check categories:
* Ledger      — pallet drift, KG/packaging drift, PKR document coverage,
                running-balance continuity
* Identity    — split pallet series, package in two locations, blank PSI,
                blank BF pallet text
* Stock       — negative stock, owner-less stock, reference-less stock,
                zero-KG with packs, stuck zero quants
* Process     — orphaned void children, stale reservation flags,
                over-reserved quants, missing withdrawal stamps
* System      — critical automations/crons watchdog, snapshot freshness

Self-contained: read-only checks, no changes to any other module's
behavior; safe to install, upgrade or remove independently.
""",
    'author': "Mark Angelo Templanza",
    'maintainer': "Elyon Solutions International Inc.",
    'website': "https://templanza-portfolio.netlify.app/",
    'depends': [
        'stock',
        'mail',
        'pallet_kilos_record_model',
        'multiple_relocation',
        'stock_quant_history',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/health_data.xml',
        'data/health_cron.xml',
        'views/health_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
