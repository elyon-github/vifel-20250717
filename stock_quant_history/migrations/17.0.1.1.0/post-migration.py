# Copyright 2024 Foodles (https://www.foodles.co/).
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Regenerate every snapshot with the corrected generation logic.

    The pre-migration removed the legacy (potentially duplicated / stale) lines;
    here we rebuild each snapshot deterministically from the move line history.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    snapshots = env["stock.quant.history.snapshot"].search([])
    if not snapshots:
        _logger.info("stock_quant_history: no snapshot to regenerate")
        return
    _logger.info(
        "stock_quant_history: regenerating %s snapshot(s) with corrected logic",
        len(snapshots),
    )
    env["stock.quant.history.snapshot"]._regenerate_all_snapshots()
