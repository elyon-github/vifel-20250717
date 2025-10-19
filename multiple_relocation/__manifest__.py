# -*- coding: utf-8 -*-
{
    'name': "multiple_relocation",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "Mark Angelo S. Templanza",
    'website': "https://templanza-portfolio.netlify.app/",

    # Categories can be used to filter modules in modules listing
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'stock', 'web','report_xlsx'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/search_views.xml',
        'views/action_views.xml',
        # 'views/templates.xml',
        'wizard/ReturnPackageWizard.xml',
        'wizard/SelectQuantWizard.xml',
        'wizard/SmallWizards.xml',
        'wizard/stock_quant_correction.xml',
        'wizard/FastEncodeRR.xml',
        'reports/inventory_summary_view.xml',
        'reports/count_sheet_view.xml',
        'data/data.xml',
        
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',

        
    ],
    'assets': {
        'web.assets_backend': [
            'multiple_relocation/static/src/images/logo_1.jpg',
            'multiple_relocation/static/src/css/custom_css.scss',
            'multiple_relocation/static/src/js/test.js',
            'multiple_relocation/static/src/js/test2.js',
            'multiple_relocation/static/src/js/list_controller_custom_keybinds.js',
            # 'multiple_relocation/static/src/js/list_controller_custom_2.js',
            'multiple_relocation/static/src/js/form_controller_custom_keybinds.js',
            'multiple_relocation/static/src/views/templates.xml',
            'multiple_relocation/static/src/js/many2many_tags_field.js',
            'multiple_relocation/static/src/js/fast_encode_rr_list_controller.js',
            'multiple_relocation/static/src/js/fast_encode_rr_list_view_template.xml',
        ],
        
    }

}

