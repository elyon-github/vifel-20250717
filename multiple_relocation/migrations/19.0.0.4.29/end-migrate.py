# -*- coding: utf-8 -*-
"""19.0.0.4.29: "Printed By" and "Last Print Date" on the RR/WR/BFRR/BFWR reports.

Added in Studio on Consultant-Test-19 on 11-18 (build 34a333f) to these 8
templates: RR / WR / BFRR / BFWR, Summary and Per Pallet. Each gets two lines:
    Printed By: <the Transfer's Printed By field, x_studio_printed_by_name>
    Last Print Date: <time of printing, PH time>
The field is created by 19.0.0.4.28, so this runs after it. Same writer as
19.0.0.4.27 (view found by key, old template kept as an attachment, a template
already the same is skipped), with the 11-18 templates in ./reports.
"""
import importlib.util
import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')


def migrate(cr, version):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        '19.0.0.4.27', 'end-migrate.py')
    spec = importlib.util.spec_from_file_location('vifel_mr_19_0_0_4_27_end', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = HERE  # 4.27's writer, 4.29's templates
    module.migrate(cr, version)
