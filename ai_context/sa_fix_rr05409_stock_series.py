# ============================================================================
# SERVER ACTION - Relabel M/RR/05409 stock with the receipt's own pallet series
#   Settings -> Technical -> Server Actions -> New
#   Model: Quants (stock.quant), Action To Do: Execute Code.
#   Paste everything below the divider, save, then click "Run".
#
# WHY: M/RR/05409 (CDO-RM 8, validated 2026-08-05) re-received the 39 pallets
# of the voided M/RR/05265. Its receipt lines and the printed pallet tags carry
# CDP-013433..013510 (+ CDP-023611), but the stock kept RR/05265's old series
# CDP-013394..013432, so Void Transfer cannot find the stock by series.
#
# WHAT IT DOES: for 39 pallets, sets stock.quant.x_studio_pallet_series_id to
# the series on that pallet's M/RR/05409 line. Nothing else changes - no
# quantity, location, package or receipt reference is touched.
#
# NB 5710 / NP 1364: the RR/05409 line for CDP-013508 still says pallet NB 5710,
# but its 747.5 kg was moved to pallet NP 1364 by stock correction
# ADJ/2026/0565 (2026-09-10, "ADJUSTMENT OF PALLET NO."). So that row fixes the
# stock on NP 1364 and checks the receipt line on NB 5710. The 75 kg on NB 5710
# (return M/RR/07092, also CDP-013430) is NOT touched.
# CONFIRM FIRST that the physical tag on NP 1364 reads CDP-013508.
#
# SAFETY
#   * DRY_RUN = True (default): checks every row and shows a report. Writes
#     nothing. Set DRY_RUN = False only after the report says all 39 are OK.
#   * All-or-nothing: if ANY row fails a check, nothing is written.
#   * A pallet is matched by pallet name + its CURRENT old series + owner, not
#     by quant id, because every relocation creates a new quant.
#   * A row is refused when: the pallet holds no stock under the old series,
#     or holds more than one stock row for it, or the stock is not from
#     M/RR/05409, or the RR/05409 line for that pallet does not carry the new
#     series, or the new series is already live on any other stock.
#   * Re-runnable: a pallet already carrying the new series is reported as
#     "already fixed" and skipped.
# ----------------------------- PASTE FROM HERE ------------------------------
DRY_RUN = True

RECEIPT_NAME = 'M/RR/05409'
OWNER_NAME = 'CDO-RM 8'

# (pallet the stock is on, old series now on the stock, series on the RR/05409
#  line / tag[, pallet named on the RR/05409 line when it differs])
FIXES = [
    ('NP 1364', 'CDP-013430', 'CDP-013508', 'NB 5710'),  # moved by ADJ/2026/0565
    ('G 2034',  'CDP-013394', 'CDP-013433'),
    ('5804 G',  'CDP-013395', 'CDP-013434'),
    ('7646 BP', 'CDP-013396', 'CDP-013435'),
    ('R 2040',  'CDP-013397', 'CDP-013436'),
    ('NB 3861', 'CDP-013398', 'CDP-013437'),
    ('G 2680',  'CDP-013399', 'CDP-013478'),
    ('G 6671',  'CDP-013400', 'CDP-013479'),
    ('NB 5348', 'CDP-013401', 'CDP-013480'),
    ('NB 7172', 'CDP-013402', 'CDP-013481'),
    ('NB 4438', 'CDP-013403', 'CDP-013482'),
    ('R 517',   'CDP-013404', 'CDP-023611'),
    ('NB 7370', 'CDP-013405', 'CDP-013483'),
    ('NB 7114', 'CDP-013406', 'CDP-013484'),
    ('NB 5740', 'CDP-013407', 'CDP-013485'),
    ('41083',   'CDP-013408', 'CDP-013486'),
    ('NP 1462', 'CDP-013409', 'CDP-013487'),
    ('G 42016', 'CDP-013410', 'CDP-013488'),
    ('NB 1659', 'CDP-013411', 'CDP-013489'),
    ('BP 6779', 'CDP-013412', 'CDP-013490'),
    ('B 117',   'CDP-013413', 'CDP-013491'),
    ('G 617',   'CDP-013414', 'CDP-013492'),
    ('R 6641',  'CDP-013415', 'CDP-013493'),
    ('3306 B',  'CDP-013416', 'CDP-013494'),
    ('NB 7227', 'CDP-013417', 'CDP-013495'),
    ('NB 1602', 'CDP-013418', 'CDP-013496'),
    ('R 5602',  'CDP-013419', 'CDP-013497'),
    ('40150',   'CDP-013420', 'CDP-013498'),
    ('G 4572',  'CDP-013421', 'CDP-013499'),
    ('NB 2242', 'CDP-013422', 'CDP-013500'),
    ('41019',   'CDP-013423', 'CDP-013501'),
    ('R 1029',  'CDP-013424', 'CDP-013502'),
    ('014 B',   'CDP-013425', 'CDP-013503'),
    ('NB 6892', 'CDP-013426', 'CDP-013504'),
    ('NB 1793', 'CDP-013427', 'CDP-013505'),
    ('G 72107', 'CDP-013428', 'CDP-013506'),
    ('NB 5923', 'CDP-013429', 'CDP-013507'),
    ('NB 5651', 'CDP-013431', 'CDP-013509'),
    ('NB 2972', 'CDP-013432', 'CDP-013510'),
]


def spellings(series):
    # CDP-13433 and CDP-013433 are the same pallet number
    prefix, sep, tail = series.rpartition('-')
    if not tail.isdigit():
        return [series]
    number = int(tail)
    return list(set([series] + ['%s-%s' % (prefix, str(number).zfill(w))
                                for w in range(1, 9)]))


Quant = env['stock.quant'].sudo()
MoveLine = env['stock.move.line'].sudo()

receipt = env['stock.picking'].sudo().search([('name', '=', RECEIPT_NAME)], limit=1)
owner = env['res.partner'].sudo().search([('name', '=', OWNER_NAME)], limit=1)
if not receipt or not owner:
    raise UserError('Cannot find %s or client %s - nothing written.'
                    % (RECEIPT_NAME, OWNER_NAME))
if receipt.x_studio_voided:
    raise UserError('%s is already voided - nothing written.' % RECEIPT_NAME)

new_series_set = [row[2] for row in FIXES]
if len(set(new_series_set)) != len(new_series_set):
    raise UserError('The fix list repeats a new series - nothing written.')

errors, skipped, planned = [], [], []

for row in FIXES:
    pallet, old, new = row[0], row[1], row[2]
    rr_pallet = row[3] if len(row) > 3 else pallet
    live_new = Quant.search([
        ('x_studio_pallet_series_id', 'in', spellings(new)),
        ('quantity', '>', 0),
    ])
    stock = Quant.search([
        ('package_id.name', '=', pallet),
        ('owner_id', '=', owner.id),
        ('x_studio_pallet_series_id', '=', old),
        ('quantity', '>', 0),
    ])

    if not stock:
        if live_new and all(q.package_id.name == pallet for q in live_new):
            skipped.append('%s already fixed (%s)' % (pallet, new))
        else:
            errors.append('%s: no stock under %s' % (pallet, old))
        continue
    if len(stock) > 1:
        errors.append('%s: %d stock rows under %s (expected 1)'
                      % (pallet, len(stock), old))
        continue
    if stock.x_studio_record_reference != receipt:
        errors.append('%s: stock is from %s, not %s'
                      % (pallet, stock.x_studio_record_reference.name or '-',
                         RECEIPT_NAME))
        continue
    rr_line = MoveLine.search([
        ('picking_id', '=', receipt.id),
        ('result_package_id.name', '=', rr_pallet),
    ])
    if len(rr_line) != 1 or rr_line.x_studio_pallet_series_id != new:
        errors.append('%s: %s line carries %s, not %s'
                      % (pallet, RECEIPT_NAME,
                         ', '.join(rr_line.mapped('x_studio_pallet_series_id')) or '-',
                         new))
        continue
    others = live_new - stock
    if others:
        errors.append('%s: %s is already live on pallet %s'
                      % (pallet, new, ', '.join(others.mapped('package_id.name'))))
        continue
    planned.append((stock, pallet, old, new))

report = ('%s - %s\n\nWill fix: %d\nAlready fixed: %d\nProblems: %d'
          % (RECEIPT_NAME, 'DRY RUN (nothing written)' if DRY_RUN else 'LIVE RUN',
             len(planned), len(skipped), len(errors)))
if errors:
    report += '\n\nPROBLEMS - nothing was written:\n' + '\n'.join(errors)
if skipped:
    report += '\n\nAlready fixed:\n' + '\n'.join(skipped)
if planned:
    report += '\n\nChanges:\n' + '\n'.join(
        '%s: %s -> %s (%s kg at %s)' % (p, o, n, s.quantity, s.location_id.complete_name)
        for s, p, o, n in planned)

if errors or DRY_RUN or not planned:
    # raising rolls back the whole run, so a dry run, a failed check or a
    # re-run with nothing left to fix writes nothing
    raise UserError(report)

for stock, pallet, old, new in planned:
    stock.with_context(vifel_skip_series_guard=True).write(
        {'x_studio_pallet_series_id': new})

receipt.message_post(body=(
    'Stock pallet series corrected to match this receipt and its printed tags '
    '(stock had kept voided M/RR/05265\'s numbers). Fixed %d pallet(s): %s.'
    % (len(planned), ', '.join('%s %s&rarr;%s' % (p, o, n) for s, p, o, n in planned))))

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Pallet series fixed',
        'message': '%d pallet(s) on %s now match the receipt. The 75 kg return on NB 5710 was not touched.'
                   % (len(planned), RECEIPT_NAME),
        'sticky': True,
        'type': 'success',
    },
}
