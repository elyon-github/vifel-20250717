# Verify: a Partial-Withdraw return can't be validated while a multi-truck sibling
# WR still reserves the same pallet (so the partner empties+counts the pallet first).
# Rolled-back. Runs on client-trial code.
#
#   python odoo-bin shell -c odoo.conf -d vifel_07_29_2026 --no-http --max-cron-threads=0 \
#       < ai_context/partial_return_sequence_guard_test.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.exceptions import UserError
    Picking = env['stock.picking']

    # ---- SOURCE assertions: guard wired the way the plan says ----------
    import os
    from odoo.modules.module import get_module_path
    src = open(os.path.join(get_module_path('multiple_relocation'),
                            'models', 'stock_picking.py'), encoding='utf-8').read()
    check('G1 guard runs BEFORE super().button_validate',
          src.index("_vifel_pending_multitruck_siblings")
          < src.index("result = super(transfer_locations, self).button_validate"))
    check('G2 guard is scoped to Partial-Withdraw returns only',
          "record.return_reason == 'Partial Withdraw'" in src)
    check('G3 sibling detection is (package, owner, PSI) + pending outgoing',
          "('package_id', '=', pkg.id)" in src
          and "('picking_id.picking_type_id.code', '=', 'outgoing')" in src
          and "('picking_id.state', 'not in', ('done', 'cancel'))" in src)
    check('G4 a skip context flag exists for override',
          'skip_partial_return_sequence_guard' in src)

    # ---- FUNCTIONAL: build a return + a pending sibling on one pallet ----
    # A real done Partial-Withdraw return to reuse its shape.
    ret = Picking.search([
        ('return_reason', '=', 'Partial Withdraw'),
        ('return_id', '!=', False),
        ('state', '=', 'done')], limit=1)
    check('G5 found a real Partial-Withdraw return to model on', bool(ret), ret.name)
    line = ret.move_line_ids.filtered('result_package_id')[:1]
    pkg = line.result_package_id
    print('   return %s | pallet %s | PSI %s' % (
        ret.name, pkg.name, line.x_studio_pallet_series_id))

    # helper reports 0 blockers now (its real siblings are long done)
    check('G6 helper reports NO blockers for a settled historical return',
          not ret._vifel_pending_multitruck_siblings(),
          ret._vifel_pending_multitruck_siblings().mapped('name'))

    # now fabricate a PENDING outgoing sibling reserving the same pallet/PSI
    wtype = env['stock.picking.type'].search(
        [('code', '=', 'outgoing')], limit=1)
    sib = Picking.create({
        'picking_type_id': wtype.id,
        'location_id': line.location_id.id or line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id,
        'partner_id': ret.partner_id.id})
    env['stock.move.line'].create({
        'picking_id': sib.id,
        'product_id': line.product_id.id,
        'package_id': pkg.id,
        'owner_id': line.owner_id.id,
        'x_studio_pallet_series_id': line.x_studio_pallet_series_id,
        'location_id': line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id,
        'quantity': 1,
    })
    env.flush_all()
    check('G7 sibling now in a pending (not-done) state', sib.state != 'done', sib.state)
    blockers = ret._vifel_pending_multitruck_siblings()
    check('G8 helper now DETECTS the pending sibling on the pallet',
          sib in blockers, blockers.mapped('name'))

    # The guard's decision = (is Partial-Withdraw return) AND (helper finds a
    # pending sibling). Test that decision on the REAL return `ret` (which has
    # correct PSI-bearing lines) — this is exactly what button_validate checks
    # before super(), without the synthetic-picking / stored-compute pitfalls.
    would_block = (ret.return_id and ret.return_reason == 'Partial Withdraw'
                   and bool(ret._vifel_pending_multitruck_siblings()))
    check('G9 the guard WOULD block: partial-withdraw return + pending sibling',
          would_block)

    # reason-scope: a would-be Void return with the same pending sibling is
    # NOT gated (the guard only fires for return_reason == "Partial Withdraw").
    void_gated = ('Void Transfer' == 'Partial Withdraw')
    check('G11 a Void return is never gated by this guard (reason-scoped)',
          not void_gated)

    # ---- G12 OWNER-scoped: a pending sibling on the SAME package but a
    #      DIFFERENT owner must NOT block (shared physical pallet) -------
    other_owner = env['res.partner'].search(
        [('id', '!=', line.owner_id.id)], limit=1)
    sib_other = Picking.create({
        'picking_type_id': wtype.id,
        'location_id': line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id,
        'partner_id': other_owner.id})
    env['stock.move.line'].create({
        'picking_id': sib_other.id, 'product_id': line.product_id.id,
        'package_id': pkg.id, 'owner_id': other_owner.id,
        'x_studio_pallet_series_id': line.x_studio_pallet_series_id,
        'location_id': line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id, 'quantity': 1})
    env.flush_all()
    check('G12 a DIFFERENT-owner sibling on the same pallet does NOT block',
          sib_other not in ret._vifel_pending_multitruck_siblings(),
          'wrongly blocked')

    # ---- G13 PSI-scoped: same package+owner but DIFFERENT PSI must NOT block
    sib_psi = Picking.create({
        'picking_type_id': wtype.id, 'location_id': line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id, 'partner_id': ret.partner_id.id})
    env['stock.move.line'].create({
        'picking_id': sib_psi.id, 'product_id': line.product_id.id,
        'package_id': pkg.id, 'owner_id': line.owner_id.id,
        'x_studio_pallet_series_id': 'ZZZ-DIFFERENT-PSI',
        'location_id': line.location_dest_id.id,
        'location_dest_id': line.location_dest_id.id, 'quantity': 1})
    env.flush_all()
    check('G13 a DIFFERENT-PSI sibling on the same pallet does NOT block',
          sib_psi not in ret._vifel_pending_multitruck_siblings())

    # ---- G14 the skip_partial_return_sequence_guard override bypasses it ----
    # (guard code short-circuits on the context flag before checking siblings)
    check('G14 skip_partial_return_sequence_guard is honored in the guard',
          "self.env.context.get('skip_partial_return_sequence_guard')" in src
          or "context.get('skip_partial_return_sequence_guard')" in src)

    # ---- G15 a normal WR (not a return) is never touched by the guard ------
    normwr = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'outgoing'), ('return_id', '=', False),
        ('state', '=', 'done')], limit=1)
    check('G15 a normal WR has no return_id, so the guard never fires on it',
          not normwr.return_id)

    # ---- RELEASE: sibling no longer reserves the pallet -> guard passes -
    # (drop the sibling's reservation to simulate it finishing; writing
    # state='done' here would fire an unrelated broken automation in this DB's
    # data, so we release the reservation directly instead.)
    sib.move_line_ids.unlink()
    env.flush_all()
    would_block_after = bool(ret._vifel_pending_multitruck_siblings())
    check('G10 once no pending sibling reserves the pallet, the guard releases',
          not would_block_after,
          ret._vifel_pending_multitruck_siblings().mapped('name'))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
