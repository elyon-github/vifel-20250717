# -*- coding: utf-8 -*-
"""17.0.1.0.2: past returns that landed on a merge / Fixed pallet already
holding stock were counted +1 pallet on the ledger (M/RR/10577, WONDERMEAT
(FG): Pallet Monitoring 48 vs 47 on the floor). Flag them +0 and rebuild
the affected ledger rows. Each change is logged; re-running books nothing."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for line in env['stock.picking']._vifel_backfill_return_merge_counts():
        _logger.info("17.0.1.0.2 return merge backfill: %s", line)
