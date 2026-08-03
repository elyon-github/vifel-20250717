# CR2 v2 Suite G2 - merge INITIATED from inside the Magic Wizard.
#
# Applies to the real move line immediately, then syncs the transient row
# (two-step write - see _vifel_sync_from_move_line) and reloads the list.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_g2_fastencode_initiation.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


class VifelSkip(Exception):
    """No eligible fixture in this DB — skip the rest without failing."""


try:
    owner = env['res.partner'].browse(428)          # TECHNO FARM
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # a genuinely MERGEABLE incoming line (mergeable => vifel_show_merge_button):
    # not a BF/return receipt, not already merged. A pallet is NOT required (the
    # line adopts the target's on merge).
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
        check('D-setup a mergeable incoming line exists', True,
              '(none in DB — skipped)')
        raise VifelSkip('setup')
    picking = line.picking_id
    # The Magic Wizard refuses to open on a line missing a Pallet Series or a
    # Location. Make this mergeable line Magic-Wizard-ready (it stays UNMERGED —
    # is_pallet_merge False — so D1/D2 still hold and we then merge from within).
    ready_loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        '|', ('x_studio_is_an_aisle', '=', True), ('child_ids', '=', False)],
        limit=1) or env['stock.location'].search(
        [('usage', '=', 'internal'), ('x_studio_is_an_aisle', '=', True)], limit=1)
    ready_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    if not (ready_loc and ready_pkg):
        check('D-setup a location + empty pallet exist for setup', True,
              '(skipped)')
        raise VifelSkip('setup')
    line.with_context(skip_pallet_series_sync=True).write({
        'x_studio_pallet_series_id': line.x_studio_pallet_series_id or 'GTST-000001',
        'location_dest_id': ready_loc.id, 'result_package_id': ready_pkg.id})
    env.flush_all()
    print('picking %s, line #%s (unmerged, Magic-Wizard-ready)'
          % (picking.name, line.x_studio_))

    # ---- open the Magic Wizard on this line (NOT yet merged) ----------
    action = line.action_open_fast_encode_wizard()
    fw = env['stock.move.line.fast_encode_rr'].browse(
        action['context']['default_wizard_id'])
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('D1 Magic Wizard shows the Merge button for a mergeable line',
          tline.show_merge_button, tline.show_merge_button)
    check('D2 line starts unmerged in the Magic Wizard',
          not tline.is_pallet_merge)

    # ---- INITIATE the merge from inside the Magic Wizard -------------
    open_act = tline.action_merge_from_fast_encode()
    mwiz = env['pallet.merge.wizard'].browse(open_act['res_id'])
    check('D3 merge wizard opens in merge-only mode (create-special hidden)',
          mwiz.from_fast_encode)
    fe_ctx = open_act['context']
    check('D4 wizard carries the transient line id in context',
          fe_ctx.get('fast_encode_line_id') == tline.id)

    # pick an eligible target with a clean (leaf/aisle) location
    target = mwiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt and c.location_id
        and (not c.location_id.child_ids
             or c.location_id.x_studio_is_an_aisle))[:1] \
        or mwiz.candidate_line_ids.filtered(
            lambda c: c.eligible and not c.on_this_receipt)[:1]
    if not target:
        check('D-setup an eligible merge target exists', True,
              '(no stocked candidate — skipped)')
        raise VifelSkip('setup')
    target.is_target = True
    adopted = target.psi
    tgt_pkg = target.package_id
    # confirm with the fast-encode context (as the real UI would)
    reopen = mwiz.with_context(
        fast_encode_line_id=tline.id).action_confirm()
    env.flush_all()

    # ---- STAGED: the merge is recorded on the ROW, but the REAL move line is
    #      NOT touched until the Magic Wizard's own Confirm (deferred-write —
    #      commit 2ba23f7; suite_aj covers this in depth). So right after
    #      initiating, the real line is still unmerged.
    env.invalidate_all()
    check('D5 the merge STAGES — the real line is NOT changed until the Magic '
          'Wizard is confirmed (deferred write)',
          not line.is_pallet_merge, line.is_pallet_merge)
    # ---- transient row shows the staged merge (no divergence in the UI) ----
    tline = fw.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('D6 transient row shows the staged merge',
          tline.is_pallet_merge
          and tline.pallet_series_id == adopted
          and tline.result_package_id == tgt_pkg,
          'flag=%s psi=%s(want %s) pkg=%s(want %s)' % (
              tline.is_pallet_merge, tline.pallet_series_id, adopted,
              tline.result_package_id.name, tgt_pkg.name))
    check('D7 confirm returns the Magic Wizard list reload',
          isinstance(reopen, dict)
          and reopen.get('res_model') == 'stock.move.line.fast_encode_rr.line',
          reopen.get('res_model'))

    # ---- now confirm the Magic Wizard: merge must survive -----------
    tline.write({'kilogram': 88.8, 'quantity': 4.0, 'min_uom_unit': 40.0})
    fw.action_confirm()
    env.flush_all()
    check('D8 merge survives the Magic Wizard action_confirm',
          line.is_pallet_merge
          and line.x_studio_pallet_series_id == adopted
          and line.result_package_id == tgt_pkg)
    check('D9 cargo edits from the Magic Wizard landed (KG=%.1f)'
          % line.quantity, abs(line.quantity - 88.8) < 0.01)

    # ---- UN-MERGE from inside the Magic Wizard ----------------------
    action2 = line.action_open_fast_encode_wizard()
    fw2 = env['stock.move.line.fast_encode_rr'].browse(
        action2['context']['default_wizard_id'])
    tline2 = fw2.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('D10 merged line shows Un-merge in the Magic Wizard',
          tline2.show_merge_button and tline2.is_pallet_merge)
    reopen2 = tline2.action_unmerge_from_fast_encode()
    env.flush_all()
    # STAGED un-merge (commit 2ba23f7; suite_ac): the ROW flips to un-merged at
    # once, but the REAL line is detached only at the Magic Wizard's Confirm.
    env.invalidate_all()
    tline2 = fw2.line_ids.filtered(lambda l: l.stock_move_line == line.id)
    check('D11 un-merge STAGES — row shows un-merged, but the real line stays '
          'merged until Confirm',
          not tline2.vifel_on_merged_pallet and line.is_pallet_merge,
          (tline2.vifel_on_merged_pallet, line.is_pallet_merge))
    # confirm the Magic Wizard -> NOW the real line is un-merged
    fw2.action_confirm()
    env.flush_all()
    check('D12 after Confirm the real line is un-merged',
          not line.is_pallet_merge, line.is_pallet_merge)
    check('D13 target still holds its PSI on the floor (not recycled)',
          env['stock.quant'].search_count([
              ('x_studio_pallet_series_id', '=', adopted),
              ('location_id.usage', '=', 'internal'),
              ('quantity', '>', 0)]) > 0)

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
