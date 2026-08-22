# Suite AV - Remarks through pallet adjustments and returns.
#
# Closes the two gaps recorded in ai_context/PALLET_FIELD_CHAIN.md:
#   G1 correction history move lines omitted Remarks / Lot No. / Batch #
#   G2 returns did not carry Remarks onto the re-received stock
# and covers the new correctable Remarks in the Correct Quants wizard.
#
# The important checks here are the NEGATIVE ones: a Remarks-only correction
# must move no stock, post no pallet leg, trigger no PSI cascade, and must not
# flip open adjustment requests to "Pallet Changed".
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_av_remarks_correction_return.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []

MARK = 'RMK-AV-NEW'


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Quant = env['stock.quant']
    Wizard = env['stock.quant.correction.wizard']
    CorrLine = env['stock.quant.correction.line']
    AdjLine = env['stock.quant.adjustment.line']
    MoveLine = env['stock.move.line']

    # ---- 1. the field is wired into the correction machinery ----------
    check('AV1 correction line has a Remarks field',
          'x_studio_remarks' in CorrLine._fields, 'missing')
    check('AV2 adjustment line has the old/new Remarks pair',
          'old_x_studio_remarks' in AdjLine._fields
          and 'new_x_studio_remarks' in AdjLine._fields,
          'the audit-line _get_changes would AttributeError without both')
    check('AV3 core exposes the neutral correction hook',
          hasattr(Wizard, '_vifel_correction_line_extra_vals'), 'hook missing')

    # ---- 2. a Remarks-only correction ---------------------------------
    quant = Quant.search([
        ('quantity', '>', 0),
        ('package_id', '!=', False),
        ('location_id.usage', '=', 'internal'),
        ('owner_id', '!=', False),
    ], limit=1)

    if not quant:
        check('AV4 found a quant to correct', False, 'none')
    else:
        print('quant %s  pallet %s  psi %s'
              % (quant.id, quant.package_id.name,
                 quant.x_studio_pallet_series_id))
        old_remarks = quant.x_studio_remarks
        old_qty = quant.quantity
        old_pkg = quant.package_id

        wiz = Wizard.create({'reason_for_adjustment': 'AV suite'})
        line = CorrLine.create(dict(
            Wizard._correction_line_vals(quant), wizard_id=wiz.id))
        # change ONLY the Remarks
        line.x_studio_remarks = MARK
        env.flush_all()

        changes = line._get_changes()
        check('AV4 a Remarks edit is detected as a change',
              changes.get('x_studio_remarks', (None, None))[1] == MARK, changes)
        check('AV5 nothing else is reported as changed',
              set(changes.keys()) == {'x_studio_remarks'}, sorted(changes))

        # THE LEDGER GUARD: no pallet leg, no KG/packaging movement.
        adj = wiz._calculate_adjustment_values(line, changes)
        check('AV6 a Remarks-only correction posts NO pallet leg',
              not adj.get('pallets'), adj)
        check('AV7 ... and no KG / packaging / units movement',
              not any(adj.get(k) for k in
                      ('kilos', 'packaging', 'units', 'quantity')), adj)

        # THE INTEGRITY GUARD: no group move of the pallet series.
        check('AV8 a Remarks-only correction triggers NO PSI cascade',
              wiz._psi_cascade_plan() == [], wiz._psi_cascade_plan())

        line._apply_changes(changes)
        env.flush_all()
        check('AV9 the corrected Remarks lands on the quant',
              quant.x_studio_remarks == MARK, quant.x_studio_remarks)
        check('AV10 the correction did not disturb weight or pallet',
              quant.quantity == old_qty and quant.package_id == old_pkg,
              (quant.quantity, quant.package_id.name))

        # ---- 3. the audit trail --------------------------------------
        # Built in memory: the permanent line normally hangs off an approval
        # request, and all we need here is that the pair is diffed and labelled.
        probe = AdjLine.new({
            'quant_id': quant.id,
            'old_x_studio_remarks': old_remarks or False,
            'new_x_studio_remarks': MARK,
        })
        check('AV11 the audit line diffs the old/new Remarks pair',
              'x_studio_remarks' in probe._get_changes(),
              sorted(probe._get_changes()))
        check('AV12 the Changes diff labels it "Remarks"',
              'Remarks' in (probe.changed_fields_display or ''),
              probe.changed_fields_display)

        # ---- 4. the correction history move line (G1) ----------------
        before = MoveLine.search([], order='id desc', limit=1).id or 0
        wiz._create_correction_move(
            line, changes, line._capture_original_state(), 'AV-BATCH',
            quant.x_studio_record_reference)
        env.flush_all()
        hist = MoveLine.search([('id', '>', before)], order='id desc', limit=1)
        check('AV13 a correction history move line was created', bool(hist), 'none')
        if hist:
            check('AV14 the history line carries Remarks (G1)',
                  hist.vifel_remarks == MARK, hist.vifel_remarks)
            if 'client_lot_no' in MoveLine._fields:
                # the hook is filled by the add-on; assert it reached the line
                # whenever the quant actually had a value to carry
                expected = quant.client_lot_no or False
                check('AV15 the history line carries the add-on Lot No. (G1)',
                      (hist.client_lot_no or False) == expected,
                      (hist.client_lot_no, expected))

    # ---- 5. the snapshot regression guard -----------------------------
    # Adding a key to ONE snapshot builder (or to both, against already-stored
    # snapshots) would make every open request read as "Pallet Changed".
    open_lines = AdjLine.search(
        [('quant_snapshot', '!=', False)], limit=25)
    if not open_lines:
        print('no stored snapshots on this DB - AV16 skipped')
    else:
        mismatched = []
        for al in open_lines:
            if not al.quant_id:
                continue
            rebuilt = al._create_quant_snapshot(al.quant_id)
            if rebuilt != al.quant_snapshot:
                mismatched.append(al.id)
        # Some drift is legitimate (write_date moves whenever a quant is
        # touched). What must NOT happen is EVERY line mismatching, which is
        # the signature of an added/removed snapshot key.
        check('AV16 snapshot builders still agree (no wholesale conflict flip)',
              len(mismatched) < len(open_lines),
              '%d/%d mismatched' % (len(mismatched), len(open_lines)))

    # ---- 6. returns carry Remarks (G2) --------------------------------
    RetLine = env['return.package.wizard.line']
    RetWiz = env['return.package.wizard']
    check('AV17 the return wizard line has a Remarks field',
          'remarks' in RetLine._fields, 'missing')

    wr_line = MoveLine.search([
        ('picking_id.picking_type_id.code', '=', 'outgoing'),
        ('product_id', '!=', False),
    ], limit=1)
    if wr_line:
        vals = RetWiz._vifel_return_wizard_line_vals(wr_line)
        check('AV18 the wizard-line hook carries Remarks (G2)',
              'remarks' in vals, sorted(vals))
        if 'client_lot_no' in MoveLine._fields:
            check('AV19 ... and the add-on Lot No. still rides the same hook',
                  'client_lot_no' in vals, sorted(vals))

        probe = RetLine.new({'remarks': MARK})
        ml_vals = RetWiz._vifel_return_move_line_vals(probe)
        check('AV20 the move-line hook carries Remarks onto the return',
              ml_vals.get('vifel_remarks') == MARK, ml_vals)

    # ---- 6b. the VOID return carries it too (hop 8b) -----------------
    # _create_return_rr_from_wr builds the wizard lines BY HAND rather than
    # going through the wizard's own builder, so it is a separate write path
    # that silently bypassed the hook: a void return RR arrived blank while
    # the withdrawal it mirrors carried the value.
    import inspect
    from odoo.addons.multiple_relocation.models import stock_picking as _sp
    src = inspect.getsource(_sp)
    start = src.find('def _create_return_rr_from_wr')
    chunk = src[start:start + 14000] if start != -1 else ''
    check('AV23 the void-return builder applies the return hook',
          '_vifel_return_wizard_line_vals' in chunk,
          'hand-built wizard lines bypass the hook again')

    # ---- 7. the HTML diff is escaped ----------------------------------
    probe_line = AdjLine.search([], limit=1)
    if probe_line:
        rendered = probe_line._format_field_value(
            'x_studio_remarks', '<img src=x onerror=alert(1)>')
        check('AV21 free text is escaped in the changes diff',
              '<img' not in rendered, rendered)
        check('AV22 the Empty marker stays real markup',
              '<em' in probe_line._format_field_value('x_studio_remarks', False),
              probe_line._format_field_value('x_studio_remarks', False))

except Exception:
    traceback.print_exc()
    FAIL.append('EXCEPTION')

print('\nRESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED: ' + ', '.join(FAIL))

env.cr.rollback()
print('ROLLED BACK - nothing committed')
