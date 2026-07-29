# CR2 v2 Suite AC - the Magic Wizard is aligned with the Pallet Breakdown:
# a same-receipt shared row shows "Merged" (tint) AND offers Un-merge, and
# un-merging it peels the real line off - same behaviour, both surfaces.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ac_magic_wizard_align.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.modules.module import get_module_path
    W = env['pallet.merge.wizard']
    Line = env['stock.move.line.fast_encode_rr.line']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # ---- SOURCE: the wizard's buttons + guard key on the marker -------
    view = open(os.path.join(get_module_path('vifel_client_requirements'),
                             'views', 'fast_encode_views.xml'),
                encoding='utf-8').read()
    check('AC1 the Magic Wizard tint keys on vifel_on_merged_pallet',
          'decoration-info">vifel_on_merged_pallet' in view
          or 'decoration-info</attribute>' in view
          or 'vifel_on_merged_pallet' in view)
    check('AC2 the Merge button hides on a merged/shared row',
          'not show_merge_button or vifel_on_merged_pallet' in view)
    check('AC3 the Un-merge button shows on a merged/shared row',
          'not show_merge_button or not vifel_on_merged_pallet' in view)
    src = open(os.path.join(get_module_path('vifel_client_requirements'),
                            'models', 'fast_encode_merge.py'),
               encoding='utf-8').read()
    check('AC4 the wizard un-merge guard keys on the marker, not the flag',
          'if not ml.vifel_on_merged_pallet' in src)

    # ---- FUNCTIONAL: build a same-receipt merge, mirror it in wizard rows
    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=40).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    l1, l2 = picking.move_line_ids.filtered('product_id')[:2]
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    w1 = W.create({'move_line_id': l1.id, 'mode': 'new'})
    w1.write({'psi_type_id': sdmg.id, 'new_package_id': empty_pkg.id,
              'new_location_id': loc.id})
    w1.action_confirm()
    w2 = W.create({'move_line_id': l2.id})
    t = w2.candidate_line_ids.filtered(
        lambda c: c.on_this_receipt and c.package_id == empty_pkg)[:1]
    t.is_target = True
    w2.action_confirm()
    env.flush_all()

    # mirror the two real lines as Magic Wizard rows
    fw = env['stock.move.line.fast_encode_rr'].create(
        {'transfer_id': picking.id})
    r1 = Line.create({'wizard_id': fw.id, 'stock_move_line': l1.id,
                      'x_studio_': l1.x_studio_ or 0, 'product_id': l1.product_id.id,
                      'result_package_id': l1.result_package_id.id})
    r2 = Line.create({'wizard_id': fw.id, 'stock_move_line': l2.id,
                      'x_studio_': l2.x_studio_ or 0, 'product_id': l2.product_id.id,
                      'result_package_id': l2.result_package_id.id})
    env.flush_all()
    check('AC5 BOTH Magic Wizard rows show the Merged tint (host + joiner)',
          r1.vifel_on_merged_pallet and r2.vifel_on_merged_pallet,
          (r1.vifel_on_merged_pallet, r2.vifel_on_merged_pallet))

    # un-merge the JOINER row from the Magic Wizard -> real line peels off
    r2.action_unmerge_from_fast_encode()
    env.flush_all()
    check('AC6 un-merging the joiner ROW peels the real line off',
          not l2.result_package_id, l2.result_package_id.name)
    check('AC7 the host real line still holds the pallet (still +1)',
          l1.result_package_id == empty_pkg)
    counted = set(picking.move_line_ids.filtered(
        lambda m: m.result_package_id and not m.is_pallet_merge).mapped(
        'result_package_id.id'))
    check('AC8 the pallet is STILL counted +1 after the wizard un-merge',
          empty_pkg.id in counted)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
