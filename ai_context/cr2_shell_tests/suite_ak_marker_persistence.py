# CR2 v2 Suite AK - a pallet's MERGE IDENTITY must be durable.
#
# The merge identity is currently INFERRED from markers on historical
# stock.move.line records. That evidence is fragile:
#   A1 - reset/clean SAs unlink() a receipt's move lines, so a genuine merge
#        pallet silently reverts to ordinary (partial withdrawal blocked again).
#   A2 - a package is never deleted, only unreserved; the predicate searches
#        move lines GLOBALLY by package (no state/owner scope), so a recycled
#        package re-received as a PLAIN pallet still matches its old merged
#        done-lines -> wrongly allows partial withdrawal (false positive).
#
# These checks assert the DESIRED (durable-identity) behaviour, so they are RED
# today (documenting the bug) and GREEN once Phase 1 persists the identity on
# the package. Rollback-only.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ak_marker_persistence.py
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

    # a throwaway incoming picking + move so we can attach synthetic move lines
    # (a merge marker on a line pointing at the package is all the predicate reads)
    itype = env['stock.picking.type'].search([('code', '=', 'incoming')], limit=1)
    prod = env['product.product'].search([('type', '=', 'product')], limit=1)
    src = env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
    dst = env['stock.location'].search([('usage', '=', 'internal')], limit=1)

    def merged_pkg(flag='captured', with_stock=True):
        """A fresh package carrying ONE merged receiving line, optionally holding
        stock (a quant) so it is a real, currently-merged pallet."""
        pkg = env['stock.quant.package'].create({})
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
        if with_stock:
            env['stock.quant'].with_context(inventory_mode=True).create({
                'product_id': prod.id, 'location_id': dst.id, 'package_id': pkg.id,
                'owner_id': owner.id, 'quantity': 100.0})
        return pkg, pick, mv, ml

    # ============ A1: reset/clean must not erase merge identity ============
    # A pallet that HOLDS its merged stock stays a merge pallet even if the
    # receiving line that recorded the merge is deleted (reset/clean SA).
    pkg, pick, mv, ml = merged_pkg('captured', with_stock=True)
    env.flush_all()
    check('AK0 a freshly-merged pallet (holding stock) allows partial '
          'withdrawal (baseline)', allows(pkg), 'setup sanity')

    # simulate the reset/clean SA: unlink the receiving move line(s)
    ml.unlink()
    env.flush_all()
    check('AK1 after the receiving line is reset/cleaned, the pallet STILL '
          'allows partial withdrawal (durable identity survives line deletion)',
          allows(pkg),
          'returns %s' % allows(pkg))

    env.cr.rollback()

    # ============ A2: an emptied/recycled package must NOT false-positive =====
    # A pallet once merged onto, now EMPTIED (its goods withdrawn), must not
    # allow partial withdrawal - even though the durable flag is still set.
    pkg, pick, mv, ml = merged_pkg('flag', with_stock=True)
    env.flush_all()
    check('AK2 the merged pallet (holding stock) allows partial withdrawal '
          '(baseline)', allows(pkg))
    # empty it: withdraw all its stock (quantity -> 0)
    pkg.quant_ids.filtered(lambda q: q.quantity > 0).write({'quantity': 0.0})
    env.flush_all()
    check('AK3 once EMPTIED it must NOT allow partial withdrawal (no recycled/'
          'empty-package false positive), even with the flag still set',
          not allows(pkg),
          'flag=%s holds_stock=%s -> allows=%s'
          % (pkg.vifel_is_merge_pallet, pkg.vifel_holds_stock(), allows(pkg)))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
print('(RED here = bug confirmed; these go GREEN after Phase 1.)')
if FAIL:
    print('FAILED:', FAIL)
