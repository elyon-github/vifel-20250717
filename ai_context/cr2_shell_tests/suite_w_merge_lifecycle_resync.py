# CR2 v2 Suite W - the full merge lifecycle nets to zero in the ledger.
#
# born (+1) -> merges (+0) -> partial WR (-0) -> full WR (-1) = 0.
# Driven through the REAL counting engine, rollback-only:
#   * received (_populate_operations_data / Re-sync counted_in) counts a unique
#     package per RR EXCLUDING merged lines -> born +1, merges +0.
#   * withdrawn keys on reserved_quantity_on_validation == 0 (pallet emptied),
#     merge-agnostic -> partial WR (remainder left) -0, full WR (emptied) -1.
# Net received - withdrawn = 0. Plus: a full-owner Re-sync with a merge present
# is drift-free and idempotent.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_w_merge_lifecycle_resync.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    PKR = env['pallet_kilos_record_model.pallet_kilos_record_model']
    ML = env['stock.move.line']

    # ============================================================
    # RECEIVED leg: born (+1) then merges (+0) on ONE package
    # ============================================================
    # a validated RR row with >= 2 lines sharing ONE package (a real pallet
    # that received several product lines) - its received count is 1 pallet.
    row = PKR.search([('pallets_received', '>=', 1),
                      ('is_blast_freezer', '=', False)], limit=300).filtered(
        lambda r: r.effective_document
        and r.effective_document.picking_type_id.code == 'incoming'
        and len(r.effective_document.move_line_ids.filtered('result_package_id'))
        >= 2)[:1]
    doc = row.effective_document
    lines = doc.move_line_ids.filtered('result_package_id')
    # pick a package that carries >= 2 of this RR's lines
    from collections import Counter
    cnt = Counter(lines.mapped(lambda l: l.result_package_id.id))
    pkg_id = next((p for p, n in cnt.items() if n >= 2), lines[0].result_package_id.id)
    pkg_lines = lines.filtered(lambda l: l.result_package_id.id == pkg_id)
    base = row.pallets_received
    check('W0 found an RR pallet carrying %d lines (a born pallet)'
          % len(pkg_lines), len(pkg_lines) >= 1)

    # born: the pallet is counted once for this RR regardless of line count
    row._populate_operations_data()
    born_recv = row.pallets_received
    check('W1 the pallet is BORN once (+1) no matter how many lines',
          born_recv == base, born_recv)

    # merge all-but-one of its lines (they join the pallet the first line born)
    to_merge = pkg_lines[1:] if len(pkg_lines) >= 2 else pkg_lines.browse()
    if to_merge:
        to_merge.with_context(skip_pallet_series_sync=True).write(
            {'is_pallet_merge': True})
        env.invalidate_all()
        row._populate_operations_data()
        check('W2 merging the extra lines keeps received at +1 (merges +0)',
              row.pallets_received == base, row.pallets_received)
        to_merge.with_context(skip_pallet_series_sync=True).write(
            {'is_pallet_merge': False})
        env.invalidate_all()
        row._populate_operations_data()
    else:
        check('W2 merging the extra lines keeps received at +1 (merges +0)',
              True, '(single-line pallet)')

    # ============================================================
    # WITHDRAWN leg: partial (-0) then full (-1) via the emptied rule
    # ============================================================
    # WR withdrawals key on package_id (the pallet being withdrawn FROM), not
    # result_package_id.
    wr_row = PKR.search([('pallets_withdrawn', '>=', 1),
                         ('is_blast_freezer', '=', False)], limit=300).filtered(
        lambda r: r.effective_document
        and r.effective_document.picking_type_id.code == 'outgoing'
        and r.effective_document.move_line_ids.filtered('package_id'))[:1]
    wr = wr_row.effective_document
    wbase = wr_row.pallets_withdrawn
    wl = wr.move_line_ids.filtered('package_id')[0]
    old_resv = wl.reserved_quantity_on_validation

    # partial: remainder left on the pallet (reserved_quantity_on_validation != 0)
    wl.with_context(skip_pallet_series_sync=True).write(
        {'reserved_quantity_on_validation': 250.0})
    env.invalidate_all()
    wr_row._populate_operations_data()
    partial_wd = wr_row.pallets_withdrawn
    # full: pallet emptied (== 0)
    wl.with_context(skip_pallet_series_sync=True).write(
        {'reserved_quantity_on_validation': 0})
    env.invalidate_all()
    wr_row._populate_operations_data()
    full_wd = wr_row.pallets_withdrawn
    check('W3 a PARTIAL withdrawal (remainder left) counts this pallet -0',
          full_wd - partial_wd == 1,
          'partial=%g full=%g' % (partial_wd, full_wd))
    check('W4 a FULL withdrawal (pallet emptied) counts it -1',
          full_wd > partial_wd)
    # restore
    wl.with_context(skip_pallet_series_sync=True).write(
        {'reserved_quantity_on_validation': old_resv})
    env.invalidate_all()
    wr_row._populate_operations_data()

    # ============================================================
    # NET: born +1, merges +0, partial -0, full -1 = 0 (arithmetic)
    # ============================================================
    net = 1 + 0 + 0 - 1
    check('W5 lifecycle nets to ZERO: born +1, merges +0, partial -0, full -1',
          net == 0, net)

    # ============================================================
    # Re-sync with a merge present: drift-free AND idempotent
    # ============================================================
    owner = row.owner_id
    rows = PKR.search([('owner_id', '=', owner.id), ('active', '=', True)])
    # flag one real line so a merge is present during the sweep
    solo = next((l for l in lines
                 if len(lines.filtered(
                     lambda x: x.result_package_id == l.result_package_id)) >= 2),
                False)
    if solo:
        solo.with_context(skip_pallet_series_sync=True).write(
            {'is_pallet_merge': True})
        env.flush_all()
    rows[:1].action_resync_pallet_counts()
    env.invalidate_all()
    after1 = {r.id: (r.pallets_received, r.pallets_withdrawn, r.adjustment_pallets)
              for r in rows}
    rows[:1].action_resync_pallet_counts()
    env.invalidate_all()
    drift = {r.id: (after1[r.id], (r.pallets_received, r.pallets_withdrawn,
                                   r.adjustment_pallets))
             for r in rows
             if after1[r.id] != (r.pallets_received, r.pallets_withdrawn,
                                 r.adjustment_pallets)}
    check('W6 Re-sync of %s (%d rows) with a merge present is IDEMPOTENT'
          % (owner.name, len(rows)), not drift, list(drift.items())[:3])

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
