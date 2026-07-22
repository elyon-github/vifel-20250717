# CR2 v2 Suite N - fixed-pallet ownership, and exact un-merge restore.
#
# A. The pinned Fixed pallet must be free or already hold THIS client's
#    stock. Pinning one occupied by someone else would point every merge
#    at another client's goods. (Multiple mode was already safe: its
#    candidate search is owner-scoped.)
#
# B. Un-merging a line that had NO series and NO location before the
#    merge used to leave the adopted series behind and reset the location
#    to a hardcoded fallback - the generic restore is gated on
#    original_pallet_series_id / x_studio_initial_location, and a line
#    with neither falls straight through it. The merge now records what
#    it displaced (vifel_premerge_*) so un-merge puts back exactly that,
#    including "there was nothing here". C repeats the whole scenario in
#    Multiple mode - both modes share the code path, and both are checked.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_n_fixed_owner_and_restore.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.exceptions import ValidationError
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)          # TECHNO FARM

    # ---- A. the pinned pallet must be free or already theirs ---------
    foreign_q = env['stock.quant'].search([
        ('package_id', '!=', False), ('quantity', '>', 0),
        ('owner_id', '!=', False), ('owner_id', '!=', owner.id),
        ('location_id.usage', '=', 'internal')], limit=1)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()
    try:
        owner.write({'vifel_fixed_package_id': foreign_q.package_id.id,
                     'vifel_fixed_psi': 'ZZZ-000001'})
        env.flush_all()
        check('A1 a pallet owned by another client is refused', False,
              'no error raised')
    except ValidationError as e:
        check('A1 a pallet owned by another client is refused',
              'holding stock owned by' in str(e), str(e)[:90])

    own_q = env['stock.quant'].search([
        ('package_id', '!=', False), ('quantity', '>', 0),
        ('owner_id', '=', owner.id),
        ('location_id.usage', '=', 'internal')], limit=1)
    owner.write({'vifel_fixed_package_id': own_q.package_id.id,
                 'vifel_fixed_psi': 'ZZZ-000001'})
    env.flush_all()
    check('A2 a pallet already holding THEIR stock is accepted',
          owner.vifel_fixed_package_id == own_q.package_id)

    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    owner.write({'vifel_fixed_package_id': empty_pkg.id,
                 'vifel_fixed_psi': 'ZZZ-000001'})
    env.flush_all()
    check('A3 an empty pallet is accepted',
          owner.vifel_fixed_package_id == empty_pkg)

    # ---- B. un-merge a line that had NO series and NO location -------
    # Fixed mode, so the pinned (empty) pallet is the target.
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    start_loc = line.location_dest_id
    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': False,
        'result_package_id': False})
    env.flush_all()
    check('B0 line starts with NO series (the reported scenario)',
          not line.x_studio_pallet_series_id)
    print('   line #%s starts at location %s'
          % (line.x_studio_, start_loc.complete_name))

    wiz = W.create({'move_line_id': line.id})
    tgt = wiz.candidate_line_ids.filtered('eligible')[:1]
    check('B1 the pinned pallet is offered', bool(tgt), len(wiz.candidate_line_ids))
    tgt.is_target = True
    wiz.action_confirm()
    env.flush_all()
    check('B2 merged and adopted the profile PSI',
          line.is_pallet_merge and line.x_studio_pallet_series_id == 'ZZZ-000001',
          line.x_studio_pallet_series_id)
    check('B3 the pre-merge state was recorded',
          line.vifel_premerge_captured
          and not line.vifel_premerge_series
          and line.vifel_premerge_location_id == start_loc,
          (line.vifel_premerge_captured, line.vifel_premerge_series,
           line.vifel_premerge_location_id.complete_name))

    line.action_unmerge_pallet_line()
    env.flush_all()
    check('B4 un-merge cleared the flag', not line.is_pallet_merge)
    check('B5 the adopted PSI is ERASED (was left behind before)',
          not line.x_studio_pallet_series_id,
          line.x_studio_pallet_series_id)
    check('B6 the location is the one it started at, not a fallback (%s)'
          % line.location_dest_id.complete_name,
          line.location_dest_id == start_loc,
          (start_loc.complete_name, line.location_dest_id.complete_name))
    check('B7 the pre-merge record is cleared after use',
          not line.vifel_premerge_captured)

    # ---- C. same scenario in MULTIPLE mode ---------------------------
    owner.write({'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    line2 = env['stock.move.line'].search([
        ('picking_id', '=', line.picking_id.id),
        ('product_id', '!=', False), ('id', '!=', line.id)], limit=1)
    start_loc2 = line2.location_dest_id
    line2.with_context(skip_pallet_series_sync=True).write(
        {'x_studio_pallet_series_id': False, 'result_package_id': False})
    env.flush_all()
    w2 = W.create({'move_line_id': line2.id})
    t2 = w2.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    t2.is_target = True
    w2.action_confirm()
    env.flush_all()
    check('C1 multiple-mode merge also records pre-merge state',
          line2.vifel_premerge_captured and not line2.vifel_premerge_series)
    line2.action_unmerge_pallet_line()
    env.flush_all()
    check('C2 multiple-mode un-merge also erases the adopted PSI',
          not line2.x_studio_pallet_series_id,
          line2.x_studio_pallet_series_id)
    check('C3 multiple-mode un-merge restores the original location',
          line2.location_dest_id == start_loc2,
          (start_loc2.complete_name, line2.location_dest_id.complete_name))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
