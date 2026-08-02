# CR2 v2 Suite Y - Batch # -> Prodcode receiving/withdrawal flow.
#
# Batch # is typed on the receiving line; at validation it is frozen into a
# Prodcode on the quant as DDMONYYYY + Batch# + building-shortname (the quant's
# x_studio_building_dropped). The withdrawal line reads that Prodcode back off
# the quant it withdraws from.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_y_batch_prodcode.py
#
# Rollback-only: nothing is committed.
import datetime
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Picking = env['stock.picking']
    Quant = env['stock.quant']

    # ---- 1. the format helper (per the client's example) --------------
    p = Picking
    d = datetime.date(2026, 5, 18)
    check('Y1 formatter: 18-May-2026 + 99 + M -> 18MAY202699M',
          p._vifel_format_prodcode(d, '99', 'M') == '18MAY202699M',
          p._vifel_format_prodcode(d, '99', 'M'))
    check('Y2 formatter zero-pads day/uses building code (01JAN + P2)',
          p._vifel_format_prodcode(datetime.date(2026, 1, 1), '7', 'P2')
          == '01JAN20267P2',
          p._vifel_format_prodcode(datetime.date(2026, 1, 1), '7', 'P2'))
    check('Y3 formatter with NO production date -> Batch# + building only',
          p._vifel_format_prodcode(False, '42', 'A') == '42A',
          p._vifel_format_prodcode(False, '42', 'A'))

    # ---- 2. profile toggle + context gating ---------------------------
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_show_batch_no': True})
    env.flush_all()
    dp = Picking.search([('picking_type_id.code', '=', 'incoming'),
                         ('partner_id', '=', owner.id)], limit=1)
    check('Y4 picking exposes show_batch_no from the profile',
          dp.show_batch_no, dp.show_batch_no)
    act = dp.action_detailed_operations()
    check('Y5 detailed-ops action injects show_batch_no into context',
          act.get('context', {}).get('show_batch_no') is True)

    # ---- 3. stamp a real DONE receipt line's Batch # onto its quant ----
    done_rr = Picking.search([
        ('picking_type_id.code', '=', 'incoming'), ('state', '=', 'done')],
        limit=400).filtered(lambda r: r.move_line_ids.filtered(
            lambda l: l.result_package_id and l.location_dest_id.usage == 'internal'
            and Quant.search_count([
                ('package_id', '=', l.result_package_id.id),
                ('location_id', '=', l.location_dest_id.id),
                ('product_id', '=', l.product_id.id),
                ('x_studio_building_dropped', '!=', False)])))[:1]
    line = done_rr.move_line_ids.filtered(
        lambda l: l.result_package_id and l.location_dest_id.usage == 'internal'
        and Quant.search_count([
            ('package_id', '=', l.result_package_id.id),
            ('location_id', '=', l.location_dest_id.id),
            ('product_id', '=', l.product_id.id),
            ('x_studio_building_dropped', '!=', False)]))[:1]
    check('Y6 found a done receipt line landed on a real quant', bool(line),
          done_rr.name)
    line.batch_no = '99'
    done_rr._vifel_stamp_batch_prodcode()
    env.flush_all()
    q = Quant.search([
        ('package_id', '=', line.result_package_id.id),
        ('location_id', '=', line.location_dest_id.id),
        ('product_id', '=', line.product_id.id),
        ('lot_id', '=', line.lot_id.id)], limit=1)
    bld = q.x_studio_building_dropped
    expect = p._vifel_format_prodcode(line.x_studio_production_date, '99', bld)
    check('Y7 the quant got the raw Batch #', q.batch_no == '99', q.batch_no)
    check('Y8 the quant got the frozen Prodcode (%s, bldg=%s)' % (expect, bld),
          q.prodcode == expect and expect.endswith(bld) and '99' in expect,
          q.prodcode)

    # ---- 4. a withdrawal line reads the Prodcode back off that quant ---
    # attach a real OUTGOING picking so picking_code == 'outgoing' (the read-back
    # is gated to withdrawals for efficiency).
    owr = env['stock.picking'].search(
        [('picking_type_id.code', '=', 'outgoing')], limit=1)
    wr_line = env['stock.move.line'].new({
        'picking_id': owr.id,
        'product_id': line.product_id.id,
        'location_id': line.location_dest_id.id,
        'lot_id': line.lot_id.id,
        'package_id': line.result_package_id.id,
    })
    wr_line._compute_vifel_quant_readback()
    check('Y9 a WR line withdrawing from that quant shows the Prodcode',
          wr_line.prodcode == expect, wr_line.prodcode)
    check('Y9b the same WR line reads the Lot No. back too',
          wr_line.vifel_lot_no_display == (q.client_lot_no or ''),
          wr_line.vifel_lot_no_display)

    # ---- 5. an unrelated line shows nothing ---------------------------
    blank = env['stock.move.line'].new(
        {'picking_id': owr.id, 'product_id': line.product_id.id})
    blank._compute_vifel_quant_readback()
    check('Y10 a line not tied to a coded quant shows no Prodcode',
          not blank.prodcode, blank.prodcode)

    # ---- 6. no Batch # typed -> nothing stamped -----------------------
    line2 = done_rr.move_line_ids.filtered(
        lambda l: l != line and l.result_package_id)[:1]
    if line2:
        before = Quant.search([
            ('package_id', '=', line2.result_package_id.id),
            ('product_id', '=', line2.product_id.id)], limit=1).prodcode
        done_rr._vifel_stamp_batch_prodcode()  # line2 has no batch_no
        after = Quant.search([
            ('package_id', '=', line2.result_package_id.id),
            ('product_id', '=', line2.product_id.id)], limit=1).prodcode
        check('Y11 a line with no Batch # leaves its quant Prodcode untouched',
              (before or '') == (after or ''))
    else:
        check('Y11 a line with no Batch # leaves its quant Prodcode untouched',
              True, '(single-line receipt)')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
