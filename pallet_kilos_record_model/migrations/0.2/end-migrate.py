# -*- coding: utf-8 -*-
"""0.2: book every past RE-UPLOAD on the Pallet Kilos ledger, for all owners.

Before 0.2 a stock count applied from Inventory (zeroing an owner, then
re-uploading its opening balance) changed the stock but never the ledger, so
Pallet Monitoring kept the old balance (e.g. WONDER MEATS (FG) 10-28 still
started at 258 pallets / 117,987 kg instead of the 46 / 18,429 uploaded).
From 0.2 on every Apply books itself (models/stock_count.py); this books the
ones that happened before, for every client, with the same rule:
zeroing -> ledger reset to 0, re-upload -> its pallets / kg / qty / packs.
See _pkr_find_reuploads for what counts as a re-upload.

Runs once (module upgrade to 0.2). Re-running books nothing: the moves are
linked to their ledger rows. Each booked row is written to the log.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    report = env['pallet_kilos_record_model.pallet_kilos_record_model'] \
        ._pkr_backfill_stock_count()
    for line in report:
        _logger.info("0.2 re-upload backfill: %s", line)
