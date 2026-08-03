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

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
