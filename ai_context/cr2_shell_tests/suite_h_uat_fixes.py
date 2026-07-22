# CR2 v2 Suite H - regressions found in UAT (2026-07-22).
#
# 1. A view-level readonly= modifier OVERRIDES a Python-level readonly field.
#    Adding readonly="is_pallet_merge" to pallet_series_id silently made PSI
#    EDITABLE on every non-merged row in the Magic Wizard. PSI is identity and
#    system-managed - it must never become typeable. Guarded by U1-U3.
#
# 2. Opening the merge dialog REPLACES the Magic Wizard behind it (Odoo swaps
#    dialogs on a target=new action), so every exit path - Confirm AND Back -
#    must return to the list, or the encoding session is lost. U6-U11.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_h_uat_fixes.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Line = env['stock.move.line.fast_encode_rr.line']

    # ---- (1) PSI readonly, both at field level and in the arch --------
    fld = Line._fields['pallet_series_id']
    check('U1 pallet_series_id is readonly at the Python level',
          bool(fld.readonly), fld.readonly)

    view = env.ref('multiple_relocation.view_fast_encode_rr_line_list')
    arch = Line.get_view(view.id, 'list')['arch']
    import re
    m = re.search(r'<field name="pallet_series_id"[^>]*>', arch)
    tag = m.group(0) if m else ''
    check('U2 the arch does NOT override PSI readonly (would unlock it)',
          'readonly=' not in tag, tag[:200])
    check('U3 merged rows are still visually marked',
          'decoration-info="is_pallet_merge"' in tag)

    # Pallet # stays editable for normal rows, locked for merged ones —
    # that field is NOT readonly in Python, so the modifier is correct there.
    m2 = re.search(r'<field name="result_package_id"[^>]*>', arch)
    tag2 = m2.group(0) if m2 else ''
    check('U4 Pallet # is locked only on merged rows',
          'readonly="is_pallet_merge"' in tag2, tag2[:200])
    check('U5 Location stays readonly (pre-existing, derived not typed)',
          'readonly="1"' in (re.search(
              r'<field name="location_dest_id"[^>]*>', arch) or
              re.match('', '')).group(0))

    # ---- (2) every exit path returns to the Magic Wizard --------------
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('result_package_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=1)
    act = ml.action_open_fast_encode_wizard()
    fw = env['stock.move.line.fast_encode_rr'].browse(
        act['context']['default_wizard_id'])
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == ml.id)

    open_act = tline.action_merge_from_fast_encode()
    wiz = env['pallet.merge.wizard'].browse(open_act['res_id'])
    check('U6 wizard remembers which Magic Wizard row opened it',
          wiz.fast_encode_line_id == tline.id, wiz.fast_encode_line_id)

    back = wiz.action_back_to_fast_encode()
    check('U7 BACK returns to the Magic Wizard list (no dead end)',
          isinstance(back, dict)
          and back.get('res_model') == 'stock.move.line.fast_encode_rr.line'
          and back.get('domain') == [('wizard_id', '=', fw.id)],
          back.get('res_model'))
    check('U8 back did NOT merge anything', not ml.is_pallet_merge)

    # and the form shows Back instead of Cancel in that mode
    warch = env['pallet.merge.wizard'].get_view(
        env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,
        'form')['arch']
    check('U9 the dialog offers Back to Magic Wizard',
          'action_back_to_fast_encode' in warch
          and 'invisible="not from_fast_encode"' in warch)

    # confirm path still returns to the list too
    tgt = wiz.candidate_line_ids.filtered('eligible')[:1]
    tgt.is_target = True
    conf = wiz.action_confirm()
    env.flush_all()
    check('U10 CONFIRM also returns to the Magic Wizard list',
          isinstance(conf, dict)
          and conf.get('res_model') == 'stock.move.line.fast_encode_rr.line',
          conf.get('res_model'))
    check('U11 ... and the merge actually applied', ml.is_pallet_merge)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
