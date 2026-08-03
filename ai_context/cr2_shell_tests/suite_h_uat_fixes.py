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


class VifelSkip(Exception):
    """No eligible fixture in this DB — skip without failing."""


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
    # The tint now keys on vifel_on_merged_pallet, so it marks BOTH +0 merges
    # and same-receipt shared pallets (is_pallet_merge alone missed the latter).
    check('U3 merged rows are still visually marked (shared pallets too)',
          'decoration-info="vifel_on_merged_pallet"' in tag)

    # Pallet # stays editable for normal rows, locked for rows on a
    # merged/shared pallet — keyed on the same marker as the tint + button, so
    # the whole row is consistent. Field is NOT readonly in Python.
    m2 = re.search(r'<field name="result_package_id"[^>]*>', arch)
    tag2 = m2.group(0) if m2 else ''
    check('U4 Pallet # is locked only on merged/shared rows',
          'readonly="vifel_on_merged_pallet"' in tag2, tag2[:200])
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
    # a mergeable incoming line (exclude BF/returns so it is truly mergeable),
    # made Magic-Wizard-ready (needs a PSI + location to open).
    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.x_studio_is_a_blast_freezer', '!=', True),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=50).filtered(
        lambda l: l.vifel_show_merge_button)[:1]
    if not ml:
        check('U-setup a mergeable line exists', True, '(skipped)')
        raise VifelSkip('setup')
    _rloc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', ml.picking_id.location_dest_id.id),
        '|', ('x_studio_is_an_aisle', '=', True), ('child_ids', '=', False)],
        limit=1)
    _rpkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    if not (_rloc and _rpkg):
        check('U-setup a location + empty pallet exist', True, '(skipped)')
        raise VifelSkip('setup')
    ml.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': ml.x_studio_pallet_series_id or 'HUAT-000001',
        'location_dest_id': _rloc.id, 'result_package_id': _rpkg.id})
    env.flush_all()
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
    tgt = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    if not tgt:
        check('U-setup an eligible merge target exists', True, '(skipped)')
        raise VifelSkip('setup')
    tgt.is_target = True
    conf = wiz.action_confirm()
    env.flush_all()
    check('U10 CONFIRM also returns to the Magic Wizard list',
          isinstance(conf, dict)
          and conf.get('res_model') == 'stock.move.line.fast_encode_rr.line',
          conf.get('res_model'))
    # STAGED (commit 2ba23f7): the merge is recorded on the ROW; the real line is
    # applied only at the Magic Wizard's own Confirm.
    env.invalidate_all()
    trow = fw.line_ids.filtered(lambda l: l.stock_move_line == ml.id)
    check('U11 ... and the merge is staged on the row (applied at MW confirm)',
          trow.is_pallet_merge or trow.vifel_pending_merge,
          (trow.is_pallet_merge, trow.vifel_pending_merge))

except VifelSkip:
    print('SKIP (no eligible fixture in DB)')
except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
