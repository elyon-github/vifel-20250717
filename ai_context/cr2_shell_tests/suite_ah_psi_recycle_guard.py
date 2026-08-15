# CR2 v2 Suite AH - a merge pallet's ADOPTED PSI is never recycled to the pool.
#
# Reported regression: the Fixed PSI (and the Multiple-mode special PSI) of a
# merge pallet was being recycled — pushed back to the client's pool and then
# re-issued to a brand-new pallet. Two causes, two guards:
#
#  1. _vifel_detach_same_receipt_join used to push the ADOPTED series to the
#     pool when "no remaining line holds it". The peeling line only BORROWED
#     that series (it belongs to the pallet), and the "sibling holds it" guard is
#     fragile (many lines carry a NULL picking_id here). It must never push the
#     adopted series; the line's OWN pre-merge series is restored separately.
#  2. push_unused_pallet now hard-refuses the client's dedicated Fixed PSI, a
#     backstop for any caller (the Fixed PSI is a permanent pallet identity, not
#     a pool number).
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ah_psi_recycle_guard.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


# spy on push_unused_pallet to record EVERY series routed to a pool
Partner = env['res.partner']
cls = type(Partner)
PUSHED = []
_orig = cls.push_unused_pallet


def _spy(self, sid):
    PUSHED.append(sid)
    return _orig(self, sid)


cls.push_unused_pallet = _spy

try:
    W = env['pallet.merge.wizard']
    owner = Partner.browse(428)
    empty_fixed = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_is_reserved', '=', False),
        ('vifel_is_merge_pallet', '=', False)], limit=400).filtered(
        lambda p: not p.quant_ids.filtered(lambda q: q.quantity > 0)
        and not env['stock.move.line'].search_count([
            ('result_package_id', '=', p.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel'))]))[:1]

    # ===== GUARD 2: the Fixed PSI can never be pooled, whatever the caller =====
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env['vifel.fixed.merge.pallet'].create({
        'partner_id': owner.id, 'package_id': empty_fixed.id, 'psi': 'TCF-000777'})
    env.flush_all()
    before = owner.unused_pallet_series_ids
    owner.push_unused_pallet('TCF-000777')
    owner.invalidate_recordset(['unused_pallet_series_ids'])
    check('AH1 push_unused_pallet hard-refuses the client Fixed PSI',
          owner.unused_pallet_series_ids == before,
          (before, owner.unused_pallet_series_ids))

    # ===== GUARD 1 (Fixed): a birth line's detach never pools the adopted PSI ==
    pk = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered(
            lambda m: m.product_id and m.result_package_id != empty_fixed)) >= 1)[:1]
    ml = pk.move_line_ids.filtered(
        lambda m: m.product_id and m.result_package_id != empty_fixed)[:1]
    w = W.create({'move_line_id': ml.id})
    t = w.candidate_line_ids.filtered('is_target')[:1]
    if not t:
        t = w.candidate_line_ids.filtered('eligible')[:1]
        t.is_target = True
    w.action_confirm()
    env.flush_all()
    check('AH2 the line birthed the Fixed pallet, captured, adopted the PSI',
          ml.result_package_id == empty_fixed and ml.vifel_premerge_captured
          and ml.x_studio_pallet_series_id == 'TCF-000777')
    # force the "no remaining sibling holds it" detach path (the bug trigger)
    PUSHED.clear()
    ml._vifel_detach_same_receipt_join(False)
    env.flush_all()
    check('AH3 detaching the lone birth line did NOT pool the Fixed PSI',
          'TCF-000777' not in PUSHED, PUSHED)
    owner.invalidate_recordset(['unused_pallet_series_ids'])
    pool = owner.unused_pallet_series_ids or []
    check('AH4 the Fixed PSI is not in the recycle pool afterwards',
          777 not in (pool if isinstance(pool, list) else []), pool)

    env.cr.rollback()

    # ===== GUARD 1 (Multiple): the special PSI is never pooled on detach ======
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    pk = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    a, b = pk.move_line_ids.filtered('product_id')[:2]
    ep = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', pk.warehouse_id.id)], limit=1)
    loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', pk.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda ty: ty.prefix == 'SDMG')
    w1 = W.create({'move_line_id': a.id, 'mode': 'new'})
    w1.write({'psi_type_id': sdmg.id, 'new_package_id': ep.id,
              'new_location_id': loc.id})
    w1.action_confirm()
    env.flush_all()
    special = a.x_studio_pallet_series_id
    w2 = W.create({'move_line_id': b.id})
    t = w2.candidate_line_ids.filtered(
        lambda c: c.on_this_receipt and c.package_id == ep)[:1]
    t.is_target = True
    w2.action_confirm()
    env.flush_all()
    PUSHED.clear()
    b.action_unmerge_pallet_line()
    env.flush_all()
    check('AH5 un-merging the joiner did NOT pool the special PSI',
          special not in PUSHED, (special, PUSHED))
    PUSHED.clear()
    a._vifel_detach_same_receipt_join(False)   # forced no-sibling detach
    env.flush_all()
    check('AH6 a forced no-sibling detach never pools the special PSI',
          special not in PUSHED, (special, PUSHED))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')
finally:
    cls.push_unused_pallet = _orig
    env.cr.rollback()

print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
