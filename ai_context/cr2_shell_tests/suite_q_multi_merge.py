# CR2 v2 Suite Q - multi-select merge.
#
# Tick several lines, merge them all onto ONE target pallet in one pass.
# The selection-bar "Merge Selected" button opens the wizard seeded with
# every mergeable line (both surfaces); ineligible lines - already merged,
# return/BF/validated - are dropped up front and any that slip through are
# skipped at confirm with a note, so one stray row never blocks the rest.
#
# Each line still decides its own flag/first-stock from the target's stock
# state, and the ledger dedupes by unique package per RR, so several lines
# on one pallet count exactly one.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_q_multi_merge.py
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
    ML = env['stock.move.line']
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 3)[:1]
    lines = picking.move_line_ids.filtered('product_id')[:3]
    print('picking %s | lines %s' % (picking.name, lines.mapped('x_studio_')))

    # ---- opener from the Pallet Breakdown ----------------------------
    act = lines.action_open_pallet_merge_wizard_multi()
    wiz = W.browse(act['res_id'])
    check('M1 the multi opener seeds all selected lines',
          set(wiz.move_line_ids.ids) == set(lines.ids), wiz.move_line_ids.ids)
    check('M2 the wizard reads as multi', wiz.is_multi and wiz.multi_count == 3)
    check('M3 aggregate weight = sum of the lines',
          abs(wiz.multi_weight - sum(lines.mapped('quantity'))) < 0.01)
    check('M4 candidates exclude every selected line\'s own pallet',
          not (wiz.candidate_line_ids.package_id
               & lines.mapped('result_package_id')),
          (wiz.candidate_line_ids.package_id & lines.mapped('result_package_id')).mapped('name'))

    # ---- merge all three onto one stocked target ---------------------
    tgt = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    adopted = tgt.psi
    tgt_pkg = tgt.package_id
    tgt.is_target = True
    res = wiz.action_confirm()
    env.flush_all()
    check('M5 all three lines landed on the one target',
          all(l.result_package_id == tgt_pkg for l in lines),
          lines.mapped('result_package_id.name'))
    check('M6 all three adopted the target PSI',
          all(l.x_studio_pallet_series_id == adopted for l in lines))
    check('M7 all three flagged is_pallet_merge (+0 each)',
          all(l.is_pallet_merge for l in lines))
    check('M8 one summary toast for the whole pass',
          isinstance(res, dict) and res.get('tag') == 'display_notification'
          and '3 line' in res['params']['message'],
          res.get('params', {}).get('message'))

    # ---- un-merge all, then test skip of ineligible ------------------
    for _l in lines:
        _l.action_unmerge_pallet_line()
    env.flush_all()
    # make line[0] already-merged, and grab an outgoing line as a bad apple
    l0, l1, l2 = lines[0], lines[1], lines[2]
    wsingle = W.create({'move_line_id': l0.id})
    st = wsingle.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    st.is_target = True
    wsingle.action_confirm()
    env.flush_all()
    check('M9 line 0 is now merged (an ineligible pick for the next pass)',
          l0.is_pallet_merge)

    act2 = (l0 + l1 + l2).action_open_pallet_merge_wizard_multi()
    wiz2 = W.browse(act2['res_id'])
    check('M10 the already-merged line was dropped from the pass',
          l0 not in wiz2.move_line_ids and l1 in wiz2.move_line_ids)
    tgt2 = wiz2.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    tgt2.is_target = True
    res2 = wiz2.action_confirm()
    env.flush_all()
    check('M11 the two eligible lines merged',
          l1.is_pallet_merge and l2.is_pallet_merge)

    # ---- multi header renders ----------------------------------------
    arch = W.get_view(
        env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,
        'form')['arch']
    check('M12 the wizard has a multi summary card',
          'multi_count' in arch and 'Lines selected' in arch)
    check('M13 the Pallet Breakdown has a Merge Selected header button',
          'action_open_pallet_merge_wizard_multi' in env['stock.move.line'].get_view(
              env.ref('stock.view_stock_move_line_detailed_operation_tree').id,
              'tree')['arch'])

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
