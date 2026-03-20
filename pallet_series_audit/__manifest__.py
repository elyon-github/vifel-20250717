# -*- coding: utf-8 -*-
{
    'name': "Pallet Series Audit",
    'summary': "Audit trail for pallet series ID operations on RR transfers",
    'description': """
        Tracks every pallet series assignment, change, pool operation,
        and deletion on Receiving Report (RR) transfers.  Provides a
        chronological event log per RR for easy debugging.
    """,
    'author': "Mark Angelo S. Templanza",
    'website': "https://templanza-portfolio.netlify.app/",
    'category': 'Inventory',
    'version': '17.0.1.0.0',
    'depends': ['multiple_relocation'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
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
