# AR#27 / SA#375 "outgoing line sync guard" — REV 2: scoped to the picking
# the user is actually acting on.
#
# Paste over the whole body of Server Action #375 (model stock.move.line,
# automation AR#27, trigger: on create or write).
# Verbatim backup of the current production code: sa375_BACKUP.txt
#
# ---------------------------------------------------------------------
# WHY THIS CHANGED
#
# This action runs on EVERY stock.move.line create/write in the database —
# a base automation is a hook on the TABLE, not on the form you have open.
# Its only filter was "skip non-outgoing lines".
#
# Validating a RECEIPT writes move lines far beyond that receipt:
#   1. the receipt's own lines are written (incoming -> skipped here);
#   2. _action_done puts the received stock on hand;
#   3. the WITHDRAWAL operation type uses reservation_method = 'at_confirm',
#      so Odoo immediately re-assigns waiting outgoing moves of that product;
#   4. _action_assign CREATES move lines on those OTHER pickings;
#   5. this automation fires again with those foreign lines in `records`.
#
# The guard then validated someone else's reservation line and raised about
# a pallet series with no connection to the record on screen. Observed on
# vifel_07_28_2026_2: validating M/RR/04985 (TECHNO FARM, 39 pallets of one
# product) raised "Please check Pallet Series ID: [AD-038645]" — a MOMMY
# LOIDA pallet (NB 2349) that Odoo was reserving for M/WR/07796, one of four
# of her withdrawals still short of that product. A freshly created
# reservation line takes a partial weight (Weight to-pick below max =
# reduced) while its packaging figure is still the whole-pallet value (not
# reduced), which is exactly the mismatch this guard raises on.
#
# THE FIX: during a validation, only validate lines that belong to the
# picking being validated. Odoo core stamps `button_validate_picking_ids`
# into the context inside button_validate (stock/models/stock_picking.py:1150)
# BEFORE any of the cascade above runs, so it is exactly the discriminator
# needed. When that key is absent (ordinary form editing, wizards) the guard
# behaves EXACTLY as it does today — this only ever skips lines it can prove
# belong to a different picking than the one being validated.
#
# KNOWN LIMIT (accepted): other paths can also trigger the reservation
# cascade — the stock scheduler cron, or pressing "Check Availability" on a
# different picking. Those do not set the key, so a foreign line could still
# raise there. That is the pre-existing behaviour, left alone deliberately
# rather than widened with context guesses that could silently disable the
# guard during normal editing. If it shows up in practice, the fix is the
# same shape, keyed on whatever that path sets.
# ---------------------------------------------------------------------

# The picking(s) being validated, when Odoo tells us. Core sets this in
# button_validate (stock/models/stock_picking.py:1150) with exactly the
# pickings the user pressed Validate on, and nothing else sets it.
#
# NOTE: active_id/active_ids are deliberately NOT used here. They are set
# by whatever action opened the view, so a picking opened from another
# record's smart button carries the OTHER record's id — scoping on that
# would silently skip the very line the encoder is editing. A guard that
# quietly stops guarding is worse than one that shouts, so we only trust
# the key that cannot be wrong.
acting_picking_ids = set(env.context.get('button_validate_picking_ids') or ())

for record in records:
    if not record.picking_id.x_studio_is_a_blast_freezer:
        # Unchanged: no-RR-return clients keep their actual values mirrored
        # onto the picked figures. Deliberately NOT scoped — it is a no-op
        # on machine-created lines (their actual_* are still 0, so both
        # values fall back to what is already on the line).
        if record.picking_id.partner_id.x_studio_special_no_rr_return_needed and record.picking_code == 'outgoing' and record.state != 'done':
            new_packaging = record.x_studio_actual_packaging or record.x_studio_affected_2nd_uom
            new_qty       = record.x_studio_actual_kg or record.quantity
            record.update({
                'x_studio_affected_2nd_uom': new_packaging,
                'quantity':                  new_qty,
            })

        if record.picking_type_id.code != 'outgoing':
            continue

        # A line with no picking is never an encoder-entered withdrawal line:
        # relocations, quant corrections and orphaned lines land here.
        if not record.picking_id:
            continue

        # Another picking's line, pulled into this transaction by the
        # reservation cascade described above. Not what the user is editing.
        if acting_picking_ids and record.picking_id.id not in acting_picking_ids:
            continue

        pallet = record.x_studio_pallet_series_id or 'Unknown PSI'
        dp = 3

        def r(val):
            return round(val or 0.0, dp)

        fields = [
            {'label': 'Packaging / Quantity', 'max': r(record.x_studio_max_2nd_uom),    'to_pick': r(record.x_studio_affected_2nd_uom), 'actual': r(record.x_studio_actual_packaging)},
            {'label': 'Packs',                'max': r(record.x_studio_max_total_units),'to_pick': r(record.x_studio_withdraw_units),   'actual': r(record.x_studio_actual_min)},
            {'label': 'Weight (KG)',          'max': r(record.x_studio_max_quant),      'to_pick': r(record.quantity),                  'actual': r(record.x_studio_actual_kg)},
        ]

        active = [f for f in fields if f['max'] > 0 and f['to_pick'] > 0]

        def join_labels(labels):
            if len(labels) == 1:
                return labels[0]
            return ', '.join(labels[:-1]) + ' and ' + labels[-1]

        sep = '─' * 25
        hint = '\n\nIf you are stuck with this error, click the Discard button at the upper left of the screen.'

        actual_over_max = [f['label'] for f in active if f['actual'] > f['max']]
        if actual_over_max:
            raise UserError(f"PSI {pallet}\n{sep}\n{join_labels(actual_over_max)} exceeds the maximum allowed value.{hint}")

        over_max = [f['label'] for f in active if f['to_pick'] > f['max']]
        if over_max:
            raise UserError(f"PSI {pallet}\n{sep}\n{join_labels(over_max)} exceeds the maximum allowed value.{hint}")

        to_pick_reduced     = [f for f in active if f['to_pick'] < f['max']]
        to_pick_not_reduced = [f for f in active if f['to_pick'] >= f['max']]
        if to_pick_reduced and to_pick_not_reduced:
            not_synced = [f['label'] for f in to_pick_not_reduced]
            raise UserError(f"Please check Pallet Series ID: [{pallet}]\n{sep}\nTo keep records in sync, {join_labels(not_synced)} (To Pick) must also be reduced.{hint}")

        actual_reduced     = [f for f in active if f['actual'] < f['to_pick']]
        actual_not_reduced = [f for f in active if f['actual'] >= f['to_pick']]
        if actual_reduced and actual_not_reduced:
            not_synced = [f['label'] for f in actual_not_reduced]
            raise UserError(f"Please check Pallet Series ID: [{pallet}]\n{sep}\nTo keep records in sync, {join_labels(not_synced)} (Actual) must also be reduced.{hint}")
