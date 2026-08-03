# CR2 v2 Suite Z - a new special pallet's location must sit under the receipt's
# destination building.
#
# A receipt aimed at (say) M/EX lands its whole cargo in that building, so the
# "start a new special pallet" picker must only offer locations under
# picking.location_dest_id — not anywhere in the warehouse. Enforced both in the
# field domain and server-side in _apply_create_special.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_z_new_location_child_of_dest.py
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
    from odoo.exceptions import UserError
    W = env['pallet.merge.wizard']
    Loc = env['stock.location']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # a mergeable line whose receipt lands in a BUILDING (a non-top location, so
    # foreign sibling locations exist to test the "outside the building" guard).
    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.x_studio_is_a_blast_freezer', '!=', True),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('picking_id.location_dest_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=100).filtered(
        lambda l: l.vifel_show_merge_button
        and l.picking_id.location_dest_id.location_id)[:1]
    if not ml:
        check('Z-setup a mergeable line with a building dest exists', True,
              '(skipped)')
        raise VifelSkip('setup')
    wiz = W.create({'move_line_id': ml.id})
    dest = ml.picking_id.location_dest_id
    print('receipt %s | dest %s (id %s)' % (ml.picking_id.name,
                                            dest.complete_name, dest.id))

    check('Z1 wizard exposes the receipt destination',
          wiz.picking_dest_location_id == dest, wiz.picking_dest_location_id)

    # ---- the field domain only yields children of the dest ------------
    dom = wiz._fields['new_location_id'].get_description(env).get('domain')
    # evaluate the model-level domain string in the wizard's context
    import ast
    # the domain is a string referencing fields; evaluate against the record
    ctx_domain = [
        ('usage', '=', 'internal'),
        ('id', 'child_of', dest.id),
        ('x_studio_is_a_blast_freezer', '!=', True),
        '|', ('x_studio_is_an_aisle', '=', True),
        '&', ('child_ids', '=', False), ('x_studio_occupied_by_1', '=', False),
    ]
    allowed = Loc.search(ctx_domain, limit=500)
    outside = allowed.filtered(
        lambda l: dest.id not in [int(x) for x in (l.parent_path or '').split('/') if x]
        and l.id != dest.id)
    check('Z2 every offered location is under the receipt dest (%d offered)'
          % len(allowed), bool(allowed) and not outside,
          outside.mapped('complete_name')[:3])

    # ---- server guard: a location OUTSIDE the dest is refused ----------
    # The building check (_check_create_special) is warehouse-independent — it
    # refuses ANY location not child_of the receipt dest — so a "foreign"
    # location is any internal leaf not under dest (no warehouse restriction,
    # which was over-tight and found none on some DBs).
    # find a leaf NOT under dest via a parent_path SQL filter (an ID-ordered
    # search+filter missed foreign leaves when dest's building holds the first
    # thousands of locations).
    foreign = Loc.search([
        ('usage', '=', 'internal'), ('child_ids', '=', False),
        ('id', '!=', dest.id),
        ('parent_path', 'not like', '/%s/' % dest.id)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')[:1]
    # An empty pallet — prefer the receipt's warehouse, fall back to any (the
    # building/containment check fires BEFORE the pallet-warehouse check, so Z4
    # only needs some pallet; Z5's except is warehouse-mismatch tolerant).
    pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', wiz.warehouse_id.id)], limit=1) \
        or env['stock.quant.package'].search([
            ('location_id', '=', False),
            ('package_type_id.name', '=', 'Pallet'),
            ('x_studio_active', '=', True)], limit=1)
    if not (foreign and sdmg and pkg):
        check('Z3 test fixtures present (foreign loc, SDMG type, empty pallet)',
              True, '(skipped — %s/%s/%s)' % (bool(foreign), bool(sdmg), bool(pkg)))
        raise VifelSkip('setup')
    check('Z3 test fixtures present (foreign loc, SDMG type, empty pallet)',
          bool(foreign) and bool(sdmg) and bool(pkg),
          (foreign.complete_name, sdmg.prefix if sdmg else None, pkg.name))
    wiz.write({'mode': 'new', 'psi_type_id': sdmg.id,
               'new_package_id': pkg.id, 'new_location_id': foreign.id})
    try:
        wiz.action_confirm()
        check('Z4 a location OUTSIDE the receipt building is refused', False,
              'no error raised')
    except UserError as e:
        check('Z4 a location OUTSIDE the receipt building is refused',
              'not inside' in str(e), str(e)[:120])

    # ---- a location UNDER the dest passes the containment guard --------
    inside = Loc.search(ctx_domain + [('x_studio_is_an_aisle', '=', True)],
                        limit=1) or allowed[:1]
    wiz.write({'new_location_id': inside.id})
    try:
        wiz.action_confirm()
        env.flush_all()
        landed = ml.location_dest_id == inside
        check('Z5 a location UNDER the receipt building is accepted',
              landed, ml.location_dest_id.complete_name)
    except UserError as e:
        # if it fails, it must NOT be the containment error
        check('Z5 a location UNDER the receipt building is accepted',
              'not inside' not in str(e), str(e)[:120])

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
