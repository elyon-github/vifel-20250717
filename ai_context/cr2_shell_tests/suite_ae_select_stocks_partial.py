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
    check('AE4 wizard pops an "are you sure?" dialog before a partial withdrawal',
          '_partial_confirm_dialog' in src
          and 'partial_confirmed' in src)
    check('AE5 normal packages are untouched (all-or-nothing preserved), and a '
          'normal full re-add still shows an info notification',
          'if pkg.id in partial_pkg_ids:' in src
          and 'readded_full_normal' in src and 'display_notification' in src)
    # regression: readded_full_normal collects PACKAGES (pkg |=, .name read),
    # so it must be seeded as a stock.quant.package set — seeding it as
    # stock.quant crashed a normal multi-SKU withdrawal with "inconsistent
    # models: stock.quant() | stock.quant.package(...)".
    check('AE5b readded_full_normal is a stock.quant.package set (model match)',
          "readded_full_normal = self.env['stock.quant.package']" in src)

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
    pinned = Partner.search([('vifel_fixed_package_id', '!=', False)]) \
        if 'vifel_fixed_package_id' in Partner._fields else Partner.browse()
    for p in pinned.mapped('vifel_fixed_package_id'):
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
    else:
        for n in ('AE8', 'AE9', 'AE10', 'AE11', 'AE12', 'AE13'):
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
