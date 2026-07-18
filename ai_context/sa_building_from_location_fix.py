# =============================================================================
# PASTE-READY FIX for Server Action #443 — "On Change Destination Location"
# Model: stock.picking   Triggered by: automation #49 (on create/write of
# location_dest_id, filtered to picking_type_code = 'incoming')
# =============================================================================
#
# WHAT IT DOES
#   Stamps x_studio_building_1 from the receipt's destination location.
#
# WHY IT NEEDS CHANGING — two faults in the version running today:
#
#   1. BLAST FREEZE IS MISFILED.  Automation #49 fires for every 'incoming'
#      type, and that includes Blast Freeze - IN. Those receipts go to the
#      freezer chambers (M/BF/M/CH1), which match neither 'M/A' nor 'M/M', so
#      they fall into the else branch and are stamped EXPANSION.
#      121 of the 125 BF receipts in the database carry that wrong building
#      right now. The chambers belong to no building at all.
#
#   2. THE BUILDING IS GUESSED FROM THE NAME.  `'M/A' in complete_name` is a
#      substring test. It is correct for all 45,885 locations that exist today
#      — I checked every one — but it is correct by luck, not by construction:
#      a location named 'M/M/Aisle 1' contains 'M/A' at offset 2 and would be
#      filed under ANNEX. The moment someone creates an aisle without a number
#      in the path, stock starts being reported in the wrong building.
#      This version walks parent_path instead, which cannot be fooled.
#
# NOTE: the else branch also assigned a recordset (`= building`) where the
# other two branches assigned an id (`= building.id`). Harmless, but the
# version below is consistent.
#
# HOW TO APPLY
#   Settings > Technical > Server Actions > #443 "Execute Code"
#   Replace the code below the comment header with this block.
# =============================================================================

building_model = env['x_warehouse_building']
by_preset = {
    b.x_studio_preset_location.id: b.id
    for b in building_model.search([('x_studio_preset_location', '!=', False)])
}

for record in records:
    # Freezer chambers sit outside the building structure. Leaving the field
    # empty is the honest answer; EXPANSION is a wrong one.
    if record.x_studio_is_a_blast_freezer:
        record['x_studio_building_1'] = False
        continue

    location = record.location_dest_id
    ancestors = [int(x) for x in (location.parent_path or '').strip('/').split('/') if x]
    building = False
    for loc_id in ancestors:
        if loc_id in by_preset:
            building = by_preset[loc_id]
            break
    record['x_studio_building_1'] = building


# =============================================================================
# OPTIONAL ONE-TIME CLEANUP of the 121 blast-freeze receipts already stamped
# EXPANSION. Run once from the shell or a scratch server action — NOT part of
# the automation. Check the count first, then clear.
#
#   bf = env['stock.picking'].search([
#       ('x_studio_is_a_blast_freezer', '=', True),
#       ('x_studio_building_1', '!=', False)])
#   print(len(bf))                       # expect ~125
#   bf.write({'x_studio_building_1': False})
#
# Decide first whether any report groups blast freeze by building — if one
# does, it is currently grouping them all under EXPANSION, and clearing the
# field will move them to an empty group rather than to a correct one.
# =============================================================================
