# Suite AU - the Remarks column lifecycle.
#
# Remarks is TYPED on a receipt (RR/BFRR), stamped onto the quant at
# validation, and READ BACK read-only on a withdrawal (WR/BFWR). It must
# survive validation, because a full withdrawal destroys the source quant the
# read-back depends on - that is what vifel_remarks_frozen is for.
#
# Unlike the client Lot No. this is CORE (multiple_relocation) and
# unconditional: no per-client profile flag gates it. The quant side reuses the
# existing Studio field stock.quant.x_studio_remarks rather than adding a
# second one, so the quant lists never show two Remarks columns.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_au_remarks_lifecycle.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []

MARK = 'RMK-TEST-AU'


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    MoveLine = env['stock.move.line']
    Quant = env['stock.quant']
    ml_fields = MoveLine._fields
    quant_fields = Quant._fields

    # ---- 1. the fields exist with the right storage semantics ---------
    check('AU1 stock.move.line.vifel_remarks is a stored Char',
          'vifel_remarks' in ml_fields
          and ml_fields['vifel_remarks'].type == 'char'
          and ml_fields['vifel_remarks'].store,
          'missing or not stored')

    check('AU2 vifel_remarks_display is a NON-stored compute',
          'vifel_remarks_display' in ml_fields
          and not ml_fields['vifel_remarks_display'].store
          and ml_fields['vifel_remarks_display'].compute,
          'display must be computed and not stored')

    check('AU3 vifel_remarks_frozen is STORED (survives the quant)',
          'vifel_remarks_frozen' in ml_fields
          and ml_fields['vifel_remarks_frozen'].store,
          'the snapshot must be stored or the value dies at validation')

    check('AU4 all three are copy=False',
          not ml_fields['vifel_remarks'].copy
          and not ml_fields['vifel_remarks_frozen'].copy,
          'void mirrors/returns must not inherit remarks')

    # The quant side must be the EXISTING Studio field, not a new one.
    check('AU5 quant side reuses the Studio x_studio_remarks',
          'x_studio_remarks' in quant_fields and quant_fields['x_studio_remarks'].store,
          'x_studio_remarks missing on stock.quant')
    check('AU6 no second Remarks field was added to stock.quant',
          'vifel_remarks' not in quant_fields,
          'a duplicate quant Remarks field would show two columns')

    # ---- 2. RR -> quant stamping --------------------------------------
    # A validated incoming line whose destination quant is still resolvable.
    # Start from stock that still EXISTS and walk back to the line that
    # received it: a receipt whose pallet was long since withdrawn has no
    # destination quant left to stamp, which says nothing about the code.
    rr_line = MoveLine.browse()
    for cand in MoveLine.search([
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', '=', 'done'),
            ('result_package_id', '!=', False),
            ('product_id', '!=', False),
            ('lot_id', '!=', False),
    ], order='id desc', limit=400):
        if Quant.search_count([
                ('product_id', '=', cand.product_id.id),
                ('location_id', '=', cand.location_dest_id.id),
                ('lot_id', '=', cand.lot_id.id),
                ('package_id', '=', cand.result_package_id.id),
                ('owner_id', '=',
                 cand.owner_id.id or cand.picking_id.partner_id.id),
        ]):
            rr_line = cand
            break

    if not rr_line:
        check('AU7 found a done receiving line to stamp', False, 'no candidate line')
    else:
        picking = rr_line.picking_id
        dest_quants = Quant.search([
            ('product_id', '=', rr_line.product_id.id),
            ('location_id', '=', rr_line.location_dest_id.id),
            ('lot_id', '=', rr_line.lot_id.id),
            ('package_id', '=', rr_line.result_package_id.id),
            ('owner_id', '=', rr_line.owner_id.id or picking.partner_id.id),
        ])
        print('receipt %s line %s -> %s dest quant(s)'
              % (picking.name, rr_line.id, len(dest_quants)))

        rr_line.vifel_remarks = MARK
        env.flush_all()
        picking._vifel_stamp_remarks()
        env.flush_all()

        check('AU7 receiving stamp writes Remarks onto the destination quant',
              bool(dest_quants) and all(q.x_studio_remarks == MARK for q in dest_quants),
              dest_quants.mapped('x_studio_remarks'))

        # The stamp must key on the DESTINATION side. If it wrongly used
        # location_id/package_id it would hit unrelated stock, so assert it did
        # not touch a same-product quant sitting in the SOURCE location.
        stray = Quant.search([
            ('product_id', '=', rr_line.product_id.id),
            ('location_id', '=', rr_line.location_id.id),
            ('id', 'not in', dest_quants.ids),
            ('x_studio_remarks', '=', MARK),
        ], limit=1)
        check('AU8 stamp did not leak onto source-side stock', not stray,
              stray and stray.id)

        # An empty Remarks must never blank an existing stamped value.
        rr_line.vifel_remarks = False
        env.flush_all()
        picking._vifel_stamp_remarks()
        env.flush_all()
        check('AU9 an empty line Remarks does not wipe the quant value',
              all(q.x_studio_remarks == MARK for q in dest_quants),
              dest_quants.mapped('x_studio_remarks'))

    # ---- 3. WR read-back and the snapshot -----------------------------
    # Same rule on the withdrawal side: a validated WR has already consumed its
    # source quant (that is precisely why the snapshot exists), so look at
    # withdrawals still in progress, and only accept a line whose quant resolves.
    wr_line = MoveLine.browse()
    for cand in MoveLine.search([
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('picking_id.state', 'not in', ('done', 'cancel')),
            ('package_id', '!=', False),
            ('product_id', '!=', False),
            ('lot_id', '!=', False),
            ('vifel_remarks_frozen', '=', False),
    ], order='id desc', limit=400):
        if Quant.search_count([
                ('product_id', '=', cand.product_id.id),
                ('location_id', '=', cand.location_id.id),
                ('lot_id', '=', cand.lot_id.id),
                ('package_id', '=', cand.package_id.id),
        ]):
            wr_line = cand
            break

    if not wr_line:
        check('AU10 found a withdrawal line to read back', False, 'no candidate line')
    else:
        src_quant = Quant.search([
            ('product_id', '=', wr_line.product_id.id),
            ('location_id', '=', wr_line.location_id.id),
            ('lot_id', '=', wr_line.lot_id.id),
            ('package_id', '=', wr_line.package_id.id),
        ], limit=1)
        print('withdrawal line %s -> src quant %s' % (wr_line.id, src_quant.id or None))

        if not src_quant:
            check('AU10 withdrawal line resolves a source quant', False, 'none found')
        else:
            src_quant.x_studio_remarks = MARK
            env.flush_all()
            wr_line.invalidate_recordset(['vifel_remarks_display'])
            check('AU10 withdrawal reads Remarks back off the source quant',
                  wr_line.vifel_remarks_display == MARK,
                  wr_line.vifel_remarks_display)

            # Snapshot, then destroy the quant's value the way a full
            # withdrawal destroys the quant itself. The display must hold.
            wr_line._vifel_freeze_remarks_readback()
            env.flush_all()
            check('AU11 the snapshot is captured before the quant is consumed',
                  wr_line.vifel_remarks_frozen == MARK,
                  wr_line.vifel_remarks_frozen)

            src_quant.x_studio_remarks = False
            env.flush_all()
            wr_line.invalidate_recordset(['vifel_remarks_display'])
            check('AU12 Remarks SURVIVES the source quant losing the value',
                  wr_line.vifel_remarks_display == MARK,
                  wr_line.vifel_remarks_display)

            # Idempotent: a second freeze must not overwrite the snapshot.
            src_quant.x_studio_remarks = 'SOMETHING-ELSE'
            env.flush_all()
            wr_line._vifel_freeze_remarks_readback()
            env.flush_all()
            check('AU13 freeze is idempotent (never overwrites a snapshot)',
                  wr_line.vifel_remarks_frozen == MARK,
                  wr_line.vifel_remarks_frozen)

    # ---- 4. receipts never read back ----------------------------------
    rr_display = MoveLine.search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('product_id', '!=', False),
    ], limit=1)
    if rr_display:
        check('AU14 a receiving line has an empty read-back column',
              not rr_display.vifel_remarks_display,
              rr_display.vifel_remarks_display)

    # ---- 5. relocation carry-over -------------------------------------
    reloc_quant = Quant.search([('quantity', '>', 0)], limit=1)
    if not reloc_quant:
        check('AU15 found a quant for relocation vals', False, 'none')
    else:
        reloc_quant.x_studio_remarks = MARK
        env.flush_all()
        vals = reloc_quant._relocation_studio_vals()
        check('AU15 relocation carries Remarks to the destination quant',
              vals.get('x_studio_remarks') == MARK, vals.get('x_studio_remarks'))
        # The hook must also pull in the add-on's own stamped fields, which
        # were silently lost on every relocation before this change.
        check('AU16 relocation hook carries the add-on Lot No. family',
              all(k in vals for k in ('client_lot_no', 'batch_no', 'prodcode')),
              sorted(vals.keys()))

    check('AU17 core exposes a neutral relocation hook',
          hasattr(Quant, '_vifel_relocation_extra_fields'),
          'hook missing')

    # ---- 6. the Magic Wizard carries it, including the BF path ---------
    WizLine = env['stock.move.line.fast_encode_rr.line']
    check('AU18 the Magic Wizard line has a Remarks column',
          'remarks' in WizLine._fields, 'wizard line field missing')

    import inspect
    from odoo.addons.multiple_relocation.wizard import FastEncodeRR as _fe
    confirm_src = inspect.getsource(_fe.stock_move_line_fast_encode_rr.action_confirm) \
        if hasattr(_fe, 'stock_move_line_fast_encode_rr') else ''
    if not confirm_src:
        # class name differs; fall back to the module source
        confirm_src = inspect.getsource(_fe)
    bf_chunk = confirm_src.split('is_blast_freeze:')[1].split('return {')[0] \
        if 'is_blast_freeze:' in confirm_src else ''
    check('AU19 the BF confirm path writes Remarks',
          'vifel_remarks' in bf_chunk, 'BF branch does not carry vifel_remarks')
    check('AU20 the BF confirm path routes through the add-on hook',
          '_vifel_line_write_vals' in bf_chunk,
          'BF branch still bypasses the hook, so add-on fields are dropped')
    check('AU21 the normal confirm path writes Remarks',
          confirm_src.count('vifel_remarks') >= 2, confirm_src.count('vifel_remarks'))

except Exception:
    traceback.print_exc()
    FAIL.append('EXCEPTION')

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED: ' + ', '.join(FAIL))

env.cr.rollback()
print('rolled back - nothing committed')
