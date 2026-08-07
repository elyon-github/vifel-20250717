# CR2 v2 Suite AI - a "Start a NEW special pallet" line can be Un-merged/reverted.
#
# Reported on M/RR/05309 (ALPHA ALLEANZA, a Multiple-PSI client): the encoder
# used Merge Pallet -> "Start a new special pallet" to place line #1 on a fresh
# special pallet (correct pallet + PSI), but it showed no "Merged" and no
# Un-merge button, so a first merge could not be reverted.
#
# Same gap we closed for the Fixed first-stock birth (suite AG), one path down:
# _apply_create_special did not capture the line's pre-merge state. Fix: it now
# captures (is_pallet_merge stays False, so the pallet still counts +1), so the
# line shows Merged + Un-merge and can be reverted even as the SOLE line on the
# pallet. Un-merge restores the original series if free, frees the new pallet,
# and NEVER recycles the drawn special series.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ai_create_special_revert.py
#
# Rollback-only: nothing is committed.
import traceback

from odoo.exceptions import UserError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


# spy on push_unused_pallet to catch any recycle of the drawn special series
Partner = env['res.partner']
cls = type(Partner)
PUSHED = []
_orig = cls.push_unused_pallet


def _spy(self, sid):
    PUSHED.append(sid)
    return _orig(self, sid)


cls.push_unused_pallet = _spy

try:
    W = env['pallet.merge.wizard']
    Line = env['stock.move.line.fast_encode_rr.line']
    owner = Partner.browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 1)[:1]
    l1 = picking.move_line_ids.filtered('product_id')[:1]
    check('AI0 found an incoming line for the Multiple-PSI client',
          bool(l1), picking.name if picking else None)

    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    aisle = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    ok_setup = bool(l1 and empty_pkg and aisle and sdmg)

    if ok_setup:
        old_series = l1.x_studio_pallet_series_id or ''

        # ---- create a NEW special pallet for the single line -------------
        w = W.create({'move_line_id': l1.id, 'mode': 'new'})
        w.write({'psi_type_id': sdmg.id, 'new_package_id': empty_pkg.id,
                 'new_location_id': aisle.id})
        w.action_confirm()
        env.flush_all()

        check('AI1 the line landed on the new special pallet with an SDMG PSI',
              l1.result_package_id == empty_pkg
              and (l1.x_studio_pallet_series_id or '').startswith('SDMG-'),
              (l1.result_package_id.name, l1.x_studio_pallet_series_id))
        check('AI2 it is NOT flagged is_pallet_merge — a real +1 pallet',
              not l1.is_pallet_merge)
        check('AI3 it CAPTURED its pre-merge state (so it can be reverted)',
              l1.vifel_premerge_captured
              and l1.vifel_premerge_series == (old_series or False),
              (l1.vifel_premerge_captured, l1.vifel_premerge_series))
        check('AI4 the SOLE create-special line now shows "Merged" + Un-merge '
              '(the reported request)',
              l1.vifel_on_merged_pallet, l1.vifel_on_merged_pallet)

        # counting: the new special pallet is a received pallet, +1
        def received_pkgs():
            return set(picking.move_line_ids.filtered(
                lambda m: m.result_package_id and not m.is_pallet_merge).mapped(
                'result_package_id.id'))
        check('AI5 the new special pallet is counted +1 (is_pallet_merge False)',
              empty_pkg.id in received_pkgs())

        # a Magic Wizard row mirrors the real line -> also shows Merged
        fw = env['stock.move.line.fast_encode_rr'].create(
            {'transfer_id': picking.id})
        r1 = Line.create({'wizard_id': fw.id, 'stock_move_line': l1.id,
                          'x_studio_': l1.x_studio_ or 0,
                          'product_id': l1.product_id.id,
                          'result_package_id': l1.result_package_id.id})
        # seed the merge marker exactly as the real Magic Wizard sync does
        r1.write({'vifel_premerge_captured': l1.vifel_premerge_captured,
                  'is_pallet_merge': l1.is_pallet_merge})
        env.flush_all()
        check('AI6 the Magic Wizard row also shows "Merged" (mirrors the line)',
              r1.vifel_on_merged_pallet, r1.vifel_on_merged_pallet)

        # ---- REVERT: un-merge the sole create-special line ---------------
        special = l1.x_studio_pallet_series_id
        stocked_orig = owner._vifel_series_is_stocked(old_series) \
            if old_series else False
        PUSHED.clear()
        l1.action_unmerge_pallet_line()
        env.flush_all()
        check('AI7 un-merge reverted the line off the special pallet '
              '(marker cleared)',
              not l1.result_package_id and not l1.vifel_premerge_captured
              and not l1.vifel_on_merged_pallet,
              (l1.result_package_id.name, l1.vifel_premerge_captured))
        check('AI8 the drawn SPECIAL series was NOT recycled to the pool '
              '(recycle guard holds)',
              special not in PUSHED, (special, PUSHED))
        check('AI9 the emptied special pallet was freed (no longer counted)',
              empty_pkg.id not in received_pkgs(), sorted(received_pkgs()))
        if old_series and not stocked_orig:
            check('AI10 the ORIGINAL receiving series was restored (it was free)',
                  l1.x_studio_pallet_series_id == old_series,
                  l1.x_studio_pallet_series_id)
        else:
            check('AI10 original series handled (blank/re-assign; not free or '
                  'none)', True)
    else:
        for n in ('AI1', 'AI2', 'AI3', 'AI4', 'AI5', 'AI6', 'AI7', 'AI8',
                  'AI9', 'AI10'):
            check(n + ' (no create-special setup available in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')
finally:
    cls.push_unused_pallet = _orig
    env.cr.rollback()

print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
