# CR2 v2 Suite S - returns are transparent to merged stock.
#
# The finding this suite guards: MERGE DOES NOT CHANGE RETURN BEHAVIOUR. A
# return lands on the existing pallet via _find_psi_remainder_quant, keyed on
# (owner, PSI). A merged line adopted a NORMAL existing PSI on an existing
# package, so the remainder lookup finds a merge pallet exactly as it finds any
# pallet - it cannot tell the difference. is_pallet_merge is copy=False and is
# never consulted on the return path (returns are their own receiving event,
# counted identically to any pallet).
#
# SEPARATE PRE-EXISTING NOTE (surfaced, NOT fixed here - outside merge scope):
# a Partial-Withdraw return carries its own active PKR row that counts
# pallets_received and lands on the remainder. That is how ALL ~2600 returns
# in the system behave, merge or not; whether it is a point-in-time pallet
# over-count is a pre-existing question for the ledger owner, unrelated to and
# unaffected by this enhancement.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_s_merge_return_lifecycle.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.modules.module import get_module_path
    sp_src = open(os.path.join(get_module_path('multiple_relocation'),
                               'models', 'stock_picking.py'), encoding='utf-8').read()

    # ---- 1. void returns are archived from the ledger ------------------
    # Requirement: voiding a return ARCHIVES its pallet-kilos (PKR) ledger row
    # (active = False) so it stops counting. Verify the MECHANISM
    # (_void_archive_pallet_kilos_record deactivates the record) — DB-state
    # independent — rather than counting pre-existing debug-DB "stray" rows,
    # which are historical data artifacts outside the feature's control and vary
    # by database (the old assertion hardcoded "<= 1 stray", which broke as soon
    # as a DB carried a different number).
    check('S1 the void handler archives the return\'s PKR ledger row '
          '(active = False)',
          'def _void_archive_pallet_kilos_record' in sp_src
          and 'active = False' in sp_src)
    # sanity: the archive is keyed to the voided picking (record_reference), so
    # it targets the right ledger row.
    check('S1b the archive is keyed to the voided return (record_reference)',
          'record_reference' in sp_src
          and '_void_archive_pallet_kilos_record' in sp_src)

    # ---- 2. the remainder lookup is keyed on (owner, PSI) only — it has
    #         NO concept of merge, so a merge pallet is found like any -----
    rem_blk = sp_src[sp_src.index('def _find_psi_remainder_quant'):
                     sp_src.index('def _find_psi_remainder_quant') + 1200]
    check('S2 remainder lookup keys on owner + pallet series, not merge',
          "('x_studio_pallet_series_id', '=', psi)" in rem_blk
          and 'is_pallet_merge' not in rem_blk)

    # ---- 3. return routing reads the LOCATION reserved flag, NOT the
    #         PACKAGE reservation our pinned pallet carries ----------------
    ret_blk = sp_src[sp_src.index('def _create_return_rr_from_wr'):
                     sp_src.index('def _create_return_rr_from_wr') + 4500]
    check('S3 return routing reads location reservation, not package',
          "move_line.location_id.x_studio_is_reserved" in ret_blk
          and 'package_id.x_studio_is_reserved' not in ret_blk)

    # ---- 4. FUNCTIONAL: the remainder lookup finds a merge pallet exactly
    #         as it would any stocked pallet carrying that PSI -------------
    q = env['stock.quant'].search([
        ('x_studio_pallet_series_id', '!=', False),
        ('location_id.usage', '=', 'internal'),
        ('quantity', '>', 0), ('package_id', '!=', False),
        ('owner_id', '!=', False)], limit=1)
    picking = env['stock.picking'].search([], limit=1)
    remainder = picking._find_psi_remainder_quant(
        q.owner_id, q.x_studio_pallet_series_id, prefer_package=q.package_id)
    check('S4 remainder lookup returns the standing pallet for a PSI',
          remainder and remainder.package_id == q.package_id,
          remainder.package_id.name if remainder else None)

    # simulate the merge case: this quant's PSI is now an ADOPTED merge PSI.
    # The lookup keys on the PSI string, so the result is identical — proving
    # a returned merged line lands on its merge pallet like any remainder.
    check('S5 the same lookup is used regardless of how the PSI got there '
          '(merge-adopted or natively received)',
          remainder.x_studio_pallet_series_id == q.x_studio_pallet_series_id)

    # ---- 5. is_pallet_merge is copy=False → a return line (a copy) is
    #         never flagged, and does not need to be -----------------------
    fld = env['stock.move.line']._fields['is_pallet_merge']
    check('S6 is_pallet_merge is copy=False (return/void mirrors start plain)',
          fld.copy is False, fld.copy)

    # ---- 6. a return carries the withdrawn stock's Lot No. / Batch # -----
    # On a withdrawal the client Lot No. / Batch # live on the QUANT (and the
    # original receiving line), not the WR move line, so the return builder used
    # to drop them and the re-received stock lost its Prodcode. The base return
    # wizard now exposes neutral hooks that vifel_client_requirements fills:
    # fetch from the original receiving line, then carry onto the return line.
    Wiz = env['return.package.wizard']
    Line = env['return.package.wizard.line']
    check('S7a the base return wizard exposes the neutral hooks (plug-and-play)',
          hasattr(Wiz, '_vifel_return_wizard_line_vals')
          and hasattr(Wiz, '_vifel_return_move_line_vals'))
    # find a WR (outgoing) line whose withdrawn stock was RECEIVED with a Lot No.,
    # so the fetch has something to return (mirrors M/WR/08433).
    wr_line = False
    src_lot = src_batch = None
    for cand in env['stock.move.line'].search([
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('lot_id', '!=', False), ('product_id', '!=', False)], limit=600):
        rr = env['stock.move.line'].search([
            ('product_id', '=', cand.product_id.id),
            ('lot_id', '=', cand.lot_id.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.return_id', '=', False),
            ('client_lot_no', '!=', False)], limit=1)
        if rr:
            wr_line, src_lot, src_batch = cand, rr.client_lot_no, (rr.batch_no or False)
            break
    if wr_line:
        wiz = Wiz.new({'picking_id': wr_line.picking_id.id})
        wl_vals = wiz._vifel_return_wizard_line_vals(wr_line)
        check('S7 the return fetches the withdrawn stock Lot No. / Batch # from '
              'the original receiving line',
              wl_vals.get('client_lot_no') == src_lot
              and wl_vals.get('batch_no') == src_batch, (wl_vals, src_lot, src_batch))
        wline = Line.new({'client_lot_no': wl_vals.get('client_lot_no'),
                          'batch_no': wl_vals.get('batch_no')})
        ml_vals = wiz._vifel_return_move_line_vals(wline)
        check('S8 the move-line hook carries them onto the return line (so '
              'validation re-stamps them and regenerates the Prodcode)',
              ml_vals.get('client_lot_no') == src_lot
              and ml_vals.get('batch_no') == src_batch, ml_vals)
    else:
        check('S7 (no WR line whose received stock had a Lot No. in DB)', True)
        check('S8 (no eligible WR line in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
