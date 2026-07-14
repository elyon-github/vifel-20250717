# =============================================================================
# PASTE TARGET: Server Action #317 "Execute Code"
#               (bound to Automation Rule #15 "Update Pallet Info OnChange
#                Validated Documents" — on_create_or_write, trigger fields =
#                the picking header details, filter_domain state = done)
#
# PURPOSE OF THIS AUTOMATION (confirmed): when a VALIDATED RR is unlocked and
# its details are edited on the stock.picking form (common adjustment), push
# the corrected details back onto the quants that came from that RR.
#
# WHAT CHANGED vs production (backup: sa317_BACKUP.txt — verbatim copy):
#   1. RR-ONLY GATE — the automation's trigger fields (end time, gate pass,
#      dock no, plate, source, ...) exist on every picking type, so today a
#      header edit on a validated WR/relocation also fires this re-stamp.
#      Now: skip everything except incoming (RR/BFRR).
#   2. REFERENCE-MATCHED QUANTS — the old search was
#      [('lot_id', '=', lines.lot_id.id)] : unscoped except lot, so it
#      touched quants that no longer belong to this RR (withdrawn, relocated,
#      corrected, re-referenced) — and, when a line had NO lot, the domain
#      became lot_id = False and stamped that line's details onto EVERY
#      lot-less quant in the database. Now: only quants that still reference
#      back to the original RR (x_studio_record_reference = this picking),
#      and lines without a lot are skipped entirely.
#   3. Field list unchanged — the quantity-like fields (2nd UOM, packs, UOMs)
#      stay commented out exactly as in production: quantities are maintained
#      by the withdrawal reducer and the correction wizard, and re-imposing
#      the RR line's full values onto partially-withdrawn stock is the
#      HEX-015573 stuck-quantity conflict.
#
# ALSO UPDATE THE AUTOMATION RULE (UI, one field): AR#15 "Apply on" domain
#   from:  [("state", "=", "done")]
#   to:    [("state", "=", "done"), ("picking_type_code", "=", "incoming")]
# (The in-code gate below is the safety net if the domain edit is skipped.)
#
# VERIFY AFTER PASTE (staging):
#   - Validate an RR -> quants stamped as usual (AR#2 does that; unchanged).
#   - Unlock the RR, edit e.g. Gate Pass / Source -> quants still referencing
#     the RR get the new values.
#   - A quant from that RR that was corrected/relocated to reference another
#     document -> untouched by the edit.
#   - Edit header fields on a validated WR -> nothing happens at all.
# =============================================================================

move_lines = record.move_line_ids


if record.state == "done" and record.picking_type_id.code == "incoming":
    for lines in move_lines:
        # a line without a lot must never match (lot_id = False would match
        # every lot-less quant in the database)
        if not lines.lot_id:
            continue
        # only quants that still reference back to the original RR — stock
        # that was withdrawn / relocated / corrected away is no longer this
        # automation's business
        quantModel = env['stock.quant'].search([
            ('lot_id', '=', lines.lot_id.id),
            ('x_studio_record_reference', '=', record.id),
        ])
        for quants in quantModel:
            quants.write({'x_studio_production_date': lines.x_studio_production_date,
                                       'x_studio_container_number': lines.x_studio_container_number,
                                       'x_studio_expiration_date': lines.x_studio_expiration_date,
                                    #   'x_studio_2nd_uom': lines.x_studio_2nd_uom,
                                    #   'x_studio_total_units': lines.x_studio_total_units,
                                    #   'x_studio_quantity_uom': lines.x_studio_quantity_uom,
                                    #   'x_studio_min_quantity_uom': lines.x_studio_min_quantity_uom,
                                       'x_studio_end_time': record.x_studio_end_time,
                                       'x_studio_gate_pass': record.x_studio_gate_pass,
                                       'x_studio_loading_dock_no': record.x_studio_loading_dock_no,
                                       'x_studio_start_time': record.x_studio_start_time,
                                       'x_studio_tally_sheet': record.x_studio_tally_sheet,
                                       'x_studio_truck_time': record.x_studio_truck_time,
                                       'x_studio_truck_number': record.x_studio_trucks_plate_,
                                       'x_studio_source': record.x_studio_source,
                                    #   'x_studio_reference': lines.picking_id.name,
                                       'x_studio_special_holding': lines.x_studio_special_holding
                                        })
