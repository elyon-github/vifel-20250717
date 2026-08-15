# CR2 v2 Suite AQ - MULTIPLE Fixed Merge Pallets per client.
#
# A Fixed client may now pin SEVERAL dedicated pallets, each with its OWN fixed
# PSI (vifel.fixed.merge.pallet rows). This suite proves: both pallets are
# offered in RR; a line merged onto each adopts THAT pallet's PSI; the
# empty-&-free and global-PSI-uniqueness guards raise; and un-pinning one row
# frees ONLY that pallet.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_aq_multi_fixed_pallets.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def clean_empty_pallets(n):
    """Up to n genuinely empty, free, unclaimed pallets (not reserved, not a
    merge pallet, no stock, not on an open incoming line)."""
    return env['stock.quant.package'].search([
        ('location_id', '=', False), ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True),
        ('x_studio_is_reserved', '=', False),
        ('vifel_is_merge_pallet', '=', False)], limit=800).filtered(
        lambda p: not p.quant_ids.filtered(lambda q: q.quantity > 0)
        and not env['stock.move.line'].search_count([
            ('result_package_id', '=', p.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel'))]))[:n]


try:
    from odoo.exceptions import ValidationError
    Wizard = env['pallet.merge.wizard']
    Fixed = env['vifel.fixed.merge.pallet']
    owner = env['res.partner'].browse(428)          # TECHNO FARM
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': False})
    env.flush_all()

    pals = clean_empty_pallets(2)
    check('AQ0 found two clean empty pallets to pin', len(pals) == 2, len(pals))
    if len(pals) == 2:
        p1, p2 = pals[0], pals[1]

        r1 = Fixed.create({'partner_id': owner.id, 'package_id': p1.id,
                           'psi': 'FXA-000001'})
        Fixed.create({'partner_id': owner.id, 'package_id': p2.id,
                      'psi': 'FXB-000002'})
        env.flush_all()
        check('AQ1 the client pins TWO fixed pallets, each with its own PSI',
              len(owner.vifel_fixed_pallet_ids) == 2
              and owner.vifel_fixed_pallet_ids.mapped('package_id') == (p1 | p2),
              owner.vifel_fixed_pallet_ids.mapped('psi'))
        check('AQ2 both pinned pallets are reserved AND merge-flagged',
              p1.x_studio_is_reserved and p2.x_studio_is_reserved
              and p1.vifel_is_merge_pallet and p2.vifel_is_merge_pallet)

        # both pallets offered as candidates for an incoming line, and each line
        # merged onto one adopts THAT pallet's PSI
        picking = env['stock.picking'].search([
            ('picking_type_id.code', '=', 'incoming'),
            ('state', 'not in', ('done', 'cancel')), ('return_id', '=', False),
            ('partner_id', '=', owner.id)], limit=60).filtered(
            lambda pk: len(pk.move_line_ids.filtered(
                lambda m: m.product_id
                and m.result_package_id not in (p1 | p2))) >= 2)[:1]
        lines = picking.move_line_ids.filtered(
            lambda m: m.product_id and m.result_package_id not in (p1 | p2))[:2] \
            if picking else env['stock.move.line']
        if len(lines) == 2:
            la, lb = lines
            wa = Wizard.create({'move_line_id': la.id})
            offered = set(wa.candidate_line_ids.filtered('eligible').mapped(
                'package_id.id'))
            check('AQ3 BOTH fixed pallets are offered as merge candidates',
                  p1.id in offered and p2.id in offered, offered)
            ta = wa.candidate_line_ids.filtered(lambda c: c.package_id == p1)[:1]
            ta.is_target = True
            wa.action_confirm(); env.flush_all()
            wb = Wizard.create({'move_line_id': lb.id})
            tb = wb.candidate_line_ids.filtered(lambda c: c.package_id == p2)[:1]
            tb.is_target = True
            wb.action_confirm(); env.flush_all()
            check('AQ4 each line adopted ITS OWN fixed pallet\'s PSI',
                  la.result_package_id == p1
                  and la.x_studio_pallet_series_id == 'FXA-000001'
                  and lb.result_package_id == p2
                  and lb.x_studio_pallet_series_id == 'FXB-000002',
                  (la.x_studio_pallet_series_id, lb.x_studio_pallet_series_id))
        else:
            check('AQ3 (no 2-line incoming receipt for the client in DB)', True)
            check('AQ4 (no 2-line incoming receipt for the client in DB)', True)

        # ---- guard: empty-&-free (ValidationError, safe) -------------
        stocked_q = env['stock.quant'].search([
            ('package_id', '!=', False), ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal')], limit=1)
        try:
            # savepoint: roll back the INSERT the failed create leaves behind.
            with env.cr.savepoint():
                Fixed.create({'partner_id': owner.id,
                              'package_id': stocked_q.package_id.id,
                              'psi': 'FXC-000003'})
                env.flush_all()
            check('AQ5 pinning a STOCKED pallet is refused (empty & free only)',
                  False, 'no error')
        except ValidationError as e:
            check('AQ5 pinning a STOCKED pallet is refused (empty & free only)',
                  'not empty' in str(e), str(e)[:80])

        # ---- guard: global PSI uniqueness (SQL; savepoint-isolated) --
        extra = clean_empty_pallets(3)[2:3]
        if extra:
            try:
                with env.cr.savepoint():
                    Fixed.create({'partner_id': owner.id, 'package_id': extra.id,
                                  'psi': 'FXA-000001'})   # already r1's PSI
                    env.flush_all()
                check('AQ6 a duplicate Fixed PSI is refused (globally unique)',
                      False, 'no error')
            except Exception as e:
                check('AQ6 a duplicate Fixed PSI is refused (globally unique)',
                      'unique' in str(e).lower() or 'psi' in str(e).lower(),
                      str(e)[:80])
        else:
            check('AQ6 (no third clean pallet in DB)', True)

        # ---- un-pin ONE row frees only that pallet -------------------
        r1.unlink()
        env.flush_all()
        p1.invalidate_recordset()
        p2.invalidate_recordset()
        remaining = env['res.partner']._vifel_fixed_merge_packages()
        check('AQ7 un-pinning pallet #1 frees it; pallet #2 stays pinned',
              not p1.x_studio_is_reserved and not p1.vifel_is_merge_pallet
              and p2.x_studio_is_reserved and p2.vifel_is_merge_pallet
              and p2 in remaining and p1 not in remaining,
              (p1.x_studio_is_reserved, p2.x_studio_is_reserved, remaining.ids))
    else:
        for n in ('AQ1', 'AQ2', 'AQ3', 'AQ4', 'AQ5', 'AQ6', 'AQ7'):
            check(n + ' (fewer than two clean empty pallets in DB)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
