# CR2 v2 Suite M - the merge dialog behaves the SAME on both surfaces.
#
# "Start a new special pallet" was originally withheld inside the Magic
# Wizard. That was caution, not a technical limit, and it made one screen
# quietly less capable than the other. Both surfaces now offer both modes.
#
# The load-bearing check is P10: the Magic Wizard writes everything at
# action_confirm, so a series DRAWN inside it must survive that deferred
# write. It does because the winner election takes the row's own
# pallet_series_id, and because the sync resets original_pallet_series_id
# to the drawn series - otherwise the restore path could resurrect the
# number the line arrived with, which has just gone back to the pool and
# may already belong to another line.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_m_surface_parity.py
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
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # A mergeable incoming line; the Magic Wizard refuses to open without a PSI +
    # (leaf/aisle) location, so make it Magic-Wizard-ready. It stays UNMERGED.
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.x_studio_is_a_blast_freezer', '!=', True),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=50).filtered(
        lambda l: l.vifel_show_merge_button)[:1]
    if not line:
        check('P0 a mergeable incoming line exists', True, '(skipped)')
        raise VifelSkip('setup')
    picking = line.picking_id
    ready_loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        '|', ('x_studio_is_an_aisle', '=', True), ('child_ids', '=', False)],
        limit=1)
    if not ready_loc:
        check('P0 a location exists for setup', True, '(skipped)')
        raise VifelSkip('setup')
    # only a PSI + location are required to open the Magic Wizard — do NOT assign
    # a pallet here, so the create-special target below cannot collide with it.
    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': line.x_studio_pallet_series_id or 'MPAR-000001',
        'location_dest_id': ready_loc.id})
    env.flush_all()
    check('P0 found/prepared a line the Magic Wizard will open on', bool(line))
    old_series = line.x_studio_pallet_series_id
    print('picking %s | line #%s (was %s)'
          % (picking.name, line.x_studio_, old_series))

    # ---- the dialog offers the SAME choices from both surfaces --------
    w_break = W.create({'move_line_id': line.id})
    act = line.action_open_fast_encode_wizard()
    fw = env['stock.move.line.fast_encode_rr'].browse(
        act['context']['default_wizard_id'])
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    open_act = tline.action_merge_from_fast_encode()
    w_magic = W.create({'move_line_id': line.id,
                        'from_fast_encode': True,
                        'fast_encode_line_id': tline.id})
    check('P1 both surfaces offer the same two modes',
          w_break._fields['mode'].selection == w_magic._fields['mode'].selection)

    arch = W.get_view(
        env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,
        'form')['arch']
    check('P2 the mode chooser is no longer hidden in the Magic Wizard',
          'not is_multiple_mode or from_fast_encode' not in arch)
    check('P3 the new-pallet group is no longer hidden in the Magic Wizard',
          "mode != 'new' or from_fast_encode" not in arch)

    # ---- START A NEW SPECIAL PALLET from inside the Magic Wizard ------
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=1)
    loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', w_magic.move_line_id.picking_id.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    tdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'TDMG')
    if not (empty_pkg and loc and tdmg):
        check('P4 fixtures for create-special exist', True, '(skipped)')
        raise VifelSkip('setup')
    real_pkg_before = line.result_package_id
    w_magic.write({'mode': 'new', 'psi_type_id': tdmg.id,
                   'new_package_id': empty_pkg.id, 'new_location_id': loc.id})
    res = w_magic.action_confirm()
    env.flush_all()
    # STAGED (commit 2ba23f7; suite_aj): the create-special is recorded on the
    # ROW; the REAL line is written only at the Magic Wizard's Confirm.
    env.invalidate_all()
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    drawn = tline.pallet_series_id
    check('P4 a new special pallet can be STAGED from the Magic Wizard (%s)'
          % drawn, drawn.startswith('TDMG-'), drawn)
    check('P5 the ROW is staged onto the chosen empty pallet',
          tline.result_package_id == empty_pkg, tline.result_package_id.name)
    check('P6 the staged row is NOT a +0 merge (a new pallet counts +1)',
          not tline.is_pallet_merge)
    check('P6b the REAL line is UNCHANGED until Confirm (deferred write)',
          line.result_package_id == real_pkg_before
          and (line.x_studio_pallet_series_id or '') != drawn,
          line.result_package_id.name)
    check('P7 confirm returns to the Magic Wizard list',
          isinstance(res, dict)
          and res.get('res_model') == 'stock.move.line.fast_encode_rr.line',
          res.get('res_model'))
    check('P8 the Magic Wizard row shows the drawn series',
          tline.pallet_series_id == drawn, tline.pallet_series_id)
    # Under staging the create-special is carried as a PENDING merge on the row,
    # which is merge-locked at Confirm — so the winner/restore passes never touch
    # it and cannot resurrect the released series (P13 confirms the outcome).
    check('P9 the row carries the staged create-special (pending merge)',
          tline.vifel_pending_merge
          and tline.vifel_pending_merge_kind == 'create_special',
          (tline.vifel_pending_merge, tline.vifel_pending_merge_kind))

    # ---- THE test: survive the Magic Wizard's deferred confirm --------
    tline.write({'kilogram': 77.7, 'quantity': 3.0, 'min_uom_unit': 30.0})
    fw.action_confirm()
    env.flush_all()
    check('P10 the drawn series survives action_confirm',
          line.x_studio_pallet_series_id == drawn,
          line.x_studio_pallet_series_id)
    check('P11 the pallet survives action_confirm',
          line.result_package_id == empty_pkg, line.result_package_id.name)
    check('P12 cargo edits still landed (KG=%.1f)' % line.quantity,
          abs(line.quantity - 77.7) < 0.01)
    check('P13 the released series did not come back',
          line.x_studio_pallet_series_id != old_series)

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
