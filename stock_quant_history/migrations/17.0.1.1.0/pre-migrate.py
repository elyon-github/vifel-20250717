# -*- coding: utf-8 -*-
"""Multi-warehouse Phase 1: pre-create and backfill warehouse_id.

stock_quant_history holds 1M+ rows. Creating the column and filling it in raw
SQL *before* the registry loads means the ORM finds the column already
populated and skips the row-by-row recompute of the new stored related field.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # --- stock.quant.history.warehouse_id (stored related -> location) ---
    cr.execute("""
        ALTER TABLE stock_quant_history
        ADD COLUMN IF NOT EXISTS warehouse_id integer
    """)
    cr.execute("""
        UPDATE stock_quant_history h
           SET warehouse_id = l.warehouse_id
          FROM stock_location l
         WHERE l.id = h.location_id
           AND h.warehouse_id IS NULL
    """)
    _logger.info("stock_quant_history.warehouse_id backfilled: %s rows", cr.rowcount)

    # --- stock.quant.history.snapshot.warehouse_id (plain m2o) ---
    cr.execute("""
        ALTER TABLE stock_quant_history_snapshot
        ADD COLUMN IF NOT EXISTS warehouse_id integer
    """)
    # A legacy snapshot gets the warehouse only when ALL its lines agree
    # (single-warehouse era: they do). Mixed snapshots stay NULL.
    cr.execute("""
        UPDATE stock_quant_history_snapshot s
           SET warehouse_id = sub.wh
          FROM (
                SELECT snapshot_id,
                       min(warehouse_id) AS wh
                  FROM stock_quant_history
                 WHERE warehouse_id IS NOT NULL
                 GROUP BY snapshot_id
                HAVING count(DISTINCT warehouse_id) = 1
               ) sub
         WHERE sub.snapshot_id = s.id
           AND s.warehouse_id IS NULL
    """)
    _logger.info("stock_quant_history_snapshot.warehouse_id backfilled: %s rows", cr.rowcount)
