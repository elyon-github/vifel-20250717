# CR2 v2 Suite Y2 - Batch # round-trips through the Magic Wizard.
#
# Batch # is seeded from the real move line into the Magic Wizard row, and on
# Confirm it is written BACK onto the move line (the same path client Lot No.
# takes). Without the write-back, a Batch # typed in the Magic Wizard would be
# silently dropped when the wizard applies.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_y2_batch_magic_wizard.py
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
    owner.write({'vifel_show_batch_no': True})
    env.flush_all()
    Line = env['stock.move.line.fast_encode_rr.line']

    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False)], limit=1)
    check('Y2-0 found a receiving line', bool(ml),
          ml.picking_id.name if ml else None)

    # ---- SEED: the row's create() copies Batch # off the move line -----
    ml.batch_no = 'MW99'
    env.flush_all()
    wizard = env['stock.move.line.fast_encode_rr'].create(
        {'transfer_id': ml.picking_id.id})
    row = Line.create({'wizard_id': wizard.id, 'stock_move_line': ml.id,
                       'x_studio_': ml.x_studio_ or 0,
                       'product_id': ml.product_id.id})
    check('Y2-1 the Magic Wizard row seeds Batch # from the move line',
          row.batch_no == 'MW99', row.batch_no)

    # ---- WRITE-BACK: the Confirm path builds a Batch # onto the line ---
    row.batch_no = 'MW77'
    env.flush_all()
    vals = wizard._vifel_line_write_vals(row)
    check('Y2-2 the Confirm write path carries the edited Batch # '
          '(normal line)', vals.get('batch_no') == 'MW77', vals.get('batch_no'))

    # ---- the merge-locked path also carries Batch # -------------------
    import os
    from odoo.modules.module import get_module_path
    src = open(os.path.join(get_module_path('vifel_client_requirements'),
                            'models', 'fast_encode_merge.py'),
               encoding='utf-8').read()
    check('Y2-3 the merge-locked write path also carries batch_no',
          "'batch_no': line.batch_no or False" in src)
    check('Y2-4 the Magic Wizard list view has a Batch # column',
          'name="batch_no"' in open(os.path.join(
              get_module_path('vifel_client_requirements'),
              'views', 'fast_encode_views.xml'), encoding='utf-8').read())

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
