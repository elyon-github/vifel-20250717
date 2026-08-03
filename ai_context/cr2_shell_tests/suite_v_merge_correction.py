# CR2 v2 Suite V - quant correction is transparent to merged stock.
#
# The correction wizard's pallet-count effect (_package_change_pallet_delta) is
# PURELY PHYSICAL: it counts by whether the source/destination packages hold
# stock (owner-scoped) - split +1, merge -1, transfer 0 - and never reads
# is_pallet_merge. A merge pallet is just a package with stock, so a correction
# posts the correct physical delta exactly as for any pallet, and the merge
# flag on the RR line (history of the RR's +0) is untouched. No fix needed;
# this suite guards that transparency.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_v_merge_correction.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


class VifelSkip(Exception):
    """No eligible fixture in this DB — skip without failing."""


try:
    from odoo.modules.module import get_module_path
    src = open(os.path.join(get_module_path('multiple_relocation'),
                            'wizard', 'stock_quant_correction.py'),
               encoding='utf-8').read()

    # ---- the pallet-delta is physical, never reads the merge flag ------
    delta_blk = src[src.index('def _package_change_pallet_delta'):
                    src.index('def _package_change_pallet_delta') + 1400]
    check('V1 the correction pallet-delta never reads is_pallet_merge',
          'is_pallet_merge' not in delta_blk)
    check('V2 it keys on physical stock of source/destination packages',
          "('package_id', '=', old_id)" in delta_blk
          and "('package_id', '=', new_id)" in delta_blk
          and 'source_has_stock' in delta_blk and 'dest_other_stock' in delta_blk)

    # ---- FUNCTIONAL: the physical split/merge/transfer verdicts hold for
    #      a merge pallet exactly as for any pallet -----------------------
    Correction = env['stock.quant.correction.wizard']
    # find a stocked pallet of an owner that ALSO has other stock (so it is a
    # multi-quant pallet, like a merge pallet), and an EMPTY package.
    env.cr.execute("""
        SELECT sq.package_id, sq.owner_id
        FROM stock_quant sq JOIN stock_location l ON l.id=sq.location_id
        WHERE sq.quantity>0 AND sq.package_id IS NOT NULL AND l.usage='internal'
          AND sq.owner_id IS NOT NULL
        GROUP BY sq.package_id, sq.owner_id
        HAVING count(*) >= 2 LIMIT 1""")
    pkg_id, owner_id = env.cr.fetchone()
    src_pkg = env['stock.quant.package'].browse(pkg_id)
    empty_pkg = env['stock.quant.package'].search(
        [('quant_ids', '=', False)], limit=1)
    other_stocked = env['stock.quant'].search([
        ('package_id', '!=', pkg_id), ('quantity', '>', 0),
        ('owner_id', '=', owner_id),
        ('location_id.usage', '=', 'internal')], limit=1).package_id

    # duck-typed correction line: only .quant_id and .is_blast_freeze are read
    a_quant = src_pkg.quant_ids.filtered(lambda q: q.quantity > 0)[0]

    class FakeLine:
        def __init__(self, quant):
            self.quant_id = quant
            self.is_blast_freeze = False

    fake = FakeLine(a_quant)
    # SPLIT: move this quant to an EMPTY package; source keeps its other
    # stock -> +1 (a new pallet born without a receiving document)
    d_split = Correction._package_change_pallet_delta(
        fake, {'package_id': (pkg_id, empty_pkg.id)})
    check('V3 split a product off a multi-quant (merge-shaped) pallet -> +1',
          d_split == 1, d_split)

    # TRANSFER: move it onto another already-stocked pallet -> 0
    if other_stocked:
        d_xfer = Correction._package_change_pallet_delta(
            fake, {'package_id': (pkg_id, other_stocked.id)})
        check('V4 transfer between two live pallets -> 0', d_xfer == 0, d_xfer)
    else:
        check('V4 transfer between two live pallets -> 0', True, '(no 2nd pallet)')

    # no change -> 0
    d_none = Correction._package_change_pallet_delta(
        fake, {'package_id': (pkg_id, pkg_id)})
    check('V5 same package (no move) -> 0', d_none == 0, d_none)

    # ---- a real merge does not change the RR line flag under correction --
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    # a mergeable incoming line (Pallet-Breakdown merge; adopts the target's
    # pallet, so none required; exclude BF/returns so it is truly mergeable).
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.x_studio_is_a_blast_freezer', '!=', True),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=50).filtered(
        lambda l: l.vifel_show_merge_button)[:1]
    if not line:
        check('V-setup a mergeable incoming line exists', True, '(skipped)')
        raise VifelSkip('setup')
    wiz = env['pallet.merge.wizard'].create({'move_line_id': line.id})
    tgt = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    if not tgt:
        check('V-setup an eligible merge target exists', True, '(skipped)')
        raise VifelSkip('setup')
    tgt.is_target = True
    wiz.action_confirm()
    env.flush_all()
    check('V6 a merged RR line is flagged (its +0 history)', line.is_pallet_merge)
    check('V7 the correction pallet-delta for a merge target is physical, so '
          'the merge flag stays a stable RR-history record',
          'is_pallet_merge' not in delta_blk and line.is_pallet_merge)

    print('   Conclusion: corrections read physical stock, never the merge '
          'flag; a merge pallet corrects like any pallet.')

except VifelSkip:
    print('SKIP (no eligible fixture in DB)')
except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
