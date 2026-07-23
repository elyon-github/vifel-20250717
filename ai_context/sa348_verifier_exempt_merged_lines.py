# ============================================================================
# PASTE FILE — Server Action #348 "X_Verifier Check on Receipt"
#             (Studio → Server Actions → id 348, model stock.picking)
#
# WHAT TO DO: find the block below inside the action's Python code and add the
# THREE marked lines. Nothing else in the action changes.
#
# WHY
# ---
# The block enforces the identity doctrine — one Pallet Series = one physical
# pallet — by refusing a receipt whose PSI is already live on stocked quants.
# That is correct for a normal line, and it is the guard that keeps split-PSI
# corruption out of the system.
#
# A MERGED line breaks the assumption on purpose. Merging means "this line
# joins a pallet already standing on the floor", so its adopted PSI is
# *supposed* to be in stock already. The guard therefore fires on the SECOND
# and every later merge onto the same pallet:
#
#     🚫 Pallet Series Already Exists in Stock:
#        Pallet Series: PSI-00001 ... Already exists in stock (Qty: 1000.000 KG)
#
# The first merge onto an empty pinned pallet passes (no stock yet), which is
# why this only appears from the second use onward.
#
# The block ALREADY skips return lines for the same reason — a return
# legitimately lands on an existing series. Merged lines need the identical
# exemption.
#
# SAFETY: getattr(..., False) means the action still runs unchanged on a
# database where vifel_client_requirements is not installed.
# ============================================================================


# ---------------------------------------------------------------------------
# FIND THIS (inside "=== DUPLICATE PALLET SERIES IN STOCK CHECK ===")
# ---------------------------------------------------------------------------
#
#         for move_line in record.move_line_ids:
#             if not move_line.x_studio_pallet_series_id:
#                 continue
#             if (move_line.x_studio_return_count or 0) != 0:
#                 continue  # Skip return lines
#             combo_key = (
#
# ---------------------------------------------------------------------------
# REPLACE IT WITH THIS (three added lines, marked)
# ---------------------------------------------------------------------------

        for move_line in record.move_line_ids:
            if not move_line.x_studio_pallet_series_id:
                continue
            if (move_line.x_studio_return_count or 0) != 0:
                continue  # Skip return lines
            # >>> ADDED: a merged line ADOPTS a series that is already in
            # >>> stock — that is what merging means. Same exemption the
            # >>> return lines above get.
            if getattr(move_line, 'is_pallet_merge', False):
                continue
            combo_key = (


# ============================================================================
# AFTER PASTING — how to confirm it worked
# ============================================================================
#
# 1. Client Profile: Can Merge Pallets ON, Multiple OFF, pin a Fixed Merge
#    Pallet + PSI.
# 2. Encode an RR, press Merge Pallet on a line, pick the pinned pallet.
#    First time: the pallet is empty, so the line counts +1 (it births the
#    pallet) — validate, and stock lands on it.
# 3. Encode a SECOND RR and merge onto the same pallet. Before this fix that
#    validation raised "Pallet Series Already Exists in Stock". After it, the
#    receipt validates and the line counts +0.
#
# A quick shell check that the exemption is reachable at all:
#
#     env['stock.move.line'].search_count([('is_pallet_merge', '=', True)])
#
# ============================================================================
