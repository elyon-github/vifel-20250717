# Copyright 2024 Foodles (https://www.foodles.co/).
# @author Pierre Verkest <pierreverkest84@gmail.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Quant History",
    "summary": "Re-generate stock quants for given date",
    "version": "17.0.1.1.0",
    "license": "AGPL-3",
    "author": "Pierre Verkest <pierreverkest84@gmail.com>, "
    "Odoo Community Association (OCA)",
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
