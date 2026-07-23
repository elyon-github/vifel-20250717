# CR2 v2 Suite P - partial withdrawal from a merge pallet, and the header strip.
#
# The Incomplete Package notice ("Detected unselected quants with the same
# pallet") assumes one pallet holds one batch, so leftovers mean the checker
# missed lines. A MERGE pallet holds several receipts' goods by design, so
# taking only some of them is the expected case. Core exposes
# _vifel_package_allows_partial_withdrawal (a no-op there); this module
# answers True for a pinned Fixed Merge Pallet and for any pallet something
# has actually been merged onto.
#
# The ledger needs no change for this: a withdrawal counts a pallet only when
# it leaves it EMPTY, so a partial take is already -0 pallets withdrawn.
#
# Also guards the dialog header, which was a run-on string
# ("Line 1 - 0.000 KG - 0 Quantity - now on 16-042026") and is now a labelled
# strip of independent flex cells.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 #       < ai_context/cr2_shell_tests/suite_p_partial_withdrawal_and_header.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
P,F=[],[]
def check(n,c,d=''):
    (P if c else F).append(n); print(('PASS ' if c else 'FAIL ')+n+('' if c else '  -> %s'%(d,)))
try:
    Q=env['stock.quant']; Partner=env['res.partner']
    owner=Partner.browse(428)
    # a normal (non-merge) pallet must still be protected
    # must be TECHNO FARM's own stock - pinning another client's pallet is
    # refused by the ownership constraint (UAT round 4)
    normal=Q.search([('package_id','!=',False),('quantity','>',0),
                     ('owner_id','=',owner.id),
                     ('x_studio_pallet_series_id','!=',False)],limit=1).package_id
    check('W1 a normal pallet still requires complete selection',
          not Q._vifel_package_allows_partial_withdrawal(normal.id), normal.name)

    # a pinned Fixed Merge Pallet may be withdrawn from partially
    owner.write({'vifel_can_merge_pallets':True,'vifel_multiple_pallet_support':False,
                 'vifel_fixed_package_id':normal.id,'vifel_fixed_psi':'ZZZ-000001'})
    env.flush_all()
    check('W2 a pinned Fixed Merge Pallet allows partial withdrawal',
          Q._vifel_package_allows_partial_withdrawal(normal.id))
    owner.write({'vifel_fixed_package_id':False,'vifel_fixed_psi':False}); env.flush_all()
    check('W3 ... and stops allowing it once un-pinned',
          not Q._vifel_package_allows_partial_withdrawal(normal.id))

    # a pallet something was merged onto allows it
    ml=env['stock.move.line'].search([('result_package_id','!=',False)],limit=1)
    ml.with_context(skip_pallet_series_sync=True).write({'is_pallet_merge':True})
    env.flush_all()
    check('W4 a pallet with merged stock allows partial withdrawal',
          Q._vifel_package_allows_partial_withdrawal(ml.result_package_id.id),
          ml.result_package_id.name)

    # the core hook is a neutral no-op
    import os
    from odoo.modules.module import get_module_path
    src=open(os.path.join(get_module_path('multiple_relocation'),'models','stock_quant.py'),encoding='utf-8').read()
    check('W5 core hook exists and is neutral',
          'def _vifel_package_allows_partial_withdrawal' in src
          and 'is_pallet_merge' not in src)

    # header UI
    W=env['pallet.merge.wizard']
    arch=W.get_view(env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,'form')['arch']
    check('W6 the run-on summary line is gone', 'line_summary' not in arch)
    check('W7 replaced by a labelled strip',
          'line_number' in arch and 'Weight (KG)' in arch and 'Currently on' in arch)
    check('W8 values are their own flex cells (cannot wrap mid-number)',
          'd-flex flex-wrap' in arch)
    check('W9 bold is inline, not fw-bold (this theme remaps it to 500)',
          'font-weight: 700' in arch and 'class="fw-bold' not in arch)
except Exception:
    traceback.print_exc(); F.append('exc')
env.cr.rollback()
print('RESULT: %d passed, %d failed' % (len(P),len(F)))
if F: print('FAILED:',F)
