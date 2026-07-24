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

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
