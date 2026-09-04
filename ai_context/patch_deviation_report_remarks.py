# Print the per-item Concern/Remarks on the Deviation Report (COMP-2026-00050).
#
# WHY: TL Gemma reported (M/RR/06513) that the Deviation Report cannot be used
# because there is nowhere to put remarks per item. The printed form HAS a
# "Concern/Remarks" column - but in the template the cell inside the per-item
# loop is a self-closing, permanently EMPTY <td>, so the column printed blank
# on every copy ever produced. The only remarks field that existed was
# stock.picking.x_studio_ncr_remarks, which is the document-wide "Description
# of Deviation" box at the top of the sheet, not the per-item column.
#
# The code side of this ships in multiple_relocation: stock.move now carries
# vifel_deviation_remarks, shown as a "Concern/Remarks" column in the
# Operations tab of the receipt (editable after validation, because the
# Deviation Report is printed after the receipt is verified).
#
# This script is the other half. The Deviation Report is a STUDIO report, so
# its template lives in ir.ui.view IN THE DATABASE and does NOT travel with a
# git merge - the same trap as the deleted Inbound Data Template
# (COMP-2026-00046). RUN THIS ONCE PER DATABASE, alongside deploying the code.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/patch_deviation_report_remarks.py
#
# DRY_RUN prints what it would do and commits nothing.
DRY_RUN = True

VIEW_KEY = ('studio_customization.studio_report_docume_'
            'fce63407-724b-402b-bbd7-34c49f6c89e2_document')

# the empty cell, exactly as Studio wrote it (verified unique in the arch)
EMPTY_CELL = (
    '<td style="border: 1px solid black; padding: 5px; height: 50px; '
    'max-height: 50px; vertical-align: middle; overflow: hidden;"/>')

# same styling, plus the value; word-wrap so a long concern does not
# overflow the fixed-height row
FILLED_CELL = (
    '<td style="border: 1px solid black; padding: 5px; height: 50px; '
    'max-height: 50px; vertical-align: middle; overflow: hidden; '
    'word-wrap: break-word;">'
    '<span t-esc="line.vifel_deviation_remarks"/>'
    '</td>')

view = env.ref(VIEW_KEY, raise_if_not_found=False)
if not view:
    view = env['ir.ui.view'].search([('key', '=', VIEW_KEY)], limit=1)

if not view:
    print('SKIP: Deviation Report template %s not found in this database.'
          % VIEW_KEY)
else:
    # arch_base, not arch_db: arch_db is translation-encoded, arch_base is the
    # plain source Studio itself reads and writes
    arch = view.arch_base
    if 'vifel_deviation_remarks' in arch:
        print('SKIP: view %s already prints vifel_deviation_remarks.' % view.id)
    elif arch.count(EMPTY_CELL) != 1:
        # the template was edited in Studio since this was written - stop
        # rather than guess which cell is the Concern column
        print('ABORT: expected exactly 1 empty Concern/Remarks cell in view '
              '%s, found %d. Patch the column by hand in Studio instead.'
              % (view.id, arch.count(EMPTY_CELL)))
    else:
        new_arch = arch.replace(EMPTY_CELL, FILLED_CELL)
        print('view %s: Concern/Remarks column will print '
              'line.vifel_deviation_remarks' % view.id)
        if DRY_RUN:
            print('DRY RUN - nothing written. Set DRY_RUN = False to apply.')
        else:
            view.write({'arch_base': new_arch})
            env.cr.commit()
            print('APPLIED and committed.')
