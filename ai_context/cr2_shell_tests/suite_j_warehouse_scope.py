# CR2 v2 Suite J - warehouse scoping of the create-new-special pallet.
#
# VIFEL runs two warehouses (Meycauayan, Tagoloan). DB record rule #99
# "Restrict to Assigned Warehouse" hides the OTHER warehouse record from a
# user - but it covers stock.warehouse only. Locations and packages of the
# other warehouse stay fully visible, so an unscoped picker will happily
# seat a pallet in the wrong building. These checks prove the pickers are
# scoped AND that the server-side guard refuses a cross-warehouse pick,
# because a domain is UI-only.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_j_warehouse_scope.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.exceptions import UserError
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # DB record rule #99 "Restrict to Assigned Warehouse" hides other
    # warehouses from a normal search; sudo() sees the real picture. That rule
    # covers stock.warehouse ONLY - locations and packages of the other
    # warehouse ARE visible, which is exactly why these domains are needed.
    whs = env['stock.warehouse'].sudo().search([])
    print('warehouses (sudo): %s' % whs.mapped('name'))
    check('W0 more than one warehouse exists (scoping is not theoretical)',
          len(whs) > 1, len(whs))

    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    wiz = W.create({'move_line_id': ml.id})
    wh = wiz.warehouse_id
    print('receipt %s -> warehouse %s' % (ml.picking_id.name, wh.name))
    check('W1 wizard knows the receipt warehouse', bool(wh), wh)

    # ---- the domains actually exclude the other warehouse --------------
    other = whs - wh
    print('other warehouse: %s' % other.mapped('name'))
    loc_dom = [('usage', '=', 'internal'), ('warehouse_id', '=', wh.id),
               ('x_studio_is_a_blast_freezer', '!=', True)]
    mine = env['stock.location'].search_count(loc_dom)
    theirs = env['stock.location'].search_count(
        [('usage', '=', 'internal'), ('warehouse_id', 'in', other.ids)])
    check('W2 location domain keeps only this warehouse (%d here, %d excluded)'
          % (mine, theirs), mine > 0 and theirs > 0, (mine, theirs))

    pkg_dom = [('location_id', '=', False),
               ('package_type_id.name', '=', 'Pallet'),
               ('x_studio_active', '=', True),
               ('x_studio_warehouse', '=', wh.id)]
    pmine = env['stock.quant.package'].search_count(pkg_dom)
    ptheirs = env['stock.quant.package'].search_count(
        [('location_id', '=', False), ('x_studio_warehouse', 'in', other.ids)])
    check('W3 pallet domain keeps only this warehouse (%d here, %d excluded)'
          % (pmine, ptheirs), pmine > 0, (pmine, ptheirs))

    # ---- server-side guard rejects a cross-warehouse pick -------------
    foreign_loc = env['stock.location'].search([
        ('usage', '=', 'internal'), ('warehouse_id', 'in', other.ids)], limit=1)
    good_pkg = env['stock.quant.package'].search(pkg_dom, limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    wiz.write({'mode': 'new', 'psi_type_id': sdmg.id,
               'new_package_id': good_pkg.id,
               'new_location_id': foreign_loc.id})
    try:
        wiz.action_confirm()
        check('W4 cross-warehouse LOCATION is refused server-side', False,
              'no error raised')
    except UserError as e:
        check('W4 cross-warehouse LOCATION is refused server-side',
              'belongs to' in str(e), str(e)[:110])

    foreign_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('x_studio_warehouse', 'in', other.ids)], limit=1)
    good_loc = env['stock.location'].search(
        loc_dom + [('x_studio_is_an_aisle', '=', True)], limit=1) \
        or env['stock.location'].search(loc_dom, limit=1)
    if foreign_pkg:
        wiz.write({'new_package_id': foreign_pkg.id,
                   'new_location_id': good_loc.id})
        try:
            wiz.action_confirm()
            check('W5 cross-warehouse PALLET is refused server-side', False,
                  'no error raised')
        except UserError as e:
            check('W5 cross-warehouse PALLET is refused server-side',
                  'belongs to' in str(e), str(e)[:110])
    else:
        check('W5 cross-warehouse PALLET is refused server-side', True,
              '(no empty pallet tagged to the other warehouse)')

    # ---- a same-warehouse pick still works ---------------------------
    wiz.write({'new_package_id': good_pkg.id, 'new_location_id': good_loc.id})
    wiz.action_confirm()
    env.flush_all()
    check('W6 same-warehouse pick still succeeds',
          (ml.x_studio_pallet_series_id or '').startswith('SDMG-')
          and ml.result_package_id == good_pkg,
          (ml.x_studio_pallet_series_id, ml.result_package_id.name))
    check('W7 ... and it landed in the receipt warehouse',
          ml.location_dest_id.warehouse_id == wh,
          ml.location_dest_id.warehouse_id.name)

    # ---- merge candidates were already scoped ------------------------
    wiz2 = W.create({'move_line_id': ml.id})
    bad = wiz2.candidate_line_ids.filtered(
        lambda c: c.location_id and c.location_id.warehouse_id != wh)
    check('W8 merge candidates stay inside the receipt warehouse',
          not bad, bad.mapped('location_id.complete_name')[:3])

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
