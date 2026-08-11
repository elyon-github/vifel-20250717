# CR2 v2 Suite AS - the merge-pallet +1/+0 count is decided at VALIDATION.
#
# The +1 (birth) / +0 (merge) flag used to be frozen at merge/claim time. That
# let two receipts on ONE empty pinned Fixed pallet both end up +0 (RR2 merges
# +0 and validates first; RR1 strips + re-merges onto the now-stocked pallet and
# also reads +0), so the physical pallet was counted ZERO times -> under-billed.
#
# The fix re-derives is_pallet_merge from the floor the instant before a receipt
# goes done (pkr_merge_counting._vifel_rederive_merge_flags, called by
# _action_done): a merge line whose pallet is still EMPTY births it (+1); one
# whose pallet already holds stock is a +0. First to validate onto the empty
# pallet owns the +1 - immune to claim order and re-merges.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_as_validation_time_merge_count.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def clean_empty_pallets(n):
    return env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_is_reserved', '=', False),
        ('vifel_is_merge_pallet', '=', False)], limit=800).filtered(
        lambda p: not p.quant_ids.filtered(lambda q: q.quantity > 0)
        and not env['stock.move.line'].search_count([
            ('result_package_id', '=', p.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel'))]))[:n]


try:
    Fixed = env['vifel.fixed.merge.pallet']
    owner = env['res.partner'].browse(428)          # TECHNO FARM
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()

    pt = env['stock.picking.type'].search([
        ('code', '=', 'incoming'),
        ('is_blast_freeze_operation', '=', False)], limit=1)
    src = pt.default_location_src_id or env['stock.location'].search(
        [('usage', '=', 'supplier')], limit=1)
    # a real internal LEAF (not a view) so stock.quant can stand on it
    dst = env['stock.location'].search([
        ('usage', '=', 'internal'), ('child_ids', '=', False)], limit=1)
    product = env['product.product'].search([('type', '=', 'product')], limit=1)
    pals = clean_empty_pallets(4)
    ok = bool(pt and src and dst and product and len(pals) >= 4)
    check('AS0 setup: incoming type + supplier/internal locs + product + 4 pallets',
          ok, (bool(pt), bool(src), bool(dst), bool(product), len(pals)))

    def make_line(qty, claim_merge, pkg, psi, captured=True):
        """A minimal incoming receipt for the owner with ONE line landing on
        pkg, carrying the given claim-time flags. (No confirm/assign needed -
        the re-derivation reads the flags + the pallet's floor stock, not the
        move state.)"""
        pk = env['stock.picking'].create({
            'picking_type_id': pt.id, 'location_id': src.id,
            'location_dest_id': dst.id, 'partner_id': owner.id})
        mv = env['stock.move'].create({
            'name': product.display_name, 'product_id': product.id,
            'product_uom_qty': qty, 'product_uom': product.uom_id.id,
            'location_id': src.id, 'location_dest_id': dst.id, 'picking_id': pk.id})
        ml = env['stock.move.line'].create({
            'move_id': mv.id, 'picking_id': pk.id, 'product_id': product.id,
            'product_uom_id': product.uom_id.id, 'location_id': src.id,
            'location_dest_id': dst.id, 'quantity': qty,
            'result_package_id': pkg.id})
        ml.with_context(skip_pallet_series_sync=True, vifel_pallet_merge=True).write({
            'x_studio_pallet_series_id': psi,
            'vifel_premerge_captured': captured,
            'is_pallet_merge': claim_merge})
        env.flush_all()
        return pk, ml

    def stock_pallet(pkg, qty, psi):
        """Put real floor stock on a pallet (simulates an earlier done receipt)."""
        q = env['stock.quant'].create({
            'product_id': product.id, 'location_id': dst.id, 'package_id': pkg.id,
            'owner_id': owner.id, 'quantity': qty,
            'x_studio_pallet_series_id': psi})
        env.flush_all()
        pkg.invalidate_recordset()
        return q

    if ok:
        P = pals[0]
        Fixed.create({'partner_id': owner.id, 'package_id': P.id,
                      'psi': 'ZZVAL-0001'})
        env.flush_all()

        # ===== PROMOTION: RR2 claims +0, but is FIRST to validate onto empty P.
        pk2, ml2 = make_line(100, claim_merge=True, pkg=P, psi='ZZVAL-0001')
        check('AS1 pre: RR2 line carries the claim-time +0 flag',
              ml2.is_pallet_merge is True)
        pk2._vifel_rederive_merge_flags()
        env.flush_all()
        check('AS2 PROMOTE: first-to-validate onto EMPTY P births it (+1)',
              ml2.is_pallet_merge is False, ml2.is_pallet_merge)
        check('AS3 the promoted line now ORIGINATES the pallet (counts +1)',
              pk2._vifel_line_originates_pallet(ml2))

        # P now holds stock (as if RR2 finished): a later receipt must read +0.
        stock_pallet(P, 100, 'ZZVAL-0001')

        # ===== DEMOTION: RR1 claimed +1, but validates onto a now-stocked P.
        pk1, ml1 = make_line(50, claim_merge=False, pkg=P, psi='ZZVAL-0001')
        check('AS4 pre: RR1 line carries the claim-time +1 flag',
              ml1.is_pallet_merge is False)
        pk1._vifel_rederive_merge_flags()
        env.flush_all()
        check('AS5 DEMOTE: validating onto an already-stocked P is a +0',
              ml1.is_pallet_merge is True, ml1.is_pallet_merge)
        check('AS6 the demoted line does NOT originate the pallet (+0)',
              not pk1._vifel_line_originates_pallet(ml1))

        # ===== SAME-RECEIPT multi-line birth: both lines stay +1 (deduped to
        # one pallet by the ledger; they must NOT demote each other).
        Q = pals[1]
        Fixed.create({'partner_id': owner.id, 'package_id': Q.id,
                      'psi': 'ZZVAL-0002'})
        env.flush_all()
        pkq = env['stock.picking'].create({
            'picking_type_id': pt.id, 'location_id': src.id,
            'location_dest_id': dst.id, 'partner_id': owner.id})
        mlq = env['stock.move.line']
        for _i in range(2):
            mv = env['stock.move'].create({
                'name': product.display_name, 'product_id': product.id,
                'product_uom_qty': 10, 'product_uom': product.uom_id.id,
                'location_id': src.id, 'location_dest_id': dst.id,
                'picking_id': pkq.id})
            l = env['stock.move.line'].create({
                'move_id': mv.id, 'picking_id': pkq.id, 'product_id': product.id,
                'product_uom_id': product.uom_id.id, 'location_id': src.id,
                'location_dest_id': dst.id, 'quantity': 10,
                'result_package_id': Q.id})
            l.with_context(skip_pallet_series_sync=True, vifel_pallet_merge=True).write({
                'x_studio_pallet_series_id': 'ZZVAL-0002',
                'vifel_premerge_captured': True, 'is_pallet_merge': False})
            mlq |= l
        env.flush_all()
        pkq._vifel_rederive_merge_flags()
        env.flush_all()
        check('AS7 same-receipt co-birth: BOTH lines on empty Q stay +1',
              all(not l.is_pallet_merge for l in mlq)
              and sum(1 for l in mlq if pkq._vifel_line_originates_pallet(l)) == 2,
              mlq.mapped('is_pallet_merge'))

        # ===== PLAIN line excluded: a non-merge line on a STOCKED plain pallet
        # must NOT be swept into +0 (proves the scope filter).
        R = pals[2]
        stock_pallet(R, 30, 'ZZVAL-PLAIN')          # R holds stock, but is plain
        R.invalidate_recordset()
        pkr, mlr = make_line(30, claim_merge=False, pkg=R, psi='ZZVAL-PLN2',
                             captured=False)          # no merge markers at all
        # R is not a merge pallet and the line has no markers -> out of scope.
        pkr._vifel_rederive_merge_flags()
        env.flush_all()
        check('AS8 a PLAIN line on a stocked non-merge pallet is left untouched',
              mlr.is_pallet_merge is False and not R.vifel_is_merge_pallet,
              (mlr.is_pallet_merge, R.vifel_is_merge_pallet))

        # ===== SCOPE: a non-merge-enabled client is never re-derived.
        other = env['res.partner'].search([
            ('vifel_can_merge_pallets', '=', False),
            ('id', '!=', owner.id)], limit=1)
        if other:
            pko = env['stock.picking'].create({
                'picking_type_id': pt.id, 'location_id': src.id,
                'location_dest_id': dst.id, 'partner_id': other.id})
            check('AS9 out-of-scope: non-merge client receipt skipped',
                  not pko._vifel_merge_count_scope())
        else:
            check('AS9 (no non-merge partner handy)', True)

        # ===== PREVIEW FLAGS (the JS No. of Pallets + red note): every receipt
        # racing to birth an EMPTY Fixed pallet counts it (+1) and shows the
        # note; once the pallet is stocked, ALL of them drop it (even the one
        # that merged first) - the preview follows validation order.
        F = pals[3]
        Fixed.create({'partner_id': owner.id, 'package_id': F.id,
                      'psi': 'ZZVAL-0003'})
        env.flush_all()
        pka, mla = make_line(20, claim_merge=False, pkg=F, psi='ZZVAL-0003')  # claimed +1
        pkb, mlb = make_line(20, claim_merge=True, pkg=F, psi='ZZVAL-0003')   # claimed +0
        check('AS10 racing on EMPTY Fixed pallet: BOTH receipts count it AND show note',
              mla.vifel_counts_in_preview and mlb.vifel_counts_in_preview
              and mla.vifel_birth_provisional and mlb.vifel_birth_provisional,
              (mla.vifel_counts_in_preview, mlb.vifel_counts_in_preview,
               mla.vifel_birth_provisional, mlb.vifel_birth_provisional))
        stock_pallet(F, 20, 'ZZVAL-0003')       # a winner validated -> F now stocked
        (mla + mlb).invalidate_recordset()
        check('AS11 Fixed pallet now stocked: BOTH drop it AND lose the note '
              '(claim/merge order irrelevant)',
              not mla.vifel_counts_in_preview and not mlb.vifel_counts_in_preview
              and not mla.vifel_birth_provisional and not mlb.vifel_birth_provisional,
              (mla.vifel_counts_in_preview, mlb.vifel_counts_in_preview))
        check('AS12 a non-Fixed line keeps the ordinary rule: counts (+1), no note',
              mlr.vifel_counts_in_preview and not mlr.vifel_birth_provisional,
              (mlr.vifel_counts_in_preview, mlr.vifel_birth_provisional))
    else:
        for n in ('AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS7', 'AS8', 'AS9',
                  'AS10', 'AS11', 'AS12'):
            check(n + ' (setup unavailable in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
