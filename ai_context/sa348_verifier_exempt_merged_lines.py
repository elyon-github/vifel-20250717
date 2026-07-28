# ============================================================================
# PASTE FILE — Server Action #348 "X_Verifier Check on Receipt"
#             (Studio → Server Actions → id 348, model stock.picking)
#
# TWO small changes, both inside the duplicate-pallet-series-in-stock check.
#   CHANGE 1 (logic)  — exempt merged lines from the guard.       3 added lines.
#   CHANGE 2 (wording)— make the error the guard raises clearer.  message only.
# Nothing else in the action changes. CHANGE 2 does NOT alter WHEN the error
# fires — only what the verifier reads when it does.
#
# WHY CHANGE 1
# -----------
# The block enforces the identity doctrine — one Pallet Series = one physical
# pallet — by refusing a receipt whose PSI is already live on stocked quants.
# That is correct for a normal line, and it is the guard that keeps split-PSI
# corruption out of the system.
#
# A MERGED line breaks the assumption on purpose. Merging means "this line
# joins a pallet already standing on the floor", so its adopted PSI is
# *supposed* to be in stock already. The guard therefore fires on the SECOND
# and every later merge onto the same pallet. The block ALREADY skips return
# lines for the same reason — a return legitimately lands on an existing
# series. Merged lines need the identical exemption.
#
# WHY CHANGE 2
# -----------
# When the guard fires for a NORMAL line it now means one of two things: a real
# duplicate (wrong series), OR the verifier wanted to add stock onto a pallet
# already on the floor but forgot to press "Merge Pallet". The old message
# stated only the fact ("Already exists in stock"). The reworded one states the
# RULE (why it is blocked) and the FIX (fresh series, or Merge Pallet) — turning
# a dead-end into a next step, without changing any logic.
#
# SAFETY: getattr(..., False) means CHANGE 1 still runs unchanged on a database
# where vifel_client_requirements is not installed.
# ============================================================================


# ============================================================================
# CHANGE 1 (logic) — exempt merged lines
# ----------------------------------------------------------------------------
# FIND THIS (inside "=== DUPLICATE PALLET SERIES IN STOCK CHECK ===")
# ----------------------------------------------------------------------------
#
#         for move_line in record.move_line_ids:
#             if not move_line.x_studio_pallet_series_id:
#                 continue
#             if (move_line.x_studio_return_count or 0) != 0:
#                 continue  # Skip return lines
#             combo_key = (
#
# ----------------------------------------------------------------------------
# REPLACE IT WITH THIS (three added lines, marked)
# ----------------------------------------------------------------------------

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
# CHANGE 2a (wording) — per-series detail line
# ----------------------------------------------------------------------------
# FIND THIS (a few lines below, where the offending series is collected)
# ----------------------------------------------------------------------------
#
#                 error_messages['existing_pallet_series'].append(
#                     f"Pallet Series: {combo['series']}\n"
#                     f"   Product: {combo['product_name']}\n"
#                     f"   Owner: {combo['owner_name']}\n"
#                     f"   ⚠️  Already exists in stock (Location: {existing_quant.location_id.display_name}, "
#                     f"Qty: {existing_quant.quantity:.3f} KG)"
#                 )
#
# ----------------------------------------------------------------------------
# REPLACE IT WITH THIS (facts only — the rule and the fix move to the header
# and footer below, so they are said ONCE instead of repeated per series)
# ----------------------------------------------------------------------------

                error_messages['existing_pallet_series'].append(
                    f"   • {combo['series']}  —  {combo['product_name']} "
                    f"({combo['owner_name']})\n"
                    f"       standing at {existing_quant.location_id.display_name}, "
                    f"{existing_quant.quantity:.3f} KG"
                )


# ============================================================================
# CHANGE 2b (wording) — section header + footer
# ----------------------------------------------------------------------------
# FIND THIS (in the final-message assembly, further down)
# ----------------------------------------------------------------------------
#
#     if error_messages['existing_pallet_series']:
#         final_error_message.append("\n\n🚫 **Pallet Series Already Exists in Stock:**")
#         final_error_message.append(separator.join(error_messages['existing_pallet_series']))
#         final_error_message.append("\n\nPlease contact your administrator if you think this is a mistake.")
#
# ----------------------------------------------------------------------------
# REPLACE IT WITH THIS
# ----------------------------------------------------------------------------

    if error_messages['existing_pallet_series']:
        final_error_message.append(
            "\n\n🚫 **Pallet Series Already In Stock**\n"
            "Each Pallet Series is one physical pallet, so it can only be "
            "received once. These are already on the floor:")
        final_error_message.append(separator.join(error_messages['existing_pallet_series']))
        final_error_message.append(
            "\n👉 What to do: give this line a fresh Pallet Series. If you meant "
            "to add this stock onto the pallet above, use the \"Merge Pallet\" "
            "button on the line instead (when merging is enabled for this client).\n"
            "If you believe the series should really be free, contact your "
            "administrator.")


# ============================================================================
# BEFORE / AFTER — what the verifier reads
# ============================================================================
#
# BEFORE:
#   🚫 Pallet Series Already Exists in Stock:
#   Pallet Series: PSI-00001
#      Product: Frozen Bangus 1kg
#      Owner: Wonder Meats
#      ⚠️  Already exists in stock (Location: WH/Stock/A-01, Qty: 1000.000 KG)
#
#   Please contact your administrator if you think this is a mistake.
#
# AFTER:
#   🚫 Pallet Series Already In Stock
#   Each Pallet Series is one physical pallet, so it can only be received once.
#   These are already on the floor:
#      • PSI-00001  —  Frozen Bangus 1kg (Wonder Meats)
#          standing at WH/Stock/A-01, 1000.000 KG
#
#   👉 What to do: give this line a fresh Pallet Series. If you meant to add
#   this stock onto the pallet above, use the "Merge Pallet" button on the line
#   instead (when merging is enabled for this client).
#   If you believe the series should really be free, contact your administrator.
#
# ============================================================================
# AFTER PASTING — how to confirm it worked
# ============================================================================
#
# 1. Client Profile: Can Merge Pallets ON, Multiple OFF, pin a Fixed Merge
#    Pallet + PSI.
# 2. Encode an RR, press Merge Pallet on a line, pick the pinned pallet.
#    First time: the pallet is empty, so the line counts +1 (it births the
#    pallet) — validate, and stock lands on it.
# 3. Encode a SECOND RR and merge onto the same pallet. Before CHANGE 1 this
#    validation raised the duplicate-series error. After it, the receipt
#    validates and the line counts +0.
# 4. To see CHANGE 2: on a normal (un-merged) line, reuse a Pallet Series that
#    is already in stock and validate — the reworded message appears.
#
# A quick shell check that the exemption is reachable at all:
#
#     env['stock.move.line'].search_count([('is_pallet_merge', '=', True)])
#
# ============================================================================
