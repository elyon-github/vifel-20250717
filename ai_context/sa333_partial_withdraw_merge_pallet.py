# ============================================================================
# SERVER ACTION #333 "Execute Code"  —  FULL CODE, ready to paste
#   Studio -> Server Actions -> id 333 (model stock.picking) -> Python Code box.
#   Select ALL in that box, delete, and paste everything BELOW the divider line.
#
# ONE change from production, marked ">>> MERGE" below (search: allows_partial_merge).
#
# WHY
# ---
# On withdrawal this action refuses a WR that leaves ANY stock on the source
# pallet — the withdrawn product's own remainder OR any OTHER product on the
# same pallet — to force a return-RR for the leftover. Correct for a normal
# pallet (one batch → empty it), WRONG for a MERGE pallet, which deliberately
# carries several products/batches at once. Withdrawing one and leaving the
# rest is the expected case there (e.g. M/WR/08086 took the shrimp off pallet
# 00001 B and left the 1250 KG "40 FT. CONTAINER VAN").
#
# THE FIX reuses the SAME predicate the Incomplete Package notice already uses:
#   env['stock.quant']._vifel_package_allows_partial_withdrawal(package_id)
# It returns True for BOTH merge configs — a Fixed-PSI pinned pallet, and a
# Multiple-mode pallet that lines have been merged onto (is_pallet_merge flag).
# Defined in multiple_relocation (always installed), so it is always callable.
#
# KNOWN residual edge (rare, documented not fixed): a pallet built ONLY by
# same-receipt joins that is NEITHER pinned NOR cross-receipt merged has no
# stored merge marker, so it is indistinguishable from a normal multi-product
# pallet and is not auto-exempted. Use the client's "special no RR return"
# flag, or un-merge, if it ever surfaces.
# ============================================================================
# ---------------------------- PASTE FROM HERE -------------------------------
# Available variables:
#  - env: environment on which the action is triggered
#  - model: model of the record on which the action is triggered; is a void recordset
#  - record: record on which the action is triggered; may be void
#  - records: recordset of all records on which the action is triggered in multi-mode; may be void
#  - time, datetime, dateutil, timezone: useful Python libraries
#  - float_compare: utility function to compare floats based on specific precision
#  - log: log(message, level='info'): logging function to record debug information in ir.logging table
#  - _logger: _logger.info(message): logger to emit messages in server logs
#  - UserError: exception class for raising user-facing warning messages
#  - Command: x2many commands namespace
# To return an action, assign: action = {...}




for record in records:
    if record.picking_type_id.code == 'outgoing':
        for lines in record.move_line_ids:
            quant_id = env['stock.quant'].search([
                ('lot_id', '=', lines.lot_id.id),
                ('location_id.usage', '=', 'internal'),
                ('package_id.id', '=', lines.package_id.id),
            ], limit=1)
            
            other_quants_same_package = env['stock.quant'].search([
                ('package_id.id', '=', lines.package_id.id),
                ('location_id.usage', '=', 'internal'),
            ])

            sum_avail_other_packages = 0
            details = ""

            if other_quants_same_package:
                sum_avail_other_packages = sum(other_quants_same_package.mapped('available_quantity'))
                # Get product-wise breakdown
                product_details = {}
                for q in other_quants_same_package:
                    if q.product_id.name in product_details:
                        product_details[q.product_id.name] += q.available_quantity
                    else:
                        product_details[q.product_id.name] = q.available_quantity
                details = "\n".join([f"- {name}: {qty:.2f} KG" for name, qty in product_details.items()])
            
            # if quant_id.available_quantity != 0 or sum_avail_other_packages != 0:
            if lines.x_studio_max_quant != lines.x_studio_actual_kg:
                search_quant = env['stock.quant'].search([('lot_id', '=', lines.lot_id.id), ('x_studio_pallet_series_id', '=', lines.x_studio_pallet_series_id)])
                if search_quant:
                    search_quant.write({
                        'x_studio_2nd_uom': search_quant.x_studio_2nd_uom - lines.x_studio_affected_2nd_uom,
                        'x_studio_total_units': search_quant.x_studio_total_units - lines.x_studio_withdraw_units
                    })
            # A MERGE PALLET legitimately holds several products/batches at once
            # — both the Fixed-PSI pinned pallet AND a Multiple-mode merge pallet
            # (a stocked pallet other lines were merged onto). Withdrawing one and
            # leaving the rest is the expected case there, not an under-pick, so
            # skip this completeness guard for them — exactly as the Incomplete
            # Package notice already does. The predicate lives on stock.quant
            # (multiple_relocation defines it; the merge module extends it to
            # return True for pinned + merged-onto pallets), so it is always
            # callable here and covers BOTH merge configs.
            allows_partial_merge = env['stock.quant']._vifel_package_allows_partial_withdrawal(lines.package_id.id)
            if not record.partner_id.x_studio_special_no_rr_return_needed and not allows_partial_merge:
                if quant_id.available_quantity != 0 or sum_avail_other_packages != 0:
                    pallet_name = quant_id.package_id.name or lines.package_id.name
                    if pallet_name:
                        message = (
                            f"It seems like Pallet #{pallet_name} still has available quantity.\n\n"
                        )
                        if quant_id.available_quantity:
                            message += f"- {quant_id.product_id.name}: {quant_id.available_quantity:.2f} KG\n"
                        if sum_avail_other_packages:
                            message += f"Other products in the same pallet:\n{details}"
                        if message:
                            raise UserError(message)
            # else:
            #     for lines in record.move_line_ids:
            #         if lines.x_studio_max_quant != lines.x_studio_actual_kg:
            #             search_quant = env['stock.quant'].search([('lot_id', '=', lines.lot_id.id)], limit=1)
            #             if search_quant:
            #                 search_quant.write({
            #                     'x_studio_2nd_uom': lines.x_studio_max_2nd_uom - lines.x_studio_affected_2nd_uom
            #                 })
        for move in record.move_ids:
            if not move.x_studio_atw_no and not move.picking_id.x_studio_is_a_blast_freezer and not move.x_studio_for_revision:
                raise UserError(f"Please input ATW Details in Product: {move.product_id.name}")
                
    elif record.picking_type_id.code == 'incoming':
        for move in record.move_ids:
            if not move.x_studio_client_ref and not move.x_studio_for_revision:
                raise UserError(f"Please input Client Reference # Details in Product: {move.product_id.name}")
                
        if record.return_id and record.return_id.state != 'done':
            raise UserError('Please make sure to validate the WR first before validating the RR return!')
                    

    is_blast_freeze, is_receiving = record.operation_type_checker(record.picking_type_id)
    if is_blast_freeze and is_receiving:
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',  'x_studio_warehouse_supervisor', 'x_studio_warehouse_checker', 'x_studio_client_reference', 'x_studio_inventory_analyst',
            'x_studio_source', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver',
        ]
    elif is_blast_freeze and not is_receiving:
        field_technical_names = [
            'x_studio_start_time', 'x_studio_end_time', 'x_studio_destination', 'x_studio_warehouse_supervisor', 'x_studio_warehouse_checker', 'x_studio_atw_no', 'x_studio_inventory_analyst',
        ]
    elif not is_blast_freeze and is_receiving:
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',
            'x_studio_source', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver', 'x_studio_warehouse_supervisor', 'x_studio_warehouse_checker', 'x_studio_client_reference', 'x_studio_inventory_analyst',
        ]
    else:  # not is_blast_freeze and not is_receiving
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',
            'x_studio_destination', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver', 'x_studio_warehouse_supervisor', 'x_studio_warehouse_checker', 'x_studio_atw_no', 'x_studio_inventory_analyst',
        ]
    
    # Collect empty fields
    # Collect empty fields (skip truck_time if truck_type == 'N/A')
    missing_fields = []
    for field_name in field_technical_names:
        # Skip truck time requirement if truck_type == 'N/A'
        if field_name == 'x_studio_truck_time' and record.truck_type == 'N/A':
            continue
    
        if not record[field_name]:
            # Use the field's label if available, otherwise fallback to the technical name
            field_label = record._fields[field_name].string or field_name
            has_signees_missing = 'Supervisor' in field_label or 'Checker' in field_label
            message = f"• {field_label}" if not has_signees_missing else f"• {field_label} - Under Additional Info Tab"
            missing_fields.append(message)
    
    # Raise error if any fields are missing
    if missing_fields:
        raise UserError(
            "Please complete the following required fields:\n\n" + "\n".join(missing_fields)
        )

                
    record['x_studio_validated_by'] = env.user.id

