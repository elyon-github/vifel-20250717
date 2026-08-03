# CR2 v2 Suite AO - the "Start a NEW special pallet" pickers exclude pallets and
# locations already selected on EITHER surface (Pallet Breakdown move lines AND
# sibling Magic Wizard rows).
#
# Reused pallet/location would mix two Pallet Series on one pallet or stack two
# pallets in one bin. The pickers already excluded the real move lines (Pallet
# Breakdown); now they also exclude a sibling Magic Wizard row's picked-but-not-
# yet-confirmed Pallet # / Location. The server check (_check_create_special)
# reads the same computed sets, so it refuses a reuse from either surface.
#
# Rollback-only.
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ao_create_special_excludes_selected.py
import traceback

from odoo.exceptions import UserError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    W = env['pallet.merge.wizard']
    FW = env['stock.move.line.fast_encode_rr']
    Line = env['stock.move.line.fast_encode_rr.line']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 3)[:1]
    lines = picking.move_line_ids.filtered('product_id')
    l_open, l_break = lines[0], lines[1]   # l_open = merge target; l_break = a PB line
    check('AO0 found a 3+ line receipt', len(lines) >= 3, picking.name if picking else None)

    # three empty pallets + three non-aisle bins under the receipt destination
    # (two get "used", one stays free for the isolated-refusal tests)
    empties = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=3)
    nonaisle = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_a_blast_freezer', '!=', True),
        ('x_studio_is_an_aisle', '=', False), ('child_ids', '=', False)], limit=3)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    ok = len(empties) >= 3 and len(nonaisle) >= 3 and bool(sdmg)
    check('AO0b fixtures: 3 empty pallets + 3 non-aisle bins + SDMG type', ok)

    if ok and len(lines) >= 3:
        pkg_break, pkg_sib, pkg_free = empties[0], empties[1], empties[2]
        loc_break, loc_sib, loc_free = nonaisle[0], nonaisle[1], nonaisle[2]

        # (1) Pallet Breakdown: put l_break on pkg_break @ loc_break (real line)
        l_break.with_context(skip_pallet_series_sync=True).write({
            'result_package_id': pkg_break.id, 'location_dest_id': loc_break.id})
        env.flush_all()

        # (2) Magic Wizard session: a sibling row picks pkg_sib @ loc_sib
        fw = FW.create({'transfer_id': picking.id})
        r_open = Line.create({'wizard_id': fw.id, 'stock_move_line': l_open.id,
                              'x_studio_': l_open.x_studio_ or 0,
                              'product_id': l_open.product_id.id})
        r_sib = Line.create({'wizard_id': fw.id, 'stock_move_line': lines[2].id,
                             'x_studio_': lines[2].x_studio_ or 0,
                             'product_id': lines[2].product_id.id,
                             'result_package_id': pkg_sib.id,
                             'location_dest_id': loc_sib.id})
        env.flush_all()

        # open the merge wizard from r_open (from the Magic Wizard)
        wiz = W.create({'move_line_id': l_open.id,
                        'move_line_ids': [(6, 0, [l_open.id])],
                        'from_fast_encode': True,
                        'fast_encode_line_id': r_open.id,
                        'fast_encode_line_ids': [(6, 0, [r_open.id])]})
        env.flush_all()

        used_pkgs = wiz.vifel_receipt_used_package_ids
        used_locs = wiz.vifel_receipt_used_location_ids

        # Pallet Breakdown exclusions (existing behaviour)
        check('AO1 the Pallet Breakdown pallet is excluded', pkg_break in used_pkgs,
              used_pkgs.mapped('name'))
        check('AO2 the Pallet Breakdown non-aisle bin is excluded',
              loc_break in used_locs, used_locs.mapped('complete_name'))
        # Magic Wizard sibling exclusions (the new behaviour)
        check('AO3 the sibling Magic Wizard row PALLET is excluded (the fix)',
              pkg_sib in used_pkgs, used_pkgs.mapped('name'))
        check('AO4 the sibling Magic Wizard row LOCATION is excluded (the fix)',
              loc_sib in used_locs, used_locs.mapped('complete_name'))

        # server backstop: reusing the sibling's pallet is refused
        wiz.write({'mode': 'new', 'psi_type_id': sdmg.id,
                   'new_package_id': pkg_sib.id, 'new_location_id': nonaisle[0].id})
        try:
            wiz._check_create_special()
            check('AO5 server refuses reusing a sibling Magic Wizard pallet', False,
                  'no error')
        except UserError as e:
            check('AO5 server refuses reusing a sibling Magic Wizard pallet',
                  'already used by another line' in str(e), str(e)[:60])
        # ...and reusing the sibling's location is refused (with a FREE pallet, so
        # the location check is what fires, not the pallet check)
        wiz.write({'new_package_id': pkg_free.id, 'new_location_id': loc_sib.id})
        try:
            wiz._check_create_special()
            check('AO6 server refuses reusing a sibling Magic Wizard location',
                  False, 'no error')
        except UserError as e:
            check('AO6 server refuses reusing a sibling Magic Wizard location',
                  'already holds another pallet' in str(e), str(e)[:60])

        # a genuinely free pallet + bin still passes
        wiz.write({'new_package_id': pkg_free.id, 'new_location_id': loc_free.id})
        try:
            wiz._check_create_special()
            check('AO7 a genuinely free pallet + bin still passes validation', True)
        except UserError as e:
            check('AO7 a genuinely free pallet + bin still passes validation',
                  False, str(e)[:80])
    else:
        for n in ('AO1','AO2','AO3','AO4','AO5','AO6','AO7'):
            check(n + ' (setup unavailable)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
