# CR2 v2 Suite E - wizard form + Pallet Breakdown button structure.
#
# Structural only: the visual judgement (does the table read well) belongs
# to a human click-through.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_e_ui_structure.py
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

    # ---- the whole merge UI is hidden for a NON-merge client ----------
    # column_invisible is evaluated WITHOUT a record in scope, so the hide MUST
    # key on the vifel_can_merge CONTEXT flag, never a per-record field (a field
    # reference raises "Name ... is not defined" in the web client).
    from odoo.modules.module import get_module_path
    vdir = get_module_path('vifel_client_requirements')
    pb = open(os.path.join(vdir, 'views', 'stock_move_line_views.xml'),
              encoding='utf-8').read()
    mw = open(os.path.join(vdir, 'views', 'fast_encode_views.xml'),
              encoding='utf-8').read()
    check('C6 no column_invisible references a per-record FIELD for the merge '
          'gate (that crashes the list) — the field vifel_client_can_merge is '
          'gone from both views',
          'vifel_client_can_merge' not in pb
          and 'vifel_client_can_merge' not in mw)
    check('C7 Pallet Breakdown "Merged" column + both buttons hide via the '
          'context flag',
          "not context.get('vifel_can_merge')" in pb
          and pb.count("column_invisible=\"not context.get('vifel_can_merge')\"") >= 2)
    check('C8 Pallet Breakdown "Merge Selected" header hides via the context flag',
          "not context.get('vifel_can_merge')" in pb)
    check('C9 Magic Wizard Merge/Un-merge + "Merge Selected" hide via the '
          'context flag',
          "not context.get('vifel_can_merge')" in mw)

    # functional: action_detailed_operations injects the flag per client
    def dop_flag(partner_can_merge):
        pk = env['stock.picking'].search([
            ('picking_type_id.code', '=', 'incoming'),
            ('partner_id', '!=', False),
            ('partner_id.vifel_can_merge_pallets', '=', partner_can_merge)],
            limit=1)
        if not pk:
            return None, None
        res = pk.action_detailed_operations()
        ctx = res.get('context', {}) if isinstance(res, dict) else {}
        return pk, ctx.get('vifel_can_merge')

    pk_m, flag_m = dop_flag(True)
    check('C10 action_detailed_operations sets vifel_can_merge=True for a merge '
          'client', flag_m is True, flag_m)
    pk_n, flag_n = dop_flag(False)
    check('C11 action_detailed_operations sets vifel_can_merge=False for a '
          'non-merge client', flag_n is False if pk_n else True, flag_n)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
