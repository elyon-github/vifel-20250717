# CR2 v2 Suite C — PKR counting doctrine. Rollback-only.
#
# THE billing invariant: a merged line contributes +0 PALLETS but its full
# Weight / Quantity / Packs. Everything else in the feature is convenience;
# this is the part that shows up on an invoice.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_c_pkr_counting.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    PKR = env['pallet_kilos_record_model.pallet_kilos_record_model']
    MoveLine = env['stock.move.line']

    # a validated RR ledger row with a real received-pallet count
    row = PKR.search([('pallets_received', '>=', 2),
                      ('is_blast_freezer', '=', False)], limit=200).filtered(
        lambda r: r.effective_document
        and r.effective_document.picking_type_id.code == 'incoming'
        and len(r.effective_document.move_line_ids.filtered(
            'result_package_id')) >= 2)[:1]
    doc = row.effective_document
    print('PKR row %s | RR %s | received=%s kilos=%s'
          % (row.id, doc.name, row.pallets_received, row.kilos_received))

    base_pallets = row.pallets_received
    base_kilos = row.kilos_received
    base_qty = row.packaging_received      # "Quantity" = the 2nd UOM
    base_units = row.units_received        # "Packs / Heads"

    # a line whose pallet is used by NO other line (so flagging it must
    # remove exactly one pallet from the count)
    lines = doc.move_line_ids.filtered('result_package_id')
    solo = None
    for ml in lines:
        if len(lines.filtered(lambda l: l.result_package_id == ml.result_package_id)) == 1:
            solo = ml
            break
    check('C0 found a solo-pallet line to flag', bool(solo))

    # ---- flag it: -1 pallet, amounts untouched -----------------------
    solo.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True})
    env.invalidate_all()
    row._populate_operations_data()
    check('C1 merged line drops out of the pallet count (%g -> %g)'
          % (base_pallets, row.pallets_received),
          row.pallets_received == base_pallets - 1, row.pallets_received)
    check('C2 Weight (KG) still fully counted',
          abs(row.kilos_received - base_kilos) < 0.001,
          (base_kilos, row.kilos_received))
    check('C3 Quantity (2nd UOM) still fully counted',
          abs(row.packaging_received - base_qty) < 0.001,
          (base_qty, row.packaging_received))
    check('C4 Packs/Heads still fully counted',
          abs(row.units_received - base_units) < 0.001,
          (base_units, row.units_received))

    # ---- unflag: count restored -------------------------------------
    solo.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': False})
    env.invalidate_all()
    row._populate_operations_data()
    check('C5 clearing the flag restores the original count (%g)'
          % base_pallets, row.pallets_received == base_pallets,
          row.pallets_received)

    # ---- the field is searchable by the PKR domain guards ------------
    check('C6 is_pallet_merge is a real searchable field',
          'is_pallet_merge' in MoveLine._fields
          and isinstance(MoveLine.search_count(
              [('is_pallet_merge', '!=', True)]), int))

    # ---- the exclusions must drop ONLY genuinely-flagged rows --------
    # The load-bearing safety property (DB-state INDEPENDENT): the
    # ('is_pallet_merge', '!=', True) clause must keep every NULL/False
    # (unflagged) row and drop ONLY the rows genuinely flagged True. If it ever
    # silently dropped NULLs (a SQL NULL-handling risk), the ledger would lose
    # real received pallets. So: n_free must equal n_all minus n_true, on ANY
    # data — whether or not real merges exist (originally this asserted
    # n_all==n_free, which only held while NO row was flagged; that premise is
    # stale now that live merges exist, so it is expressed against n_true).
    base_dom = [('state', '=', 'done'), ('result_package_id', '!=', False),
                ('picking_id.picking_type_id.code', '=', 'incoming')]
    n_all = MoveLine.search_count(base_dom)
    n_free = MoveLine.search_count(base_dom + [('is_pallet_merge', '!=', True)])
    n_true = MoveLine.search_count(base_dom + [('is_pallet_merge', '=', True)])
    check('C9 merge-free domain keeps all unflagged rows, drops only the %d '
          'flagged (NULL/False are not silently dropped; %d rows total)'
          % (n_true, n_all), n_free == n_all - n_true, (n_all, n_free, n_true))

    # ---- full-owner Re-sync: IDEMPOTENT ------------------------------
    # (runs BEFORE the copy test: a copied line cannot be unlinked from a
    # done picking, and leaving it behind would distort these counts)
    # A FIRST Re-sync on a debug DB legitimately corrects stale stored
    # values from evidence - that is the tool working. What must hold is
    # that a SECOND run changes nothing more: corrections converge, they do
    # not oscillate.
    owner = row.owner_id
    rows = PKR.search([('owner_id', '=', owner.id), ('active', '=', True)])
    rows[:1].action_resync_pallet_counts()
    env.invalidate_all()
    after1 = {r.id: (r.pallets_received, r.pallets_withdrawn,
                     r.adjustment_pallets) for r in rows}
    rows[:1].action_resync_pallet_counts()
    env.invalidate_all()
    drift = {r.id: (after1[r.id], (r.pallets_received, r.pallets_withdrawn,
                                   r.adjustment_pallets))
             for r in rows
             if after1[r.id] != (r.pallets_received, r.pallets_withdrawn,
                                 r.adjustment_pallets)}
    check('C10 Re-sync of %s (%d rows) is idempotent'
          % (owner.name, len(rows)), not drift, list(drift.items())[:3])

    # ---- copy=False: void mirrors / returns start plain (R5) ---------
    # LAST, because a line copied onto a done picking cannot be unlinked.
    solo.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True, 'client_lot_no': 'LOT-COPY-TEST'})
    env.flush_all()
    dup = solo.copy()
    check('C11 copy() drops the merge flag (void mirrors stay plain)',
          not dup.is_pallet_merge, dup.is_pallet_merge)
    check('C12 copy() drops the client Lot No.',
          not dup.client_lot_no, dup.client_lot_no)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
