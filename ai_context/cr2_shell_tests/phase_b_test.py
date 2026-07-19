# Phase B: merge core — availability, candidates, confirm, un-merge, guards.
import traceback

from odoo.exceptions import UserError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))

def expects_user_error(label, fn, needle=''):
    try:
        with env.cr.savepoint():
            fn()
        check(label, False, 'no error raised')
    except UserError as e:
        check(label, (needle in str(e)) if needle else True, str(e)[:120])
        env.invalidate_all()

try:
    P, Q, L = env['res.partner'], env['stock.quant'], env['stock.location']
    ML = env['stock.move.line']
    W = env['pallet.merge.wizard']

    # ---- setup: a merge-enabled client with real stock -----------------
    stocked_quant = Q.search([
        ('owner_id.category_id.name', '=', 'Client'),
        ('package_id', '!=', False),
        ('x_studio_pallet_series_id', '!=', False),
        ('location_id.usage', '=', 'internal'),
        ('location_id.x_studio_is_a_blast_freezer', '!=', True),
        ('quantity', '>', 0)], limit=1)
    client = stocked_quant.owner_id
    target_pkg = stocked_quant.package_id
    target_psi = stocked_quant.x_studio_pallet_series_id
    code = (client.x_studio_client_unique_code_1 or '').strip()
    print('client: %s | target %s (%s) at %s' % (
        client.name, target_pkg.name, target_psi,
        stocked_quant.location_id.complete_name))

    # a draft RR of that client with an encodable line
    rr = env['stock.picking'].search([
        ('partner_id', '=', client.id),
        ('picking_type_id.code', '=', 'incoming'),
        ('picking_type_id.is_blast_freeze_operation', '!=', True),
        ('return_id', '=', False),
        ('state', 'not in', ['done', 'cancel']),
        ('move_line_ids', '!=', False)], limit=1)
    if not rr:
        rr = env['stock.picking'].search([
            ('partner_id', '=', client.id),
            ('picking_type_id.code', '=', 'incoming'),
            ('picking_type_id.is_blast_freeze_operation', '!=', True),
            ('return_id', '=', False),
            ('state', '=', 'done'),
            ('move_line_ids', '!=', False)], limit=1).copy({'origin': 'CR2 merge test'})
    line = rr.move_line_ids[0]
    print('RR: %s (%s), line #%s %s' % (rr.name, rr.state, line.x_studio_,
                                        line.product_id.name))

    # ---- 1. availability -----------------------------------------------
    check('B1 button hidden while the client is not merge-enabled',
          not line.vifel_show_merge_button)
    client.write({'vifel_can_merge_pallets': True})
    env.invalidate_all()
    check('B2 button appears once Can Merge Pallets is ON',
          line.vifel_show_merge_button)

    # ---- 2. FIXED mode ---------------------------------------------------
    client.write({'vifel_fixed_package_id': target_pkg.id,
                  'vifel_fixed_psi': target_psi})
    wiz = W.create({'move_line_id': line.id})
    check('B3 fixed mode pre-selects the pinned pallet',
          wiz.target_package_id == target_pkg, wiz.target_package_id.name)
    check('B4 fixed mode offers ONLY the pinned pallet',
          [p.id for p in wiz.allowed_package_ids] == [target_pkg.id])
    check('B5 target info shows PSI / location / KG',
          wiz.target_psi == target_psi
          and wiz.target_location_id == stocked_quant.location_id
          and wiz.target_kg > 0,
          (wiz.target_psi, wiz.target_location_id.complete_name, wiz.target_kg))

    old_series = line.x_studio_pallet_series_id
    old_pkg = line.result_package_id
    old_loc = line.location_dest_id
    pool_before = list(client.unused_pallet_series_ids or [])
    wiz.action_confirm()
    check('B6 merge adopts the target PSI',
          line.x_studio_pallet_series_id == target_psi,
          line.x_studio_pallet_series_id)
    check('B7 ... the target pallet', line.result_package_id == target_pkg)
    check('B8 ... and the target quant location',
          line.location_dest_id == stocked_quant.location_id,
          line.location_dest_id.complete_name)
    check('B9 the line is flagged is_pallet_merge', line.is_pallet_merge)
    check('B10 the previously drawn PSI was recycled to the pool',
          old_series and int(old_series.split('-')[-1])
          in (client.unused_pallet_series_ids or []),
          (old_series, client.unused_pallet_series_ids))
    check('B11 the stocked target was NOT stamped as reserved',
          not target_pkg.x_studio_is_reserved
          and not target_pkg.x_studio_receiving_report_id)
    if old_pkg:
        check('B12 the old empty pallet reservation was freed',
              not old_pkg.x_studio_is_reserved)
    check('B13 the merge is chattered on the RR',
          any('merged onto pallet' in (m.body or '')
              for m in rr.message_ids[:3]))

    # merging to the very same pallet is refused
    wiz2 = W.create({'move_line_id': line.id})
    expects_user_error('B14 re-merging onto the same pallet is refused',
                       lambda: wiz2.action_confirm(), 'already on that pallet')

    # ---- 3. un-merge -----------------------------------------------------
    # give the line a different package outside the wizard -> flag clears,
    # adopted PSI must NOT be pooled (it is stocked)
    pool_before_unmerge = list(client.unused_pallet_series_ids or [])
    line.write({'result_package_id': False})
    env.invalidate_all()
    check('B15 un-merge clears the flag', not line.is_pallet_merge)
    check('B16 the adopted (stocked) PSI was NOT recycled',
          int(target_psi.split('-')[-1])
          not in (client.unused_pallet_series_ids or []))
    check('B17 the original series machinery restored the line',
          line.x_studio_pallet_series_id
          and line.x_studio_pallet_series_id != target_psi,
          line.x_studio_pallet_series_id)

    # ---- 4. MULTIPLE mode candidates ------------------------------------
    client.write({'vifel_multiple_pallet_support': True})
    wiz3 = W.create({'move_line_id': line.id})
    # client's types are freshly seeded -> no stocked special pallets exist,
    # Include Regular is OFF -> the seeded types exist so no regular fallback
    check('B18 with fresh types and no Include Regular, no candidates',
          not wiz3.allowed_package_ids,
          [p.name for p in wiz3.allowed_package_ids][:5])
    client.write({'vifel_include_regular_pallets': True})
    env.invalidate_all()
    wiz4 = W.create({'move_line_id': line.id})
    check('B19 Include Regular widens to the client\'s stocked pallets',
          target_pkg in wiz4.allowed_package_ids,
          len(wiz4.allowed_package_ids))
    check('B20 candidates all belong to this client and are stocked',
          all(any(q.owner_id == client and q.quantity > 0
                  for q in p.quant_ids) for p in wiz4.allowed_package_ids))
    # no-types fallback: drop the types -> regular pallets stand in
    client.write({'vifel_include_regular_pallets': False})
    client.vifel_psi_type_ids.unlink()
    env.invalidate_all()
    wiz5 = W.create({'move_line_id': line.id})
    check('B21 empty types table falls back to regular stocked pallets',
          target_pkg in wiz5.allowed_package_ids)

    # re-seed for the special-path test
    client.write({'vifel_multiple_pallet_support': False})
    client.write({'vifel_multiple_pallet_support': True})

    # ---- 5. create-new-special path -------------------------------------
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_receiving_report_id', '=', False)], limit=1)
    free_loc = L.search([
        ('usage', '=', 'internal'), ('child_ids', '=', False),
        ('x_studio_is_a_blast_freezer', '!=', True),
        ('x_studio_occupied_by_1', '=', False),
        ('x_studio_receiving_report_id', '=', False)], limit=1)
    sdmg = client.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    wiz6 = W.create({'move_line_id': line.id,
                     'psi_type_id': sdmg.id,
                     'new_package_id': empty_pkg.id,
                     'new_location_id': free_loc.id})
    wiz6.action_create_special()
    env.invalidate_all()
    check('B22 special path draws from the type (SDMG-000001)',
          line.x_studio_pallet_series_id == 'SDMG-000001',
          line.x_studio_pallet_series_id)
    check('B23 ... plain line, NOT flagged as merge', not line.is_pallet_merge)
    check('B24 ... new pallet + location reserved like a normal receive',
          empty_pkg.x_studio_is_reserved
          and empty_pkg.x_studio_receiving_report_id.id == rr.id
          and free_loc.x_studio_is_reserved)
    check('B25 the type counter advanced', sdmg.next_number == 2)

    # merging that special line onto the stocked target now recycles the
    # SDMG series into ITS OWN type pool
    client.write({'vifel_include_regular_pallets': True})
    wiz7 = W.create({'move_line_id': line.id,
                     'target_package_id': target_pkg.id})
    wiz7.action_confirm()
    env.invalidate_all()
    check('B26 special line merges onto the regular stocked target',
          line.is_pallet_merge
          and line.x_studio_pallet_series_id == target_psi)
    check('B27 the SDMG series went back to the TYPE pool, not the normal one',
          (sdmg.number_pool or []) == [1]
          and 1 not in [n for n in (client.unused_pallet_series_ids or [])
                        if n not in pool_before_unmerge],
          (sdmg.number_pool, client.unused_pallet_series_ids))

    # ---- 6. FastEncodeRR guard exemption --------------------------------
    fe_action = line.action_open_fast_encode_wizard()
    fe = env['stock.move.line.fast_encode_rr'].browse(
        fe_action['context']['default_wizard_id'])
    fe_line = fe.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('B28 FastEncodeRR maps the merge flag onto its line',
          fe_line.is_pallet_merge)
    try:
        fe._validate_result_package_availability()
        check('B29 availability validation tolerates the occupied target', True)
    except UserError as e:
        check('B29 availability validation tolerates the occupied target',
              False, str(e)[:150])
    fe_line.write({'kilogram': 123.0})
    fe.action_confirm()
    env.invalidate_all()
    check('B30 FastEncodeRR confirm keeps the adopted identity, writes cargo',
          line.is_pallet_merge
          and line.x_studio_pallet_series_id == target_psi
          and line.result_package_id == target_pkg
          and line.quantity == 123.0,
          (line.is_pallet_merge, line.x_studio_pallet_series_id, line.quantity))
    check('B31 ... and still no reservation stamped on the target',
          not target_pkg.x_studio_is_reserved)

    # ---- 7. multi-PSI target refused (synthesized in the rollback) ------
    other_q = Q.search([
        ('owner_id', '=', client.id), ('package_id', '!=', False),
        ('package_id', '!=', target_pkg.id), ('quantity', '>', 0),
        ('location_id.usage', '=', 'internal'),
        ('x_studio_pallet_series_id', '!=', target_psi),
        ('x_studio_pallet_series_id', '!=', False)], limit=1)
    other_q.write({'package_id': target_pkg.id})
    env.invalidate_all()
    # un-merge our line first so the wizard is confirmable again
    line.write({'result_package_id': False})
    wiz8 = W.create({'move_line_id': line.id,
                     'target_package_id': target_pkg.id})
    expects_user_error('B32 a target with several PSIs is refused',
                       lambda: wiz8.action_confirm(), 'different Pallet Series')

except Exception:
    print('UNEXPECTED ERROR:'); traceback.print_exc(); FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
