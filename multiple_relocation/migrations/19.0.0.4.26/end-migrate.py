# -*- coding: utf-8 -*-
"""19.0.0.4.26: run the Studio xpath cleanup (19.0.0.4.5) again, after 19.0.0.4.25.

Odoo.sh test upgrade 11-17: Studio could not open on Transfers (RR Summary
report edit) - "xpath ...move_ids']/list[1]/field[@name='display_assign_serial']
cannot be located". 19.0.0.4.5 only checks ACTIVE Studio views, and the
upgrade had switched the Studio Transfer form off; 19.0.0.4.25 turns it back
on (and renames move_ids_without_package) but runs after 19.0.0.4.5, so that
view was never cleaned. Same cleanup, same rules, now in the right order.
Running it again changes nothing.
"""
import importlib.util
import os


def migrate(cr, version):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        '19.0.0.4.5', 'end-migrate.py')
    spec = importlib.util.spec_from_file_location('vifel_mr_19_0_0_4_5_end', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(cr, version)
