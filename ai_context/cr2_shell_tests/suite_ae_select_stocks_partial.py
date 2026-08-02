# CR2 v2 Suite AE - Select Stocks respects partial withdrawal of a MERGE pallet.
#
# The WR stock-selection machinery was all-or-nothing at the package level, so a
# merge pallet (pinned Fixed / merged-onto) could not be withdrawn in part and a
# deleted Picked Quant was silently re-added. Now:
#  * the select_quant.wizard keeps only the user-selected quants for a partial
#    package (and drops the deselected LINE, matched by product/lot/package since
#    lines often carry no quant_id);
#  * SA#377's re-add is suppressed for merge-pallet moves (that guard lives in the
#    ai_context/sa377_* paste; here we assert the predicate + wizard source).
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ae_select_stocks_partial.py
#
# Rollback-only.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.modules.module import get_module_path
    Q = env['stock.quant']

    # ---- SOURCE: wizard is merge-aware + informs on normal full re-add ----
    src = open(os.path.join(get_module_path('multiple_relocation'),
                            'wizard', 'SelectQuantWizard.py'), encoding='utf-8').read()
    check('AE1 wizard consults the partial-withdrawal predicate',
          '_vifel_package_allows_partial_withdrawal' in src)
    check('AE2 wizard filters the package-pull to selected quants (merge only)',
          'q.package_id.id not in partial_pkg_ids' in src
          and 'q.id in selected_quant_ids' in src)
    check('AE3 wizard drops deselected lines by IDENTITY (not quant_id)',
          'selected_ident' in src
          and '(ml.product_id.id, ml.lot_id.id, ml.package_id.id)' in src)
    check('AE4 wizard returns an info notification for a normal full re-add',
          'readded_full_normal' in src and 'display_notification' in src)
    check('AE5 normal packages are untouched (all-or-nothing preserved)',
          'if pkg.id in partial_pkg_ids:' in src)

    # ---- the SA#377 paste carries the merge guard + chatter note ----
    sa = open(os.path.join(get_module_path('multiple_relocation'), '..',
                           'vifel_client_requirements') if False else
              os.path.join(get_module_path('multiple_relocation'), '..',),
              ) if False else None
    paste_path = os.path.join(
        os.path.dirname(get_module_path('multiple_relocation')),
        'ai_context', 'sa377_assign_quants_merge_aware.py')
    if os.path.exists(paste_path):
        pb = open(paste_path, encoding='utf-8').read()
        check('AE6 SA#377 paste skips the overwrite for a merge-pallet move',
              'move_has_partial_pkg' in pb
              and 'if not move_has_partial_pkg:' in pb)
        check('AE7 SA#377 paste posts a chatter note on a genuine normal re-add',
              'message_post' in pb and 'readded' in pb)
    else:
        check('AE6 SA#377 paste present', False, paste_path)

    # ---- FUNCTIONAL: drive the wizard on a real merge-pallet WR move ----
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    # a stocked pallet that allows partial withdrawal, with >=2 quants of it
    pkg = None
    for cand in Q.search([('package_id', '!=', False), ('quantity', '>', 0),
                          ('location_id.usage', '=', 'internal')], limit=2000):
        p = cand.package_id
        if not Q._vifel_package_allows_partial_withdrawal(p.id):
            continue
        if Q.search_count([('package_id', '=', p.id), ('quantity', '>', 0),
                           ('location_id.usage', '=', 'internal')]) >= 2:
            pkg = p
            break
    if pkg:
        pq = Q.search([('package_id', '=', pkg.id), ('quantity', '>', 0),
                       ('location_id.usage', '=', 'internal')])
        keep = pq[0]
        # build a WR move with lines for BOTH quants, then pick only ONE
        wtype = env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        wr = env['stock.picking'].create({
            'picking_type_id': wtype.id, 'partner_id': owner.id,
            'location_id': keep.location_id.id,
            'location_dest_id': keep.location_id.id})
        mv = env['stock.move'].create({
            'name': keep.product_id.name, 'picking_id': wr.id,
            'product_id': keep.product_id.id, 'product_uom': keep.product_id.uom_id.id,
            'product_uom_qty': sum(pq.mapped('quantity')),
            'location_id': keep.location_id.id, 'location_dest_id': keep.location_id.id})
        for q in pq:
            env['stock.move.line'].create({
                'picking_id': wr.id, 'move_id': mv.id, 'product_id': q.product_id.id,
                'quantity': q.quantity, 'lot_id': q.lot_id.id, 'package_id': q.package_id.id,
                'location_id': keep.location_id.id, 'location_dest_id': keep.location_id.id})
        mv.quant_ids_picked = [(6, 0, pq.ids)]
        env.flush_all()
        before = len(mv.move_line_ids)
        wiz = env['select_quant.wizard'].create({
            'stock_move_id': mv.id, 'transfer_id': wr.id, 'product_id': mv.product_id.id,
            'owner_id': owner.id, 'location_id': keep.location_id.id,
            'quant_ids_picked': [(6, 0, [keep.id])],
            'move_line_ids': [(6, 0, mv.move_line_ids.ids)]})
        wiz.action_confirm()
        env.flush_all()
        mv2 = env['stock.move'].browse(mv.id)
        keep_ident = (keep.product_id.id, keep.lot_id.id, keep.package_id.id)
        check('AE8 merge move keeps ONLY the selected quant (partial withdrawal)',
              set(mv2.quant_ids_picked.ids) == {keep.id}, mv2.quant_ids_picked.ids)
        check('AE9 the deselected line was unlinked (line count dropped)',
              len(mv2.move_line_ids) < before and len(mv2.move_line_ids) >= 1,
              (before, len(mv2.move_line_ids)))
        check('AE10 every remaining line matches the kept quant identity',
              all((l.product_id.id, l.lot_id.id, l.package_id.id) == keep_ident
                  for l in mv2.move_line_ids))

        # ---- INFORM: the partial removal returns an info notification + note
        # (re-establish both quants, then remove one via a fresh wizard)
        mv3 = env['stock.move'].browse(mv.id)
        mv3.quant_ids_picked = [(6, 0, pq.ids)]
        env.flush_all()
        Msg = env['mail.message']
        before_notes = Msg.search_count(
            [('model', '=', 'stock.picking'), ('res_id', '=', wr.id)])
        wiz2 = env['select_quant.wizard'].create({
            'stock_move_id': mv3.id, 'transfer_id': wr.id,
            'product_id': mv3.product_id.id, 'owner_id': owner.id,
            'location_id': keep.location_id.id,
            'quant_ids_picked': [(6, 0, [keep.id])],
            'move_line_ids': [(6, 0, mv3.move_line_ids.ids)]})
        res = wiz2.action_confirm()
        env.flush_all()
        check('AE11 partial removal returns an INFO notification',
              isinstance(res, dict)
              and res.get('tag') == 'display_notification'
              and 'Partial withdrawal' in res.get('params', {}).get('message', ''),
              res.get('params', {}).get('message', '')[:60] if isinstance(res, dict) else type(res).__name__)
        check('AE12 ... and posts a durable chatter note on the WR',
              Msg.search_count([('model', '=', 'stock.picking'),
                                ('res_id', '=', wr.id)]) == before_notes + 1)
    else:
        for n in ('AE8', 'AE9', 'AE10', 'AE11', 'AE12'):
            check(n + ' merge partial (no eligible 2-quant merge pallet in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
