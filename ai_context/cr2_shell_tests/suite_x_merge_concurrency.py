# CR2 v2 Suite X - the empty pinned pallet is born exactly once.
#
# Two receipts for the same client both merging onto the pinned Fixed pallet
# while it is EMPTY would both see "no stock" and both birth it (+1 each) - the
# one physical pallet counted twice, and Re-sync does not self-heal because it
# counts a unique package once per RR. The fix: the birth happens once; if
# another OPEN receipt already claimed the empty pinned pallet, this one merges
# (+0, flagged). A FOR UPDATE lock on the package serialises true simultaneity.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_x_merge_concurrency.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    W = env['pallet.merge.wizard']
    ML = env['stock.move.line']
    owner = env['res.partner'].browse(428)

    # Fixed client, pinned to an EMPTY pallet.
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False,
                 'vifel_fixed_package_id': empty_pkg.id,
                 'vifel_fixed_psi': 'ZZZ-000001'})
    env.flush_all()
    check('X0 pinned pallet starts empty',
          not env['stock.quant'].search_count(
              [('package_id', '=', empty_pkg.id), ('quantity', '>', 0)]))

    # two DIFFERENT open incoming receipts for this owner
    pickings = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: p.move_line_ids.filtered('product_id'))[:2]
    check('X1 found two distinct open receipts', len(pickings) == 2,
          pickings.mapped('name'))
    rrA, rrB = pickings[0], pickings[1]
    lineA = rrA.move_line_ids.filtered('product_id')[0]
    lineB = rrB.move_line_ids.filtered('product_id')[0]

    # ---- receipt A: FIRST claim → births the pinned pallet (+1) --------
    wA = W.create({'move_line_id': lineA.id})
    tA = wA.candidate_line_ids.filtered('eligible')[:1]
    check('X2 A sees the empty pinned pallet as first stock',
          tA.first_stock, tA.first_stock)
    tA.is_target = True
    wA.action_confirm()
    env.flush_all()
    check('X3 A birthed the pinned pallet: unflagged (+1)',
          lineA.result_package_id == empty_pkg and not lineA.is_pallet_merge
          and lineA.x_studio_pallet_series_id == 'ZZZ-000001',
          (lineA.is_pallet_merge, lineA.x_studio_pallet_series_id))

    # ---- receipt B: the pinned pallet is now CLAIMED (A's line pending),
    #      still no stock → B must MERGE (+0, flagged), not birth again ----
    # the check is picking-RELATIVE: from A's own wizard the claim is its own
    # (not "another receipt"), so it must read False there; from a B-side
    # wizard, A's pending birth IS a foreign claim.
    check('X4a from A the claim is its own, not foreign',
          not wA._pinned_pallet_already_claimed(empty_pkg))
    wB = W.create({'move_line_id': lineB.id})
    check('X4b from B, A\'s pending birth reads as a foreign claim',
          wB._pinned_pallet_already_claimed(empty_pkg))
    tB = wB.candidate_line_ids.filtered('eligible')[:1]
    check('X5 B does NOT see it as first stock (already claimed)',
          not tB.first_stock, tB.first_stock)
    tB.is_target = True
    wB.action_confirm()
    env.flush_all()
    check('X6 B merged onto the pinned pallet: FLAGGED (+0), same PSI',
          lineB.result_package_id == empty_pkg and lineB.is_pallet_merge
          and lineB.x_studio_pallet_series_id == 'ZZZ-000001',
          (lineB.is_pallet_merge, lineB.x_studio_pallet_series_id))

    # ---- the ledger effect: one birth (+1), one merge (+0) = +1, not +2 -
    born = ML.search_count([
        ('result_package_id', '=', empty_pkg.id),
        ('is_pallet_merge', '=', False),
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel'))])
    check('X7 exactly ONE unflagged birth line across both receipts (+1)',
          born == 1, '%d unflagged lines on the pinned pallet' % born)

    # ---- the lock helper runs without error (serialisation path) --------
    wB._lock_pinned_pallet(empty_pkg)
    check('X8 the pinned-pallet row lock executes (serialises concurrency)',
          True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
