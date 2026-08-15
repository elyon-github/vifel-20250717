# One-time backfill: legacy single Fixed pallet/PSI -> vifel.fixed.merge.pallet.
#
# WHEN TO RUN: only on a DB that already had the OLD single Fixed fields with data
# (existing dev/test DBs, e.g. vifel_08_03_2026, CR2-test clones). A FRESH
# production install of vifel_client_requirements never had those columns, so this
# script no-ops there — nothing to do at go-live.
#
# WHY A SCRIPT (not a module migration): the manifest version stays PINNED, so an
# Odoo version-gated migration would never fire. Run this once per legacy DB.
#
# Raw SQL on purpose: it bypasses the model's empty-&-free create guard (a migrated
# pallet legitimately already holds stock / is reserved from the original pin), and
# reads the now-orphan legacy columns directly. Idempotent (a pallet that already
# has a row is skipped; ON CONFLICT covers the unique(package_id)/unique(psi)).
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/backfill_fixed_merge_pallets.py
cr = env.cr
cr.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'res_partner'
      AND column_name IN ('vifel_fixed_package_id', 'vifel_fixed_psi')
""")
cols = {r[0] for r in cr.fetchall()}
if 'vifel_fixed_package_id' not in cols or 'vifel_fixed_psi' not in cols:
    print('No legacy Fixed pallet columns present — nothing to backfill.')
else:
    cr.execute("""
        INSERT INTO vifel_fixed_merge_pallet
            (partner_id, package_id, psi,
             create_uid, write_uid, create_date, write_date)
        SELECT p.id, p.vifel_fixed_package_id, UPPER(TRIM(p.vifel_fixed_psi)),
               1, 1, (now() at time zone 'UTC'), (now() at time zone 'UTC')
        FROM res_partner p
        WHERE p.vifel_fixed_package_id IS NOT NULL
          AND COALESCE(TRIM(p.vifel_fixed_psi), '') <> ''
          AND NOT EXISTS (
              SELECT 1 FROM vifel_fixed_merge_pallet f
              WHERE f.package_id = p.vifel_fixed_package_id)
        ON CONFLICT DO NOTHING
    """)
    migrated = cr.rowcount
    cr.execute("""
        SELECT COUNT(*) FROM res_partner p
        WHERE p.vifel_fixed_package_id IS NOT NULL
          AND COALESCE(TRIM(p.vifel_fixed_psi), '') <> ''
    """)
    total = cr.fetchone()[0]
    env.cr.commit()
    note = '' if migrated == total else \
        '  (shortfall = a package/PSI collision was skipped — review those clients)'
    print('Backfilled %s of %s legacy Fixed pallet(s). COMMITTED.%s'
          % (migrated, total, note))
