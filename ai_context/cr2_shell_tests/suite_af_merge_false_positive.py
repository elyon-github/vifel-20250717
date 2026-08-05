# CR2 v2 Suite AF - the "Merged" marker tells a real merge from ordinary
# multi-line-on-one-pallet encoding, and un-merge restores the original series.
#
# Reported on M/RR/05299: two normal lines share one pallet (same PSI, NO merge
# markers) and were wrongly shown "Merged" on BOTH the Pallet Breakdown and the
# Magic Wizard; un-merging them destroyed their real data. Root cause: the
# marker keyed on "shares a pallet" alone. Now it requires a genuine marker
# (is_pallet_merge / vifel_premerge_captured) on the shared pallet, and a
# same-receipt un-merge restores the joiner's ORIGINAL Pallet Series when it is
# still free.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_af_merge_false_positive.py
#
# The Magic Wizard STAGED un-merge (row flips now, real line only on Confirm) is
# covered by suite_ac; here we cover false-positive detection, restore-if-free,
# and the defensive detach guard.
#
# Rollback-only: nothing is committed.
import traceback

from odoo.exceptions import UserError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    W = env['pallet.merge.wizard']
    Line = env['stock.move.line.fast_encode_rr.line']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    l1, l2 = picking.move_line_ids.filtered('product_id')[:2]
    check('AF0 found a 2+ line receipt', bool(l1) and bool(l2),
          picking.name if picking else None)

    # ====================================================================
    # FALSE POSITIVE: two ORDINARY lines on one pallet (same PSI, no merge
    # marker) - the M/RR/05299 scenario. NOT a merge.
    # ====================================================================
    pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    for l in (l1, l2):
        l.with_context(skip_pallet_series_sync=True, vifel_pallet_merge=True).write(
            {'result_package_id': pkg.id,
             'x_studio_pallet_series_id': '7S-000049',
             'is_pallet_merge': False, 'vifel_premerge_captured': False})
    env.flush_all()
    check('AF1 two ordinary lines share the pallet with NO merge marker',
          l1.result_package_id == pkg and l2.result_package_id == pkg
          and not l1.is_pallet_merge and not l2.is_pallet_merge
          and not l1.vifel_premerge_captured and not l2.vifel_premerge_captured)
    check('AF2 NEITHER line is flagged "Merged" on the Pallet Breakdown '
          '(sharing a pallet is not a merge)',
          not l1.vifel_on_merged_pallet and not l2.vifel_on_merged_pallet,
          (l1.vifel_on_merged_pallet, l2.vifel_on_merged_pallet))

    # same two lines mirrored as Magic Wizard rows -> also NOT merged
    fw = env['stock.move.line.fast_encode_rr'].create({'transfer_id': picking.id})
    r1 = Line.create({'wizard_id': fw.id, 'stock_move_line': l1.id,
                      'x_studio_': l1.x_studio_ or 0, 'product_id': l1.product_id.id,
                      'result_package_id': pkg.id})
    r2 = Line.create({'wizard_id': fw.id, 'stock_move_line': l2.id,
                      'x_studio_': l2.x_studio_ or 0, 'product_id': l2.product_id.id,
                      'result_package_id': pkg.id})
    env.flush_all()
    check('AF3 the Magic Wizard rows are NOT flagged "Merged" either',
          not r1.vifel_on_merged_pallet and not r2.vifel_on_merged_pallet,
          (r1.vifel_on_merged_pallet, r2.vifel_on_merged_pallet))
    try:
        l1.action_unmerge_pallet_line()
        check('AF4 an ordinary line refuses Un-merge (nothing to peel)', False,
              'no error raised')
    except UserError:
        check('AF4 an ordinary line refuses Un-merge (nothing to peel)', True)

    # DEFENSIVE: even the raw detach helper is a no-op on a plain line - it must
    # never blank an ordinary line's Pallet Series.
    series_before = l1.x_studio_pallet_series_id
    l1._vifel_detach_same_receipt_join(False)
    env.flush_all()
    check('AF5 the detach helper never blanks a plain line (defensive guard)',
          l1.result_package_id == pkg
          and l1.x_studio_pallet_series_id == series_before,
          (l1.result_package_id.name, l1.x_studio_pallet_series_id))

    env.cr.rollback()   # discard the false-positive fixture before the next part

    # ====================================================================
    # RESTORE-IF-FREE: a genuine same-receipt merge whose joiner HAD its own
    # series - un-merge restores that original series (drawn back), not blank.
    # ====================================================================
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    l1, l2 = picking.move_line_ids.filtered('product_id')[:2]
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    aisle = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')

    # line 1 starts a new special pallet; give line 2 its OWN drawn series first
    w1 = W.create({'move_line_id': l1.id, 'mode': 'new'})
    w1.write({'psi_type_id': sdmg.id, 'new_package_id': empty_pkg.id,
              'new_location_id': aisle.id})
    w1.action_confirm()
    joiner_series = sdmg.draw_number()
    l2.with_context(skip_pallet_series_sync=True, vifel_pallet_merge=True).write(
        {'x_studio_pallet_series_id': joiner_series})
    env.flush_all()
    check('AF6 the joiner starts with its own drawn series',
          bool(joiner_series) and l2.x_studio_pallet_series_id == joiner_series,
          joiner_series)

    # line 2 joins line 1's pallet (same-receipt merge)
    w2 = W.create({'move_line_id': l2.id})
    t = w2.candidate_line_ids.filtered(
        lambda c: c.on_this_receipt and c.package_id == empty_pkg)[:1]
    t.is_target = True
    w2.action_confirm()
    env.flush_all()
    check('AF7 the joiner captured its ORIGINAL series for restore',
          l2.vifel_premerge_captured
          and l2.vifel_premerge_series == joiner_series,
          (l2.vifel_premerge_captured, l2.vifel_premerge_series))
    check('AF8 while merged the joiner wears the adopted series (not its own)',
          l2.x_studio_pallet_series_id != joiner_series
          and l2.vifel_on_merged_pallet)

    # un-merge -> the original series is still free, so it is RESTORED
    stocked = owner._vifel_series_is_stocked(joiner_series)
    l2.action_unmerge_pallet_line()
    env.flush_all()
    if not stocked:
        check('AF9 un-merge RESTORED the joiner\'s original series (it was free)',
              l2.x_studio_pallet_series_id == joiner_series,
              l2.x_studio_pallet_series_id)
    else:
        check('AF9 un-merge blanked the series (original no longer free)',
              not l2.x_studio_pallet_series_id, l2.x_studio_pallet_series_id)
    check('AF10 the joiner is no longer merged and left the pallet',
          not l2.vifel_on_merged_pallet and not l2.result_package_id)
    check('AF11 the host still holds the pallet (still counted +1)',
          l1.result_package_id == empty_pkg)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
