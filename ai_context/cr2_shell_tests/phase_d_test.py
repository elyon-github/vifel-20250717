# Phase D: end-to-end gaps — Lot No. stamping, mirrors, blocks, picklist,
# and the Re-sync regression sweep. Rollback-only.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))

try:
    P, Q, ML = env['res.partner'], env['stock.quant'], env['stock.move.line']
    Picking = env['stock.picking']
    W = env['pallet.merge.wizard']

    # ---- 1. Lot No. stamping onto real quants ---------------------------
    done_line = ML.search([
        ('state', '=', 'done'),
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('result_package_id', '!=', False),
        ('owner_id', '!=', False)], order='id desc', limit=50).filtered(
        lambda l: Q.search_count([
            ('product_id', '=', l.product_id.id),
            ('location_id', '=', l.location_dest_id.id),
            ('lot_id', '=', l.lot_id.id),
            ('package_id', '=', l.result_package_id.id),
            ('owner_id', '=', l.owner_id.id)]))[:1]
    pick = done_line.picking_id
    done_line.write({'client_lot_no': 'LOT-CR2-TEST'})
    pick._vifel_stamp_client_lot_no()
    quant = Q.search([
        ('product_id', '=', done_line.product_id.id),
        ('location_id', '=', done_line.location_dest_id.id),
        ('lot_id', '=', done_line.lot_id.id),
        ('package_id', '=', done_line.result_package_id.id),
        ('owner_id', '=', done_line.owner_id.id)], limit=1)
    check('D1 validation stamping lands the Lot No. on the matching quant',
          quant.client_lot_no == 'LOT-CR2-TEST',
          (pick.name, quant.client_lot_no))

    # ---- 2. void mirrors & copies start unflagged/blank ------------------
    src = ML.search([('result_package_id', '!=', False)], limit=1)
    src.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True, 'client_lot_no': 'LOT-X'})
    dup = src.copy({'picking_id': src.picking_id.id})
    check('D2 a copied line drops the merge flag AND the Lot No. (copy=False)',
          not dup.is_pallet_merge and not dup.client_lot_no,
          (dup.is_pallet_merge, dup.client_lot_no))
    src.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': False, 'client_lot_no': False})

    # ---- 3. availability blocks: BF, return, outgoing --------------------
    # the merge client is the partner of a REAL open incoming line, so the
    # candidate/wizard sections below always have a line to work with
    line = ML.search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.picking_type_id.is_blast_freeze_operation', '!=', True),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '!=', False),
        ('picking_id.state', 'not in', ['done', 'cancel'])], limit=1)
    merge_client = line.picking_id.partner_id
    merge_client.write({'vifel_can_merge_pallets': True})
    bf_line = ML.search([
        ('picking_id.picking_type_id.is_blast_freeze_operation', '=', True),
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.partner_id', '!=', False),
        ('picking_id.state', 'not in', ['done', 'cancel'])], limit=1)
    if bf_line:
        bf_line.picking_id.partner_id.write({'vifel_can_merge_pallets': True})
        env.invalidate_all()
        check('D3 blast freeze lines never offer the merge button',
              not bf_line.vifel_show_merge_button)
    ret_line = ML.search([
        ('picking_id.return_id', '!=', False),
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('picking_id.partner_id', '!=', False)], limit=1)
    if ret_line:
        # return RRs are owner-locked (existing guard) — flip merge on
        # the return's OWN client instead
        ret_line.picking_id.partner_id.write({'vifel_can_merge_pallets': True})
        env.invalidate_all()
        check('D4 return lines never offer the merge button',
              not ret_line.vifel_show_merge_button)
    else:
        print('   (no open return RR — D4 via picking-level rule already '
              'covered by compute test B-series)')
    out_line = ML.search([
        ('picking_id.picking_type_id.code', '=', 'outgoing'),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('picking_id.partner_id', '!=', False)], limit=1)
    if out_line:
        out_line.picking_id.partner_id.write({'vifel_can_merge_pallets': True})
        env.invalidate_all()
        check('D5 outgoing lines never offer the merge button',
              not out_line.vifel_show_merge_button)

    # ---- 4. candidates strictly owner-scoped -----------------------------
    merge_client.write({'vifel_multiple_pallet_support': True,
                        'vifel_include_regular_pallets': True})
    wiz = W.create({'move_line_id': line.id})
    foreign = [p for p in wiz.allowed_package_ids
               if not any(q.owner_id == merge_client and q.quantity > 0
                          for q in p.quant_ids)]
    check('D6 no other client\'s pallet ever appears as a candidate (%d offered)'
          % len(wiz.allowed_package_ids), not foreign,
          [p.name for p in foreign][:3])

    # ---- 5. picklist contiguity with a merged line -----------------------
    pl_pick = ML.search([('picking_id.picking_type_id.code', '=', 'incoming'),
                         ('result_package_id', '!=', False)],
                        limit=1).picking_id
    some_line = pl_pick.move_line_ids.filtered('result_package_id')[:1]
    some_line.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True})
    try:
        ordered = pl_pick.get_picklist_sorted_move_line_ids()
        pages = pl_pick.get_picklist_page_boundaries()
        # contiguity: equal PSIs must sit in one block
        psis = [l.x_studio_pallet_series_id for l in ordered]
        blocks, prev = [], object()
        for p in psis:
            if p != prev:
                blocks.append(p); prev = p
        check('D7 picklist sorts an RR containing a merged line '
              '(%d lines, %d pages)' % (len(psis), len(pages)),
              len(blocks) == len(set(blocks)),
              'PSI appears in two separate blocks')
    except Exception as e:
        check('D7 picklist sorts an RR containing a merged line', False, str(e)[:150])
    # un-flag before the sweep: D8 asserts the exclusions are NO-OPS on
    # unflagged data, and this line sits on a validated RR (leaving it
    # flagged legitimately shifts that owner's counts — observed 36->35
    # received +1 residual adjustment, i.e. the merge semantics working)
    some_line.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': False})

    # ---- 6. Re-sync regression sweep over every owner --------------------
    PKR = env['pallet_kilos_record_model.pallet_kilos_record_model']
    all_rows = PKR.search([('active', '=', True), ('owner_id', '!=', False)])
    owners = all_rows.mapped('owner_id')
    before = {r.id: (r.pallets_received, r.pallets_withdrawn, r.adjustment_pallets)
              for r in all_rows}
    all_rows.action_resync_pallet_counts()
    env.invalidate_all()
    drift = {}
    for r in all_rows:
        now = (r.pallets_received, r.pallets_withdrawn, r.adjustment_pallets)
        if before[r.id] != now:
            drift[r.id] = (before[r.id], now)
    check('D8 full Re-sync sweep: %d owners, %d rows, zero regressions'
          % (len(owners), len(all_rows)), not drift,
          list(drift.items())[:3])

except Exception:
    print('UNEXPECTED ERROR:'); traceback.print_exc(); FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
