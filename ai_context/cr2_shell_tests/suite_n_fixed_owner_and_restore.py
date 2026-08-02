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

    # ---- B. FIRST STOCK on the empty pinned pallet (+1, unflagged) ---
    # User ruling 2026-07-23: +0 applies ONLY while the target already
    # holds stock. The first line to stock the pinned pallet BIRTHS it -
    # a plain +1 line - otherwise the WR that later empties it (-1) walks
    # the ledger negative on every empty->fill cycle.
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': False,
        'result_package_id': False})
    env.flush_all()
    check('B0 line starts with NO series (the reported scenario)',
          not line.x_studio_pallet_series_id)

    wiz = W.create({'move_line_id': line.id})
    tgt = wiz.candidate_line_ids.filtered('eligible')[:1]
    check('B1 the pinned (empty) pallet is offered', bool(tgt),
          len(wiz.candidate_line_ids))
    check('B1b ... and marked as first stock', tgt.first_stock)
    tgt.is_target = True
    wiz.action_confirm()
    env.flush_all()
    check('B2 first stock adopts the profile PSI but is NOT flagged (+1)',
          line.x_studio_pallet_series_id == 'ZZZ-000001'
          and not line.is_pallet_merge,
          (line.x_studio_pallet_series_id, line.is_pallet_merge))
    # Since UAT round 6 a pinned pallet is reserved the moment it is pinned,
    # stock or no stock, and deliberately carries NO receiving report: it is
    # dedicated to a client across many receipts, not reserved FOR one
    # document. So first stock finds it already reserved and leaves it alone.
    rr_ref = empty_pkg.x_studio_receiving_report_id
    check('B3 the pinned pallet is reserved but NOT tied to this receipt',
          empty_pkg.x_studio_is_reserved and not rr_ref,
          (empty_pkg.x_studio_is_reserved, rr_ref))
    check('B4 a LONE first-stock birth shows no Un-merge — it is the sole '
          'owner of the pallet, nothing to peel off (it captures its pre-merge '
          'state so it CAN un-merge once a sibling joins, but stays plain while '
          'alone)',
          not line.vifel_on_merged_pallet, line.vifel_on_merged_pallet)

    # ---- B-flagged: merge onto a STOCKED pinned pallet, exact restore -
    env.cr.execute("""
        SELECT sq.package_id FROM stock_quant sq
        JOIN stock_location sl ON sl.id=sq.location_id
        WHERE sq.owner_id=%s AND sq.quantity>0 AND sq.package_id IS NOT NULL
          AND sq.x_studio_pallet_series_id IS NOT NULL AND sl.usage='internal'
        GROUP BY sq.package_id
        HAVING COUNT(DISTINCT sq.x_studio_pallet_series_id)=1
        LIMIT 1""", (owner.id,))
    prow = env.cr.fetchone()
    check('B5 found a single-PSI stocked pallet of the client', bool(prow))
    pin = env['stock.quant.package'].browse(prow[0])
    pin_psi = pin.quant_ids.filtered(
        lambda q: q.quantity > 0
        and q.location_id.usage == 'internal').mapped(
        'x_studio_pallet_series_id')[0]
    owner.write({'vifel_fixed_package_id': pin.id,
                 'vifel_fixed_psi': 'ZZZ-000001'})
    env.flush_all()

    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': False, 'result_package_id': False})
    env.flush_all()
    start_loc = line.location_dest_id
    print('   line #%s starts at location %s'
          % (line.x_studio_, start_loc.complete_name))
    wiz2 = W.create({'move_line_id': line.id})
    t2 = wiz2.candidate_line_ids.filtered('eligible')[:1]
    t2.is_target = True
    wiz2.action_confirm()
    env.flush_all()
    check('B6 merge onto the STOCKED pinned pallet IS flagged (+0)',
          line.is_pallet_merge
          and line.x_studio_pallet_series_id == pin_psi,
          (line.is_pallet_merge, line.x_studio_pallet_series_id, pin_psi))
    check('B7 the pre-merge state was recorded',
          line.vifel_premerge_captured and not line.vifel_premerge_series,
          (line.vifel_premerge_captured, line.vifel_premerge_series))

    line.action_unmerge_pallet_line()
    env.flush_all()
    check('B8 un-merge cleared the flag', not line.is_pallet_merge)
    check('B9 the adopted PSI is ERASED (was left behind before)',
          not line.x_studio_pallet_series_id,
          line.x_studio_pallet_series_id)
    check('B10 the location is the one it started at, not a fallback (%s)'
          % line.location_dest_id.complete_name,
          line.location_dest_id == start_loc,
          (start_loc.complete_name, line.location_dest_id.complete_name))
    check('B11 the pre-merge record is cleared after use',
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
