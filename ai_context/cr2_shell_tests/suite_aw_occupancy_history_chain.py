# Suite AW - the occupancy-history hop of the pallet-field chain.
#
# stock_quant_history does NOT hand-maintain a field list like the other hops.
# It DISCOVERS fields by name: a stock.quant field is mirrored onto
# stock.quant.history only if the name starts with "x_studio_" (or is in the
# extra list) AND a same-named field exists on the history model.
#
# Two traps that this suite pins down:
#   G3  a field whose name lacks the x_studio_ prefix reaches occupancy history
#       NOWHERE unless it is declared on the history model AND added to the
#       extra list. Lot No. / Batch # / Prodcode were in exactly that hole.
#   G4  the move-line replay reads QUANT-named fields off a MOVE LINE, so a
#       field the two models name differently was silently dropped.
#       x_studio_remarks on the quant is vifel_remarks on the move line.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_aw_occupancy_history_chain.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []

MARK = 'RMK-AW-ALIAS'


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Snap = env['stock.quant.history.snapshot']
    Hist = env['stock.quant.history']._fields
    Quant = env['stock.quant']
    MoveLine = env['stock.move.line']

    copy_fields = Snap._get_quant_copy_fields()
    print('discovered copy fields: %d' % len(copy_fields))

    # ---- G3: the Lot No. family reaches occupancy history ------------
    for fname in ('client_lot_no', 'batch_no', 'prodcode'):
        check('AW1 %s is declared on stock.quant.history' % fname,
              fname in Hist, 'not declared, so it can never be mirrored')
        check('AW2 %s is in the snapshot copy list' % fname,
              fname in copy_fields,
              'declared but not in the extra list, so still never copied')

    check('AW3 the extras hook is overridable',
          hasattr(Snap, '_extra_copy_fields'), 'hook missing')
    check('AW4 the base extras are still present',
          all(f in copy_fields for f in ('owner_id', 'package_id')),
          copy_fields)

    # Remarks must keep riding the prefix rule. It qualifies ONLY because the
    # quant field is the Studio-named one; a vifel_-prefixed quant field would
    # have been silently excluded here.
    check('AW5 x_studio_remarks is still discovered',
          'x_studio_remarks' in copy_fields, copy_fields)

    # ---- G4: the move-line replay resolves the name mismatch ---------
    check('AW6 an alias map exists',
          hasattr(Snap, '_quant_field_aliases'), 'no alias map')
    aliases = Snap._quant_field_aliases()
    check('AW7 remarks is aliased to its move-line name',
          'vifel_remarks' in aliases.get('x_studio_remarks', ()), aliases)

    line = MoveLine.search([('product_id', '!=', False)], limit=1)
    if not line:
        check('AW8 found a move line to read', False, 'none')
    else:
        line.vifel_remarks = MARK
        env.flush_all()
        vals = Snap._copy_field_values(line, copy_fields)
        check('AW8 the replay reads Remarks off a move line via the alias',
              vals.get('x_studio_remarks') == MARK,
              vals.get('x_studio_remarks'))
        check('AW9 the value is keyed by the HISTORY name, not the alias',
              'vifel_remarks' not in vals, sorted(vals)[:6])

    # ---- the quant path must be untouched by the alias logic ---------
    quant = Quant.search([('quantity', '>', 0)], limit=1)
    if quant:
        quant.x_studio_remarks = MARK
        quant.client_lot_no = 'LOT-AW'
        env.flush_all()
        qvals = Snap._copy_field_values(quant, copy_fields)
        check('AW10 a quant source still reads its own field names',
              qvals.get('x_studio_remarks') == MARK, qvals.get('x_studio_remarks'))
        check('AW11 a quant source now carries the Lot No. family',
              qvals.get('client_lot_no') == 'LOT-AW', qvals.get('client_lot_no'))
        # every discovered name must be writable onto the history model
        bad = [f for f in qvals if f not in Hist]
        check('AW12 every copied name exists on stock.quant.history',
              not bad, bad)

except Exception:
    traceback.print_exc()
    FAIL.append('EXCEPTION')

print('\nRESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED: ' + ', '.join(FAIL))

env.cr.rollback()
print('ROLLED BACK - nothing committed')
