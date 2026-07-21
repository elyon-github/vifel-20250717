# -*- coding: utf-8 -*-
{
    'name': "VIFEL Utility Tools",
    'summary': "Auto-create products from the NAME (BRAND) convention during quant import",
    'description': """
VIFEL Utility Tools
===================

Small utilities that smooth over day-to-day VIFEL operations.

Product auto-create on Inventory Adjustment import
--------------------------------------------------
Importing ``stock.quant`` fails with "No matching records found in field Product"
whenever a product in the client's file does not exist yet. With the import option
*"When a value cannot be matched" -> "Create new values"*, this module creates the
missing product from VIFEL's naming convention::

    CHICKEN WINGS (NAT)  =  template "CHICKEN WINGS"  +  BRAND value "NAT"

Existing templates are never modified. Every unmatched name yields a brand-new
template, so an unbranded product can never be silently renamed into a branded one.

Only active during an import (``import_file`` context); normal many2one
quick-create everywhere else is untouched.

See ``ai_context/vifel_utility_tools_PLAN.md`` for the full design.
    """,
    'author': "Mark Angelo S. Templanza",
    'category': 'Inventory/Inventory',
    'version': '17.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'stock', 'multiple_relocation'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
