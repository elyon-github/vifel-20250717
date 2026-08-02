# CR2 v2 Suite AG - several lines birthing ONE Fixed pallet show as "Merged".
#
# Reported on M/RR/05300 (Wonder Meats, a Fixed client): lines 1, 2 and 8 were
# all placed on the pinned Fixed pallet with the Merge button, adopting the
# correct pallet # and PSI — yet none showed "Merged" and no Un-merge button
# appeared. Root cause: a FIRST-STOCK birth line is left unflagged (so the
# pallet still counts +1), and it used to be left UNcaptured too — so once the
# detection tightened to "a real merge marker, not merely a shared pallet"
# (M/RR/05299 fix), these birth lines looked like plain multi-line encoding.
#
# Fix: the Merge button now CAPTURES every line it places, including a
# first-stock birth (still unflagged). Detection still requires the pallet to be
# SHARED, so a LONE birth line reads as a plain sole-owner line — but several
# lines birthing one Fixed pallet correctly show "Merged" and offer Un-merge.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ag_fixed_psi_multi_birth.py
#
# Rollback-only: nothing is committed.
import traceback

from odoo.exceptions import UserError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Wizard = env['pallet.merge.wizard']
    owner = env['res.partner'].browse(428)
    # Fixed client: ONE pinned pallet, one profile PSI, NOT multiple mode
    empty_fixed = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=1)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False,
                 'vifel_fixed_package_id': empty_fixed.id,
                 'vifel_fixed_psi': 'AGFX-000001'})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered(
            lambda m: m.product_id and m.result_package_id != empty_fixed)) >= 3)[:1]
    lines = picking.move_line_ids.filtered(
        lambda m: m.product_id and m.result_package_id != empty_fixed)[:3]
    check('AG0 found a 3+ line incoming receipt for the Fixed client',
          len(lines) == 3, picking.name if picking else None)

    def merge_onto_fixed(ml):
        w = Wizard.create({'move_line_id': ml.id})
        # Fixed mode offers exactly the pinned pallet, pre-selected
        tgt = w.candidate_line_ids.filtered('is_target')[:1]
        if not tgt:
            tgt = w.candidate_line_ids.filtered('eligible')[:1]
            tgt.is_target = True
        w.action_confirm()
        env.flush_all()

    if len(lines) == 3:
        l1, l2, l3 = lines
        for ml in (l1, l2, l3):
            merge_onto_fixed(ml)

        on_fixed = [l for l in (l1, l2, l3) if l.result_package_id == empty_fixed]
        check('AG1 all three lines were placed on the ONE Fixed pallet',
              len(on_fixed) == 3,
              [(l.x_studio_, l.result_package_id.name) for l in (l1, l2, l3)])
        check('AG2 all three adopted the profile PSI',
              all(l.x_studio_pallet_series_id == 'AGFX-000001'
                  for l in (l1, l2, l3)),
              [l.x_studio_pallet_series_id for l in (l1, l2, l3)])
        check('AG3 NONE is flagged is_pallet_merge — births count +1',
              not any(l.is_pallet_merge for l in (l1, l2, l3)))
        check('AG4 each birth line CAPTURED its pre-merge state (so it can '
              'un-merge)',
              all(l.vifel_premerge_captured for l in (l1, l2, l3)))
        check('AG5 all three now show "Merged" (the reported bug)',
              all(l.vifel_on_merged_pallet for l in (l1, l2, l3)),
              [l.vifel_on_merged_pallet for l in (l1, l2, l3)])

        # counting: three lines, one pallet -> +1
        def received_pkgs():
            return set(picking.move_line_ids.filtered(
                lambda m: m.result_package_id and not m.is_pallet_merge).mapped(
                'result_package_id.id'))
        check('AG6 the Fixed pallet is counted ONCE (+1) across the three lines',
              empty_fixed.id in received_pkgs()
              and len([m for m in picking.move_line_ids
                       if m.result_package_id == empty_fixed]) == 3)

        # ---- un-merge the THIRD line: it peels off; the other two stay ----
        l3.action_unmerge_pallet_line()
        env.flush_all()
        check('AG7 un-merge peeled line 3 off the Fixed pallet',
              l3.result_package_id != empty_fixed)
        check('AG8 lines 1 & 2 remain merged, pallet STILL counts +1',
              l1.result_package_id == empty_fixed
              and l2.result_package_id == empty_fixed
              and l1.vifel_on_merged_pallet and l2.vifel_on_merged_pallet
              and empty_fixed.id in received_pkgs())

        # ---- peel the SECOND: line 1 is now the sole owner -> plain line ----
        l2.action_unmerge_pallet_line()
        env.flush_all()
        check('AG9 with only line 1 left, it reads as a PLAIN sole-owner line '
              '(not merged) — nothing to peel it off from',
              not l1.vifel_on_merged_pallet, l1.vifel_on_merged_pallet)
        check('AG10 the lone line still holds the Fixed pallet (+1 preserved)',
              l1.result_package_id == empty_fixed
              and empty_fixed.id in received_pkgs())
        try:
            l1.action_unmerge_pallet_line()
            check('AG11 the sole line refuses Un-merge', False, 'no error')
        except UserError:
            check('AG11 the sole line refuses Un-merge', True)
    else:
        for n in ('AG1', 'AG2', 'AG3', 'AG4', 'AG5', 'AG6', 'AG7', 'AG8',
                  'AG9', 'AG10', 'AG11'):
            check(n + ' (no 3-line Fixed receipt in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
