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
    check('AE4 wizard pops an "are you sure?" dialog before ANY removal',
          '_removal_confirm_dialog_if_needed' in src
          and 'partial_confirmed' in src)
    check('AE5 the confirmation covers all three cases in one prompt: merge '
          'partial, merge removed-entirely, and normal whole-pallet',
          'merge_partial' in src and 'merge_full' in src
          and 'normal_partial' in src)
    # WR 08420: removing the ONLY picked quant of a merge pallet is a full
    # removal, not a "partial withdrawal — rest stays" (which read wrong).
    check('AE5b a merge pallet with nothing left picked is worded as a full '
          'removal, not a partial withdrawal',
          'removed from this withdrawal' in src.lower())
    # XSS: the message is HTML built from free-text / Studio fields (product,
    # pallet, PSI) into a sanitize=False Html field, so cell values must be
    # escaped.
    check('AE5c the confirmation table HTML-escapes its cell values (no XSS / '
          'no broken markup on a "<"/"&" in a name)',
          'from markupsafe import escape' in src
          and 'escape(q.product_id.display_name' in src)
    # destructive: the empty-move delete only fires for a move on THIS transfer.
    check('AE5d the empty-move deletion is scoped to this wizard\'s transfer',
          'main_move.picking_id.id == self.transfer_id' in src)

    # ---- the SA#377 paste carries the merge guard (no chatter note) ----
    paste_path = os.path.join(
        os.path.dirname(get_module_path('multiple_relocation')),
        'ai_context', 'sa377_assign_quants_merge_aware.py')
    if os.path.exists(paste_path):
        pb = open(paste_path, encoding='utf-8').read()
        check('AE6 SA#377 paste skips the overwrite for a merge-pallet move',
              'move_has_partial_pkg' in pb
              and 'if not move_has_partial_pkg:' in pb)
        check('AE7 SA#377 paste has NO chatter note (per requirement)',
              'message_post' not in pb)
    else:
        check('AE6 SA#377 paste present', False, paste_path)

    # ---- FUNCTIONAL: drive the wizard on a real merge-pallet WR move ----
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    # a stocked pallet that allows partial withdrawal, with >=2 quants of it.
    # Pinned Fixed Merge Pallets are the deterministic source; fall back to a
    # broad quant scan (merged-onto pallets) if none is stocked with >=2 quants.
    pkg = None
    Partner = env['res.partner']
    pinned_pkgs = env['vifel.fixed.merge.pallet'].sudo().search([]).mapped('package_id') \
        if 'vifel.fixed.merge.pallet' in env else env['stock.quant.package'].browse()
    for p in pinned_pkgs:
        if Q.search_count([('package_id', '=', p.id), ('quantity', '>', 0),
                           ('location_id.usage', '=', 'internal')]) >= 2:
            pkg = p
            break
    if not pkg:
        for cand in Q.search([('package_id', '!=', False), ('quantity', '>', 0),
                              ('location_id.usage', '=', 'internal')], limit=3000):
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
        keep_ident = (keep.product_id.id, keep.lot_id.id, keep.package_id.id)

        # --- CONFIRM: Confirm returns the floating 'are you sure?' dialog and
        #     does NOT apply anything yet ---
        wiz = env['select_quant.wizard'].create({
            'stock_move_id': mv.id, 'transfer_id': wr.id, 'product_id': mv.product_id.id,
            'owner_id': owner.id, 'location_id': keep.location_id.id,
            'quant_ids_picked': [(6, 0, [keep.id])],
            'move_line_ids': [(6, 0, mv.move_line_ids.ids)]})
        res = wiz.action_confirm()
        check('AE8 Confirm returns the "are you sure?" dialog (nothing applied)',
              isinstance(res, dict)
              and res.get('res_model') == 'select_quant.partial.confirm'
              and res.get('target') == 'new',
              res.get('res_model') if isinstance(res, dict) else type(res).__name__)
        mv_now = env['stock.move'].browse(mv.id)
        check('AE9 the move is UNCHANGED at dialog time (both quants kept)',
              set(mv_now.quant_ids_picked.ids) == set(pq.ids))
        confirm = env['select_quant.partial.confirm'].browse(res['res_id'])
        check('AE10 dialog names the removed pallet + says it stays in storage',
              keep.package_id.name in (confirm.message or '')
              and 'stays in storage' in (confirm.message or ''),
              (confirm.message or '')[:60])

        # --- PROCEED: applies the partial withdrawal ---
        confirm.action_proceed()
        env.flush_all()
        mv2 = env['stock.move'].browse(mv.id)
        check('AE11 Proceed applies: move keeps ONLY the selected quant',
              set(mv2.quant_ids_picked.ids) == {keep.id}, mv2.quant_ids_picked.ids)
        check('AE12 Proceed dropped the deselected line, and it matches the kept '
              'quant identity',
              len(mv2.move_line_ids) < before and len(mv2.move_line_ids) >= 1
              and all((l.product_id.id, l.lot_id.id, l.package_id.id) == keep_ident
                      for l in mv2.move_line_ids),
              (before, len(mv2.move_line_ids)))

        # --- CANCEL: re-establish both, Confirm -> dialog -> do NOT proceed ---
        mv2.quant_ids_picked = [(6, 0, pq.ids)]
        env.flush_all()
        wiz3 = env['select_quant.wizard'].create({
            'stock_move_id': mv.id, 'transfer_id': wr.id, 'product_id': mv.product_id.id,
            'owner_id': owner.id, 'location_id': keep.location_id.id,
            'quant_ids_picked': [(6, 0, [keep.id])],
            'move_line_ids': [(6, 0, mv2.move_line_ids.ids)]})
        wiz3.action_confirm()  # dialog returned; user cancels (no proceed)
        env.flush_all()
        check('AE13 Cancel (no proceed) leaves the move unchanged',
              set(env['stock.move'].browse(mv.id).quant_ids_picked.ids) == set(pq.ids))

        # --- WR 08420: remove the ONLY picked quant of a merge pallet. That is
        #     a FULL removal (nothing left to withdraw), NOT a partial
        #     withdrawal — the old wording ("the rest stays in storage") read
        #     wrong when there was no rest. ---
        mv.quant_ids_picked = [(6, 0, [keep.id])]   # only ONE picked now
        env.flush_all()
        wiz4 = env['select_quant.wizard'].create({
            'stock_move_id': mv.id, 'transfer_id': wr.id, 'product_id': mv.product_id.id,
            'owner_id': owner.id, 'location_id': keep.location_id.id,
            'quant_ids_picked': [(6, 0, [])],        # drop the only one
            'move_line_ids': [(6, 0, mv.move_line_ids.ids)]})
        res4 = wiz4.action_confirm()
        check('AE14 removing the ONLY picked quant still pops the dialog',
              isinstance(res4, dict)
              and res4.get('res_model') == 'select_quant.partial.confirm',
              res4.get('res_model') if isinstance(res4, dict) else type(res4).__name__)
        cmsg = (env['select_quant.partial.confirm'].browse(res4['res_id']).message
                or '') if isinstance(res4, dict) and res4.get('res_id') else ''
        check('AE15 it is worded as a FULL removal (nothing left to withdraw), '
              'NOT "partial withdrawal"',
              'removed from this withdrawal' in cmsg.lower()
              and 'partial withdrawal' not in cmsg.lower(), cmsg[:90])
        check('AE16 the move is untouched until the user proceeds',
              set(env['stock.move'].browse(mv.id).quant_ids_picked.ids) == {keep.id})
        # PROCEED: the selection is now empty, so the empty product move is
        # dropped from the transfer (no lingering 0-qty line).
        env['select_quant.partial.confirm'].browse(res4['res_id']).action_proceed()
        env.flush_all()
        check('AE16b Proceed on an empty selection removes the empty product '
              'move from the transfer',
              not env['stock.move'].browse(mv.id).exists())
    else:
        for n in ('AE8', 'AE9', 'AE10', 'AE11', 'AE12', 'AE13',
                  'AE14', 'AE15', 'AE16'):
            check(n + ' merge partial (no eligible 2-quant merge pallet in DB)', True)

    # ====================================================================
    # EQUAL TREATMENT: dropping ONE SKU of a NORMAL (non-merge) multi-SKU
    # pallet now ALSO pops the floating confirmation BEFORE applying — it used
    # to apply silently and only show an after-the-fact notice.
    # ====================================================================
    npkg = None
    for cand in Q.search([('package_id', '!=', False), ('quantity', '>', 0),
                          ('location_id.usage', '=', 'internal'),
                          ('lot_id', '!=', False)], limit=5000):
        p = cand.package_id
        if Q._vifel_package_allows_partial_withdrawal(p.id):
            continue
        if Q.search_count([('package_id', '=', p.id), ('quantity', '>', 0),
                           ('location_id.usage', '=', 'internal'),
                           ('lot_id', '!=', False)]) >= 2:
            npkg = p
            break
    if npkg:
        nq = Q.search([('package_id', '=', npkg.id), ('quantity', '>', 0),
                       ('location_id.usage', '=', 'internal'),
                       ('lot_id', '!=', False)])
        nkeep = nq[0]
        nowner = nkeep.owner_id or owner
        wtype = env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        nwr = env['stock.picking'].create({
            'picking_type_id': wtype.id, 'partner_id': nowner.id,
            'location_id': nkeep.location_id.id,
            'location_dest_id': nkeep.location_id.id})
        nmv = env['stock.move'].create({
            'name': nkeep.product_id.name, 'picking_id': nwr.id,
            'product_id': nkeep.product_id.id,
            'product_uom': nkeep.product_id.uom_id.id,
            'product_uom_qty': sum(nq.mapped('quantity')),
            'location_id': nkeep.location_id.id,
            'location_dest_id': nkeep.location_id.id})
        for q in nq:
            env['stock.move.line'].create({
                'picking_id': nwr.id, 'move_id': nmv.id, 'product_id': q.product_id.id,
                'quantity': q.quantity, 'lot_id': q.lot_id.id, 'package_id': q.package_id.id,
                'location_id': nkeep.location_id.id, 'location_dest_id': nkeep.location_id.id})
        nmv.quant_ids_picked = [(6, 0, nq.ids)]
        env.flush_all()
        nwiz = env['select_quant.wizard'].create({
            'stock_move_id': nmv.id, 'transfer_id': nwr.id,
            'product_id': nmv.product_id.id, 'owner_id': nowner.id,
            'location_id': nkeep.location_id.id,
            'quant_ids_picked': [(6, 0, [nkeep.id])],   # drop the other SKU(s)
            'move_line_ids': [(6, 0, nmv.move_line_ids.ids)]})
        nres = nwiz.action_confirm()
        check('AE17 dropping ONE SKU of a NORMAL pallet ALSO pops the dialog '
              '(equal treatment, no longer a silent notice)',
              isinstance(nres, dict)
              and nres.get('res_model') == 'select_quant.partial.confirm',
              nres.get('res_model') if isinstance(nres, dict) else type(nres).__name__)
        nmsg = (env['select_quant.partial.confirm'].browse(nres['res_id']).message
                or '') if isinstance(nres, dict) and nres.get('res_id') else ''
        check('AE18 it warns the WHOLE pallet (every SKU) is withdrawn together '
              'and asks "are you sure", not a partial withdrawal',
              'whole pallet' in nmsg.lower()
              and 'are you sure' in nmsg.lower()
              and 'entire pallet' in nmsg.lower()
              and 'partial withdrawal' not in nmsg.lower(), nmsg[:120])
        check('AE19 the move is untouched until the user proceeds',
              set(env['stock.move'].browse(nmv.id).quant_ids_picked.ids) == set(nq.ids))

        # Fully deselecting the normal pallet: no dialog needed (a plain
        # removal), and the now-empty product move is dropped from the transfer.
        nwiz2 = env['select_quant.wizard'].create({
            'stock_move_id': nmv.id, 'transfer_id': nwr.id,
            'product_id': nmv.product_id.id, 'owner_id': nowner.id,
            'location_id': nkeep.location_id.id,
            'quant_ids_picked': [(6, 0, [])],
            'move_line_ids': [(6, 0, nmv.move_line_ids.ids)]})
        r2 = nwiz2.action_confirm()
        env.flush_all()
        check('AE20 fully deselecting a NORMAL pallet needs no dialog and '
              'removes the empty product move',
              r2 is None and not env['stock.move'].browse(nmv.id).exists(),
              type(r2).__name__)
    else:
        for n in ('AE17', 'AE18', 'AE19', 'AE20'):
            check(n + ' normal partial (no normal 2-SKU pallet in DB)', True)

    # ====================================================================
    # CO-STORED PRODUCT on a shared MERGE pallet (M/WR/08424 regression).
    # A merge pallet legitimately holds MORE THAN ONE product, each on its own
    # move under the SAME pallet #. Confirming Select Stocks for ONE product must
    # NOT drop the OTHER product's already-selected quant/move on that pallet.
    # Before the fix, Step 1b/Step 1 iterated every move in the transfer and
    # unlinked any quant on the partial pallet not in THIS wizard's (one-product)
    # selection — deleting the co-stored product's move entirely.
    # ====================================================================
    mpkg = None
    # Target MERGE packages directly (flagged or pinned) — scanning raw quants
    # can miss a valid pallet that sits past the scan window, which would skip the
    # regression instead of running it. A merge pallet holding >=2 distinct
    # products with positive internal stock is exactly the M/WR/08424 shape.
    Pkg = env['stock.quant.package']
    merge_pkgs = Pkg.search([('vifel_is_merge_pallet', '=', True)]) \
        if 'vifel_is_merge_pallet' in Pkg._fields else Pkg.browse()
    merge_pkgs |= env['res.partner']._vifel_fixed_merge_packages() \
        if hasattr(env['res.partner'], '_vifel_fixed_merge_packages') else Pkg.browse()
    for p in merge_pkgs:
        if not Q._vifel_package_allows_partial_withdrawal(p.id):
            continue
        prods = Q.search([('package_id', '=', p.id), ('quantity', '>', 0),
                          ('location_id.usage', '=', 'internal'),
                          ('lot_id', '!=', False)]).mapped('product_id')
        if len(prods) >= 2:
            mpkg = p
            break
    if mpkg:
        mq = Q.search([('package_id', '=', mpkg.id), ('quantity', '>', 0),
                       ('location_id.usage', '=', 'internal'),
                       ('lot_id', '!=', False)])
        qa = mq[0]
        qb = next((q for q in mq if q.product_id != qa.product_id), False)
        powner = qa.owner_id or owner
        wtype = env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        mwr = env['stock.picking'].create({
            'picking_type_id': wtype.id, 'partner_id': powner.id,
            'location_id': qa.location_id.id, 'location_dest_id': qa.location_id.id})

        def _mk_move(q):
            mv = env['stock.move'].create({
                'name': q.product_id.name, 'picking_id': mwr.id,
                'product_id': q.product_id.id, 'product_uom': q.product_id.uom_id.id,
                'product_uom_qty': q.quantity,
                'location_id': q.location_id.id, 'location_dest_id': q.location_id.id})
            env['stock.move.line'].create({
                'picking_id': mwr.id, 'move_id': mv.id, 'product_id': q.product_id.id,
                'quantity': q.quantity, 'lot_id': q.lot_id.id, 'package_id': q.package_id.id,
                'location_id': q.location_id.id, 'location_dest_id': q.location_id.id})
            mv.quant_ids_picked = [(6, 0, [q.id])]
            return mv

        mva = _mk_move(qa)          # product A move (Select Stocks opened here)
        mvb = _mk_move(qb)          # product B move (the "other" selection)
        env.flush_all()
        # Select Stocks on move A, its own quant selected (a partial withdrawal —
        # the user only reduced qty, not the selection). MUST NOT touch move B.
        wizc = env['select_quant.wizard'].create({
            'stock_move_id': mva.id, 'transfer_id': mwr.id,
            'product_id': mva.product_id.id, 'owner_id': powner.id,
            'location_id': qa.location_id.id,
            'quant_ids_picked': [(6, 0, [qa.id])],
            'move_line_ids': [(6, 0, mva.move_line_ids.ids)]})
        wizc.with_context(partial_confirmed=True).action_confirm()
        env.flush_all()
        env.invalidate_all()
        mvb_now = env['stock.move'].browse(mvb.id)
        check('AE21 the co-stored product move on the same merge pallet SURVIVES',
              mvb_now.exists() and set(mvb_now.quant_ids_picked.ids) == {qb.id},
              (mvb_now.exists(),
               mvb_now.quant_ids_picked.ids if mvb_now.exists() else 'GONE'))
        check('AE22 the co-stored product move line survives too',
              mvb_now.exists() and len(mvb_now.move_line_ids) >= 1
              and mvb_now.move_line_ids[0].product_id == qb.product_id,
              len(mvb_now.move_line_ids) if mvb_now.exists() else 'GONE')
        check('AE23 the opened move keeps its own quant (product A intact)',
              env['stock.move'].browse(mva.id).exists()
              and qa.id in env['stock.move'].browse(mva.id).quant_ids_picked.ids)
    else:
        for n in ('AE21', 'AE22', 'AE23'):
            check(n + ' co-stored merge pallet (no 2-product merge pallet in DB)',
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
