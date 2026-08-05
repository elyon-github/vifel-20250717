# ============================================================================
# SERVER ACTION "Backfill Merge-Pallet Identity"  (model: stock.quant.package,
#   type: Execute Code)  —  ONE-TIME deploy step, paste-ready.
#
#   Studio -> Server Actions -> New -> Model = Package (stock.quant.package),
#   Type = Execute Python Code -> paste everything below the divider -> Save ->
#   run once via "Run" (Action menu). Idempotent — safe to run again.
#
# WHY
# ---
# The durable merge identity `vifel_is_merge_pallet` is set going forward by the
# module (a line merged onto a package, or a Fixed pin). This backfills the flag
# for packages that ALREADY are merge/condition pallets, so partial withdrawal
# keeps working the moment the module is upgraded. Run it in the SAME maintenance
# window as the `vifel_client_requirements` upgrade.
#
# A package is backfilled True when it is EITHER:
#   (a) pinned as some client's Fixed Merge Pallet, OR
#   (b) currently HOLDS stock AND has any move line carrying a merge marker
#       (`is_pallet_merge` or `vifel_premerge_captured`).
# Empty packages with only historical merged lines are deliberately NOT flagged
# (they have been withdrawn — the next receipt re-sets the flag if it merges).
# ============================================================================
# ---------------------------- PASTE FROM HERE -------------------------------
Package = env['stock.quant.package']
MoveLine = env['stock.move.line']

# (a) pinned Fixed pallets
pinned = env['res.partner']._vifel_fixed_merge_packages()

# (b) packages that currently hold stock AND have a marker-bearing line
stocked_pkg_ids = set(env['stock.quant'].search([
    ('package_id', '!=', False), ('quantity', '>', 0),
    ('location_id.usage', '=', 'internal'),
]).mapped('package_id').ids)

marked_pkg_ids = set(MoveLine.search([
    ('result_package_id', '!=', False),
    '|', ('is_pallet_merge', '=', True),
         ('vifel_premerge_captured', '=', True),
]).mapped('result_package_id').ids)

to_flag_ids = set(pinned.ids) | (stocked_pkg_ids & marked_pkg_ids)

to_flag = Package.browse(list(to_flag_ids)).exists().filtered(
    lambda p: not p.vifel_is_merge_pallet)
if to_flag:
    to_flag.write({'vifel_is_merge_pallet': True})

# NOTE: do NOT raise here — a Studio "Execute Code" action rolls back on any
# raised exception, which would DISCARD the backfill. The write above persists on
# a clean run (Studio's sandbox also blocks logging/imports, so nothing is
# printed). To see the result afterwards, run in a shell or a second action:
#   env['stock.quant.package'].search_count([('vifel_is_merge_pallet','=',True)])
