# Phase C: PKR counting — merged lines count +0 pallets, full KG/qty.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))

try:
    PKR = env['pallet_kilos_record_model.pallet_kilos_record_model']
    ML = env['stock.move.line']

    # a validated, non-BF RR whose PKR row counts >= 2 pallets
    row = PKR.search([
        ('pallets_received', '>=', 2),
        ('is_blast_freezer', '=', False),
        ('kilos_received', '>', 0)], limit=200).filtered(
        lambda r: r.effective_document
        and r.effective_document.picking_type_id.code == 'incoming'
        and len(r.effective_document.move_line_ids.filtered(
            'result_package_id').mapped('result_package_id')) >= 2)[:1]
    doc = row.effective_document
    print('PKR row: %s | RR %s | pallets=%s kilos=%s' % (
        row.id, doc.name, row.pallets_received, row.kilos_received))

    base_pallets = row.pallets_received
    base_kilos = row.kilos_received
    base_pkgs = row.units_received, row.packaging_received

    # flag every line of ONE pallet as merged
    one_pkg = doc.move_line_ids.filtered('result_package_id')[0].result_package_id
    flag_lines = doc.move_line_ids.filtered(
        lambda l: l.result_package_id == one_pkg)
    flag_lines.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': True})
    row._populate_operations_data()
    check('C1 flagged pallet drops out of the count (-1)',
          row.pallets_received == base_pallets - 1,
          (base_pallets, row.pallets_received))
    check('C2 kilos still fully counted',
          abs(row.kilos_received - base_kilos) < 0.001,
          (base_kilos, row.kilos_received))
    check('C3 units/packaging still fully counted',
          (row.units_received, row.packaging_received) == base_pkgs)

    # un-flag -> the count comes back (idempotent recompute)
    flag_lines.with_context(skip_pallet_series_sync=True).write(
        {'is_pallet_merge': False})
    row._populate_operations_data()
    check('C4 clearing the flag restores the original count',
          row.pallets_received == base_pallets, row.pallets_received)

    # ---- Re-sync smoke: idempotent, and the domains accept the clause ---
    check('C5 is_pallet_merge is visible to the PKR domain guard',
          'is_pallet_merge' in ML._fields)
    owner = row.owner_id
    rows = PKR.search([('owner_id', '=', owner.id), ('active', '=', True)])
    before = {r.id: (r.pallets_received, r.pallets_withdrawn,
                     r.adjustment_pallets) for r in rows}
    rows[:1].action_resync_pallet_counts()
    env.invalidate_all()
    after = {r.id: (r.pallets_received, r.pallets_withdrawn,
                    r.adjustment_pallets) for r in rows}
    drift = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check('C6 full owner Re-sync runs clean with the merge exclusions '
          '(%s, %d rows)' % (owner.name, len(rows)), not drift,
          list(drift.items())[:3])

    # withdrawals/void mirrors untouched: copy=False keeps mirrors blank
    check('C7 the flag is copy=False (void mirrors stay plain lines)',
          ML._fields['is_pallet_merge'].copy is False)

except Exception:
    print('UNEXPECTED ERROR:'); traceback.print_exc(); FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
