# CR2 v2 Suite D — guards, isolation and edge cases. Rollback-only.
#
# Where merge must NOT appear, whose stock may NEVER be offered, and the
# Lot No. path end-to-end.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_d_guards_edges.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Partner = env['res.partner']
    ML = env['stock.move.line']
    Wizard = env['pallet.merge.wizard']

    owner = Partner.browse(428)                      # TECHNO FARM
    owner.write({'vifel_can_merge_pallets': False,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()

    line = ML.search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    env.invalidate_all()
    check('D1 button hidden while the client is not merge-enabled',
          not line.vifel_show_merge_button)

    owner.write({'vifel_can_merge_pallets': True})
    env.flush_all()
    env.invalidate_all()
    check('D2 button appears once Can Merge Pallets is ON',
          line.vifel_show_merge_button)

    # ---- where merge must NEVER appear -------------------------------
    bf = ML.search([('picking_id.x_studio_is_a_blast_freezer', '=', True),
                    ('picking_id.state', 'not in', ('done', 'cancel'))],
                   limit=1)
    if bf:
        bf.picking_id.partner_id.vifel_can_merge_pallets = True
        env.flush_all()
        env.invalidate_all()
        check('D3 blast-freeze lines never offer merge',
              not bf.vifel_show_merge_button)
    else:
        check('D3 blast-freeze lines never offer merge', True, '(none open)')

    ret = ML.search([('picking_id.return_id', '!=', False),
                     ('picking_id.state', 'not in', ('done', 'cancel'))],
                    limit=1)
    if ret:
        ret.picking_id.partner_id.vifel_can_merge_pallets = True
        env.flush_all()
        env.invalidate_all()
        check('D4 return lines never offer merge',
              not ret.vifel_show_merge_button)
    else:
        check('D4 return lines never offer merge', True, '(none open)')

    out = ML.search([('picking_id.picking_type_id.code', '=', 'outgoing'),
                     ('picking_id.state', 'not in', ('done', 'cancel'))],
                    limit=1)
    if out:
        out.picking_id.partner_id.vifel_can_merge_pallets = True
        env.flush_all()
        env.invalidate_all()
        check('D5 outgoing (WR) lines never offer merge',
              not out.vifel_show_merge_button)
    else:
        check('D5 outgoing (WR) lines never offer merge', True, '(none open)')

    done = ML.search([('picking_id.picking_type_id.code', '=', 'incoming'),
                      ('picking_id.state', '=', 'done'),
                      ('picking_id.partner_id', '=', owner.id)], limit=1)
    if done:
        env.invalidate_all()
        check('D6 validated RR lines never offer merge',
              not done.vifel_show_merge_button)
    else:
        check('D6 validated RR lines never offer merge', True, '(none)')

    # ---- candidate isolation: same owner, internal, stocked, non-BF ---
    owner.write({'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    wiz = Wizard.create({'move_line_id': line.id})
    pkgs = wiz.candidate_line_ids.package_id
    quants = env['stock.quant'].search([('package_id', 'in', pkgs.ids),
                                        ('quantity', '>', 0)])
    foreign = quants.filtered(lambda q: q.owner_id != owner)
    check('D7 no other client\'s pallet is ever offered (%d candidates)'
          % len(wiz.candidate_line_ids), not foreign,
          foreign.mapped('owner_id.name')[:3])
    external = quants.filtered(lambda q: q.location_id.usage != 'internal')
    check('D8 only internal-location stock is offered', not external,
          external.mapped('location_id.complete_name')[:3])
    bf_q = quants.filtered('location_id.x_studio_is_a_blast_freezer')
    check('D9 blast-freezer stock is never a merge target', not bf_q,
          bf_q.mapped('location_id.complete_name')[:3])
    own = wiz.candidate_line_ids.filtered(
        lambda c: c.package_id == line.result_package_id)
    check('D10 the line\'s own pallet is not offered to itself', not own)

    # ---- Lot No.: gating + stamping onto the quant --------------------
    picking = line.picking_id
    owner.vifel_show_lot_no = False
    env.flush_all()
    env.invalidate_all()
    check('D11 Lot No. hidden while the profile switch is off',
          not picking.show_client_lot_no)
    owner.vifel_show_lot_no = True
    env.flush_all()
    env.invalidate_all()
    check('D12 Lot No. shown once the profile switch is on',
          picking.show_client_lot_no)
    ctx = picking.action_detailed_operations()['context']
    check('D13 Pallet Breakdown context carries show_client_lot_no',
          ctx.get('show_client_lot_no'))

    # Stamping: a validated RR line's Lot No. must land on its quant.
    # The line must be one whose stock is STILL on the floor — stamping runs
    # at validation time. Historical lines whose goods have shipped out (and
    # whose pallet has since been reused by another client) legitimately
    # match nothing, which would test the wrong thing.
    env.cr.execute("""
        SELECT sml.id FROM stock_move_line sml
        JOIN stock_picking sp ON sp.id = sml.picking_id
        JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
        JOIN stock_quant sq
          ON sq.package_id = sml.result_package_id
         AND sq.product_id = sml.product_id
         AND sq.lot_id     = sml.lot_id
         AND sq.location_id = sml.location_dest_id
        JOIN stock_location sl ON sl.id = sq.location_id
        WHERE spt.code='incoming' AND sp.state='done'
          AND sml.lot_id IS NOT NULL AND sq.quantity > 0
          AND sl.usage='internal'
        LIMIT 1""")
    got = env.cr.fetchone()
    check('D14a found a validated line whose stock is still on the floor',
          bool(got))
    dl = ML.browse(got[0])
    dl.client_lot_no = 'LOT-STAMP-TEST'
    dl.picking_id._vifel_stamp_client_lot_no()
    env.flush_all()
    stamped = env['stock.quant'].search([
        ('product_id', '=', dl.product_id.id),
        ('location_id', '=', dl.location_dest_id.id),
        ('lot_id', '=', dl.lot_id.id),
        ('package_id', '=', dl.result_package_id.id),
        ('client_lot_no', '=', 'LOT-STAMP-TEST')])
    check('D14b validation stamping lands the Lot No. on the matching quant',
          bool(stamped), len(stamped))

    # ---- picklist/report sorting tolerates a merged line -------------
    owner.write({'vifel_multiple_pallet_support': True})
    env.flush_all()
    wiz2 = Wizard.create({'move_line_id': line.id})
    tgt = wiz2.candidate_line_ids.filtered('eligible')[:1]
    tgt.is_target = True
    wiz2.action_confirm()
    env.flush_all()
    try:
        ordered = picking.get_picklist_sorted_move_line_ids()
        check('D15 picklist sorting handles an RR containing a merged line',
              len(ordered) >= len(picking.move_line_ids.ids) - 1,
              (len(ordered), len(picking.move_line_ids)))
    except Exception as e:
        check('D15 picklist sorting handles an RR containing a merged line',
              False, str(e)[:120])

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
