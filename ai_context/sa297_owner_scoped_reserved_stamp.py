# SA#297 "Pallet Kilos Record - Create Record Per Move" (AR#6)
# PATCH: owner-scoped reserved_quantity_on_validation stamp.
#
# Replace ONLY this block inside the outgoing section:
#
#     if code  == "outgoing" and not is_blast_freeze:
#         for record in records:
#                 if record.state in ['done']:
#                     for line in record.move_line_ids:
#                         if line.quantity != 0:
#                             line['reserved_quantity_on_validation'] = line.package_id.x_studio_total_quantity
#
# with the version below. Everything after (the pallet_kilos_model.create
# call etc.) stays unchanged.
#
# WHY: x_studio_total_quantity is the package total across ALL owners.
# On a shared pallet, another client's stock keeps the total above zero,
# so this owner's final withdrawal never reads 0 and never counts as a
# pallet withdrawn in the per-owner ledger (760 historical lines
# affected). The stamp must measure what is left on the pallet FOR THE
# LINE'S OWNER only.

    if code == "outgoing" and not is_blast_freeze:
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
                                    and q.quantity > 0):
                                remaining += q.quantity
                        line['reserved_quantity_on_validation'] = remaining
