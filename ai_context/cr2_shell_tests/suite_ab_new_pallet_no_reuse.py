# CR2 v2 Suite AB - a new special pallet cannot reuse a sibling line's pallet
# or (non-aisle) location.
#
# On one receipt, starting a NEW special pallet for line 3 must not offer the
# pallet or bin that line 1 already claimed: reusing the pallet mixes two Pallet
# Series on it; reusing a non-aisle bin stacks two pallets in one spot. Enforced
# in the pickers' domains AND server-side in _apply_create_special.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ab_new_pallet_no_reuse.py
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
    Loc = env['stock.location']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 3)[:1]
    lines = picking.move_line_ids.filtered('product_id')
    l1, l3 = lines[0], lines[2]
    check('AB0 found a 3+ line receipt', bool(l1) and bool(l3), picking.name)

    # a NON-AISLE leaf location under the dest, so the reuse test is meaningful
    non_aisle = Loc.search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_a_blast_freezer', '!=', True),
        ('x_studio_is_an_aisle', '=', False),
        ('child_ids', '=', False),
        ('x_studio_occupied_by_1', '=', False)], limit=1)
    pkg1 = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    check('AB0b fixtures: non-aisle bin + empty pallet + SDMG type',
          bool(non_aisle) and bool(pkg1) and bool(sdmg),
          (non_aisle.complete_name if non_aisle else None))

    # ---- line 1 starts a new special pallet on pkg1 at the non-aisle bin ----
    w1 = W.create({'move_line_id': l1.id, 'mode': 'new'})
    w1.write({'psi_type_id': sdmg.id, 'new_package_id': pkg1.id,
              'new_location_id': non_aisle.id})
    w1.action_confirm()
    env.flush_all()
    check('AB1 line 1 seated on pkg1 @ the non-aisle bin',
          l1.result_package_id == pkg1 and l1.location_dest_id == non_aisle)

    # ---- wizard for line 3: the used pallet/location are known -------------
    w3 = W.create({'move_line_id': l3.id, 'mode': 'new'})
    check('AB2 wizard sees pkg1 as already used by the receipt',
          pkg1 in w3.vifel_receipt_used_package_ids,
          w3.vifel_receipt_used_package_ids.mapped('name'))
    check('AB3 wizard sees the non-aisle bin as already used',
          non_aisle in w3.vifel_receipt_used_location_ids,
          w3.vifel_receipt_used_location_ids.mapped('complete_name'))

    # ---- server guard: reusing pkg1 for line 3 is refused -----------------
    other_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id),
        ('id', '!=', pkg1.id)], limit=1)
    other_loc = Loc.search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_a_blast_freezer', '!=', True),
        ('x_studio_is_an_aisle', '=', False), ('child_ids', '=', False),
        ('x_studio_occupied_by_1', '=', False), ('id', '!=', non_aisle.id)],
        limit=1)
    w3.write({'psi_type_id': sdmg.id, 'new_package_id': pkg1.id,
              'new_location_id': other_loc.id})
    try:
        w3.action_confirm()
        check('AB4 reusing a sibling line\'s PALLET is refused', False,
              'no error')
    except UserError as e:
        check('AB4 reusing a sibling line\'s PALLET is refused',
              'already used by another line' in str(e), str(e)[:100])

    # ---- server guard: reusing the non-aisle bin is refused ---------------
    w3.write({'new_package_id': other_pkg.id, 'new_location_id': non_aisle.id})
    try:
        w3.action_confirm()
        check('AB5 reusing a sibling line\'s non-aisle BIN is refused', False,
              'no error')
    except UserError as e:
        check('AB5 reusing a sibling line\'s non-aisle BIN is refused',
              'already holds another pallet' in str(e), str(e)[:100])

    # ---- a fresh pallet in a fresh bin still works ------------------------
    w3.write({'new_package_id': other_pkg.id, 'new_location_id': other_loc.id})
    w3.action_confirm()
    env.flush_all()
    check('AB6 a fresh pallet + fresh bin still succeeds',
          l3.result_package_id == other_pkg
          and l3.location_dest_id == other_loc,
          (l3.result_package_id.name, l3.location_dest_id.complete_name))

    # ====================================================================
    # "On this receipt" candidates respect the include_regular policy.
    # Reported on M/RR/05309: a Multiple client with include_regular=OFF was
    # offered its sibling lines' ORDINARY receiving pallets as merge targets.
    # Now only SPECIAL-type sibling pallets are offered; regular ones are not.
    # (l1 sits on a fresh SDMG special pallet from AB1; l3 on another SDMG one.)
    # ====================================================================
    owner.write({'vifel_include_regular_pallets': False})
    env.flush_all()
    # a 4th line whose OWN pallet is a REGULAR (client-code) pallet
    l_reg = None
    for l in lines:
        psi = l.x_studio_pallet_series_id or ''
        if l not in (l1, l3) and psi and not psi.startswith('SDMG'):
            l_reg = l
            break
    wf = W.create({'move_line_id': (l_reg or lines[1]).id})
    on_receipt = wf.candidate_line_ids.filtered('on_this_receipt')
    check('AB7 with include_regular OFF, the SDMG special sibling pallet(s) '
          'are still offered',
          any((c.psi or '').startswith('SDMG') for c in on_receipt),
          [(c.package_id.name, c.psi) for c in on_receipt])
    check('AB8 with include_regular OFF, NO regular (non-SDMG) sibling pallet '
          'is offered as an on-this-receipt candidate',
          all((c.psi or '').startswith('SDMG') for c in on_receipt),
          [(c.package_id.name, c.psi) for c in on_receipt])
    # flip include_regular back ON: a regular sibling MAY now be offered
    owner.write({'vifel_include_regular_pallets': True})
    env.flush_all()
    wf2 = W.create({'move_line_id': (l_reg or lines[1]).id})
    check('AB9 with include_regular ON, regular siblings are offered again '
          '(filter is policy-driven, not a blanket ban)',
          len(wf2.candidate_line_ids.filtered('on_this_receipt'))
          >= len(on_receipt),
          (len(wf2.candidate_line_ids.filtered('on_this_receipt')),
           len(on_receipt)))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
