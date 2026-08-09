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

    # a pinned Fixed Merge Pallet may be withdrawn from partially. Under the
    # empty-&-free rule it is pinned WHILE EMPTY then takes stock, so pin a fresh
    # empty pallet and give it a quant.
    owner.write({'vifel_can_merge_pallets':True,'vifel_multiple_pallet_support':False})
    env.flush_all()
    prod0=env['product.product'].search([('type','=','product')],limit=1)
    dst0=env['stock.location'].search([('usage','=','internal')],limit=1)
    fixpkg=env['stock.quant.package'].create({})
    fixed_row=env['vifel.fixed.merge.pallet'].create({
        'partner_id':owner.id,'package_id':fixpkg.id,'psi':'ZZZ-000001'})
    env.flush_all()
    env['stock.quant'].with_context(inventory_mode=True).create({
        'product_id':prod0.id,'location_id':dst0.id,'package_id':fixpkg.id,
        'owner_id':owner.id,'quantity':100.0,'x_studio_pallet_series_id':'ZZZ-000001'})
    env.flush_all()
    check('W2 a pinned Fixed Merge Pallet allows partial withdrawal',
          Q._vifel_package_allows_partial_withdrawal(fixpkg.id))
    # DURABLE IDENTITY: un-pinning (removing the row) a Fixed pallet that STILL
    # HOLDS its merged stock KEEPS partial withdrawal (freed only once emptied).
    fixed_row.unlink(); env.flush_all()
    check('W3 un-pinned while still holding stock, it KEEPS partial withdrawal '
          '(durable; freed only once emptied)',
          Q._vifel_package_allows_partial_withdrawal(fixpkg.id))
    # empty it -> now it stops
    fixpkg.quant_ids.filtered(lambda q: q.quantity>0).write({'quantity':0.0})
    env.flush_all()
    check('W3b ... and stops once the pallet is emptied (fully withdrawn)',
          not Q._vifel_package_allows_partial_withdrawal(fixpkg.id))

    # helper: a fresh package holding stock, marked via a move line
    prod=env['product.product'].search([('type','=','product')],limit=1)
    dst=env['stock.location'].search([('usage','=','internal')],limit=1)
    src=env['stock.location'].search([('usage','=','supplier')],limit=1)
    itype=env['stock.picking.type'].search([('code','=','incoming')],limit=1)
    def marked_pkg_with_stock(flagkey):
        pkg=env['stock.quant.package'].create({})
        pk=env['stock.picking'].create({'picking_type_id':itype.id,'partner_id':owner.id,
            'location_id':src.id,'location_dest_id':dst.id})
        mv=env['stock.move'].create({'name':prod.name,'picking_id':pk.id,'product_id':prod.id,
            'product_uom':prod.uom_id.id,'product_uom_qty':1,'location_id':src.id,'location_dest_id':dst.id})
        line=env['stock.move.line'].with_context(skip_pallet_series_sync=True).create({
            'picking_id':pk.id,'move_id':mv.id,'product_id':prod.id,'location_id':src.id,
            'location_dest_id':dst.id,'result_package_id':pkg.id,
            'is_pallet_merge':(flagkey=='flag'),'vifel_premerge_captured':(flagkey=='captured')})
        env['stock.quant'].with_context(inventory_mode=True).create({'product_id':prod.id,
            'location_id':dst.id,'package_id':pkg.id,'owner_id':owner.id,'quantity':100.0})
        return pkg,line

    # a +0 merge pallet holding stock allows partial withdrawal
    pkg4,ml=marked_pkg_with_stock('flag'); env.flush_all()
    check('W4 a +0 merge pallet (holding stock) allows partial withdrawal',
          Q._vifel_package_allows_partial_withdrawal(pkg4.id), pkg4.name)

    # M/WR/08420: a Multiple-mode condition/special pallet placed via the Merge
    # button (is_pallet_merge False, vifel_premerge_captured True) also allows it.
    pkg4b,ml2=marked_pkg_with_stock('captured'); env.flush_all()
    check('W4b a CAPTURED (merge-button-placed, unflagged) condition pallet '
          'allows partial withdrawal', Q._vifel_package_allows_partial_withdrawal(pkg4b.id))
    # DURABLE: clearing the LINE marker does NOT drop the PACKAGE identity - it is
    # freed only when the pallet is emptied/unpinned, not when a line is edited.
    ml2.with_context(skip_pallet_series_sync=True).write({'vifel_premerge_captured':False})
    env.flush_all()
    check('W4c clearing the line marker does NOT drop partial withdrawal '
          '(durable package identity survives line edits)',
          Q._vifel_package_allows_partial_withdrawal(pkg4b.id))

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
    check('W7 replaced by a labelled strip (Line #, Product, Currently PSI '
          'On, Quantity, Quantity UOM, Weight)',
          'line_number' in arch and 'line_product_id' in arch
          and 'Currently PSI On' in arch and 'line_quantity_uom' in arch
          and 'Weight (KG)' in arch)
    check('W8 values are their own flex cells (cannot wrap mid-number)',
          'd-flex flex-wrap' in arch)
    check('W9 bold is inline, not fw-bold (this theme remaps it to 500)',
          'font-weight: 700' in arch and 'class="fw-bold' not in arch)
except Exception:
    traceback.print_exc(); F.append('exc')
env.cr.rollback()
print('RESULT: %d passed, %d failed' % (len(P),len(F)))
if F: print('FAILED:',F)
