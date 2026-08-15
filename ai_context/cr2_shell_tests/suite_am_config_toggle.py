# CR2 v2 Suite AM - merge config toggled ON then OFF (or a Fixed pallet un-pinned).
#
#   D1 [reassurance, PASSES today]: a past +0 merge keeps its counting behaviour
#       after the client's merge feature is switched off - counting reads the
#       per-line is_pallet_merge marker, NOT the partner config.
#   D2 [regression, RED today]: a Fixed pallet whose identity came ONLY from the
#       pin (a legacy birth with no is_pallet_merge / vifel_premerge_captured
#       marker) loses partial withdrawal the moment it is un-pinned - even while
#       it still holds its merged stock. Desired: it stays a merge pallet until
#       that stock is withdrawn (durable identity, set while pinned).
#
# Rollback-only.
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_am_config_toggle.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def allows(pkg):
    return env['stock.quant']._vifel_package_allows_partial_withdrawal(pkg.id)


try:
    Q = env['stock.quant']
    owner = env['res.partner'].browse(428)
    itype = env['stock.picking.type'].search([('code', '=', 'incoming')], limit=1)
    prod = env['product.product'].search([('type', '=', 'product')], limit=1)
    src = env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
    dst = env['stock.location'].search([('usage', '=', 'internal')], limit=1)

    def line_on(pkg, flag):
        pick = env['stock.picking'].create({
            'picking_type_id': itype.id, 'partner_id': owner.id,
            'location_id': src.id, 'location_dest_id': dst.id})
        mv = env['stock.move'].create({
            'name': prod.name, 'picking_id': pick.id, 'product_id': prod.id,
            'product_uom': prod.uom_id.id, 'product_uom_qty': 1,
            'location_id': src.id, 'location_dest_id': dst.id})
        ml = env['stock.move.line'].with_context(skip_pallet_series_sync=True).create({
            'picking_id': pick.id, 'move_id': mv.id, 'product_id': prod.id,
            'location_id': src.id, 'location_dest_id': dst.id,
            'result_package_id': pkg.id,
            'is_pallet_merge': (flag == 'flag'),
            'vifel_premerge_captured': (flag == 'captured')})
        return pick, ml

    # ================= D1: counting survives a profile-off =================
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True})
    env.flush_all()
    pkg1 = env['stock.quant.package'].create({})
    pick1, ml1 = line_on(pkg1, 'flag')   # a +0 merge line
    env.flush_all()
    # counting: a +0 merge line originates NO pallet (+0)
    orig_before = pick1._vifel_line_originates_pallet(ml1)
    owner.write({'vifel_can_merge_pallets': False})   # switch the feature OFF
    env.flush_all()
    orig_after = pick1._vifel_line_originates_pallet(ml1)
    check('AM1 [D1] a +0 merge still counts +0 after the merge feature is '
          'switched off (counting keys on the line marker, not the config)',
          orig_before is False and orig_after is False,
          (orig_before, orig_after))

    env.cr.rollback()

    # ============ D2: un-pinning a still-full Fixed pallet ============
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()
    pkg2 = env['stock.quant.package'].create({})
    # a LEGACY birth: placed on the pallet but with NO merge marker at all
    pick2, ml2 = line_on(pkg2, 'none')
    # Pin the Fixed pallet WHILE it is still empty (empty-&-free rule), THEN let
    # it take stock - a Fixed pallet fills via merges after it is pinned.
    fixed_row = env['vifel.fixed.merge.pallet'].create({
        'partner_id': owner.id, 'package_id': pkg2.id, 'psi': 'WMF-000999'})
    env.flush_all()
    # the pallet genuinely HOLDS merged stock (a quant on it)
    env['stock.quant'].with_context(inventory_mode=True).create({
        'product_id': prod.id, 'location_id': dst.id, 'package_id': pkg2.id,
        'owner_id': owner.id, 'quantity': 100.0,
        'x_studio_pallet_series_id': 'WMF-000999'})
    env.flush_all()
    check('AM2 while pinned, the Fixed pallet allows partial withdrawal (baseline)',
          allows(pkg2))
    still_stocked = bool(pkg2.quant_ids.filtered(lambda q: q.quantity > 0))
    check('AM2b the Fixed pallet still holds its merged stock', still_stocked)

    # un-pin the Fixed pallet WHILE it still holds stock -> remove the row
    fixed_row.unlink()
    env.flush_all()
    check('AM3 [D2] a Fixed pallet un-pinned WHILE it still holds its merged '
          'stock stays a merge pallet (partial withdrawal preserved until that '
          'stock is withdrawn)',
          allows(pkg2),
          'TODAY returns %s (identity was pin-only; un-pin dropped it even '
          'though stock remains)' % allows(pkg2))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
print('(AM1 should PASS = reassurance; AM3 RED = D2 bug confirmed, GREEN after Phase 1.)')
if FAIL:
    print('FAILED:', FAIL)
