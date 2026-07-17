# =============================================================================
# SA "Clean Picking (Reset to Empty Draft)" — PASTE FILE (DB-side, no module code)
#
# Setup (once per DB):
#   Settings > Technical > Server Actions > New
#     Model:  Transfer (stock.picking)
#     Type:   Execute Code
#     Name:   Clean Picking (Reset to Empty Draft)
#     Code:   everything below the "SA CODE STARTS HERE" line
#   Then click "Add in the 'More' menu" so it appears under Actions on the form.
#   RECOMMENDED: set Groups = Inventory Super Admin (destructive tool).
#
# What it does (per selected record):
#   - Blocks validated documents (state done / any done move) and VOIDED documents
#     (their void equivalent must keep mirroring them — unvoid first).
#   - Frees pallets/bins reserved FOR this picking (claimant key
#     x_studio_receiving_report_id), unreserves outgoing stock, deletes all
#     pallet lines and moves.
#   - PSI pool doctrine:
#       * normal RR  -> recycles its drawn Pallet Series IDs back to the owner's
#                       pool (audited; series present on stocked quants are NEVER
#                       recycled — split-PSI guard),
#       * return RR / void children / WR / BF -> pool untouched (those series
#         still identify stock in storage; BF has no PSI).
#   - Severs links BOTH directions (return_id, void links — own and inbound).
#   - Resets every stored, writable x_studio_* field to its default (Studio
#     fields added later are covered automatically), plus origin/note; keeps
#     Contact, Operation Type, and everything structural.
#   - Posts one chatter note summarizing exactly what was cleaned.
# =============================================================================
# ------------------------------ SA CODE STARTS HERE --------------------------
Quant = env['stock.quant']
Location = env['stock.location']
Package = env['stock.quant.package']
Picking = env['stock.picking']
FieldsModel = env['ir.model.fields']

for rec in records:
    # ---- 1. Guards -----------------------------------------------------------
    if rec.state == 'done' or any(m.state == 'done' for m in rec.move_ids):
        raise UserError(
            "%s is validated (or has validated moves) — a validated document "
            "cannot be cleaned." % rec.name)
    if rec.x_studio_voided:
        raise UserError(
            "%s is VOIDED — its void equivalent must keep mirroring it. "
            "Unvoid first if you really need to clean it." % rec.name)

    is_return = bool(rec.return_id or rec.is_void_return)
    is_rr = rec.picking_type_id.code == 'incoming'
    is_bf = bool(rec.picking_type_id.is_blast_freeze_operation)

    # ---- 2. Snapshot series + owner BEFORE deleting anything ----------------
    series_owner = {}
    for line in rec.move_line_ids:
        psi = line.x_studio_pallet_series_id
        if psi and psi not in series_owner:
            series_owner[psi] = line.owner_id or rec.owner_id or rec.partner_id
    line_count = len(rec.move_line_ids)

    # ---- 3. Free bins/pallets reserved FOR THIS PICKING only ----------------
    freed_locs = Location.search([('x_studio_receiving_report_id', '=', rec.id)])
    freed_pkgs = Package.search([('x_studio_receiving_report_id', '=', rec.id)])
    reserve_reset = {'x_studio_is_reserved': False,
                     'x_studio_receiving_report_id': False}
    if freed_locs:
        freed_locs.write(reserve_reset)
    if freed_pkgs:
        freed_pkgs.write(reserve_reset)

    # Cleanup legitimately dismantles the document — exempt it from the
    # void-mirror guards (which block USER edits) and the series sync.
    rec_x = rec.with_context(
        skip_void_mirror_guard=True,
        skip_pallet_series_sync=True,
        audit_source='pool_operation',
    )

    # ---- 4. Release outgoing reservations before touching lines -------------
    if rec.picking_type_id.code == 'outgoing' and rec.state not in ('draft', 'cancel'):
        rec_x.do_unreserve()

    # ---- 5. Delete lines THEN moves (order matters: lines go while the ------
    #         document is still bound, so no code path pushes return/WR series)
    if rec_x.move_line_ids:
        rec_x.move_line_ids.with_context(
            skip_pallet_series_sync=True,
            audit_source='pool_operation',
        ).unlink()
    if rec_x.move_ids:
        # NOTE: server-action sandbox forbids private methods (_action_cancel),
        # so cancel by writing state — lines are already gone and outgoing
        # reservations already released above, which is what cancel ensures.
        rec_x.move_ids.write({'state': 'cancel'})
        rec_x.move_ids.unlink()

    # ---- 6. Pool bookkeeping — NORMAL (non-return, non-BF) RR only ----------
    # The incoming ondelete hook (stock_move.py: unreserve_ondelete_location)
    # already auto-recycled every deleted line's series to the pool — which is
    # correct for a normal RR EXCEPT for series that still identify stocked
    # pallets (typo/adoption cases): pull those back OUT of the pool
    # (split-PSI guard), and push any series the hook missed (mixed owners).
    pushed, skipped = [], []
    if is_rr and not is_return and not is_bf:
        for psi, owner in series_owner.items():
            if not owner or '-' not in psi:
                skipped.append(psi)
                continue
            num_txt = psi.split('-')[-1]
            if not num_txt.isdigit():
                skipped.append(psi)
                continue
            num = int(num_txt)
            on_stock = Quant.search_count([
                ('x_studio_pallet_series_id', '=', psi),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
            ])
            pool = list(owner.unused_pallet_series_ids or [])
            if on_stock:
                if num in pool:   # undo the unsafe auto-push
                    owner.write({'unused_pallet_series_ids':
                                 [n for n in pool if n != num]})
                skipped.append(psi)
            elif num in pool:
                pushed.append(psi)     # auto-push already did it
            else:
                owner.with_context(
                    audit_picking_id=rec.id,
                    audit_source='pool_operation',
                ).push_unused_pallet(psi)
                pushed.append(psi)

    # ---- 7. Sever links BOTH directions -------------------------------------
    inbound = Picking.search(['|', ('return_id', '=', rec.id),
                                   ('void_source_picking_id', '=', rec.id)])
    for other in inbound:
        vals = {}
        if other.return_id and other.return_id.id == rec.id:
            vals.update({'return_id': False, 'is_void_return': False,
                         'return_reason': False})
        if other.void_source_picking_id and other.void_source_picking_id.id == rec.id:
            vals.update({'void_source_picking_id': False, 'is_void_wr': False})
        if vals:
            other.with_context(skip_void_mirror_guard=True).write(vals)

    unbind_vals = {
        'return_id': False,
        'is_void_return': False,
        'is_void_wr': False,
        'void_source_picking_id': False,
        'return_reason': False,
        'origin': False,
        'note': False,
    }
    if rec.x_studio_manual_document_ == 'VOIDED':
        unbind_vals['x_studio_manual_document_'] = False

    # ---- 8. Dynamic wipe: every stored, writable x_studio_* field -----------
    studio_fields = FieldsModel.search([
        ('model', '=', 'stock.picking'),
        ('name', '=like', 'x_studio_%'),
        ('store', '=', True),
        ('readonly', '=', False),
    ])
    defaults = rec.default_get([f.name for f in studio_fields])
    for f in studio_fields:
        if f.ttype == 'one2many':
            continue                       # sub-records handled above / not detail inputs
        if f.name in unbind_vals:
            continue
        if f.ttype == 'many2many':
            unbind_vals[f.name] = [(5, 0, 0)]
        else:
            unbind_vals[f.name] = defaults.get(f.name, False)
    rec_x.write(unbind_vals)

    # ---- 9. Traceability ----------------------------------------------------
    if is_rr and not is_return and not is_bf:
        pool_note = ("%d series recycled to the pool%s" % (
            len(pushed),
            (", %d skipped (still on stock)" % len(skipped)) if skipped else ""))
    else:
        pool_note = "pallet series pool untouched (%s)" % (
            "return document" if is_return else
            ("blast freeze" if is_bf else "withdrawal"))
    rec.message_post(body=(
        "Document cleaned to empty draft by %s: %d pallet line(s) removed, "
        "%d location(s) and %d pallet(s) unreserved, %s, %d linked document(s) "
        "unbound, all detail fields reset. Contact and operation type kept."
        % (env.user.name, line_count, len(freed_locs), len(freed_pkgs),
           pool_note, len(inbound))))
