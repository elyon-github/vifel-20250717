# PASTE TARGET: SA#432  (Automation BA#42 "On Create Stock Move Lines Assign ID")
# Model: stock.move.line   Trigger: On Create
# Author: Mark Angelo S. Templanza / Elyon    Date: 2026-07-21
# Backup of the current prod code: ai_context/sa432_assign_line_id_BACKUP.txt
#
# SCOPE / IMPACT (measured 2026-07-21 -- read this first)
# -------------------------------------------------------
# This is a REAL but MINOR fix: measured end-to-end benefit on inventory-adjustment Apply is
# only ~1.1x (~6%). It is NOT the cause of the "Apply is unusable at 800+ quants" problem.
# The dominant cost (~11.3x) is a family of stored x_studio_ computed fields on
# stock.move.line that scan the 22.9k-quant virtual location for picking-less lines.
# See: ai_context/studio_computes_inventory_apply_perf_FIX.md
# Apply this one too (it is correct and free), but expect the big win from that document.
#
# WHY THIS CHANGE
# ----------------
# The old code ran a search per created move line to find the next line # ("x_studio_").
# For move lines with NO picking -- inventory-adjustment "Apply", scrap, internal quant
# moves -- record.picking_id.id is False, so the domain degraded to
#   [('picking_id', '=', False), ('x_studio_', '!=', False)]
# which is an UNINDEXED full seq-scan over EVERY picking-less move line in the DB
# (53,002 rows in vifel_07_06_2026, ~72 ms each measured live), executed once per line --
# and it grows as the picking-less set grows. Worth removing, but see SCOPE above: it is
# ~6% of the total, not the headline problem.
#
# THE FIX
# --------
# Skip lines that have no picking -- they belong to no RR/WR and never need a line number.
# For real RR/WR lines the behaviour is IDENTICAL (still numbered 1,2,3... within the
# picking), and the search is scoped by picking_id (indexed), so it stays fast.
#
# RECOMMENDED (belt-and-suspenders): also set the automation's "Apply on" domain to
#   [("picking_id", "!=", False)]
# so the rule doesn't even enter Python for picking-less lines.

for record in records:
    # No picking -> not part of an RR/WR (inventory adjustment / scrap / quant move). Skip.
    if not record.picking_id:
        continue

    # Only assign x_studio_ if it's not already set (0, False, or None)
    if not record.x_studio_:
        # Highest existing line number within THIS picking (indexed by picking_id)
        max_line = env['stock.move.line'].search(
            [('picking_id', '=', record.picking_id.id), ('x_studio_', '!=', False)],
            order='x_studio_ desc',
            limit=1,
        )
        record['x_studio_'] = (max_line.x_studio_ + 1) if max_line else 1
