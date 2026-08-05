# CR2 v2 Suite A - client profile, PSI types, prefix routing, audit.
#
# Seeding is idempotent; special series never enter the client's normal
# numbers; a series live on stocked quants is never recycled; and a
# type-pool recycle still reaches the pallet series audit trail (this
# module's override runs BEFORE the audit wrapper, so it logs explicitly).
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_a_profile_routing.py
#
# Rollback-only: nothing is committed.
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    Partner = env['res.partner']

    # ---- MRO: who wraps whom on push_unused_pallet? -------------------
    order = [c.__module__ for c in type(Partner).__mro__
             if 'push_unused_pallet' in c.__dict__]
    print('push_unused_pallet override order (outermost first):')
    for m in order:
        print('    %s' % m)
    check('A0 routing runs BEFORE the audit wrapper (documents the real MRO)',
          len(order) >= 2
          and 'vifel_client_requirements' in order[0]
          and 'pallet_series_audit' in order[1], order)

    # ---- a merge-enabled client with special types --------------------
    partner = Partner.search([('x_studio_client_unique_code_1', '!=', False)],
                             limit=1)
    print('test client: %s (code %s)' % (partner.display_name,
                                         partner.x_studio_client_unique_code_1))

    partner.write({'vifel_can_merge_pallets': True,
                   'vifel_multiple_pallet_support': True})
    env.flush_all()
    types = partner.vifel_psi_type_ids
    check('A1 seeding created the 4 standard types (%s)'
          % ', '.join(sorted(types.mapped('prefix'))), len(types) == 4, len(types))

    partner.write({'vifel_multiple_pallet_support': True})   # re-flip
    env.flush_all()
    check('A2 seeding is idempotent', len(partner.vifel_psi_type_ids) == 4,
          len(partner.vifel_psi_type_ids))

    sdmg = types.filtered(lambda t: t.prefix == 'SDMG')
    s1 = sdmg.draw_number()
    check('A3 draw_number formats prefix-zfill(6) (%s)' % s1,
          s1 == 'SDMG-000001', s1)

    # ---- routing: a special number must NOT enter the normal pool -----
    normal_before = list(partner.unused_pallet_series_ids or [])
    Audit = env['pallet.series.audit.line']
    audit_before = Audit.search_count([])

    # log_event SILENTLY skips validated/cancelled/return pickings — the
    # audit assertions are meaningless unless the picking is still open.
    picking = env['stock.picking'].search(
        [('picking_type_id.code', '=', 'incoming'),
         ('state', 'not in', ('done', 'cancel')),
         ('return_id', '=', False)], limit=1)
    print('audit picking: %s (state %s)' % (picking.name, picking.state))
    check('A3b found an OPEN incoming picking for the audit assertions',
          bool(picking), 'no open RR — A6/A7 would be vacuous')
    partner.with_context(audit_picking_id=picking.id,
                         audit_source='wizard').push_unused_pallet(s1)
    env.flush_all()

    normal_after = list(partner.unused_pallet_series_ids or [])
    check('A4 special series did NOT enter the normal pool',
          normal_after == normal_before, (normal_before, normal_after))
    check('A5 special series went back to its OWN type pool',
          1 in (sdmg.number_pool or []), sdmg.number_pool)

    audit_after = Audit.search_count([])
    check('A6 special-type recycle IS audited (audit rows %d -> %d)'
          % (audit_before, audit_after), audit_after > audit_before,
          'no audit row written for the type-pool recycle')

    # ---- a NORMAL series still audits (regression on the super chain) --
    code = (partner.x_studio_client_unique_code_1 or '').strip()
    normal_series = '%s-%s' % (code, str(999123).zfill(6))
    audit_before2 = Audit.search_count([])
    partner.with_context(audit_picking_id=picking.id,
                         audit_source='wizard').push_unused_pallet(normal_series)
    env.flush_all()
    check('A7 normal recycle still reaches the audit wrapper',
          Audit.search_count([]) > audit_before2, 'super() chain broken')
    check('A8 normal recycle still lands in the normal pool',
          999123 in (partner.unused_pallet_series_ids or []),
          partner.unused_pallet_series_ids)

    # ---- stocked guard -------------------------------------------------
    q = env['stock.quant'].search([('x_studio_pallet_series_id', '!=', False),
                                   ('location_id.usage', '=', 'internal'),
                                   ('quantity', '>', 0)], limit=1)
    stocked = q.x_studio_pallet_series_id
    owner = q.owner_id or partner
    pool_before = list(owner.unused_pallet_series_ids or [])
    owner.push_unused_pallet(stocked)
    env.flush_all()
    check('A9 a series live on stocked quants is refused (%s)' % stocked,
          list(owner.unused_pallet_series_ids or []) == pool_before,
          (pool_before, owner.unused_pallet_series_ids))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
