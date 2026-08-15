# CR2 v2 Suite AR - receipt-local recycle of voided special pallet series.
#
# When a create-special line is un-merged (last holder), its drawn special series
# is saved to the receipt's voided list instead of being lost; a later
# create-special of the same type on the SAME receipt recycles the LOWEST voided
# series (removing it). A +0 merge or a series still held by a sibling never
# voids; a non-special series is ignored; a concurrent receipt never sees the list.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ar_voided_special_recycle.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def series_on(pick):
    return pick.vifel_voided_special_psi_ids.mapped('series')


try:
    Partner = env['res.partner']
    owner = Partner.search([('vifel_multiple_pallet_support', '=', True),
                            ('vifel_psi_type_ids', '!=', False)], limit=1)
    if not owner:
        owner = Partner.search([('x_studio_client_unique_code_1', '!=', False)],
                               limit=1)
        owner.write({'vifel_can_merge_pallets': True,
                     'vifel_multiple_pallet_support': True})
        env.flush_all()
    ptype = owner.vifel_psi_type_ids[:1]
    check('AR0 Multiple client with a PSI type (%s / %s)'
          % (owner.display_name, ptype.prefix), bool(ptype))

    itype = env['stock.picking.type'].search([('code', '=', 'incoming')], limit=1)
    prod = env['product.product'].search([('type', '=', 'product')], limit=1)
    src = env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
    dst = env['stock.location'].search([('usage', '=', 'internal')], limit=1)

    def mk_picking(n_lines=1):
        pick = env['stock.picking'].create({
            'picking_type_id': itype.id, 'partner_id': owner.id,
            'location_id': src.id, 'location_dest_id': dst.id})
        mls = env['stock.move.line']
        for _i in range(n_lines):
            mv = env['stock.move'].create({
                'name': prod.name, 'picking_id': pick.id, 'product_id': prod.id,
                'product_uom': prod.uom_id.id, 'product_uom_qty': 1,
                'location_id': src.id, 'location_dest_id': dst.id})
            mls |= env['stock.move.line'].with_context(
                skip_pallet_series_sync=True).create({
                    'picking_id': pick.id, 'move_id': mv.id, 'product_id': prod.id,
                    'location_id': src.id, 'location_dest_id': dst.id})
        return pick, mls

    def as_create_special(ml, pkg, series, merge=False):
        ml.with_context(skip_pallet_series_sync=True).write({
            'result_package_id': pkg.id, 'x_studio_pallet_series_id': series,
            'location_dest_id': dst.id, 'is_pallet_merge': merge,
            'vifel_premerge_captured': True, 'vifel_premerge_series': False})

    # ---- helper level: void + pull ------------------------------------
    pick0, mls0 = mk_picking(1)
    s1 = ptype._format(900001)
    pick0._vifel_void_special_series(s1)
    env.flush_all()
    check('AR1 void stores a special-type series', series_on(pick0) == [s1])
    pick0._vifel_void_special_series(s1)
    check('AR1b void is idempotent per (picking, series)',
          len(pick0.vifel_voided_special_psi_ids) == 1)
    pick0._vifel_void_special_series('ZZZ-999999')
    check('AR1c a non-special series is NOT voided',
          len(pick0.vifel_voided_special_psi_ids) == 1)
    s0 = ptype._format(900000)
    pick0._vifel_void_special_series(s0)
    env.flush_all()
    check('AR2 pull returns the LOWEST voided series',
          pick0._vifel_pull_voided_special(ptype) == s0)
    check('AR2b pull removed it; the higher one remains', series_on(pick0) == [s1])
    check('AR2c pull returns None once the type has none left',
          pick0._vifel_pull_voided_special(ptype) == s1
          and pick0._vifel_pull_voided_special(ptype) is None)

    # ---- functional: un-merge of a create-special voids ---------------
    pick1, mls1 = mk_picking(1)
    series1 = ptype.draw_number()
    as_create_special(mls1, env['stock.quant.package'].create({}), series1)
    env.flush_all()
    mls1.action_unmerge_pallet_line()
    env.flush_all()
    check('AR3 un-merging a create-special line VOIDS its series (%s)' % series1,
          series1 in series_on(pick1), series_on(pick1))

    # ---- a +0 merge line un-merged does NOT void ----------------------
    pick2, mls2 = mk_picking(1)
    series2 = ptype.draw_number()
    as_create_special(mls2, env['stock.quant.package'].create({}), series2,
                      merge=True)
    env.flush_all()
    mls2.action_unmerge_pallet_line()
    env.flush_all()
    check('AR4 a +0 merge (is_pallet_merge) un-merged does NOT void',
          series2 not in series_on(pick2))

    # ---- a sibling still holding the series -> no void until the last -
    pick3, mls3 = mk_picking(2)
    m3a, m3b = mls3
    series3 = ptype.draw_number()
    pkg3 = env['stock.quant.package'].create({})
    as_create_special(m3a, pkg3, series3)
    as_create_special(m3b, pkg3, series3)
    env.flush_all()
    m3a.action_unmerge_pallet_line()
    env.flush_all()
    check('AR5 no void while a sibling still holds the series',
          series3 not in series_on(pick3))
    m3b.action_unmerge_pallet_line()
    env.flush_all()
    check('AR5b voided once the LAST holder is peeled off',
          series3 in series_on(pick3))

    # ---- recycle: a same-receipt create-special draw pulls voided -----
    check('AR6 create-special on the SAME receipt recycles the voided series',
          pick1._vifel_pull_voided_special(ptype) == series1)

    # ---- scope: a concurrent receipt does not see the list ------------
    pick4, _mls4 = mk_picking(1)
    check('AR7 a different receipt has an empty voided list (per-picking scope)',
          pick4._vifel_pull_voided_special(ptype) is None)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
