# Copyright 2024 Foodles (https://www.foodles.co/).
# @author Pierre Verkest <pierreverkest84@gmail.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Quant History",
    "summary": "Point-in-time stock quant snapshots with VIFEL occupancy "
               "and historical inventory reports",
    "description": """
Stock Quant History (OCA base + VIFEL customizations)
=====================================================
OCA module that records stock.quant history lines and can re-generate the
quant state as of any past date (snapshots built by cron).

VIFEL customizations on top of the OCA base
-------------------------------------------
* History lines carry the VIFEL quant details (PSI, pallet #, owner,
  2nd UOM/packs, building) so past states are fully reconstructable —
  used to prove timing bugs (e.g. when a quant's quantity fields changed).
* Warehouse dimension on history lines and snapshots (SQL-backfilled via
  migration) for multi-warehouse filtering.
* Occupancy Report wizard + XLSX: location occupancy per building/
  warehouse as of a chosen date, with a list-view report button.
* Historical Inventory Summary XLSX report.
    """,
    "version": "17.0.1.0.0",
    "license": "AGPL-3",
    "author": "Pierre Verkest <pierreverkest84@gmail.com>, "
    "Odoo Community Association (OCA), "
    "Mark Angelo Templanza (VIFEL customizations)",
    "website": "https://github.com/OCA/stock-logistics-reporting",
    'depends': ['report_xlsx', 'stock'],
    "maintainers": [
        "petrus-v",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "wizard/occupancy_report_wizard.xml",
        "views/stock-quant-history-snapshot.xml",
        "views/stock-quant-history.xml",
        "reports/inventory_summary_view.xml",
        "reports/occupancy_report_view.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'stock_quant_history/static/src/js/occupancy_report_button.js',
            'stock_quant_history/static/src/js/occupancy_report_button.xml',
        ],
    },
}
