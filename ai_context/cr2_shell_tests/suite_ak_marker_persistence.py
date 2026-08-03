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

    def merged_pkg(flag='captured'):
        """A fresh empty package carrying ONE merged receiving line."""
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
        return pkg, pick, mv, ml

    # ============ A1: reset/clean must not erase merge identity ============
    pkg, pick, mv, ml = merged_pkg('captured')
    env.flush_all()
    check('AK0 a freshly-merged pallet allows partial withdrawal (baseline)',
          allows(pkg), 'setup sanity')

    # simulate the reset/clean SA: unlink the receiving move line(s)
    ml.unlink()
    env.flush_all()
    check('AK1 after the receiving line is reset/cleaned, the pallet STILL '
          'allows partial withdrawal (durable identity)',
          allows(pkg),
          'TODAY returns %s (identity lost when the marker line is deleted)'
          % allows(pkg))

    env.cr.rollback()

    # ============ A2: a recycled package must NOT false-positive ============
    pkg, pick, mv, ml = merged_pkg('flag')
    env.flush_all()
    check('AK2 the merged pallet allows partial withdrawal (baseline)', allows(pkg))
    # recycle: the pallet is emptied and freed (today: only unreserved)
    env['stock.move.line']._free_pallet_if_unused(pick.id, pkg.id)
    # ...and there is NO current merge stock on it (the line is historical/done-like)
    env.flush_all()
    check('AK3 once emptied/freed and NOT currently a merge pallet, it must NOT '
          'allow partial withdrawal (no recycled-package false positive)',
          not allows(pkg),
          'TODAY returns %s (old marker line still matches the global search)'
          % allows(pkg))

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
