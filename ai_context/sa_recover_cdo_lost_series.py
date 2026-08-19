# ============================================================================
# SERVER ACTION - Recover the pallet series lost on M/RR/05792 into the pool
#   Studio -> Server Actions, Model: res.partner, type Python code.
#   RUN IT with the CDO FOODSPHERE INC. (FG) contact selected (or from its form).
#
# Five series - CDF-021779, CDF-021780, CDF-021781, CDF-021782, CDF-021783 -
# were consumed and written nowhere by the old get_pallet_series_by_id
# smallest-fallback on 2026-08-13 20:54:03 (the leak fixed by "Never substitute
# a different pallet series when restoring an original"). They are on no quant,
# no move line and not in the pool, so the client's numbering jumped over them.
# This pushes exactly those five back into the client's unused pool, smallest
# kept sorted, so the numbering is whole again.
#
# SAFE: a number is added ONLY when it belongs to THIS client, is on no live
# quant and no move line, and is not already in the pool. Re-runnable (a second
# run adds nothing). Nothing else is touched. Paste everything below the divider.
# ----------------------------- PASTE FROM HERE ------------------------------
TO_RECOVER = ['CDF-021779', 'CDF-021780', 'CDF-021781',
              'CDF-021782', 'CDF-021783']

for record in records:
    code = (record.x_studio_client_unique_code_1 or '').strip().upper()
    added, skipped = [], []
    for series in TO_RECOVER:
        prefix, _sep, num = series.rpartition('-')
        if prefix.upper() != code:
            skipped.append('%s (not %s)' % (series, code or 'this client'))
            continue
        if not num.isdigit():
            skipped.append('%s (unparseable)' % series)
            continue
        number = int(num)
        # never re-pool a number that is actually in use or already pooled
        if env['stock.quant'].sudo().search_count([
                ('x_studio_pallet_series_id', '=', series),
                ('quantity', '>', 0)]):
            skipped.append('%s (live stock exists)' % series)
            continue
        if env['stock.move.line'].sudo().search_count([
                ('x_studio_pallet_series_id', '=', series)]):
            skipped.append('%s (on a move line)' % series)
            continue
        if number in (record.unused_pallet_series_ids or []):
            skipped.append('%s (already in pool)' % series)
            continue
        record.push_unused_pallet(series)
        added.append(series)
    record.message_post(body=(
        'Pallet-series recovery (M/RR/05792 loss): pushed back into the pool: '
        '<b>%s</b>. Skipped: %s.'
        % (', '.join(added) or 'none', ', '.join(skipped) or 'none')))
