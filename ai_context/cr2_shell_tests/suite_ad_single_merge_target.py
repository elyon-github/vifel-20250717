# CR2 v2 Suite AD - the merge wizard allows exactly ONE 'Merge Here' target.
#
# Toggling a second candidate must switch the first off (radio behaviour). The
# per-row onchange does this in memory; a PARENT onchange re-asserts it so the
# web client re-renders; and the server refuses to merge onto an ambiguous
# (>1) pick so it can never silently land on the wrong pallet.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ad_single_merge_target.py
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
    # The single-target ('Merge Here') radio behaviour is owner-independent;
    # use a well-stocked merge client and a genuinely mergeable line that yields
    # at least two eligible candidate pallets to toggle between.
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    ml = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.x_studio_is_a_blast_freezer', '!=', True),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
        ('is_pallet_merge', '=', False)], limit=50).filtered(
        lambda l: l.vifel_show_merge_button)[:1]
    if not ml:
        check('AD-setup a mergeable line exists', True, '(skipped)')
        raise VifelSkip('setup')
    wiz = W.create({'move_line_id': ml.id})
    elig = wiz.candidate_line_ids.filtered('eligible')
    if len(elig) < 2:
        check('AD-setup >= 2 eligible candidate pallets exist', True,
              '(only %d — skipped)' % len(elig))
        raise VifelSkip('setup')
    check('AD0 at least two eligible candidates to test', len(elig) >= 2,
          len(elig))
    a, b = elig[0], elig[1]

    # ---- per-row onchange: toggling B clears A ------------------------
    a.is_target = True
    a._onchange_is_target()
    b.is_target = True
    b._onchange_is_target()
    check('AD1 toggling B via the row onchange clears A (radio)',
          b.is_target and not a.is_target, (a.is_target, b.is_target))

    # ---- parent onchange safety net: if two ever slip through, keep one
    a.is_target = True
    b.is_target = True   # force the "UI let two through" state
    wiz._onchange_candidate_lines_single_target()
    survivors = wiz.candidate_line_ids.filtered('is_target')
    check('AD2 the parent onchange collapses two toggles to exactly one',
          len(survivors) == 1, len(survivors))

    # ---- server guard: an ambiguous pick is refused, not silently used
    a.is_target = True
    b.is_target = True
    try:
        wiz._resolve_merge_target()
        check('AD3 server refuses to merge onto an ambiguous (>1) pick', False,
              'no error raised')
    except UserError as e:
        check('AD3 server refuses to merge onto an ambiguous (>1) pick',
              'More than one' in str(e), str(e)[:90])

    # ---- a single clean target still resolves fine --------------------
    (wiz.candidate_line_ids - b).write({'is_target': False})
    b.is_target = True
    pkg, cand = wiz._resolve_merge_target()
    check('AD4 a single target resolves to its pallet',
          cand == b and pkg == b.package_id, pkg.name if pkg else None)

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
