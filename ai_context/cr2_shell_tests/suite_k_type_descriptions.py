# CR2 v2 Suite K - pallet type descriptions and their backfill.
#
# The four seeded types are MDGM Mildly Damaged, SDMG Semi Damaged,
# TDMG Totally Damaged and BOC Client Static PSI (user-supplied wording,
# 2026-07-22). Note BOC is NOT a damage grade - it is the client's own
# static pallet - which is why the UI group is "Pallet Types" and not
# "condition pallets".
#
# Earlier rows were seeded with the bare code as their description because
# the wording was unknown. Re-saving the client profile backfills those,
# but must NEVER overwrite a description someone has edited (D5).
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_k_type_descriptions.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
P,F=[],[]
def check(n,c,d=''):
    (P if c else F).append(n); print(('PASS ' if c else 'FAIL ')+n+('' if c else '  -> %s'%(d,)))
try:
    from odoo.addons.vifel_client_requirements.models.vifel_psi_type import SEED_TYPES
    owner = env['res.partner'].browse(428)
    # simulate a client seeded BEFORE the descriptions were known
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True})
    env.flush_all()
    for t in owner.vifel_psi_type_ids:
        t.name = t.prefix                      # the old bare-code state
    env.flush_all()
    check('D1 rows start as bare codes (pre-fix state)',
          all(t.name == t.prefix for t in owner.vifel_psi_type_ids))

    # one row deliberately customised by a configurer
    boc = owner.vifel_psi_type_ids.filtered(lambda x: x.prefix == 'BOC')
    boc.name = 'Their own pallet'
    env.flush_all()

    owner.write({'vifel_multiple_pallet_support': True})   # re-save profile
    env.invalidate_all()
    got = {t.prefix: t.name for t in owner.vifel_psi_type_ids}
    print('   after backfill: %s' % got)
    check('D2 MDGM backfilled', got.get('MDGM') == 'Mildly Damaged', got.get('MDGM'))
    check('D3 SDMG backfilled', got.get('SDMG') == 'Semi Damaged', got.get('SDMG'))
    check('D4 TDMG backfilled', got.get('TDMG') == 'Totally Damaged', got.get('TDMG'))
    check('D5 a CUSTOMISED description is never overwritten',
          got.get('BOC') == 'Their own pallet', got.get('BOC'))

    # a brand-new client gets descriptions from the start
    fresh = env['res.partner'].create({'name': 'ZZ TEST CLIENT',
                                       'vifel_can_merge_pallets': True,
                                       'vifel_multiple_pallet_support': True})
    env.flush_all()
    new = {t.prefix: t.name for t in fresh.vifel_psi_type_ids}
    check('D6 a new client is seeded with descriptions, not codes',
          new == dict(SEED_TYPES), new)
    check('D7 seeding is still idempotent (4 rows)',
          len(fresh.vifel_psi_type_ids) == 4, len(fresh.vifel_psi_type_ids))
except Exception:
    traceback.print_exc(); F.append('exc')
env.cr.rollback()
print('RESULT: %d passed, %d failed' % (len(P),len(F)))
