# CR2 v2 Suite AA - a same-receipt joined line can be UN-merged (peeled off).
#
# Fixes the reported inconsistency: two lines sharing one pallet both show
# "Merged", but the joiner used to keep a "Merge Pallet" button and no way to
# un-merge (its is_pallet_merge is False, on purpose, so the pallet still counts
# +1). Now the joiner captures its pre-merge state, so it offers Un-merge and
# peels back off to its own pallet - WITHOUT ever flagging is_pallet_merge, so
# the ledger is untouched.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_aa_same_receipt_unmerge.py
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
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # the exact RR-5126 scenario: line 1 starts a NEW special pallet, line 2
    # joins it (same-receipt merge). Mirrors suite_l's controlled setup.
    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    l1, l2 = picking.move_line_ids.filtered('product_id')[:2]
    check('AA0 found a 2+ line receipt', bool(l1) and bool(l2),
          picking.name if picking else None)

    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    w1 = W.create({'move_line_id': l1.id, 'mode': 'new'})
    w1.write({'psi_type_id': sdmg.id, 'new_package_id': empty_pkg.id,
              'new_location_id': loc.id})
    w1.action_confirm()
    env.flush_all()

    # ---- line 2 joins line 1's new special pallet (same-receipt) ------
    w2 = W.create({'move_line_id': l2.id})
    tgt = w2.candidate_line_ids.filtered(
        lambda c: c.on_this_receipt and c.package_id == empty_pkg)[:1]
    join_pkg = tgt.package_id
    tgt.is_target = True
    w2.action_confirm()
    env.flush_all()
    check('AA1 line 2 joined the shared pallet, UNFLAGGED',
          l2.result_package_id == join_pkg and not l2.is_pallet_merge,
          (l2.result_package_id.name, l2.is_pallet_merge))
    check('AA2 the joiner captured its pre-merge state (so it can peel off)',
          l2.vifel_premerge_captured, l2.vifel_premerge_captured)
    # SYMMETRIC: both the host and the joiner show "Merged" and Un-merge.
    check('AA3 BOTH lines show the Merged marker (host + joiner)',
          l1.vifel_on_merged_pallet and l2.vifel_on_merged_pallet,
          (l1.vifel_on_merged_pallet, l2.vifel_on_merged_pallet))
    check('AA4 BOTH lines would show Un-merge (marker drives the button)',
          l1.vifel_on_merged_pallet and l2.vifel_on_merged_pallet)
    check('AA5 NEITHER flagged is_pallet_merge (pallet stays counted)',
          not l1.is_pallet_merge and not l2.is_pallet_merge)

    # ---- COUNTING: two lines on one pallet count as ONE received pallet
    def received_pkgs():
        return set(picking.move_line_ids.filtered(
            lambda m: m.result_package_id and not m.is_pallet_merge).mapped(
            'result_package_id.id'))
    check('AA6 shared pallet counts ONCE (both lines, +1)',
          join_pkg.id in received_pkgs()
          and len([m for m in picking.move_line_ids
                   if m.result_package_id == join_pkg]) == 2)

    # ---- UN-MERGE the JOINER: it peels off; the HOST keeps the pallet --
    l2.action_unmerge_pallet_line()
    env.flush_all()
    check('AA7 un-merge dropped the shared pallet off line 2',
          not l2.result_package_id, l2.result_package_id.name)
    check('AA8 un-merge cleared the adopted series (line is blank, re-assign)',
          not l2.x_studio_pallet_series_id, l2.x_studio_pallet_series_id)
    check('AA9 line 2 is no longer "merged"',
          not l2.vifel_premerge_captured and not l2.vifel_on_merged_pallet)
    check('AA10 the HOST line is untouched - still on its pallet',
          l1.result_package_id == join_pkg, l1.result_package_id.name)
    # CRITICAL COUNTING: pallet is STILL counted +1 (host remains on it)
    check('AA10b the pallet STILL counts +1 after the joiner left',
          join_pkg.id in received_pkgs(), sorted(received_pkgs()))
    # the host is now the sole line -> no longer "shared" -> marker off, and it
    # goes back to offering Merge Pallet. Consistent.
    check('AA10c the HOST is now a plain line again (marker off, can Merge)',
          not l1.vifel_on_merged_pallet)
    # the stored display series is cleared too (no stale PSI)
    if 'x_studio_pallet_series_display' in l2._fields:
        check('AA11 the stored display series was cleared (no stale PSI)',
              not l2.x_studio_pallet_series_display,
              l2.x_studio_pallet_series_display)
    else:
        check('AA11 the stored display series was cleared (no stale PSI)', True)

    # ---- a plain line (never merged) still cannot be un-merged --------
    from odoo.exceptions import UserError
    l3 = picking.move_line_ids.filtered(
        lambda m: m != l1 and m != l2 and not m.vifel_premerge_captured
        and not m.is_pallet_merge)[:1]
    if l3:
        try:
            l3.action_unmerge_pallet_line()
            check('AA12 a never-merged line still refuses Un-merge', False)
        except UserError:
            check('AA12 a never-merged line still refuses Un-merge', True)
    else:
        check('AA12 a never-merged line still refuses Un-merge', True, '(n/a)')

    # ====================================================================
    # HOST un-merge + full peel: re-join line 2, then peel BOTH off.
    # ====================================================================
    w2b = W.create({'move_line_id': l2.id})
    t2b = w2b.candidate_line_ids.filtered(
        lambda c: c.on_this_receipt and c.package_id == l1.result_package_id)[:1]
    host_pkg = l1.result_package_id
    host_series = l1.x_studio_pallet_series_id
    t2b.is_target = True
    w2b.action_confirm()
    env.flush_all()
    check('AA13 re-joined: both lines share the pallet again, +1',
          l1.result_package_id == host_pkg and l2.result_package_id == host_pkg
          and host_pkg.id in received_pkgs())

    # peel the HOST (line 1) off — the JOINER keeps the pallet, count holds
    l1.action_unmerge_pallet_line()
    env.flush_all()
    check('AA14 the HOST peeled off (blank line now)',
          not l1.result_package_id and not l1.x_studio_pallet_series_id)
    check('AA15 the JOINER now solely holds the pallet - STILL counts +1',
          l2.result_package_id == host_pkg and host_pkg.id in received_pkgs(),
          sorted(received_pkgs()))

    # the joiner is now the SOLE line on the pallet -> a plain line again, NOT
    # "merged" -> it cannot be un-merged (there is nothing to peel it off from;
    # it IS the pallet now). This is why a pallet can never be emptied by
    # un-merging: the last line just becomes its normal owner, still +1.
    check('AA16 the sole remaining line is a plain line (marker off)',
          not l2.vifel_on_merged_pallet, l2.vifel_on_merged_pallet)
    try:
        l2.action_unmerge_pallet_line()
        check('AA17 the sole line refuses Un-merge (it IS the pallet, +1)',
              False, 'no error')
    except UserError:
        check('AA17 the sole line refuses Un-merge (it IS the pallet, +1)',
              True)
    check('AA18 the pallet is STILL counted +1 (its lone owner holds it)',
          host_pkg.id in received_pkgs(), sorted(received_pkgs()))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
