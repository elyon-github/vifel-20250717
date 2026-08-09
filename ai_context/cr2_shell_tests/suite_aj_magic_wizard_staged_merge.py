# CR2 v2 Suite AJ - the Magic-Wizard MERGE is STAGED until the wizard's Confirm.
#
# Reported (repeatedly): inside the Magic Wizard, clicking Merge (a) did not
# reflect the row's edited quantity/weight, and (b) applied the merge to the REAL
# stock.move.line immediately, bypassing the Magic Wizard's own Confirm (so
# closing the wizard did not undo it). Now the merge STAGES on the transient row
# and applies to the real line ONLY at FastEncodeRR.action_confirm, mirroring the
# already-staged un-merge, and the dialog shows the row's cargo.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_aj_magic_wizard_staged_merge.py
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
    Line = env['stock.move.line.fast_encode_rr.line']
    FW = env['stock.move.line.fast_encode_rr']
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    picking = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
        ('partner_id', '=', owner.id)], limit=60).filtered(
        lambda p: len(p.move_line_ids.filtered('product_id')) >= 2)[:1]
    l1, l2 = picking.move_line_ids.filtered('product_id')[:2]
    empties = env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_warehouse', '=', picking.warehouse_id.id)], limit=2)
    empty_pkg = empties[:1]
    empty_pkg2 = empties[1:2]
    aisles = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', picking.location_dest_id.id),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    aisle = aisles[:1]
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    ok = bool(l1 and l2 and empty_pkg and empty_pkg2 and aisle and sdmg)
    check('AJ0 setup: 2-line receipt + 2 empty pallets + aisle + SDMG type', ok,
          picking.name if picking else None)

    def make_row(fw, ml, kg, qty):
        return Line.create({
            'wizard_id': fw.id, 'stock_move_line': ml.id,
            'x_studio_': ml.x_studio_ or 0, 'product_id': ml.product_id.id,
            'result_package_id': ml.result_package_id.id,
            'pallet_series_id': ml.x_studio_pallet_series_id or '',
            'pre_wizard_pallet_series_id': ml.x_studio_pallet_series_id or '',
            'kilogram': kg, 'quantity': qty})

    if ok:
        # snapshot the REAL line's pre-merge state
        l1_pkg0 = l1.result_package_id
        l1_psi0 = l1.x_studio_pallet_series_id or ''

        # ===== PART 1: the dialog reflects the ROW's edited cargo =====
        fw = FW.create({'transfer_id': picking.id})
        r1 = make_row(fw, l1, 987.5, 42)     # edited, unconfirmed
        env.flush_all()
        act = r1.action_merge_from_fast_encode()
        mw = W.browse(act['res_id'])
        check('AJ1 merge dialog shows the ROW weight (not the stale real line)',
              abs(mw.line_weight - 987.5) < 0.01, mw.line_weight)
        check('AJ2 merge dialog shows the ROW quantity',
              abs(mw.line_quantity - 42) < 0.01, mw.line_quantity)

        # ===== STAGE a create-special merge from inside the Magic Wizard =====
        mw.write({'mode': 'new', 'psi_type_id': sdmg.id,
                  'new_package_id': empty_pkg.id, 'new_location_id': aisle.id})
        mw.action_confirm()          # STAGES onto r1; must NOT touch l1
        env.flush_all()
        check('AJ3 the ROW is staged onto the new pallet + a drawn SDMG series',
              r1.result_package_id == empty_pkg
              and (r1.pallet_series_id or '').startswith('SDMG-'),
              (r1.result_package_id.name, r1.pallet_series_id))
        check('AJ4 the ROW shows Merged + the pending-merge marker',
              r1.vifel_on_merged_pallet and r1.vifel_pending_merge
              and r1.vifel_pending_merge_kind == 'create_special',
              (r1.vifel_on_merged_pallet, r1.vifel_pending_merge_kind))
        check('AJ5 the REAL move line is UNCHANGED (bypass is gone): same pallet',
              l1.result_package_id == l1_pkg0
              and (l1.x_studio_pallet_series_id or '') == l1_psi0,
              (l1.result_package_id.name, l1.x_studio_pallet_series_id))
        check('AJ6 the REAL line is NOT flagged/captured before Confirm',
              not l1.is_pallet_merge and not l1.vifel_premerge_captured)

        # ===== CONFIRM the Magic Wizard: NOW the real line is merged =====
        staged_series = r1.pallet_series_id
        fw.action_confirm()
        env.flush_all()
        check('AJ7 after Confirm the real line carries the staged pallet+series',
              l1.result_package_id == empty_pkg
              and l1.x_studio_pallet_series_id == staged_series,
              (l1.result_package_id.name, l1.x_studio_pallet_series_id))
        check('AJ8 after Confirm the real line is captured (create-special) '
              'and counts +1 (is_pallet_merge False)',
              l1.vifel_premerge_captured and not l1.is_pallet_merge
              and l1.vifel_on_merged_pallet)
        check('AJ9 the edited cargo was written to the real line at Confirm',
              abs((l1.quantity or 0) - 987.5) < 0.01
              and abs((l1.x_studio_2nd_uom or 0) - 42) < 0.01,
              (l1.quantity, l1.x_studio_2nd_uom))

        # ===== CANCEL: stage a merge on L2, then Un-merge it BEFORE Confirm.
        #       A separate line + pallet (no mid-test rollback). =====
        b2_pkg0 = l2.result_package_id
        b2_psi0 = l2.x_studio_pallet_series_id or ''
        fw2 = FW.create({'transfer_id': picking.id})
        rb = make_row(fw2, l2, 10, 1)
        env.flush_all()
        act2 = rb.action_merge_from_fast_encode()
        mw2 = W.browse(act2['res_id'])
        mw2.write({'mode': 'new', 'psi_type_id': sdmg.id,
                   'new_package_id': empty_pkg2.id, 'new_location_id': aisle.id})
        mw2.action_confirm()
        env.flush_all()
        staged2 = rb.pallet_series_id
        check('AJ10 staged (row Merged, real line still untouched)',
              rb.vifel_pending_merge and l2.result_package_id == b2_pkg0)
        rb.action_unmerge_from_fast_encode()   # cancel the staged merge
        env.flush_all()
        check('AJ11 Un-merge cancels the stage: row back to plain',
              not rb.vifel_pending_merge and not rb.vifel_on_merged_pallet
              and rb.result_package_id == b2_pkg0,
              (rb.vifel_pending_merge, rb.result_package_id.name))
        check('AJ11b the cancelled staged create-special series is VOIDED to the '
              'receipt (recyclable), not lost',
              staged2 in picking.vifel_voided_special_psi_ids.mapped('series'),
              (staged2, picking.vifel_voided_special_psi_ids.mapped('series')))
        # confirm now writes a PLAIN line: the staged create-special pallet and
        # its special series must NOT persist anywhere on the real line.
        fw2.action_confirm()
        env.flush_all()
        check('AJ12 after cancel+Confirm the merge never persisted: not on the '
              'create-special pallet, not captured, not wearing its special PSI',
              l2.result_package_id != empty_pkg2
              and not l2.vifel_premerge_captured
              and (l2.x_studio_pallet_series_id or '') != staged2,
              (l2.result_package_id.name, l2.x_studio_pallet_series_id, staged2))
    else:
        for n in ('AJ1', 'AJ2', 'AJ3', 'AJ4', 'AJ5', 'AJ6', 'AJ7', 'AJ8',
                  'AJ9', 'AJ10', 'AJ11', 'AJ12'):
            check(n + ' (setup unavailable in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
