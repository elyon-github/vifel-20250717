# ============================================================================
# SERVER ACTION #377 "Execute Code"  (Automation Rule #29 "Stock Move Assign
#   Quants Picked", model stock.move, on_create_or_write)  —  FULL CODE, paste-ready.
#   Studio -> Server Actions -> id 377 -> Python Code box: select all, delete,
#   paste everything BELOW the divider line.
#
# WHAT & WHY
# ----------
# The original body OVERWRITES quant_ids_picked on every save with EVERY internal
# quant matching the move's lots+product:
#     record['quant_ids_picked'] = [(6, 0, initial_quant_ids.ids)]
# That enforces "withdraw the whole pallet" — correct for a normal pallet, but it
# also SILENTLY re-adds a quant the user deleted from the Picked Quants tab, and
# it blocks partial withdrawal of a MERGE pallet (a pinned Fixed pallet or a
# merged-onto pallet), which is legitimate (same rule the verifier SA#333 and the
# Incomplete Package notice already exempt).
#
# TWO changes, both marked ">>> MERGE":
#   1. If the move has ANY line on a partial-withdrawal-allowed (merge) package,
#      DO NOT overwrite — keep the user's curated quant_ids_picked. The Select
#      Stocks wizard already populates it, so nothing is lost.
#   2. For a NORMAL pallet, when the overwrite genuinely RE-ADDS quants the user
#      had removed, post ONE info note to the picking chatter (an on-write
#      automation cannot pop a live toast) so the re-add is never a silent
#      surprise. Posts only on a real re-add, never on an unrelated save.
#
# _vifel_package_allows_partial_withdrawal is defined on stock.quant by
# multiple_relocation (always present), so it is called directly — server actions
# run sandboxed (no getattr/hasattr).
# ============================================================================
# ---------------------------- PASTE FROM HERE -------------------------------
if record.picking_id.picking_type_id.code == 'outgoing' and record.move_line_ids:

    Quant = env['stock.quant']

    # >>> MERGE 1: a merge pallet may be withdrawn in part — never force-overwrite
    # its curated selection. If any of the move's lines sit on a partial-withdrawal
    # package, leave quant_ids_picked exactly as the user/wizard set it.
    move_pkg_ids = record.move_line_ids.mapped('package_id').ids
    move_has_partial_pkg = any(
        Quant._vifel_package_allows_partial_withdrawal(pid)
        for pid in move_pkg_ids if pid)

    if not move_has_partial_pkg:
        lot_ids = record.move_line_ids.mapped('lot_id.id')

        initial_quant_ids = env['stock.quant'].search([
            ('lot_id', 'in', lot_ids),
            ('location_id.usage', '=', 'internal'),
            ('product_id', '=', record.product_id.id),
        ])

        # >>> MERGE 2: detect a genuine re-add (quants coming back that the move
        # did not already have) so we can INFORM instead of silently reverting.
        before_ids = set(record.quant_ids_picked.ids)
        after_ids = set(initial_quant_ids.ids)
        readded = after_ids - before_ids

        record['quant_ids_picked'] = [(6, 0, initial_quant_ids.ids)]

        # only speak up when the move already had a curated selection (before_ids
        # non-empty) and the overwrite put back quants that were removed — i.e. a
        # real revert, not the initial population.
        if before_ids and readded:
            pkgs = env['stock.quant'].browse(list(readded)).mapped('package_id.name')
            pkgs = ', '.join(p for p in pkgs if p) or record.product_id.display_name
            record.picking_id.message_post(body=(
                "Whole pallet withdrawn: pallet(s) %s are taken as a whole, so "
                "stock removed from the Picked Quants was added back. Un-merge or "
                "use a merge pallet to withdraw only part of a pallet." % pkgs))
