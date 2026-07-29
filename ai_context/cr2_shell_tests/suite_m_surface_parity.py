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


try:
    W = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # The Magic Wizard refuses to open on a line without a PSI or whose
    # location is a non-aisle parent — find a line it will accept first.
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('x_studio_pallet_series_id', '!=', False),
        ('location_dest_id', '!=', False),
    ], limit=300).filtered(
        lambda m: not m.location_dest_id.child_ids
        or m.location_dest_id.x_studio_is_an_aisle)[:1]
    check('P0 found a line the Magic Wizard will open on', bool(line))
    picking = line.picking_id
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
    w_magic.write({'mode': 'new', 'psi_type_id': tdmg.id,
                   'new_package_id': empty_pkg.id, 'new_location_id': loc.id})
    res = w_magic.action_confirm()
    env.flush_all()
    drawn = line.x_studio_pallet_series_id
    check('P4 a new special pallet can be started from the Magic Wizard (%s)'
          % drawn, drawn.startswith('TDMG-'), drawn)
    check('P5 it landed on the chosen empty pallet',
          line.result_package_id == empty_pkg, line.result_package_id.name)
    check('P6 it is NOT flagged merged (a new pallet counts +1)',
          not line.is_pallet_merge)
    check('P7 confirm returns to the Magic Wizard list',
          isinstance(res, dict)
          and res.get('res_model') == 'stock.move.line.fast_encode_rr.line',
          res.get('res_model'))

    # ---- transient row synced, including its "original" ---------------
    env.invalidate_all()
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('P8 the Magic Wizard row shows the drawn series',
          tline.pallet_series_id == drawn, tline.pallet_series_id)
    check('P9 the row no longer claims the released series as its original',
          tline.original_pallet_series_id == drawn,
          tline.original_pallet_series_id)

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

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
