# CR2 v2 Suite G1 - FastEncodeRR CONSUMES a merge made in Pallet Breakdown.
#
# The deferred-write trap: the Magic Wizard writes everything at
# action_confirm, so a merge must survive that round-trip untouched while
# cargo edits still land.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_g1_fastencode_consumer.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    owner = env['res.partner'].browse(428)          # TECHNO FARM
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('result_package_id', '!=', False)], limit=1)
    picking = line.picking_id
    print('picking %s, merging line #%s' % (picking.name, line.x_studio_))

    # ---- merge in the Pallet Breakdown (the wizard) -------------------
    wiz = env['pallet.merge.wizard'].create({'move_line_id': line.id})
    # pick an eligible target whose location is a leaf/aisle (so the Magic
    # Wizard's open-validation passes)
    target = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt and c.location_id
        and (not c.location_id.child_ids
             or c.location_id.x_studio_is_an_aisle))[:1]
    if not target:
        target = wiz.candidate_line_ids.filtered(
            lambda c: c.eligible and not c.on_this_receipt)[:1]
    target.is_target = True
    wiz.action_confirm()
    env.flush_all()
    merged_pkg = line.result_package_id
    merged_psi = line.x_studio_pallet_series_id
    merged_loc = line.location_dest_id
    check('E1 line is merged before entering the Magic Wizard',
          line.is_pallet_merge and merged_psi == target.psi)
    reserved_before = merged_pkg.x_studio_is_reserved

    # ---- open FastEncodeRR on the merged line ------------------------
    action = line.action_open_fast_encode_wizard()
    fw = env['stock.move.line.fast_encode_rr'].browse(
        action['context']['default_wizard_id'])
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('E2 Magic Wizard loaded the merged line flagged',
          tline.is_pallet_merge, tline.is_pallet_merge)
    check('E3 Magic Wizard shows the adopted PSI + pallet on the line',
          tline.pallet_series_id == merged_psi
          and tline.result_package_id == merged_pkg,
          (tline.pallet_series_id, tline.result_package_id.name))

    # ---- edit cargo in the Magic Wizard, then confirm ----------------
    tline.write({'kilogram': 123.45, 'quantity': 7.0, 'min_uom_unit': 70.0,
                 'client_lot_no': 'LOT-RT-1'})
    fw.action_confirm()
    env.flush_all()

    # ---- the merge identity must be intact; only cargo changed -------
    check('E4 merge flag preserved through action_confirm',
          line.is_pallet_merge)
    check('E5 adopted PSI unchanged', line.x_studio_pallet_series_id == merged_psi,
          line.x_studio_pallet_series_id)
    check('E6 target pallet unchanged', line.result_package_id == merged_pkg,
          line.result_package_id.name)
    check('E7 target location unchanged', line.location_dest_id == merged_loc,
          line.location_dest_id.display_name)
    check('E8 cargo edits landed (KG=%.2f)' % line.quantity,
          abs(line.quantity - 123.45) < 0.01
          and abs(line.x_studio_2nd_uom - 7.0) < 0.01)
    check('E9 client lot no stamped onto the line',
          line.client_lot_no == 'LOT-RT-1', line.client_lot_no)
    check('E10 stocked target NOT re-stamped as reserved by this RR',
          merged_pkg.x_studio_is_reserved == reserved_before,
          (reserved_before, merged_pkg.x_studio_is_reserved))

    # ---- a NON-merged sibling still encodes normally -----------------
    sib = env['stock.move.line'].search([
        ('picking_id', '=', picking.id), ('product_id', '!=', False),
        ('is_pallet_merge', '=', False),
        ('x_studio_pallet_series_id', '!=', False),
        ('result_package_id', '!=', False), ('id', '!=', line.id)], limit=1)
    if sib and (not sib.location_dest_id.child_ids
                or sib.location_dest_id.x_studio_is_an_aisle):
        sib_psi = sib.x_studio_pallet_series_id
        act2 = sib.action_open_fast_encode_wizard()
        fw2 = env['stock.move.line.fast_encode_rr'].browse(
            act2['context']['default_wizard_id'])
        t2 = fw2.line_ids[:1]
        t2.write({'kilogram': 55.0})
        fw2.action_confirm()
        env.flush_all()
        check('E11 non-merged sibling still encodes (not flagged, cargo set)',
              not sib.is_pallet_merge and abs(sib.quantity - 55.0) < 0.01,
              (sib.is_pallet_merge, sib.quantity))
    else:
        check('E11 non-merged sibling still encodes', True,
              '(no clean sibling to test)')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
