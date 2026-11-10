# -*- coding: utf-8 -*-
"""0.2: book the WONDER MEATS (FG) stock count of 2026-10-28 on the ledger.

On 10-28 the owner was zeroed (Inventory > Apply) and the opening balance was
re-uploaded. Neither reached the Pallet Kilos ledger, so Pallet Monitoring
still started 10-28 from the old balance (258 pallets / 117,987 kg) instead
of the upload (46 pallets / 18,429 kg). From 0.2 on every Apply books itself
(models/stock_count.py); this books the one that happened before.

Runs once (module upgrade 0.1 -> 0.2). Re-running books nothing: the moves
are linked to their ledger row and skipped next time.
"""
import logging
from datetime import datetime

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OWNER_ID = 309                                  # WONDER MEATS (FG)
DATE_FROM = datetime(2026, 10, 27, 16, 0, 0)    # 2026-10-28 00:00 Manila, in UTC
DATE_TO = datetime(2026, 10, 28, 15, 59, 59)    # 2026-10-28 23:59 Manila, in UTC


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    owner = env['res.partner'].browse(OWNER_ID).exists()
    name = (owner.name or '').upper().replace(' ', '') if owner else ''
    if not owner or 'WONDER' not in name or 'FG' not in name:
        _logger.info("0.2 stock-count backfill: owner %s is not WONDER MEATS (FG) here - skipped", OWNER_ID)
        return
    report = env['pallet_kilos_record_model.pallet_kilos_record_model'] \
        ._pkr_backfill_stock_count(OWNER_ID, DATE_FROM, DATE_TO)
    for line in report:
        _logger.info("0.2 stock-count backfill %s: %s", owner.name, line)
