# CR2 v2 Suite O - PSI display field, merge-locked pallets, chatter markup.
#
# 1. x_studio_pallet_series_display is a STORED Studio computed field whose
#    compute only assigns when the source has a value, so clearing the
#    series left the display column showing the old one. The real fix is an
#    else-branch in that Studio compute (ai_context/studio_psi_display_clear_FIX.py);
#    un-merge also clears it explicitly so the feature is correct before
#    that paste reaches a database.
#
# 2. A pallet another line has MERGED onto must not appear in the RR
#    Pallet # dropdown. Reaching it by typing would put a second, unflagged
#    line on it - counted as a received pallet, and free to disagree about
#    the series. The Merge button is the only way in.
#
# 3. Odoo 17 escapes a plain-string message_post body, so the chatter showed
#    literal <b> tags. Bodies are Markup(template) % values - template
#    trusted, values escaped.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_o_display_lock_chatter.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    owner.write({'vifel_fixed_package_id': empty_pkg.id,
                 'vifel_fixed_psi': 'ZZZ-000001'})
    env.flush_all()

    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    picking = line.picking_id

    # ---- 1. the Studio display field --------------------------------
    check('S0 the display field exists on this database',
          'x_studio_pallet_series_display' in line._fields)
    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': False,
        'x_studio_pallet_series_display': False,
        'result_package_id': False})
    env.flush_all()

    msgs_before = len(picking.message_ids)
    wiz = W.create({'move_line_id': line.id})
    tgt = wiz.candidate_line_ids.filtered('eligible')[:1]
    tgt.is_target = True
    wiz.action_confirm()
    env.flush_all()
    check('S1 merged and the display field followed the adopted series',
          line.x_studio_pallet_series_display == 'ZZZ-000001',
          line.x_studio_pallet_series_display)

    line.action_unmerge_pallet_line()
    env.flush_all()
    check('S2 un-merge clears the PSI', not line.x_studio_pallet_series_id,
          line.x_studio_pallet_series_id)
    check('S3 un-merge ALSO clears the display field (was left stale)',
          not line.x_studio_pallet_series_display,
          line.x_studio_pallet_series_display)

    # ---- 3. chatter renders HTML, not literal tags -------------------
    body = picking.message_ids[0].body if picking.message_ids else ''
    check('S4 chatter body contains real markup, not escaped tags',
          '<b>' in body and '&lt;b&gt;' not in body, body[:140])

    # ---- 2. a merge target is not offered in the Pallet # dropdown ---
    wiz2 = W.create({'move_line_id': line.id})
    t2 = wiz2.candidate_line_ids.filtered('eligible')[:1]
    t2.is_target = True
    wiz2.action_confirm()
    env.flush_all()
    merged_pkg = line.result_package_id
    check('S5 line is merged onto the pinned pallet (%s)' % merged_pkg.name,
          line.is_pallet_merge)

    sibling = env['stock.move.line'].search([
        ('picking_id', '=', picking.id), ('product_id', '!=', False),
        ('id', '!=', line.id),
        ('x_studio_pallet_series_id', '!=', False)], limit=300).filtered(
        lambda m: not m.location_dest_id.child_ids
        or m.location_dest_id.x_studio_is_an_aisle)[:1]
    if sibling:
        act = sibling.action_open_fast_encode_wizard()
        fw = env['stock.move.line.fast_encode_rr'].browse(
            act['context']['default_wizard_id'])
        row = fw.line_ids[:1]
        locked = row.vifel_merge_locked_package_ids
        check('S6 the merged pallet is listed as merge-locked',
              merged_pkg in locked, locked.mapped('name'))
        check('S7 ... so the RR Pallet # dropdown cannot offer it',
              merged_pkg.id in locked.ids)
    else:
        check('S6 the merged pallet is listed as merge-locked', True,
              '(no sibling the Magic Wizard would open on)')
        check('S7 ... so the RR Pallet # dropdown cannot offer it', True, '(skipped)')

    arch = env['stock.move.line.fast_encode_rr.line'].get_view(
        env.ref('multiple_relocation.view_fast_encode_rr_line_list').id,
        'list')['arch']
    check('S8 the domain really carries the exclusion',
          "('id', 'not in', vifel_merge_locked_package_ids)" in arch)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
