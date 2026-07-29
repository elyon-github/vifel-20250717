# ============================================================================
# SERVER ACTION #348 "X_Verifier Check on Receipt"  —  FULL CODE, ready to paste
#   Studio -> Server Actions -> id 348 (model stock.picking) -> Python Code box.
#   Select ALL in that box, delete, and paste everything BELOW the divider line.
#
# This is the COMPLETE action with two changes already applied inline. Nothing
# else differs from production. The three changed spots are marked with the
# comment ">>> MERGE" so you can find them:
#   1. LOGIC   — a merged line skips the duplicate-series-in-stock guard, the
#                same exemption return lines already get (search: is_pallet_merge).
#   2. WORDING — the offending-series detail line is trimmed to facts.
#   3. WORDING — the section header/footer now states the RULE and the FIX
#                (fresh series, or use Merge Pallet). No change to WHEN it fires.
# is_pallet_merge is defined on stock.move.line by multiple_relocation (always
# installed here), so change 1 reads the field directly — server actions run
# sandboxed and have no getattr/hasattr.
# ============================================================================
# ---------------------------- PASTE FROM HERE -------------------------------
lines = record.move_line_ids
reserved_pallets = []
error_messages = {
    'no_pallets': [],
    'reserved_pallets': [],
    'multiple_products': [],
    'multiple_locations': [],
    'duplicate_lines': [],
    'multiple_pallets': [],
    'missing_dates': [],
    'missing_container_number': [],
    'missing_package': [],
    'missing_pallet_series_id': [],
    'product_limit': [],
    'zero_quantity': [],
    'invalid_location': [],
    'missing_bf_pallet_text': [],
    'already_reserved': [],
    'missing_uom': [],
    'multiple_pallet_series': [],
    'existing_pallet_series': [],
}

final_error_message = []
for record in records:
    
    for stock_moves in record.move_ids_without_package:
        # Group move lines by pallet series
        pallet_series_groups = {}
        for multiple_withdrawal_line in stock_moves.quant_ids_multiple_withdrawal:
            pallet_series = multiple_withdrawal_line.x_studio_pallet_series_id
            
            # Skip if no pallet series
            if not pallet_series:
                continue
            
            # Initialize group if not exists
            if pallet_series not in pallet_series_groups:
                pallet_series_groups[pallet_series] = {
                    'pallet_series': pallet_series,
                    'lines': [],
                    'max_2nd_uom': multiple_withdrawal_line.x_studio_max_2nd_uom,
                    'max_total_units': multiple_withdrawal_line.x_studio_max_total_units,
                    'max_quant': multiple_withdrawal_line.x_studio_max_quant,
                    'total_affected_2nd_uom': 0,
                    'total_max_units': 0,
                    'total_quantity': 0
                }
            
            # Add line to group
            pallet_series_groups[pallet_series]['lines'].append(multiple_withdrawal_line)
            
            # Accumulate picked values
            pallet_series_groups[pallet_series]['total_affected_2nd_uom'] += multiple_withdrawal_line.x_studio_affected_2nd_uom
            pallet_series_groups[pallet_series]['total_max_units'] += multiple_withdrawal_line.x_studio_withdraw_units
            pallet_series_groups[pallet_series]['total_quantity'] += multiple_withdrawal_line.quantity
        
        # Validate each pallet series group
        all_pallet_errors = []
        for pallet_series, group_data in pallet_series_groups.items():
            errors = []
            warnings = []
            
            # Check for zero values when max is not zero
            for line in group_data['lines']:
                line_issues = []
                
                if group_data['max_2nd_uom'] != 0 and line.x_studio_affected_2nd_uom == 0:
                    line_issues.append("Quantity")
                
                if group_data['max_total_units'] != 0 and line.x_studio_withdraw_units == 0:
                    line_issues.append("Heads")
                
                if group_data['max_quant'] != 0 and line.quantity == 0:
                    line_issues.append("Weight (KG)")
                
                if line_issues:
                    warnings.append(f"      • Missing: {', '.join(line_issues)}")
            
            # Check if total affected 2nd UOM exceeds max
            if round(group_data['total_affected_2nd_uom'], 3) > round(group_data['max_2nd_uom'], 3):
                errors.append(
                    f"      • Quantity → Picked: {group_data['total_affected_2nd_uom']:.3f} | Available: {group_data['max_2nd_uom']:.3f}"
                )
            
            # Check if total max units exceeds max total units
            if round(group_data['total_max_units'], 3) > round(group_data['max_total_units'], 3):
                errors.append(
                    f"      • Packs → Picked: {group_data['total_max_units']:.3f} | Available: {group_data['max_total_units']:.3f}"
                )
            
            # Check if total quantity exceeds max quant
            if round(group_data['total_quantity'], 3) > round(group_data['max_quant'], 3):
                errors.append(
                    f"      • Weight (KG) → Picked: {group_data['total_quantity']:.3f} | Available: {group_data['max_quant']:.3f}"
                )
            
            # Collect error if any validation failed
            if errors or warnings:
                message_parts = [
                    f"\n{'='*50}",
                    f"⚠️  PALLET VALIDATION ERROR",
                    f"{'='*50}",
                    f"📦 Pallet Series: {pallet_series}",
                    ""
                ]
                
                if errors:
                    message_parts.append("❌ EXCEEDED LIMITS:")
                    message_parts.extend(errors)
                    message_parts.append("")
                
                if warnings:
                    message_parts.append("⚠️  INCOMPLETE ENTRIES:")
                    message_parts.append("      All lines should share the available quantity.")
                    message_parts.extend(warnings)
                    message_parts.append("")
                
                message_parts.append(f"{'='*50}\n")
                all_pallet_errors.append("\n".join(message_parts))
        
        # Raise all collected pallet errors at once
        if all_pallet_errors:
            raise UserError("\n".join(all_pallet_errors))
                
                
    # === NEGATIVE STOCK PREVENTION (Outgoing Only) ===
    if record.picking_type_code == 'outgoing' and record.move_line_ids:
        pallet_product_demand = {}
        for move_line in record.move_line_ids:
            if not move_line.package_id:
                continue
            key = (move_line.package_id.id, move_line.product_id.id, move_line.lot_id.id)
            if key not in pallet_product_demand:
                pallet_product_demand[key] = {
                    'package_name': move_line.package_id.name,
                    'product_name': move_line.product_id.display_name,
                    'lot_name': move_line.lot_id.name if move_line.lot_id else 'N/A',
                    'pallet_series': move_line.x_studio_pallet_series_id if move_line.x_studio_pallet_series_id else '',
                    'total_demand_kg': 0.0,
                    'total_demand_2nd_uom': 0.0,
                    'total_demand_total_units': 0.0,
                    'location_id': move_line.location_id.id,
                }
            pallet_product_demand[key]['total_demand_kg'] += move_line.quantity
            pallet_product_demand[key]['total_demand_2nd_uom'] += move_line.x_studio_affected_2nd_uom
            pallet_product_demand[key]['total_demand_total_units'] += move_line.x_studio_withdraw_units
        
        negative_stock_errors = []
        for (package_id, product_id, lot_id), demand in pallet_product_demand.items():
            quant = env['stock.quant'].search([
                ('package_id', '=', package_id),
                ('product_id', '=', product_id),
                ('lot_id', '=', lot_id),
            ], limit=1)
            available_kg = quant.quantity if quant else 0.0
            available_2nd_uom = quant.x_studio_2nd_uom if quant else 0.0
            available_total_units = quant.x_studio_total_units if quant else 0.0
            
            pallet_label = demand['pallet_series'] or demand['package_name']
            error_parts = []
            
            # Check KG (quantity)
            if round(demand['total_demand_kg'], 3) > round(available_kg, 3) and available_kg >= 0:
                error_parts.append(
                    f"   Weight (KG) → Demand: {demand['total_demand_kg']:.3f} | Available: {available_kg:.3f} | ⚠️  Exceeds by {demand['total_demand_kg'] - available_kg:.3f}"
                )
            
            # Check 2nd UOM (affected_2nd_uom)
            if round(demand['total_demand_2nd_uom'], 3) > round(available_2nd_uom, 3) and available_2nd_uom >= 0:
                error_parts.append(
                    f"   Quantity (2nd UOM) → Demand: {demand['total_demand_2nd_uom']:.3f} | Available: {available_2nd_uom:.3f} | ⚠️  Exceeds by {demand['total_demand_2nd_uom'] - available_2nd_uom:.3f}"
                )
            
            # Check total units (withdraw_units)
            if round(demand['total_demand_total_units'], 3) > round(available_total_units, 3) and available_total_units >= 0:
                error_parts.append(
                    f"   Packs (Total Units) → Demand: {demand['total_demand_total_units']:.3f} | Available: {available_total_units:.3f} | ⚠️  Exceeds by {demand['total_demand_total_units'] - available_total_units:.3f}"
                )
            
            if error_parts:
                error_msg = f"📦 Pallet: {pallet_label}\n"
                error_msg += f"   Product: {demand['product_name']}\n"
                error_msg += "\n".join(error_parts)
                negative_stock_errors.append(error_msg)
        
        if negative_stock_errors:
            raise UserError(
                "🚫 NEGATIVE STOCK PREVENTION\n\n"
                "The following pallet(s) do not have enough stock to fulfill the requested withdrawal:\n\n"
                + "\n\n".join(negative_stock_errors) + "\n\n"
                "Please adjust the quantities or select different Pallets."
            )
            
    # === END NEGATIVE STOCK PREVENTION ===
    
    # Check location restrictions
    if record.location_id.name == "Vendors" and record.state == "assigned" and record.picking_type_code == "outgoing":
        raise UserError("Please Change the Source Location")
    
    if (record.location_dest_id.name == "Customers" or record.location_dest_id.name == "Stock") and record.state == "assigned" and record.picking_type_code == "incoming":
        raise UserError("Please Change the Destination Location")
        
    if record.location_dest_id.name == "BF":
        raise UserError("Please Change the Destination Location")
    
    # Check required fields based on operation type
    is_blast_freeze, is_receiving = record.operation_type_checker(record.picking_type_id)
    if is_blast_freeze and is_receiving:
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',  'x_studio_warehouse_checker', 'x_studio_warehouse_supervisor', 'x_studio_client_reference',
            'x_studio_source', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver', 'documentation_staff_id', 'x_studio_blastman'
        ]
    elif is_blast_freeze and not is_receiving:
        field_technical_names = [
            'x_studio_start_time', 'x_studio_end_time', 'x_studio_destination', 'x_studio_warehouse_checker', 'x_studio_warehouse_supervisor', 'x_studio_atw_no', 'documentation_staff_id', 'x_studio_blastman'
        ]
    elif not is_blast_freeze and is_receiving:
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',
            'x_studio_source', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver', 'x_studio_warehouse_checker', 'x_studio_warehouse_supervisor', 'x_studio_client_reference', 'documentation_staff_id', 'x_studio_operator', 'x_studio_warehouseman'
        ]
    else:  # not is_blast_freeze and not is_receiving
        field_technical_names = [
            'x_studio_truck_time', 'x_studio_start_time', 'x_studio_end_time',
            'x_studio_destination', 'x_studio_loading_dock_no', 'x_studio_gate_pass',
            'truck_type', 'x_studio_trucks_plate_', 'x_studio_driver', 'x_studio_warehouse_checker', 'x_studio_warehouse_supervisor', 'x_studio_atw_no', 'documentation_staff_id', 'x_studio_operator', 'x_studio_warehouseman'
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

    def validate_move_line_combination(data, line, error_messages, locs_and_pallets_expiration):
        """Helper function to validate pallet, product, and location combinations for each move line."""
        if line.result_package_id.id:
            
            if data['package_id'] == line.result_package_id.id and data['product_id'] != line.product_id.id:
                if data['location_id'] != line.location_dest_id.id:
                    error_messages['multiple_products'].append(
                        f"Pallet: {line.result_package_id.name}, Products: {line.product_id.display_name} with another product."
                    )
    
    
            
            if data['package_id'] == line.result_package_id.id and data['product_id'] == line.product_id.id:
                if data['location_id'] != line.location_dest_id.id:
                    error_messages['multiple_locations'].append(
                        f"Product: {line.product_id.display_name}, Pallet: {line.result_package_id.name} with different locations."
                    )
    
                if (data['x_studio_production_date'] == line.x_studio_production_date and
                    data['x_studio_expiration_date'] == line.x_studio_expiration_date) and line.x_studio_production_date and line.x_studio_expiration_date:
                    error_messages['duplicate_lines'].append(
                        f"Product: {line.product_id.display_name}, Pallet: {line.result_package_id.name} with identical details."
                    )
    
    location_pallet_tracker = {}
    locs_and_pallets_expiration = []
    
    # Initialize a dictionary to keep track of unique products per pallet
    pallet_product_tracker = {}
    
    # Initialize a dictionary to track pallet series per package
    package_pallet_series_tracker = {}

    for line in lines:
        location, package = line.location_dest_id, line.result_package_id
    
    
        if line.result_package_id.x_studio_is_reserved and line.result_package_id.x_studio_receiving_report_id.id != line.picking_id.id:
            error_messages['already_reserved'].append(
                f"Pallet: {line.result_package_id.name}, is already reserved in another Transfer: {line.picking_id.name}. Please change the Pallet manually."
            )
          
        # Check for missing pallet (destination_package_id) and skip further validation if missing
        if not package and not line.picking_id.x_studio_is_a_blast_freezer and record.picking_type_code == 'incoming':
            error_messages['missing_package'].append(
                f"Product: {line.product_id.display_name}, Location: {location.display_name} - Missing Pallet."
            )
            continue  # Skip further checks if package is not set
    
        # Track pallet series per package to detect multiple series assignments
        if line.result_package_id and line.x_studio_pallet_series_id:
            # Get pallet series name - check if it's a recordset or a simple value
            try:
                pallet_series_name = line.x_studio_pallet_series_id.name
            except:
                pallet_series_name = str(line.x_studio_pallet_series_id)
            
            if line.result_package_id.id not in package_pallet_series_tracker:
                package_pallet_series_tracker[line.result_package_id.id] = {
                    'package_name': line.result_package_id.name,
                    'series': set([pallet_series_name])
                }
            else:
                package_pallet_series_tracker[line.result_package_id.id]['series'].add(pallet_series_name)
    
        # Check for missing production or expiration dates
        if not line.x_studio_production_date or not line.x_studio_expiration_date:
            error_messages['missing_dates'].append(
                f"Product: {line.product_id.display_name}, Pallet: {package.name}, "
                f"Location: {location.display_name} - Missing Production or Expiration Date."
            )
        # Check for missing container
        if not line.x_studio_container_number:
            error_messages['missing_container_number'].append(
                f"Product: {line.product_id.display_name}, Pallet: {package.name}, "
                f"Location: {location.display_name} - Missing Container Number."
            )
            
        # Check for missing pallet_series id
        if not line.x_studio_pallet_series_id:
            error_messages['missing_pallet_series_id'].append(
                f"Product: {line.product_id.display_name}, Pallet: {package.name}, "
                f"Location: {location.display_name} - Unassigned Pallet Series ID."
            )
            
        # Check for zero quantity
        if line.quantity == 0:  # Here, we're checking if quantity is 0
            error_messages['zero_quantity'].append(
                f"Product: {line.product_id.display_name}, Pallet: {package.name}, "
                f"Location: {location.display_name} - Quantity is zero."
            )
    
        # Continue if not an internal location or if pallet owner matches line owner
        if location.usage != 'internal' or package.owner_id == line.owner_id:
            continue
    
        # Track unique products for each pallet
        if package.id not in pallet_product_tracker:
            pallet_product_tracker[package.id] = {line.product_id.id}
        else:
            pallet_product_tracker[package.id].add(line.product_id.id)
    
        # Validate product count per pallet
        max_limit = env['x_inventory_static_var'].search([('x_studio_warehouse', '=', record.picking_type_id.warehouse_id.id), ('x_name', '=', 'Max Unique Product Per Pallet')], limit=1).x_studio_float_value

        if len(pallet_product_tracker[package.id]) > max_limit:
            error_messages['product_limit'].append(
                f"Pallet '{package.name}' contains more than 3 unique products. "
                f"Only 3 products are allowed per pallet."
            )
    
        #Check if Location has Child then its an invalid location
        if line.location_dest_id.child_ids:
            error_messages['invalid_location'].append(
                f"Product: {line.product_id.display_name}, Pallet: {package.name}, "
                f"Has a detailed operation line that does have a valid location set!"
                )

        if not line.bf_pallet_char and line.is_blast_freeze:
            error_messages['missing_bf_pallet_text'].append(
                f"Product: {line.product_id.display_name}"
                f"Has a missing Pallet # - Text input!"
                )
        

        # Validate other conditions
        for data in locs_and_pallets_expiration:
            validate_move_line_combination(data, line, error_messages, locs_and_pallets_expiration)
    
        locs_and_pallets_expiration.append({
            'location_id': location.id,
            'package_id': package.id,
            'product_id': line.product_id.id,
            'x_studio_production_date': line.x_studio_production_date,
            'x_studio_expiration_date': line.x_studio_expiration_date,
            'x_studio_container_number': line.x_studio_container_number,
        })
    
        # Check for multiple pallets in a single location if it's not an aisle
        if not location.x_studio_is_an_aisle:
            if location.id not in location_pallet_tracker:
                location_pallet_tracker[location.id] = {package.name}
            else:
                if package.name not in location_pallet_tracker[location.id]:
                    location_pallet_tracker[location.id].add(package.name)
                    error_messages['multiple_pallets'].append(
                        f"Location ID '{location.id}' has multiple pallets assigned: {', '.join(location_pallet_tracker[location.id])}."
                    )

    # Check for packages with multiple pallet series
    for package_id, data in package_pallet_series_tracker.items():
        if len(data['series']) > 1:
            series_list = '\n      • '.join(sorted(data['series']))
            error_messages['multiple_pallet_series'].append(
                f"Pallet: {data['package_name']}\n"
                f"   Has multiple Pallet Series IDs assigned ({len(data['series'])} found):\n"
                f"      • {series_list}\n"
                f"   ⚠️  Please check the Pallet # field and avoid using multi-select when setting Pallet # to avoid this error."
            )

    # New UOM validation checks
    for move_line in record.move_line_ids:
        # Check if x_studio_2nd_uom is set but x_studio_quantity_uom is not
        if move_line.x_studio_2nd_uom and not move_line.x_studio_quantity_uom:
            error_messages['missing_uom'].append(
                f"Product: {move_line.product_id.display_name}, Pallet: {move_line.result_package_id.name if move_line.result_package_id else 'N/A'} - "
                f"Has Quantity set but Unit of Measure is missing (e.g Boxes, Crates, Blocks)."
            )
            
        # Check if x_studio_total_units is set but x_studio_min_quantity_uom is not
        if move_line.x_studio_total_units and not move_line.x_studio_min_quantity_uom:
            error_messages['missing_uom'].append(
                f"Product: {move_line.product_id.display_name}, Pallet: {move_line.result_package_id.name if move_line.result_package_id else 'N/A'} - "
                f"Has Packs set but Packs Unit of Measure is missing. (e.g Packs, Heads, Chicken Heads)"
            )
            
            
    if record.return_id and record.return_id.state == "done":
        if record.return_id.partner_id != record.partner_id:
            raise UserError(
                "Please set the Customer on this Document the same as the Source WR Document.\n"
                f"Source WR Customer: {record.return_id.partner_id.name}"
            )
            
            
    # === DUPLICATE PALLET SERIES IN STOCK CHECK (Incoming non-return only) ===
    if record.picking_type_code == 'incoming' and not record.return_id and not record.picking_type_id.is_blast_freeze_operation:
        # Collect unique (pallet_series, owner) combos from NEW lines only
        seen_combos = set()
        combos_to_check = []
        for move_line in record.move_line_ids:
            if not move_line.x_studio_pallet_series_id:
                continue
            if (move_line.x_studio_return_count or 0) != 0:
                continue  # Skip return lines
            # A merged line ADOPTS a series already in stock — that is what
            # merging means. Same exemption the return lines above get.
            # (is_pallet_merge is defined on stock.move.line by
            # multiple_relocation, so it is always present here. Server actions
            # run sandboxed — no getattr/hasattr builtins — so access it direct.)
            if move_line.is_pallet_merge:
                continue
            combo_key = (
                move_line.x_studio_pallet_series_id,
                move_line.owner_id.id,
            )
            if combo_key not in seen_combos:
                seen_combos.add(combo_key)
                combos_to_check.append({
                    'series': move_line.x_studio_pallet_series_id,
                    'owner_id': move_line.owner_id.id,
                    'owner_name': move_line.owner_id.name,
                    'product_id': move_line.product_id.id,
                    'product_name': move_line.product_id.display_name,
                })
    
        for combo in combos_to_check:
            existing_quant = env['stock.quant'].search([
                ('x_studio_pallet_series_id', '=', combo['series']),
                ('owner_id', '=', combo['owner_id']),
                ('quantity', '>', 0),
            ], limit=1)

            if existing_quant:
                error_messages['existing_pallet_series'].append(
                    f"   • {combo['series']}  —  {combo['product_name']} "
                    f"({combo['owner_name']})\n"
                    f"       standing at {existing_quant.location_id.display_name}, "
                    f"{existing_quant.quantity:.3f} KG"
                )
    # === END DUPLICATE PALLET SERIES CHECK ===
    
    # Assemble final error messages for readability and grouped output with separators
    separator = "\n--------------------------------------------------------------------------------------\n"
    
    if error_messages['missing_package']:
        final_error_message.append("\n\n❗ **Missing Pallets:**")
        final_error_message.append(separator.join(error_messages['missing_package']))
    
    if error_messages['missing_dates']:
        final_error_message.append("\n\n❗ **Missing Production or Expiration Dates:**")
        final_error_message.append(separator.join(error_messages['missing_dates']))
        
    if error_messages['missing_container_number'] and record.picking_type_id and record.picking_type_code == 'incoming'  and not record.picking_type_id.is_blast_freeze_operation:
        final_error_message.append("\n\n❗ **Missing Container Number**")
        final_error_message.append(separator.join(error_messages['missing_container_number']))
        
    if error_messages['missing_pallet_series_id']  and record.picking_type_id and record.picking_type_code == 'incoming' and not record.picking_type_id.is_blast_freeze_operation:
        final_error_message.append("\n\n❗ **Unassigned Pallet Series ID**")
        final_error_message.append(separator.join(error_messages['missing_pallet_series_id']))
    
    if error_messages['multiple_pallet_series']:
        final_error_message.append("\n\n⚠️ **Multiple Pallet Series per Package:**")
        final_error_message.append(separator.join(error_messages['multiple_pallet_series']))
    
    if error_messages['reserved_pallets']:
        final_error_message.append("\n\n🚫 **Reserved Pallets:**")
        final_error_message.append(separator.join(error_messages['reserved_pallets']))
    
    if error_messages['multiple_products']:
        final_error_message.append("\n\n🔄 **Multiple Products in One Pallet with Different Locations:**")
        final_error_message.append(separator.join(error_messages['multiple_products']))
    
    if error_messages['multiple_locations']:
        final_error_message.append("\n\n📍 **Single Pallet with Multiple Locations:**")
        final_error_message.append(separator.join(error_messages['multiple_locations']))
    
    if error_messages['multiple_pallets'] and record.picking_type_id and record.picking_type_code == 'incoming' and not record.picking_type_id.is_blast_freeze_operation:
        final_error_message.append("\n\n🚧 **Multiple Pallets in One Location:**")
        final_error_message.append(separator.join(error_messages['multiple_pallets']))
        
    if error_messages['already_reserved'] and record.picking_type_id and record.picking_type_code == 'incoming' and not record.picking_type_id.is_blast_freeze_operation:
        final_error_message.append("\n\n🚧 **Already reserved Pallets:**")
        final_error_message.append(separator.join(error_messages['already_reserved']))
        
    if error_messages['product_limit']:
        final_error_message.append("\n\n⚠️ **Exceeded Product Limit per Pallet:**")
        final_error_message.append(separator.join(error_messages['product_limit']))
    
    if error_messages['zero_quantity']:
        final_error_message.append("\n\n🚫 **Zero Quantity:**")
        final_error_message.append(separator.join(error_messages['zero_quantity']))
    
    if error_messages['invalid_location']:
        final_error_message.append("\n\n🎯 **Invalid Location:**")
        final_error_message.append(separator.join(error_messages['invalid_location']))
        
    if error_messages['missing_bf_pallet_text']:
        final_error_message.append("\n\n🧊 **Missing Blast Freeze Pallet # - Text Input:**")
        final_error_message.append(separator.join(error_messages['missing_bf_pallet_text']))
        
    if error_messages['missing_uom']:
        final_error_message.append("\n\n📏 **Missing UOM Assignments:**")
        final_error_message.append(separator.join(error_messages['missing_uom']))
        
    if error_messages['existing_pallet_series']:
        final_error_message.append(
            "\n\n🚫 **Pallet Series Already In Stock**\n"
            "Each Pallet Series is one physical pallet, so it can only be "
            "received once. These are already on the floor:")
        final_error_message.append(separator.join(error_messages['existing_pallet_series']))
        final_error_message.append(
            "\n👉 What to do: give this line a fresh Pallet Series. If you meant "
            "to add this stock onto the pallet above, use the \"Merge Pallet\" "
            "button on the line instead (when merging is enabled for this client).\n"
            "If you believe the series should really be free, contact your "
            "administrator.")
        
    # Raise the final error message if there are any errors collected
    if final_error_message:
        raise UserError('\n'.join(final_error_message))
    

        
    # If no errors, mark the record as verified
    record['x_studio_verified'] = True
    # Check for discrepancy without NCR report
    if record.x_studio_has_discrepancy and not record.x_studio_has_generated_an_ncr:
        raise UserError("Discrepancy Detected, Please generate an NCR Report first before validating the record.")
     
   
        
    customer_location = env['stock.location'].search([('usage', '=', 'customer')], limit=1)
    if customer_location and record.picking_type_code == 'outgoing':
        for move_line in record.move_line_ids:
            if move_line.location_dest_id.usage != 'customer':
                move_line['location_dest_id'] = customer_location
                
                
                
                
for record in records:
    if record.is_void_return or record.is_void_wr:
        continue
    if not record.picking_type_id:
        continue

    max_days_back = record._get_max_days_back_config()
    now = datetime.datetime.utcnow()
    cutoff_past = now - datetime.timedelta(days=max_days_back)
    cutoff_future = now + datetime.timedelta(days=max_days_back)

    date_errors = []
    for field, label in [('x_studio_truck_time', 'Truck Time'), ('x_studio_start_time', 'Start Time'), ('x_studio_end_time', 'End Time')]:
        value = record[field]
        if value:
            if value < cutoff_past:
                days_off = (now - value).days
                date_errors.append("• %s: %s days too far in the past (max %s days allowed)." % (label, days_off, int(max_days_back)))
            elif value > cutoff_future:
                days_off = (value - now).days
                date_errors.append("• %s: %s days too far in the future (max %s days allowed)." % (label, days_off, int(max_days_back)))

    if date_errors:
        raise UserError("The following date(s) are out of the allowed range:\n\n" + "\n".join(date_errors))
