# -*- coding: utf-8 -*-
"""19.0.0.4.27: keep the 19 report fixes made in Studio on Consultant-Test-19.

On 11-17 these 11 Studio report templates were fixed by hand in Studio on the
Odoo.sh 19 test upgrade (Consultant-Test-19, build ae539c9):
WR Summary / Per Pallet, RR Summary / Per Pallet, BFRR Summary / Per Pallet,
BFWR Summary / Per Pallet, Tally Sheet, Pallet Tag Form, Picklist.
Every push in upgrade mode, and the real production upgrade, starts again from
the live 17 backup, so those edits would be lost. This script writes the fixed
templates back after the upgrade.

reports/index.json lists report name, view key and file. The view is found by
its key (the same on every copy of live). The old template is kept as an
attachment on the view first. A template that is already the same is skipped,
so running it again changes nothing. A template Odoo refuses is logged and
left as it was (the upgrade itself does not stop).
"""
import base64
import json
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    View = env['ir.ui.view'].with_context(active_test=False)
    with open(os.path.join(HERE, 'index.json'), encoding='utf-8') as f:
        index = json.load(f)
    done, same, missing, failed = [], [], [], []
    for item in index:
        with open(os.path.join(HERE, item['file']), encoding='utf-8') as f:
            arch = f.read()
        views = View.search([('key', '=', item['key']), ('type', '=', 'qweb')])
        if not views:
            missing.append(item['report'])
            continue
        for view in views:
            if (view.arch_db or '') == arch:
                same.append(item['report'])
                continue
            try:
                with cr.savepoint():
                    env['ir.attachment'].create({
                        'name': f"before_19.0.0.4.27_{view.id}.xml",
                        'res_model': 'ir.ui.view',
                        'res_id': view.id,
                        'mimetype': 'application/xml',
                        'datas': base64.b64encode((view.arch_db or '').encode('utf-8')),
                    })
                    view.write({'arch_db': arch})
                done.append(f"{item['report']} (view {view.id})")
            except Exception as e:  # keep the upgrade going; report it
                failed.append(f"{item['report']} (view {view.id}): {e}")
    _logger.info("19.0.0.4.27: report templates restored: %s", done)
    _logger.info("19.0.0.4.27: already up to date: %s", same)
    if missing:
        _logger.warning("19.0.0.4.27: report template not found: %s", missing)
    for line in failed:
        _logger.error("19.0.0.4.27: report template NOT restored: %s", line)
