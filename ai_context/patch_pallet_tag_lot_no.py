# Print the client Lot No. on the Pallet Tag Form, directly below the Batch #.
#
# WHY a script: the Pallet Tag Form is a STUDIO report, so its template lives in
# ir.ui.view IN THE DATABASE and does NOT travel with a git merge - the same
# trap as the Inbound Data Template (COMP-2026-00046) and the Deviation Report
# (COMP-2026-00050). RUN THIS ONCE PER DATABASE.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/patch_pallet_tag_lot_no.py
#
# No code change accompanies this one: the Lot No. hooks it calls already ship
# in multiple_relocation (falsy defaults) and vifel_client_requirements (the
# real values), and have been live since the 2026-08-18 deployment.
#
# DRY_RUN prints what it would do and commits nothing.
DRY_RUN = True

# There are THREE pallet tag reports. Only this one carries the Batch #, by the
# user's decision on 2026-08-17; the other two (views 1155 "copy(1)" and 1160
# "MAT COPY") were deliberately left plain. Lot No. follows Batch #, so it goes
# on the same one. Add the other keys here if that decision changes.
VIEW_KEYS = [
    'studio_customization.studio_report_docume_'
    '345e0dbd-6a9e-441f-9196-40eecdf0cc24_document',
]

# The Batch # block, verbatim, as Studio wrote it -- irregular indentation and
# all. Used as the anchor so the Lot No. lands immediately BELOW it.
BATCH_BLOCK = (
    '<t t-if="lines.picking_id.show_batch_no">\n'
    '                          <tr style="height: 50px;">\n'
    '                            <td style="vertical-align: middle; font-weight: bold;">\n'
    '                              <h4 style="font-weight: bold;">Batch #:</h4>\n'
    '                        </td>\n'
    '                            <td style="vertical-align: middle; font-weight: bold;" colspan="3">\n'
    '                              <h4 style="font-weight: bold;">\n'
    '                                <t t-esc="lines.batch_no or \'\'"/>\n'
    '                              </h4>\n'
    '                            </td>\n'
    '                        </tr>\n'
    '                        </t>'
)

# Same shape and styling as the Batch # row, so the two read as a pair.
#
# Gated on the client's own profile flag through the report hooks, exactly as
# the RR/WR reports do -- never on the add-on's fields directly, so the tag
# still renders on a database where vifel_client_requirements is absent:
#   _vifel_report_show_lot_no()      -> the client's profile flag
#   _vifel_report_lot_no(move_line)  -> typed on a receipt, quant read-back on a
#                                       withdrawal (tags are receipts, so typed)
LOT_BLOCK = (
    '\n'
    '                        <t t-if="lines.picking_id._vifel_report_show_lot_no()">\n'
    '                          <tr style="height: 50px;">\n'
    '                            <td style="vertical-align: middle; font-weight: bold;">\n'
    '                              <h4 style="font-weight: bold;">Lot No.:</h4>\n'
    '                            </td>\n'
    '                            <td style="vertical-align: middle; font-weight: bold;" colspan="3">\n'
    '                              <h4 style="font-weight: bold;">\n'
    '                                <t t-esc="lines.picking_id._vifel_report_lot_no(lines) or \'\'"/>\n'
    '                              </h4>\n'
    '                            </td>\n'
    '                          </tr>\n'
    '                        </t>'
)

MARKER = '_vifel_report_lot_no(lines)'

for key in VIEW_KEYS:
    view = env.ref(key, raise_if_not_found=False) or env['ir.ui.view'].search(
        [('key', '=', key)], limit=1)
    if not view:
        print('SKIP: template %s not found on this database.' % key)
        continue

    # arch_base, not arch_db: arch_db is translation-encoded, arch_base is the
    # plain source Studio itself reads and writes
    arch = view.arch_base
    if MARKER in arch:
        print('SKIP: view %s already prints the Lot No.' % view.id)
        continue
    if arch.count(BATCH_BLOCK) != 1:
        # Studio has been used on this template since the block was captured -
        # stop rather than guess where "below the Batch #" is
        print('ABORT: view %s does not contain exactly one Batch # block '
              '(found %d). Add the Lot No. row by hand in Studio, directly '
              'below the Batch # row.' % (view.id, arch.count(BATCH_BLOCK)))
        continue

    new_arch = arch.replace(BATCH_BLOCK, BATCH_BLOCK + LOT_BLOCK)
    print('view %s: Lot No. row will be inserted directly below the Batch # row'
          % view.id)
    if DRY_RUN:
        print('DRY RUN - nothing written. Set DRY_RUN = False to apply.')
    else:
        view.write({'arch_base': new_arch})
        env.cr.commit()
        print('APPLIED and committed.')

print('\nReminder: the Lot No. only prints for clients whose profile has it '
      'enabled (res.partner show_client_lot_no), exactly like the Batch #. '
      'A client with the flag off prints neither, which is not a fault.')
