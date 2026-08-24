# Recreate the "Inbound Data Template" export template (COMP-2026-00046).
#
# WHY: AI ABI reported the Inbound Data Template no longer appears when
# exporting a client's inbound details. It was DELETED from ir.exports some time
# between 2026-08-18 and 2026-08-21 - it is present in the 07-28, 08-16 and
# 08-18 production backups (id 29, stock.move.line, 17 fields, identical in all
# three) and absent from the 08-24 one. Export templates are global per model
# (ir.exports has no user column), so this was never a visibility problem.
#
# A stopgap template called "inbound" was created on 08-21 with a different and
# largely unrelated field set - it is left alone; this only restores the
# original.
#
# Field list reconstructed from the three backups, which agree exactly.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/restore_inbound_data_template.py
#
# DRY_RUN prints what it would do and commits nothing.
DRY_RUN = True

NAME = 'Inbound Data Template'
MODEL = 'stock.move.line'
FIELDS = [
    'date',
    'picking_id',
    'picking_id/x_studio_source',
    'picking_id/x_studio_trucks_plate_',
    'picking_id/x_studio_gate_pass',
    'x_studio_pallet_series_id',
    'product_id',
    'picking_id/x_studio_container_',
    'x_studio_production_date',
    'x_studio_expiration_date',
    'x_studio_2nd_uom',
    'x_studio_quantity_uom',
    'quantity',
    'product_uom_id',
    'picking_id/x_studio_building_1',
    'picking_id/documentation_staff_id',
    'location_dest_id',
]

Exports = env['ir.exports']
existing = Exports.search([('name', '=', NAME), ('resource', '=', MODEL)])
if existing:
    print('Already present (id %s) - nothing to do.' % existing.ids)
else:
    # Every path must still resolve, or the template would be broken on arrival.
    print('Checking the %d field paths against %s ...' % (len(FIELDS), MODEL))
    bad = []
    for path in FIELDS:
        model, parts = MODEL, path.split('/')
        for i, part in enumerate(parts):
            fields = env[model]._fields
            if part not in fields:
                bad.append('%s  (%s not on %s)' % (path, part, model))
                break
            f = fields[part]
            if i < len(parts) - 1:
                if not f.comodel_name:
                    bad.append('%s  (%s is not relational)' % (path, part))
                    break
                model = f.comodel_name
    if bad:
        print('  BROKEN paths - not creating anything:')
        for b in bad:
            print('   -', b)
    else:
        print('  all %d resolve.' % len(FIELDS))
        if DRY_RUN:
            print('\nDRY RUN - would create "%s" on %s with:' % (NAME, MODEL))
            for i, f in enumerate(FIELDS, 1):
                print('  %2d. %s' % (i, f))
            print('\nSet DRY_RUN = False to apply.')
        else:
            rec = Exports.create({
                'name': NAME,
                'resource': MODEL,
                'export_fields': [(0, 0, {'name': f}) for f in FIELDS],
            })
            env.cr.commit()
            print('\nCreated "%s" (id %s) with %d fields. COMMITTED.'
                  % (NAME, rec.id, len(rec.export_fields)))
