# CR2 v2 Suite I - wizard simplicity, held to core Odoo conventions.
#
# Checked against Odoo core: ZERO of the 35 stock/mrp/sale wizard views use
# an "alert alert-info" banner, and Return Picking puts its guidance in a
# plain <div class="oe_grey"> shown only when it applies. This suite keeps
# the merge dialog to that standard so it cannot drift back into a wall of
# banners and label/value grids.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_i_ui_simplicity.py
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
    arch = W.get_view(
        env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,
        'form')['arch']

    check('S1 no coloured alert boxes left (core Odoo convention)',
          'alert alert-' not in arch,
          [l.strip() for l in arch.split('\n') if 'alert alert-' in l][:2])
    check('S2 guidance uses oe_grey like core Return Picking',
          'oe_grey' in arch)
    check('S3 the 4-field header group is gone (it wrapped the KG value)',
          'Line being merged' not in arch)
    check('S4 replaced by a single summary line', 'line_summary' in arch)
    check('S5 the candidate table is still the focus',
          'candidate_line_ids' in arch)
    check('S6 ineligible reason column renamed to plain language',
          'Unavailable because' in arch)

    # the summary renders as one line with the numbers that matter
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    wiz = W.create({'move_line_id': ml.id})
    print('   summary renders as: %r' % wiz.line_summary)
    check('S7 summary is a single line (no wrapping possible)',
          '\n' not in (wiz.line_summary or ''))
    check('S8 summary carries KG and Quantity',
          'KG' in wiz.line_summary and 'Quantity' in wiz.line_summary,
          wiz.line_summary)
    check('S9 summary does not repeat the product (already in the title)',
          (ml.product_id.display_name or 'zz') not in wiz.line_summary,
          wiz.line_summary)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
