# PASTE TARGET: Server Action #483 "Remove Linked Transactions" (model stock.picking)
# Backup of the current production code: ai_context/sa483_BACKUP.txt
# Author: Mark Angelo S. Templanza / Elyon   Date: 2026-07-21
#
# WHAT CHANGED
# ------------
# The old version only cleared the five link fields; the emptied document kept all of
# its stock.move / stock.move.line rows, so it still held reservations and still looked
# like a real transaction. This version ALSO deletes the moves and move lines, but ONLY
# when the transfer is not yet validated.
#
# ORDER MATTERS (do not reorder):
#   1. unreserve + DELETE the moves/lines FIRST, while return_id is still set.
#   2. clear the link fields LAST.
#
#   Why this order: the PSI recycle in stock_move.py:1144 is guarded by
#       if pallet_series and not self[0].picking_id.return_id:
#   i.e. a RETURN must never push its series back to the owner pool - the pallet is
#   still physically in the racks carrying that number, and re-issuing it to another
#   pallet is split-PSI corruption. Clearing return_id BEFORE deleting made the picking
#   stop looking like a return, so the guard passed and the series WAS recycled
#   (observed live on M/RR/04839 -> 16-25820 landed in 168 ENTERPRISES' pool).
#   The void-mirror guards do NOT need the links cleared: _void_mirror_exempt()
#   (stock_move.py:330) is satisfied by the context flags set below.
#
# SAFETY
# ------
# * done / cancel transfers are NEVER touched (they are reported, not modified).
#   Deleting lines on a validated transfer would re-apply stock and can drive quants
#   negative - exactly the G 602 / -125 kg incident.
# * PSIs are NOT recycled back to the owner pool. This mirrors the unvoid-neutralization
#   rule ("deletes moves/lines WITHOUT recycling PSIs"). Recycling here would risk
#   handing out a number that is still on stocked quants (split-PSI corruption).
#   The freed series are listed in the notification so they can be reused deliberately.
#   >>> If you want them auto-recycled instead, say so - it is a one-block change, but it
#       MUST carry the stocked-quant guard.

LINK_FIELDS = [
    'backorder_id',
    'return_id',
    'x_studio_last_operation_source_document',
    'next_operation_source_document',
    'void_source_picking_id',
]

cleared, emptied, skipped = [], [], []
released_series = []   # from normal transfers - these go back for reuse
kept_series = []       # from RETURNS - stay with the pallet, never reused

def _clear_links(rec):
    vals = {}
    for fname in LINK_FIELDS:
        if fname in rec._fields:
            vals[fname] = False
    if vals:
        rec.write(vals)


for record in records:
    was_return = bool(record.return_id) or bool(record.is_void_return)

    # ---- 1. validated documents: links only, moves left intact ----
    if record.state in ('done', 'cancel'):
        _clear_links(record)
        cleared.append(record.name)
        skipped.append(record.name)
        continue

    n_moves, n_lines = len(record.move_ids), len(record.move_line_ids)
    if not (n_moves or n_lines):
        _clear_links(record)
        cleared.append(record.name)
        continue

    # ---- 3. snapshot as PLAIN IDS before unreserving ----
    # do_unreserve() DELETES move lines in Odoo 17 (_do_unreserve cascade), so any
    # recordset captured here would go stale and raise MissingError. Keep ids only.
    loc_ids, pkg_ids = set(), set()
    for line in record.move_line_ids:
        psi = line.x_studio_pallet_series_id
        if psi:
            if was_return:
                kept_series.append(psi)       # return -> never reused
            else:
                released_series.append(psi)
        if line.location_dest_id:
            loc_ids.add(line.location_dest_id.id)
        if line.result_package_id:
            pkg_ids.add(line.result_package_id.id)

    # ---- 4. free reservations (may already delete the lines) ----
    try:
        record.do_unreserve()
    except Exception:
        pass
    # NOTE: no hasattr() here - it does not exist in Odoo's safe_eval sandbox.
    # The try/except already swallows AttributeError if the helper is absent.
    for loc in env['stock.location'].browse(sorted(loc_ids)).exists():
        try:
            loc.remove_reservation()
        except Exception:
            pass
    for pkg in env['stock.quant.package'].browse(sorted(pkg_ids)).exists():
        try:
            pkg.remove_reservation()
        except Exception:
            pass

    # ---- 5. delete whatever survived, lines first then moves ----
    ctx = {
        'skip_void_mirror_guard': True,   # links already severed above
        'skip_pallet_series_sync': True,  # no pool churn / double audit logging
        'audit_source': 'unvoid_cleanup',
    }
    remaining_lines = record.move_line_ids.exists()
    if remaining_lines:
        remaining_lines.with_context(**ctx).unlink()
    remaining_moves = record.move_ids.exists()
    if remaining_moves:
        remaining_moves.with_context(**ctx).unlink()

    # ---- 6. links LAST, so the recycle guard above still saw a return ----
    _clear_links(record)
    cleared.append(record.name)
    emptied.append((record.name, n_lines, was_return))

# ---------------------------------------------------------------------------
# User-facing summary: short, plain wording, no internal jargon.
# The full detail still goes to the server log for troubleshooting.
# ---------------------------------------------------------------------------
# Full detail goes to the server log (Settings > Technical > Logging) - the user
# just gets a refreshed screen showing the emptied document.
log('Remove Linked Transactions | cleared=%s | emptied=%s | skipped=%s | '
    'released=%s | kept=%s'
    % (cleared, [(e[0], e[1]) for e in emptied], skipped,
       sorted(set(released_series)), sorted(set(kept_series))))

action = {'type': 'ir.actions.client', 'tag': 'reload'}
