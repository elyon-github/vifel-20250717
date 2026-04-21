# Reserved Quantity Bug Fix Recommendations

## Problem Summary

When quants are picked in a WR and then removed, their `reserved_quantity` on `stock.quant` doesn't get recalculated to 0. This is a data consistency issue affecting inventory tracking.

---

## The Culprit: `do_not_unreserve` Context

**File**: `multiple_relocation/models/stock_move.py` (Lines 188-194)

```python
def write(self, vals):
    # ... product swap logic ...
    
    # Check if we have incoming moves and need to prevent unreservation
    if 'product_uom_qty' in vals:
        has_incoming_moves = any(move.picking_type_id.code == 'incoming' for move in self)
        if has_incoming_moves:
            # Set context to prevent unreservation for incoming moves
            return super(StockMove, self.with_context(do_not_unreserve=True)).write(vals)
    
    return super(StockMove, self).write(vals)
```

### Why This Was Added
The comment says "prevent unreservation for incoming moves". The intent was likely to:
- Avoid cascading unreservation when product_uom_qty changes
- Keep certain qty adjustments from triggering move_line deletions

**But the problem**: This context, while scoped to that one write() call, has side effects through Odoo's ORM cascade behavior.

---

## Proposed Fix #1: Explicit Context Cleanup (Recommended)

**Approach**: Properly cleanup reserved quantities when move_lines are deleted, regardless of context.

### Step 1: Add a context flag to SelectQuantWizard.py

When removing move lines, explicitly clean up reservations:

```python
# File: multiple_relocation/wizard/SelectQuantWizard.py
# Replace line ~156:

if move_lines_to_remove:
    # Ensure quants are properly unreserved when lines are deleted
    # Even if they were reserved during a do_not_unreserve context
    move_lines_to_remove.with_context(unreserve_all=True).unlink()
```

### Step 2: Add custom unlink override in stock_move_line_Override

**File**: `multiple_relocation/models/stock_move.py`

Uncomment and fix the currently disabled unlink method (lines 526-531):

```python
def unlink(self):
    """Override unlink to explicitly handle reserved quantity cleanup.
    
    This handles the case where move_lines were created/modified with
    do_not_unreserve=True context and need proper cleanup on deletion.
    """
    # Get quants that are reservations for these move_lines
    reserved_quant_ids = []
    for line in self:
        # Find any stock.quant that has reservations pointing to this line
        quants = self.env['stock.quant'].search([
            ('reserved_quantity', '>', 0),
            # Match by location, product, lot, package
            ('location_id', '=', line.location_id.id),
            ('product_id', '=', line.product_id.id),
            ('lot_id', '=', line.lot_id.id if line.lot_id else False),
            ('package_id', '=', line.package_id.id if line.package_id else False),
        ])
        if quants:
            reserved_quant_ids.extend(quants.ids)
    
    # Proceed with deletion
    res = super(stock_move_line_Override, self).unlink()
    
    # Force recompute of reserved_quantity for affected quants
    # This ensures they get recalculated even if do_not_unreserve was used
    if reserved_quant_ids:
        quants = self.env['stock.quant'].browse(reserved_quant_ids)
        for quant in quants:
            quant._compute_reserved_quantity()
    
    return res
```

---

## Proposed Fix #2: Scope the `do_not_unreserve` Context Better (Alternative)

**File**: `multiple_relocation/models/stock_move.py`

Instead of relying on context that persists, explicitly control what should/shouldn't unreserve:

```python
def write(self, vals):
    if 'product_id' in vals:
        incoming_moves_with_lines = self.filtered(
            lambda m: m.picking_type_id.code == 'incoming'
            and m.state not in ('done', 'cancel')
            and m.move_line_ids
        )
        if incoming_moves_with_lines:
            return incoming_moves_with_lines._write_swap_product(vals)

    if 'product_uom_qty' in vals:
        has_incoming_moves = any(move.picking_type_id.code == 'incoming' for move in self)
        if has_incoming_moves:
            # Instead of context, explicitly handle the write without cascading unreservation
            # by temporarily disconnecting move_lines, writing, then reconnecting
            moves_to_update = self.filtered(lambda m: m.picking_type_id.code == 'incoming')
            
            for move in moves_to_update:
                # Store move_line associations
                move_lines = move.move_line_ids
                move_line_ids = move_lines.ids
                
                # Temporarily detach move_lines using raw SQL to avoid cascade triggers
                self.env.cr.execute(
                    "UPDATE stock_move_line SET move_id = NULL WHERE move_id = %s",
                    (move.id,)
                )
                move.invalidate_recordset(['move_line_ids'])
                
                # Now write the vals (including product_uom_qty) without triggering unreservation
                super(StockMove, move).write(vals)
                
                # Re-attach move_lines
                self.env.cr.execute(
                    "UPDATE stock_move_line SET move_id = %s WHERE id IN %s",
                    (move.id, tuple(move_line_ids))
                )
                move.invalidate_recordset(['move_line_ids'])
            
            # Process non-incoming moves normally
            non_incoming = self.filtered(lambda m: m.picking_type_id.code != 'incoming')
            if non_incoming:
                super(StockMove, non_incoming).write(vals)
            
            return True
    
    return super(StockMove, self).write(vals)
```

---

## Proposed Fix #3: Quant State Cleanup Routine (Simplest)

Add a maintenance method to clean up orphaned reservations:

**File**: `multiple_relocation/models/stock_quant.py` (create if doesn't exist)

```python
def cleanup_orphaned_reservations(self):
    """Find and cleanup reserved quantities that have no associated move_lines."""
    
    orphaned_quants = []
    
    for quant in self:
        if quant.reserved_quantity > 0:
            # Find move_lines that would cover this reservation
            move_lines = self.env['stock.move.line'].search([
                ('product_id', '=', quant.product_id.id),
                ('location_id', '=', quant.location_id.id),
                ('lot_id', '=', quant.lot_id.id if quant.lot_id else False),
                ('package_id', '=', quant.package_id.id if quant.package_id else False),
                ('state', 'not in', ['done', 'cancel']),
            ])
            
            # If no move_lines exist for this quant but it has reserved qty, it's orphaned
            if not move_lines:
                orphaned_quants.append(quant.id)
    
    # Clear reserved quantities for orphaned quants
    if orphaned_quants:
        self.env['stock.quant'].browse(orphaned_quants).write({
            'reserved_quantity': 0
        })
    
    return len(orphaned_quants)
```

Then call it from SelectQuantWizard after removing lines:

```python
# In SelectQuantWizard.py action_confirm(), after move_lines_to_remove.unlink():
if move_lines_to_remove:
    move_lines_to_remove.unlink()
    
    # Cleanup any orphaned reservations
    affected_locations = move_lines_to_remove.mapped('location_id')
    if affected_locations:
        affected_quants = self.env['stock.quant'].search([
            ('location_id', 'in', affected_locations.ids)
        ])
        affected_quants.cleanup_orphaned_reservations()
```

---

## Recommendation

**Use Fix #1** (Explicit Context Cleanup) because:

1. ✅ **Minimal change**: Only uncomment + fix existing code
2. ✅ **Targeted**: Only affects move_line deletion and its results
3. ✅ **Preserves intent**: Doesn't remove the do_not_unreserve logic, just cleans up after it
4. ✅ **No side effects**: Doesn't reshape the product_uom_qty write logic
5. ✅ **Testable**: Clear cause-effect between deletion and cleanup

**Alternative**: If Fix #1 causes issues, use Fix #3 (Cleanup Routine) as a safety net—run it periodically or after major operations.

---

## Testing Steps After Fix

1. **Pick quants in WR**: Select multiple quants from packages
2. **Check reserved_qty**: Verify `select reserved_quantity from stock_quant where id = X` shows reserved > 0
3. **Remove quants**: Remove them from the WR (via SelectQuantWizard)
4. **Re-check**: Verify `reserved_quantity = 0` now  
5. **Test edge cases**:
   - Remove ALL quants from a picking
   - Remove SOME quants from a picking
   - Multiple products/lots on same pallet
   - Blast freeze vs. normal pickings
