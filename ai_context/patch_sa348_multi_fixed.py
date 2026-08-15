# One-time patch: update Server Action "X_Verifier Check on Receipt" (SA#348) for
# the multiple-Fixed-Merge-Pallet change. It read the OLD single field
# res.partner.vifel_fixed_package_id (now removed) to exempt a line on the client's
# pinned Fixed pallet from the "already reserved elsewhere" guard; a client may now
# pin SEVERAL, so it must check membership in vifel_fixed_pallet_ids.mapped('package_id').
#
# WHEN TO RUN: on any DB where SA#348 still reads the old field (an existing dev DB,
# or production if it carries the pre-change SA). Idempotent. Equivalent to just
# re-pasting the whole SA from sa348_verifier_exempt_merged_lines.py.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/patch_sa348_multi_fixed.py
sa = env['ir.actions.server'].sudo().search(
    [('name', '=', 'X_Verifier Check on Receipt')], limit=1)
if not sa:
    sa = env['ir.actions.server'].sudo().browse(348).exists()
if not sa:
    print('SA "X_Verifier Check on Receipt" not found - nothing to patch.')
else:
    code = sa.code or ''
    if 'vifel_fixed_package_id' not in code:
        print('SA#%s already patched (no vifel_fixed_package_id) - nothing to do.' % sa.id)
    else:
        old_A = ("        _fixed_pkg = line.picking_id.partner_id.vifel_fixed_package_id\n"
                 "        _reserved_ok = line.is_pallet_merge or (\n"
                 "            _fixed_pkg and line.result_package_id == _fixed_pkg)")
        new_A = ("        _fixed_pkgs = line.picking_id.partner_id.vifel_fixed_pallet_ids.mapped('package_id')\n"
                 "        _reserved_ok = line.is_pallet_merge or (\n"
                 "            line.result_package_id and line.result_package_id in _fixed_pkgs)")
        old_B = "# is_pallet_merge and vifel_fixed_package_id are defined"
        new_B = "# is_pallet_merge and vifel_fixed_pallet_ids are defined"
        if code.count(old_A) != 1:
            print('WARNING: expected code block not found exactly once (found %d). '
                  'Re-paste the full SA from sa348_verifier_exempt_merged_lines.py '
                  'instead.' % code.count(old_A))
        else:
            code = code.replace(old_A, new_A).replace(old_B, new_B)
            sa.code = code
            env.cr.commit()
            print('SA#%s patched + committed. remaining old-field refs: %d'
                  % (sa.id, code.count('vifel_fixed_package_id')))
