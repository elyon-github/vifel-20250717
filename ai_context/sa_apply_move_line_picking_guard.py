# PASTE TARGET: a NEW server action, model = ir.model.fields (or any model), type "Execute Code"
# Suggested name: "VIFEL: Apply picking_id guard to move-line computes"
# Run it once from Settings > Technical > Server Actions > (this action) > Run.
#
# WHAT IT DOES
# ------------
# Rewrites the compute code of 13 stored Studio fields on stock.move.line so they SKIP
# move lines that belong to no picking (inventory adjustment / scrap / quant moves).
#
# Those computes loop over `location.quant_ids`. For a POSITIVE inventory adjustment the
# source location is the virtual "Inventory adjustment" location, which holds 23,000+
# quants -- so every created line scanned all of them, ~15 times over. Measured:
# 1226 ms/line before, 109 ms/line after = 11.3x  (~16.4 min -> ~1.5 min for 800 quants).
# Full evidence: ai_context/studio_computes_inventory_apply_perf_FIX.md
#
# SAFETY
# ------
# * Idempotent - re-running skips fields that already carry the guard.
# * Refuses to touch a field whose code does not match the expected pattern exactly
#   (reports it instead, so nothing is mangled silently).
# * Backs up every original body into ir.config_parameter before writing.
#   Restore script at the bottom of this file.
# * Real RR/WR lines are unaffected: they always have a picking, so they take the
#   identical code path as today.
# * x_studio_pallet_series_id is deliberately NOT in the list - it already guards on
#   'outgoing' only, so it never ran for inventory lines.

MODEL = 'stock.move.line'
BACKUP_PREFIX = 'vifel.smlguard.backup.'

# NOT HERE - these two are Python computes in multiple_relocation/models/stock_move.py
# (state='base', so this action deliberately refuses them). Edit them in the module:
#   _compute_container_number        (~line 447)  -> x_studio_container_number
#   _compute_x_studio_building_dropped (~line 461)-> x_studio_building_dropped
# Same change: "if record.picking_id and (record['picking_code'] == ... )".
#
# Group A - already have the guard; add "record.picking_id and"
GROUP_A = [
    'x_studio_affected_2nd_uom',
    'x_studio_withdraw_units',
    'x_studio_expiration_date',
    'x_studio_min_quantity_uom',
    'x_studio_production_date',
    'x_studio_quantity_uom_delivery',
    'x_studio_return_count',
    'x_studio_sh_reason',
    'x_studio_special_holding',
]
# Group B - no guard at all; insert an early skip
GROUP_B = [
    'x_studio_max_2nd_uom',
    'x_studio_max_quant',
    'x_studio_max_total_units',
]

OLD_GUARD = "if record['picking_code'] == 'outgoing' or not record['picking_code']:"
NEW_GUARD = ("if record.picking_id and (record['picking_code'] == 'outgoing' "
             "or not record['picking_code']):")
LOOP = 'for record in self:'
SKIP = ("\n    # inventory-adjustment / scrap lines have no transfer to size against"
        "\n    if not record.picking_id:\n        continue\n")

Fields = env['ir.model.fields'].sudo()
Param = env['ir.config_parameter'].sudo()

done, skipped, problems = [], [], []

for fname in GROUP_A + GROUP_B:
    field = Fields.search([('model', '=', MODEL), ('name', '=', fname)], limit=1)
    if not field:
        problems.append('%s: field not found' % fname)
        continue
    if field.state != 'manual':
        problems.append('%s: not a custom field (state=%s) - edit in code instead'
                        % (fname, field.state))
        continue

    code = field.compute or ''
    if not code.strip():
        problems.append('%s: no compute code' % fname)
        continue
    if 'record.picking_id' in code:
        skipped.append('%s: already guarded' % fname)
        continue

    if fname in GROUP_A:
        if code.count(OLD_GUARD) != 1:
            problems.append('%s: expected guard found %d time(s) - left untouched'
                            % (fname, code.count(OLD_GUARD)))
            continue
        new_code = code.replace(OLD_GUARD, NEW_GUARD)
    else:
        if code.count(LOOP) != 1:
            problems.append('%s: loop header found %d time(s) - left untouched'
                            % (fname, code.count(LOOP)))
            continue
        new_code = code.replace(LOOP, LOOP + SKIP, 1)

    Param.set_param(BACKUP_PREFIX + fname, code)
    field.write({'compute': new_code})
    done.append(fname)

lines = ['Patched: %d   Already done: %d   Needs attention: %d'
         % (len(done), len(skipped), len(problems))]
if done:
    lines.append('')
    lines.append('PATCHED:')
    lines += ['  + ' + n for n in done]
if skipped:
    lines.append('')
    lines.append('SKIPPED (already guarded):')
    lines += ['  = ' + n for n in skipped]
if problems:
    lines.append('')
    lines.append('NEEDS ATTENTION (nothing was changed for these):')
    lines += ['  ! ' + n for n in problems]
lines.append('')
lines.append('Originals saved in System Parameters under "%s".' % BACKUP_PREFIX)
lines.append('Now re-test: a normal WR must still fill Max / Actual / container / expiry / PSI.')

message = '\n'.join(lines)
log(message)

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'VIFEL: move-line compute guard',
        'message': message,
        'sticky': True,
        'type': 'warning' if problems else 'success',
    },
}


# =====================================================================================
# ROLLBACK - paste this into a SECOND server action if you ever need to undo the above.
# =====================================================================================
#
# BACKUP_PREFIX = 'vifel.smlguard.backup.'
# MODEL = 'stock.move.line'
# NAMES = [
#     'x_studio_affected_2nd_uom', 'x_studio_withdraw_units', 'x_studio_container_number',
#     'x_studio_expiration_date', 'x_studio_min_quantity_uom', 'x_studio_production_date',
#     'x_studio_quantity_uom_delivery', 'x_studio_return_count', 'x_studio_sh_reason',
#     'x_studio_special_holding', 'x_studio_max_2nd_uom', 'x_studio_max_quant',
#     'x_studio_max_total_units',
# ]
# Fields = env['ir.model.fields'].sudo()
# Param = env['ir.config_parameter'].sudo()
# restored, missing = [], []
# for fname in NAMES:
#     original = Param.get_param(BACKUP_PREFIX + fname)
#     if not original:
#         missing.append(fname)
#         continue
#     field = Fields.search([('model', '=', MODEL), ('name', '=', fname)], limit=1)
#     if field:
#         field.write({'compute': original})
#         restored.append(fname)
# action = {
#     'type': 'ir.actions.client', 'tag': 'display_notification',
#     'params': {'title': 'VIFEL: rollback',
#                'message': 'Restored %d field(s). No backup for: %s'
#                           % (len(restored), ', '.join(missing) or 'none'),
#                'sticky': True, 'type': 'success'},
# }
