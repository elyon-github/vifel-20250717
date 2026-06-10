# Copyright 2024 Foodles (https://www.foodles.co/).
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Clear every previously generated stock quant history line.

    The generation logic has been rewritten (deterministic full recompute) and
    a unique index is introduced on (snapshot_id, product_id, lot_id,
    location_id). Wiping the legacy lines guarantees the new unique index can be
    created cleanly; the post-migration then regenerates every snapshot with the
    corrected logic.

    Only reporting copies are removed here: stock.quant and stock.move.line
    source data are never touched.
    """
    if not version:
        return
    cr.execute("SELECT count(*) FROM stock_quant_history")
    (count,) = cr.fetchone()
    _logger.info(
        "stock_quant_history: clearing %s legacy history line(s) before "
        "regeneration",
        count,
    )
    cr.execute("DELETE FROM stock_quant_history")
