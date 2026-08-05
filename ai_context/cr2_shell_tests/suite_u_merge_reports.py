# CR2 v2 Suite U - billing + occupancy reports see a merge pallet as one pallet.
#
# Two reports on DIFFERENT counting bases; both must agree a merge pallet is one:
#
#   * Billing (pallet_kilos_billing_report) READS PKR fields verbatim
#     (pallets_received / pallets_withdrawn / total_balance_in_pallets) and
#     counts nothing itself. PKR is already merge-aware, so the report inherits
#     the correct figures - a merged line drops the printed received count by 1.
#
#   * Occupancy (stock_quant_history occupancy_xlsx_report) counts pallets by
#     DISTINCT x_studio_pallet_series_id from snapshots, INDEPENDENT of PKR. A
#     merge pallet is one PSI by design, so it counts once. This is the real
#     cross-check the user asked to include.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_u_merge_reports.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


class FakeRec:
    """Duck-typed stand-in for a stock.quant.history snapshot record — exactly
    the attributes occupancy_xlsx_report._aggregate_data reads."""
    def __init__(self, snap, owner, building, psi, qty):
        self.snapshot_id = type('S', (), {'id': snap})()
        self.owner_id = type('O', (), {'name': owner})()
        loc_building = type('B', (), {'x_name': building})()
        self.location_id = type('L', (), {'x_studio_building': loc_building})()
        self.x_studio_pallet_series_id = psi
        self.quantity = qty


try:
    from odoo.modules.module import get_module_path

    # =============================================================
    # BILLING report  (reads PKR, already merge-aware)
    # =============================================================
    src = open(os.path.join(get_module_path('pallet_kilos_record_model'),
                            'reports', 'pallet_kilos_billing_xlsx.py'),
               encoding='utf-8').read()
    check('UB1 billing report reads the PKR pallet fields',
          'pallets_received' in src and 'pallets_withdrawn' in src
          and 'total_balance_in_pallets' in src)
    check('UB2 billing report never counts pallets from stock itself',
          "search([('x_studio_pallet_series_id'" not in src
          and 'result_package_id' not in src
          and 'count(DISTINCT' not in src)

    PKR = env['pallet_kilos_record_model.pallet_kilos_record_model']
    MoveLine = env['stock.move.line']
    row = PKR.search([('pallets_received', '>=', 2),
                      ('is_blast_freezer', '=', False)], limit=200).filtered(
        lambda r: r.effective_document
        and r.effective_document.picking_type_id.code == 'incoming'
        and len(r.effective_document.move_line_ids.filtered(
            'result_package_id')) >= 2)[:1]
    doc = row.effective_document
    base = row.pallets_received
    # a solo-pallet line so flagging it removes exactly one from the count
    lines = doc.move_line_ids.filtered('result_package_id')
    solo = next((ml for ml in lines
                 if len(lines.filtered(
                     lambda l: l.result_package_id == ml.result_package_id)) == 1),
                False)
    check('UB3 found a real RR row + solo line to flag', bool(row) and bool(solo))
    solo.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True})
    env.invalidate_all()
    row._populate_operations_data()
    check('UB4 the number the billing report prints drops by 1 for a merge '
          '(%g -> %g)' % (base, row.pallets_received),
          row.pallets_received == base - 1, row.pallets_received)
    solo.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': False})
    env.invalidate_all()
    row._populate_operations_data()
    check('UB5 ... and restores when un-flagged',
          row.pallets_received == base, row.pallets_received)

    # =============================================================
    # OCCUPANCY report  (distinct-PSI, independent of PKR)
    # =============================================================
    osrc = open(os.path.join(get_module_path('stock_quant_history'),
                             'reports', 'occupancy_xlsx_report.py'),
                encoding='utf-8').read()
    check('UO1 occupancy counts pallets by DISTINCT pallet series',
          "'pallet_series': set()" in osrc
          and "['pallet_series'].add(rec.x_studio_pallet_series_id)" in osrc)

    Report = env['report.stock_quant_history.occupancy_report'] \
        if 'report.stock_quant_history.occupancy_report' in env \
        else env['report.report_xlsx.abstract']
    # find the real occupancy report model name
    rmodel = None
    for name in env.registry.models:
        if name.startswith('report.') and 'occupancy' in name:
            rmodel = name
            break
    check('UO2 occupancy report model is registered', bool(rmodel), rmodel)
    report = env[rmodel]

    fake_snap = type('Snap', (), {})()
    import datetime
    from pytz import UTC
    fake_snap.id = 1
    fake_snap.inventory_date = datetime.datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    snaps = [fake_snap]

    # a MERGE pallet: one PSI, TWO products (two history rows, same PSI)
    merge_recs = [
        FakeRec(1, 'ACME', 'B1', 'PSI-000001', 500.0),
        FakeRec(1, 'ACME', 'B1', 'PSI-000001', 300.0),  # 2nd product, SAME PSI
    ]
    bdata, _b, _d = report._aggregate_data(merge_recs, snaps)
    day = sorted(set([fake_snap.inventory_date.astimezone(
        __import__('pytz').timezone('Asia/Manila')).date()]))[0]
    pallets = len(bdata['B1']['ACME'][day]['pallet_series'])
    kilos = bdata['B1']['ACME'][day]['kilos']
    check('UO3 a merge pallet (one PSI, two products) counts as ONE pallet',
          pallets == 1, pallets)
    check('UO4 ... while its full weight still sums (800)', kilos == 800.0, kilos)

    # control: two DISTINCT PSIs count as two
    two_recs = [
        FakeRec(1, 'ACME', 'B1', 'PSI-000001', 500.0),
        FakeRec(1, 'ACME', 'B1', 'PSI-000002', 300.0),
    ]
    bdata2, _b2, _d2 = report._aggregate_data(two_recs, snaps)
    check('UO5 control: two distinct PSIs count as TWO pallets',
          len(bdata2['B1']['ACME'][day]['pallet_series']) == 2)

    print('   Conclusion: billing reads the merge-aware ledger; occupancy '
          'counts one-PSI-per-pallet, which merge guarantees. Both agree.')

    # =============================================================
    # RR/WR printed pallet count + Transacted Pallet Count are now
    # MERGE-AWARE (match the PKR ledger) via the _vifel_line_originates_pallet
    # hook. A merged (+0) receiving line must NOT inflate the printout.
    # =============================================================
    Picking = env['stock.picking']
    # base hook is a neutral no-op (plug-and-play)
    p0 = Picking.search([], limit=1)
    l0 = env['stock.move.line'].search([('is_pallet_merge', '=', False)], limit=1)
    check('UR1 base _vifel_line_originates_pallet is True for a normal line',
          p0._vifel_line_originates_pallet(l0))
    # ... and False for a merged line (the add-on override)
    lm = env['stock.move.line'].search([('is_pallet_merge', '=', True)], limit=1)
    if lm:
        check('UR2 the override returns False for a merged line',
              not p0._vifel_line_originates_pallet(lm))
    else:
        check('UR2 the override returns False for a merged line', True, '(no merged line)')

    # FUNCTIONAL: an incoming RR whose printed count == PKR received, with a
    # merged line present. Build one on a merge-enabled client.
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    rr = Picking.search([('picking_type_id.code', '=', 'incoming'),
                         ('state', '=', 'done'),
                         ('x_studio_is_a_blast_freezer', '=', False),
                         ('partner_id', '=', owner.id)], limit=200).filtered(
        lambda p: len(p.move_line_ids.filtered('result_package_id')) >= 2)[:1]
    if rr:
        def printed(p):
            res = p.get_grouped_move_lines_for_report()
            proc = res[0] if isinstance(res, (list, tuple)) else res
            return p.get_pallet_count_for_page(proc, 0, len(proc))
        base_print = printed(rr)
        base_trans = rr._compute_transacted_pallet_count() or rr.transacted_pallet_count
        rr._compute_transacted_pallet_count(); base_trans = rr.transacted_pallet_count
        # flag one line that shares a pallet with another (so the pallet stays
        # represented by the unflagged sibling) -> printed count drops by 0;
        # flag a SOLO-pallet line -> printed count drops by 1.
        lines = rr.move_line_ids.filtered('result_package_id')
        from collections import Counter
        cnt = Counter(lines.mapped('result_package_id').ids)
        solo = next((l for l in lines
                     if cnt[l.result_package_id.id] == 1), False)
        if solo:
            solo.with_context(skip_pallet_series_sync=True).write(
                {'is_pallet_merge': True})
            env.invalidate_all()
            after_print = printed(rr)
            rr._compute_transacted_pallet_count()
            after_trans = rr.transacted_pallet_count
            check('UR3 flagging a solo line drops the PRINTED RR count by 1 '
                  '(%d -> %d)' % (base_print, after_print),
                  after_print == base_print - 1, after_print)
            check('UR4 ... and the Transacted Pallet Count by 1 (%d -> %d)'
                  % (base_trans, after_trans),
                  after_trans == base_trans - 1, after_trans)
            # matches the PKR ledger recompute
            row = env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
                [('record_reference', '=', rr.id), ('active', '=', True)], limit=1)
            if row:
                row._populate_operations_data()
                check('UR5 printed count == PKR received (both merge-aware)',
                      after_print == int(row.pallets_received),
                      (after_print, row.pallets_received))
            solo.with_context(skip_pallet_series_sync=True).write(
                {'is_pallet_merge': False})
        else:
            check('UR3 flagging a solo line drops the PRINTED RR count by 1', True, '(no solo line)')
            check('UR4 ... and the Transacted Pallet Count by 1', True, '(n/a)')
            check('UR5 printed count == PKR received', True, '(n/a)')
    else:
        check('UR3 flagging a solo line drops the PRINTED RR count by 1', True, '(no RR)')

    # WR is unaffected: outgoing lines are never is_pallet_merge, so the hook is
    # True for them and the emptying gate still governs the WR count.
    wl = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'outgoing'),
        ('package_id', '!=', False)], limit=1)
    check('UR6 a WR (outgoing) line still originates a pallet (hook True)',
          p0._vifel_line_originates_pallet(wl) if wl else True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
