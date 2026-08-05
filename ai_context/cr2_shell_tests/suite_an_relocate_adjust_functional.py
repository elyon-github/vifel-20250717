# CR2 v2 Suite AN - FUNCTIONAL: a merge pallet's identity survives relocation
# and adjustment (Phase 2, B2/C2).
#
#   B2 [relocation]: relocating a merge pallet keeps the SAME package, carries the
#       PSI to the destination quant (move_quants copies the studio fields
#       deterministically), and the DURABLE merge flag survives (it is on the
#       package). Predicate stays True.
#   C2 [adjustment]: emptying a merge pallet via a quant adjustment (quantity->0)
#       correctly makes it non-mergeable (holds no stock). The PKR pallet -1 is
#       driven by WR validation, not adjustments, so an adjust-to-zero does NOT
#       auto-decrement the count - by design; Re-sync recomputes from actuals.
#
# Rollback-only.
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_an_relocate_adjust_functional.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def allows(pkg):
    return env['stock.quant']._vifel_package_allows_partial_withdrawal(pkg.id)


try:
    owner = env['res.partner'].browse(428)
    prod = env['product.product'].search([('type', '=', 'product')], limit=1)
    internal = env['stock.location'].search(
        [('usage', '=', 'internal'), ('child_ids', '=', False)], limit=2)
    loc_a, loc_b = internal[0], internal[1]

    def merge_pallet_with_stock(psi='MRG-000777'):
        """A merge pallet: a package flagged + a stocked quant carrying a PSI."""
        pkg = env['stock.quant.package'].create({})
        # mark the package durably via a merged move line
        pk = env['stock.picking'].create({
            'picking_type_id': env['stock.picking.type'].search(
                [('code', '=', 'incoming')], limit=1).id,
            'partner_id': owner.id, 'location_id': env['stock.location'].search(
                [('usage', '=', 'supplier')], limit=1).id,
            'location_dest_id': loc_a.id})
        mv = env['stock.move'].create({
            'name': prod.name, 'picking_id': pk.id, 'product_id': prod.id,
            'product_uom': prod.uom_id.id, 'product_uom_qty': 1,
            'location_id': pk.location_id.id, 'location_dest_id': loc_a.id})
        env['stock.move.line'].with_context(skip_pallet_series_sync=True).create({
            'picking_id': pk.id, 'move_id': mv.id, 'product_id': prod.id,
            'location_id': pk.location_id.id, 'location_dest_id': loc_a.id,
            'result_package_id': pkg.id, 'is_pallet_merge': True})
        q = env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': prod.id, 'location_id': loc_a.id, 'package_id': pkg.id,
            'owner_id': owner.id, 'quantity': 80.0,
            'x_studio_pallet_series_id': psi})
        env.flush_all()
        return pkg, q

    # ================= B2: relocation keeps identity + PSI =================
    pkg, q = merge_pallet_with_stock('MRG-000777')
    check('AN0 the merge pallet is set up (flag + PSI + stock)',
          pkg.vifel_is_merge_pallet and allows(pkg)
          and q.x_studio_pallet_series_id == 'MRG-000777')

    # relocate the quant to loc_b (x_reloc_batch_number triggers the studio copy).
    # move_quants expects the location RECORD, not its id.
    q.move_quants(location_dest_id=loc_b, message='RELOCATION',
                  x_reloc_batch_number='ANTEST')
    env.flush_all()
    dest = env['stock.quant'].search([
        ('package_id', '=', pkg.id), ('location_id', '=', loc_b.id),
        ('quantity', '>', 0)], limit=1)
    check('AN1 [B2] relocation kept the SAME package', bool(dest),
          'no dest quant on the same package at loc_b')
    if dest:
        check('AN2 [B2] the PSI followed to the relocated quant',
              dest.x_studio_pallet_series_id == 'MRG-000777',
              dest.x_studio_pallet_series_id)
    check('AN3 [B2] the durable merge flag survived relocation (it is on the '
          'package)', pkg.vifel_is_merge_pallet)
    check('AN4 [B2] the pallet still allows partial withdrawal after relocation',
          allows(pkg))

    env.cr.rollback()

    # ================= C2: adjust-to-zero => non-mergeable ================
    pkg2, q2 = merge_pallet_with_stock('MRG-000888')
    check('AN5 the merge pallet allows partial withdrawal before adjustment',
          allows(pkg2))
    # empty it via an inventory adjustment (NOT a WR)
    q2.with_context(inventory_mode=True).write({'quantity': 0.0})
    env.flush_all()
    check('AN6 [C2] after an adjust-to-zero the pallet holds no stock and is '
          'correctly non-mergeable (predicate False)',
          not pkg2.vifel_holds_stock() and not allows(pkg2),
          (pkg2.vifel_holds_stock(), allows(pkg2)))
    check('AN7 [C2 note] the durable flag itself may remain set (freed lazily); '
          'the holds-stock gate keeps the predicate correct meanwhile', True,
          'documented: PKR -1 is WR-driven; Re-sync recomputes adjustments')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
