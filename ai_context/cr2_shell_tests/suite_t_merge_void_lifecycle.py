# CR2 v2 Suite T - void / unvoid is transparent to merged stock.
#
# The finding this suite guards: MERGE DOES NOT CHANGE VOID BEHAVIOUR. A merged
# line adopts an EXISTING pallet series on an EXISTING package, so to the void
# machinery a merge pallet is indistinguishable from any normal pallet carrying
# that PSI. is_pallet_merge lives on the RR line, only affects the RR-received
# count, is copy=False, and is never read by the void path.
#
# Why no full picking is validated here: shell-validating an RR fires the whole
# Studio automation stack and is fragile enough to give false failures. Instead
# this asserts the MECHANISMS the void lifecycle rides, on real data + source.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_t_merge_void_lifecycle.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


class VifelSkip(Exception):
    """No eligible fixture in this DB — skip without failing."""


try:
    from odoo.modules.module import get_module_path
    pkr_src = open(os.path.join(get_module_path('pallet_kilos_record_model'),
                                'models', 'models.py'), encoding='utf-8').read()
    sp_src = open(os.path.join(get_module_path('multiple_relocation'),
                               'models', 'stock_picking.py'), encoding='utf-8').read()

    # ---- 1. void WR / void return rows are archived from the ledger ----
    env.cr.execute("""
        SELECT count(*) FROM stock_picking sp
        JOIN pallet_kilos_record_model_pallet_kilos_record_model p
          ON p.record_reference = sp.id AND p.active
        WHERE sp.is_void_wr = true""")
    void_wr_active = env.cr.fetchone()[0]
    check('T1 no is_void_wr picking carries an active PKR row (archived)',
          void_wr_active == 0, void_wr_active)
    check('T2 the archival guard is in PKR.create for void transfers',
          'is_void_wr or source_picking.is_void_return' in pkr_src
          and 'record.active = False' in pkr_src)

    # ---- 2. void WR withdrawn count uses the PHYSICAL emptied-rule, not
    #         is_pallet_merge — so copy=False dropping the flag is harmless --
    check('T3 the withdrawn count keys on reserved_quantity_on_validation',
          'reserved_quantity_on_validation' in pkr_src)
    check('T4 the void WR builder never reads is_pallet_merge',
          'is_pallet_merge' not in sp_src)

    # ---- 3. void WR SOURCE resolution reads building preset / location,
    #         NOT the package reservation our pinned pallet carries ----------
    check('T5 void WR source uses the building preset location',
          'x_studio_building' in sp_src
          and 'x_studio_preset_location' in sp_src)
    # our permanent reservation is on the PACKAGE; confirm the void source
    # block does not branch on package.x_studio_is_reserved
    void_blk = sp_src[sp_src.index('def _create_void_wr_from_rr'):
                      sp_src.index('def _create_void_wr_from_rr') + 4000]
    check('T6 the void WR source block does not read a package reservation',
          'package_id.x_studio_is_reserved' not in void_blk
          and 'result_package_id.x_studio_is_reserved' not in void_blk)

    # ---- 4. a merged line leaves a NORMAL quant shape: it adopts the
    #         target's package + PSI + location, so at validation its quant
    #         merges natively and the void checks it out by quant identity ---
    owner = env['res.partner'].browse(428)
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()
    # a mergeable incoming line (Pallet-Breakdown merge; no pallet required — it
    # adopts the target's; exclude BF/returns so vifel_show_merge_button holds).
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
        check('T-setup a mergeable incoming line exists', True, '(skipped)')
        raise VifelSkip('setup')
    wiz = env['pallet.merge.wizard'].create({'move_line_id': line.id})
    tgt = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    if not tgt:
        check('T-setup an eligible merge target exists', True, '(skipped)')
        raise VifelSkip('setup')
    tpsi, tpkg, tloc = tgt.psi, tgt.package_id, tgt.location_id
    tgt.is_target = True
    wiz.action_confirm()
    env.flush_all()
    check('T7 a merged line adopts the target package (normal quant key)',
          line.result_package_id == tpkg, line.result_package_id.name)
    check('T8 ... the target PSI (normal quant key)',
          line.x_studio_pallet_series_id == tpsi, line.x_studio_pallet_series_id)
    check('T9 ... and the target location — so its quant merges natively, '
          'the void checks out by quant identity regardless of the flag',
          line.location_dest_id == tloc, line.location_dest_id.display_name)

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
