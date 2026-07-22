# CR2 v2 Suite L - same-receipt pallets, and pinning a merged line.
#
# Two things found in UAT:
#
# 1. A pallet started earlier on the SAME receipt has no quant yet, so the
#    stocked-pallet search could not see it and a second line could not
#    join it. Such targets are now offered, labelled "On this receipt",
#    and are deliberately NOT flagged is_pallet_merge: the ledger counts
#    unique pallets per receipt, so the two lines already count one. Flag
#    them and deleting the line that CREATED the pallet would leave it
#    counted zero - an undercount on a pallet that physically exists.
#    Offered in Multiple mode only; a Fixed client keeps its one pallet.
#
# 2. A merged line could have its Location or Series edited silently -
#    the un-merge intercept only watched result_package_id - leaving the
#    document pointing where the adopted pallet is not. Both are refused
#    now; Un-merge is the only way out. The guard skips a merged line
#    whose pallet is already cleared, which is the un-merge restore
#    machinery re-entering write through base_automation.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_l_same_receipt_and_pinning.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.exceptions import UserError
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # needs at least three encodable lines: two to share a pallet, one to
    # merge onto stored stock
    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')),
        ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 3)[:1]
    check('U0 found a receipt with at least 3 lines', bool(picking))
    lines = picking.move_line_ids.filtered('product_id')[:2]
    l1, l2 = lines[0], lines[1]
    print('picking %s | line1 #%s | line2 #%s'
          % (picking.name, l1.x_studio_, l2.x_studio_))

    # ---- line 1 starts a NEW special pallet (nothing stocked yet) -----
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('warehouse_id', '=', picking.warehouse_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    mdgm = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'MDGM')
    w1 = W.create({'move_line_id': l1.id, 'mode': 'new'})
    w1.write({'psi_type_id': mdgm.id, 'new_package_id': empty_pkg.id,
              'new_location_id': loc.id})
    w1.action_confirm()
    env.flush_all()
    new_psi = l1.x_studio_pallet_series_id
    check('U1 line 1 started a new special pallet (%s on %s)'
          % (new_psi, empty_pkg.name),
          new_psi.startswith('MDGM-') and l1.result_package_id == empty_pkg)
    stocked = env['stock.quant'].search_count([
        ('package_id', '=', empty_pkg.id), ('quantity', '>', 0)])
    check('U2 that pallet holds NO stock yet (the reason it was invisible)',
          stocked == 0, stocked)

    # ---- line 2 must now be able to join it --------------------------
    w2 = W.create({'move_line_id': l2.id})
    same_rr = w2.candidate_line_ids.filtered('on_this_receipt')
    check('U3 line 2 is now offered the pallet from THIS receipt',
          empty_pkg.id in same_rr.mapped('package_id').ids,
          same_rr.mapped('psi'))
    cand = same_rr.filtered(lambda c: c.package_id == empty_pkg)[:1]
    check('U4 it is labelled so the user knows it is not in storage',
          cand.source_label == 'On this receipt', cand.source_label)
    check('U5 it shows the series line 1 drew', cand.psi == new_psi, cand.psi)

    cand.is_target = True
    w2.action_confirm()
    env.flush_all()
    check('U6 line 2 adopted the same pallet / series / location',
          l2.result_package_id == empty_pkg
          and l2.x_studio_pallet_series_id == new_psi
          and l2.location_dest_id == l1.location_dest_id,
          (l2.result_package_id.name, l2.x_studio_pallet_series_id))
    check('U7 line 2 is NOT flagged Merged (protects the pallet count)',
          not l2.is_pallet_merge)

    # both lines on one pallet must count as ONE received pallet
    pkgs = set(picking.move_line_ids.filtered(
        lambda m: m.result_package_id and not m.is_pallet_merge)
        .mapped('result_package_id').ids)
    check('U8 the two lines together count as one pallet',
          len([p for p in pkgs if p == empty_pkg.id]) == 1)

    # ---- a MERGED line refuses silent edits --------------------------
    l3 = picking.move_line_ids.filtered(
        lambda m: m.product_id and m.id not in (l1.id, l2.id))[:1]
    w3 = W.create({'move_line_id': l3.id})
    stocked_cand = w3.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    stocked_cand.is_target = True
    w3.action_confirm()
    env.flush_all()
    check('U9 line 3 merged onto a stocked pallet and IS flagged',
          l3.is_pallet_merge)

    other_loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('warehouse_id', '=', picking.warehouse_id.id),
        ('id', '!=', l3.location_dest_id.id)], limit=1)
    try:
        l3.write({'location_dest_id': other_loc.id})
        check('U10 changing LOCATION on a merged line is refused', False,
              'no error raised — silent mismatch possible')
    except UserError as e:
        check('U10 changing LOCATION on a merged line is refused',
              'Un-merge' in str(e), str(e)[:90])
    try:
        l3.write({'x_studio_pallet_series_id': 'ZZZ-000001'})
        check('U11 changing the SERIES on a merged line is refused', False,
              'no error raised')
    except UserError as e:
        check('U11 changing the SERIES on a merged line is refused',
              'Un-merge' in str(e), str(e)[:90])

    # ---- but Un-merge itself still works -----------------------------
    l3.action_unmerge_pallet_line()
    env.flush_all()
    check('U12 Un-merge still works and clears the flag',
          not l3.is_pallet_merge)
    l3.write({'location_dest_id': other_loc.id})
    check('U13 after un-merging, the location can be changed again',
          l3.location_dest_id == other_loc)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
