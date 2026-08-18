# Recover the client Lot No. / Batch # lost from RETURNED stock (and blanked on
# already-validated withdrawals).
#
# WHY: a withdrawal keeps client_lot_no on the QUANT, not the move line; when the
# quant is consumed (and its stock later returned) the value is lost, so the
# returned quant - and any withdrawal read-back off it - shows blank. This scans
# for those and re-assigns from the ORIGINAL receiving line, matched by
# (product_id, lot_id) - the same key return_lot_batch.py uses (the lot is
# receipt-specific, so it identifies exactly one original Lot No.).
#
# SAFETY (this run's DB showed 0 ambiguous (product,lot) pairs):
#   * only fills a MISSING value - never overwrites an existing one;
#   * skips any (product, lot) that maps to MORE THAN ONE client_lot_no on the
#     original receiving lines (ambiguous - reported, not touched);
#   * DRY_RUN=True by default: prints what it WOULD do and commits nothing.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/recover_lost_client_lot_no.py
#
# Flip DRY_RUN to False (below) to apply. Re-runnable (idempotent).
DRY_RUN = True

Quant = env['stock.quant']
MoveLine = env['stock.move.line']

# Scope to clients that actually use Lot No. / Batch # - much cheaper than
# scanning every quant, and correct: only those clients ever carry a
# client_lot_no to recover.
_partners = env['res.partner'].search(
    ['|', ('vifel_show_lot_no', '=', True), ('vifel_show_batch_no', '=', True)])
PIDS = tuple(_partners.ids) or (0,)
print('Scoped to %d Lot-No/Batch-enabled client(s).' % len(_partners))


def _original_lot_batch(product_id, lot_id):
    """The single original receiving Lot No. / Batch # for this product+lot, or
    (None, None) when there is none or it is ambiguous (>1 distinct value)."""
    rows = MoveLine.search([
        ('product_id', '=', product_id), ('lot_id', '=', lot_id),
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.return_id', '=', False),
        ('client_lot_no', '!=', False)])
    lots = {(r.client_lot_no or '').strip() for r in rows if (r.client_lot_no or '').strip()}
    if len(lots) != 1:
        return None, None, len(lots)          # 0 = nothing, >1 = ambiguous
    src = rows[0]
    return src.client_lot_no, src.batch_no, 1


# ---- Part A: returned/other quants that lost the Lot No. ------------------
env.cr.execute("""
    SELECT q.id, q.product_id, q.lot_id FROM stock_quant q
    JOIN stock_location l ON l.id = q.location_id
    WHERE l.usage='internal' AND q.quantity>0 AND q.lot_id IS NOT NULL
      AND q.owner_id IN %s
      AND COALESCE(TRIM(q.client_lot_no),'')=''
      AND EXISTS (SELECT 1 FROM stock_move_line ml
                  JOIN stock_picking sp ON sp.id=ml.picking_id
                  JOIN stock_picking_type pt ON pt.id=sp.picking_type_id
                  WHERE ml.product_id=q.product_id AND ml.lot_id=q.lot_id
                    AND pt.code='incoming' AND sp.return_id IS NULL
                    AND COALESCE(TRIM(ml.client_lot_no),'')<>'')
""", (PIDS,))
qids = [r[0] for r in env.cr.fetchall()]
print('=== Part A: quants missing Lot No. with a recoverable original: %d ===' % len(qids))
a_fixed = a_ambig = 0
for q in Quant.browse(qids):
    lot_no, batch_no, n = _original_lot_batch(q.product_id.id, q.lot_id.id)
    if n != 1:
        a_ambig += 1
        print('  SKIP ambiguous quant %s %s lot %s (%d distinct Lot Nos)'
              % (q.id, q.product_id.display_name[:20], q.lot_id.name, n))
        continue
    a_fixed += 1
    print('  quant %-8s %-20s lot %s  ->  Lot No %r  Batch %r'
          % (q.id, q.product_id.display_name[:20], q.lot_id.name, lot_no, batch_no))
    if not DRY_RUN:
        vals = {'client_lot_no': lot_no}
        if batch_no and not (q.batch_no or '').strip():
            vals['batch_no'] = batch_no
        q.sudo().write(vals)

# ---- Part B: done withdrawal lines whose read-back would print blank ------
env.cr.execute("""
    SELECT ml.id, ml.product_id, ml.lot_id FROM stock_move_line ml
    JOIN stock_picking sp ON sp.id=ml.picking_id
    JOIN stock_picking_type pt ON pt.id=sp.picking_type_id
    WHERE pt.code='outgoing' AND sp.state='done' AND ml.lot_id IS NOT NULL
      AND sp.partner_id IN %s
      AND COALESCE(TRIM(ml.vifel_lot_no_frozen),'')=''
      AND EXISTS (SELECT 1 FROM stock_move_line r
                  JOIN stock_picking rp ON rp.id=r.picking_id
                  JOIN stock_picking_type rpt ON rpt.id=rp.picking_type_id
                  WHERE r.product_id=ml.product_id AND r.lot_id=ml.lot_id
                    AND rpt.code='incoming' AND rp.return_id IS NULL
                    AND COALESCE(TRIM(r.client_lot_no),'')<>'')
""", (PIDS,))
mids = [r[0] for r in env.cr.fetchall()]
print('\n=== Part B: done WR lines with a recoverable Lot No. (frozen): %d ===' % len(mids))
b_fixed = b_ambig = 0
for ml in MoveLine.browse(mids):
    lot_no, batch_no, n = _original_lot_batch(ml.product_id.id, ml.lot_id.id)
    if n != 1:
        b_ambig += 1
        continue
    b_fixed += 1
    print('  WR line %-8s %-20s (%s) lot %s  ->  frozen Lot No %r'
          % (ml.id, ml.picking_id.name, ml.product_id.display_name[:16], ml.lot_id.name, lot_no))
    if not DRY_RUN:
        ml.sudo().write({'vifel_lot_no_frozen': lot_no})

print('\n--- summary ---')
print('  Part A quants:   %d recoverable, %d ambiguous-skipped' % (a_fixed, a_ambig))
print('  Part B WR lines: %d recoverable, %d ambiguous-skipped' % (b_fixed, b_ambig))
if DRY_RUN:
    env.cr.rollback()
    print('DRY RUN - nothing written. Set DRY_RUN=False to apply.')
else:
    env.cr.commit()
    print('COMMITTED recovery.')
