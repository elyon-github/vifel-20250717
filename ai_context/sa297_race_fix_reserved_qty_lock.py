# =============================================================================
# PASTE TARGET: Server Action #297 "Execute Code"
#               (bound to Automation Rule #6 "Pallet Kilos Record - Create
#                Record Per Move", trigger on_state_set, state = done)
#
# WHAT CHANGED vs the current production code (only the non-BF outgoing branch):
#   1. RACE FIX — before stamping reserved_quantity_on_validation, take a
#      FOR UPDATE row lock on every pallet (stock_quant_package) touched by
#      this WR, in sorted id order. Two WRs validating the same shared pallet
#      simultaneously now serialize: the second waits, re-reads the quants
#      AFTER the first committed, and correctly sees remaining = 0 — so the
#      pallet-out (-1) is never lost. Without this, both could compute a
#      stale remaining > 0 and the pallet silently never counts out
#      (the upward ledger drift found on ALPHA ALLEANZA).
#      env.invalidate_all() is REQUIRED after the lock: it flushes pending
#      writes and drops the ORM cache so the quant re-read hits fresh
#      committed data instead of values cached during validation.
#   2. FLOAT HARDENING — remaining is rounded to 3 decimals before writing;
#      the PKR counting rule requires exactly == 0, and a float residue
#      would silently block the count.
#   3. (OPTIONAL, commented) PSI drift tolerance — see the marked line.
#
# Everything else (incoming branches, BF branches, revision branch, PKR row
# creation) is byte-identical to production.
#
# VERIFY AFTER PASTE (staging):
#   - Validate a normal single WR: stamps unchanged vs before, PKR row created.
#   - Shared-pallet sequence: WR-A partial then WR-B empties -> B's lines
#     stamp 0, B's PKR row counts the pallet out. Same as before.
#   - True race is hard to trigger by hand; the lock semantics guarantee it.
#     Optional simulation: two psql sessions, BEGIN; SELECT id FROM
#     stock_quant_package WHERE id = <pkg> FOR UPDATE; observe the second
#     session block until the first commits.
# =============================================================================

code = record.picking_type_id.code
is_blast_freeze = record.picking_type_id.is_blast_freeze_operation

if not record.x_studio_for_revision:
    pallet_kilos_model = env['pallet_kilos_record_model.pallet_kilos_record_model']

    if code == "incoming" and not is_blast_freeze:
        # Creating the record using the determined field name
        pallet_kilos_model.create({'owner_id': record.owner_id.id,
                                   'report_no': record.name,
                                   'record_reference': record.id,
                                   'warehouse': record.location_dest_id.warehouse_id.id,

        })

    if code == "outgoing" and not is_blast_freeze:
        # ---- RACE FIX ------------------------------------------------
        # Serialize on every pallet touched by this validation (all WRs
        # in the batch, one sorted pass -> deadlock-free even between
        # concurrent mass-validations). Another WR validating the same
        # pallet at the same moment blocks here until we commit (or we
        # block until it does); the loser then recomputes from committed
        # data and correctly sees 0 remaining.
        pkg_ids = sorted({l.package_id.id
                          for rec in records if rec.state in ['done']
                          for l in rec.move_line_ids
                          if l.quantity != 0 and l.package_id})
        if pkg_ids:
            env.cr.execute(
                "SELECT id FROM stock_quant_package "
                "WHERE id IN %s ORDER BY id FOR UPDATE",
                [tuple(pkg_ids)])
            # flush pending writes + drop ORM cache so the quant reads
            # below see fresh committed data, not values cached before
            # the lock was acquired
            env.invalidate_all()
        # ----------------------------------------------------------------
        for record in records:
            if record.state in ['done']:
                for line in record.move_line_ids:
                    if line.quantity != 0 and line.package_id:
                        # Remaining stock on this pallet FOR THIS OWNER only
                        # (post-validation state). The package-wide total
                        # would let another owner's stock on a shared pallet
                        # block this owner's withdrawal from ever counting.
                        remaining = 0.0
                        for q in line.package_id.quant_ids:
                            if (q.owner_id == line.owner_id
                                    and q.location_id.usage == 'internal'
                                    and q.quantity > 0
                                    and q.x_studio_pallet_series_id == line.x_studio_pallet_series_id):
                                # OPTIONAL drift tolerance: replace the
                                # condition above with
                                #   and (q.x_studio_pallet_series_id == line.x_studio_pallet_series_id
                                #        or not q.x_studio_pallet_series_id)
                                # so a quant whose series was wiped by the
                                # disappearing-series bug still blocks a
                                # premature pallet-out.
                                remaining += q.quantity
                        # exact-zero matters downstream (PKR counts only
                        # stamp == 0); kill float residue
                        line['reserved_quantity_on_validation'] = round(remaining, 3)

        # Creating the record using the determined field name
        pallet_kilos_model.create({'owner_id': record.owner_id.id,
                                   'report_no': record.name,
                                   'record_reference': record.id,
                                   'warehouse': record.location_id.warehouse_id.id,

        })

    if code == "incoming" and is_blast_freeze:
        # Creating the record using the determined field name
        pallet_kilos_model.create({'owner_id': record.owner_id.id,
                                   'report_no': record.name,
                                   'record_reference': record.id,
                                   'warehouse': record.location_dest_id.warehouse_id.id,

        })

    if code == "outgoing" and is_blast_freeze:

        for record in records:
                if record.state in ['done']:
                    for line in record.move_line_ids:
                        if line.quantity != 0:
                            line['reserved_quantity_on_validation'] = line.package_id.x_studio_total_quantity

        # Creating the record using the determined field name
        pallet_kilos_model.create({'owner_id': record.owner_id.id,
                                   'report_no': record.name,
                                   'record_reference': record.id,
                                   'warehouse': record.location_id.warehouse_id.id,

        })



elif record.x_studio_for_revision and code == "incoming":
    original_document = env['pallet_kilos_record_model.pallet_kilos_record_model'].search(
        [('record_reference', '=', record.x_studio_re_adjustment_for_document.id)],
        order='create_date desc',
        limit=1
    )
    original_document.write({'readjustment_document': record.id})
