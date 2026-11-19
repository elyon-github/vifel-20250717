# -*- coding: utf-8 -*-
"""17.0.1.0.3: the earlier return-merge backfill read some emptied merge / Fixed
pallets as still holding stock (stock that left a package without a move line
of its own stayed in the rebuilt history), so returns that really brought a
pallet back were cut to +0 (M/RR/06528, IRONFISH: Pallet Monitoring 2 -> 1).
Re-check those flags with the corrected history, put back +1 where the pallet
was empty, and rebuild the affected ledger rows. Each change is logged;
re-running books nothing."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for line in env['stock.picking']._vifel_undo_ghost_return_merge_flags():
        _logger.info("17.0.1.0.3 return merge undo: %s", line)
