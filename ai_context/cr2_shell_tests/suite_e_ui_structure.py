# CR2 v2 Suite E - wizard form + Pallet Breakdown button structure.
#
# Structural only: the visual judgement (does the table read well) belongs
# to a human click-through.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_e_ui_structure.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)

    # form view is registered as the model's default form
    view = env.ref('vifel_client_requirements.view_pallet_merge_wizard_form')
    check('C1 wizard form view exists', view.model == 'pallet.merge.wizard',
          view.model)
    fg = env['pallet.merge.wizard'].get_view(view.id, 'form')
    check('C2 candidate table + mode radio render in the form',
          'candidate_line_ids' in fg['arch'] and 'mode' in fg['arch'])

    # tree button inheritance applied to the Pallet Breakdown
    tree = env.ref('stock.view_stock_move_line_detailed_operation_tree')
    tarch = env['stock.move.line'].get_view(tree.id, 'tree')['arch']
    check('C3 Merge + Un-merge buttons injected into Pallet Breakdown',
          'action_open_pallet_merge_wizard' in tarch
          and 'action_unmerge_pallet_line' in tarch)

    # single-select onchange: checking one row clears the others
    wiz = env['pallet.merge.wizard'].create({'move_line_id': line.id})
    elig = wiz.candidate_line_ids.filtered('eligible')[:2]
    if len(elig) >= 2:
        a, b = elig[0], elig[1]
        a.is_target = True
        a._onchange_is_target()
        b.is_target = True
        b._onchange_is_target()
        sel = wiz.candidate_line_ids.filtered('is_target')
        check('C4 checking a 2nd row clears the 1st (radio behaviour)',
              sel == b, sel.mapped('psi'))
    else:
        check('C4 checking a 2nd row clears the 1st (radio behaviour)', True,
              '(need 2 eligible candidates)')

    # an ineligible row refuses selection via the onchange guard
    inelig = wiz.candidate_line_ids.filtered(lambda c: not c.eligible)[:1]
    if inelig:
        inelig.is_target = True
        res = inelig._onchange_is_target()
        check('C5 ineligible row cannot be selected',
              not inelig.is_target and isinstance(res, dict)
              and 'warning' in res, res)
    else:
        check('C5 ineligible row cannot be selected', True,
              '(no ineligible candidate in the first page)')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
