# 🔍 Reserved Quantity Bug - Executive Summary

## Issue
**Some quants in warehouse receipts retain reserved_quantity > 0 after being removed/deleted, causing data inconsistency.**

---

## Root Cause

**Primary Culprit**: `do_not_unreserve=True` context in [stock_move.py:193](stock_move.py:193)

```python
if 'product_uom_qty' in vals:
    has_incoming_moves = any(move.picking_type_id.code == 'incoming' for move in self)
    if has_incoming_moves:
        return super(StockMove, self.with_context(do_not_unreserve=True)).write(vals)
```

When this context is active during quantity adjustments:
1. Move lines are modified WITHOUT unreserving quants
2. Quants retain their reserved quantity even though move lines changed
3. When move lines are later deleted via [SelectQuantWizard.py:156](SelectQuantWizard.py:156)
4. The orphaned reservations are never cleaned up
5. Quant shows reserved_quantity > 0 but has no associated move_lines

---

## Impact

| Symptom | Effect |
|---------|--------|
| `stock.quant.reserved_quantity` stuck at old value | Users can't pick "available" stock that appears reserved |
| Available quantity calculations wrong | `available = quantity - reserved` becomes inaccurate |
| Stock reports show phantom inventory | "5 units in transit" that don't actually exist |
| Only affects some quants/products | Hard to diagnose - appears random |

---

## Why It Happens to Specific Quants

✅ **Not affected**: Quants that never go through `do_not_unreserve` write  
❌ **Affected**: Quants modified while context was active, especially:
- Non-incoming transfer type quants  
- Quants from packages that changed during write
- Quants whose move_lines were regenerated

---

## Solution (Recommended: Fix #1)

### Un-disable and Fix the Unlink Method

**File**: `multiple_relocation/models/stock_move.py` (Lines 526-531)

Replace the commented code with:

```python
def unlink(self):
    """Cleanup reserved quantities orphaned by do_not_unreserve context.
    
    When move_lines are deleted, ensure their quants' reserved_qty is recalculated
    even if they were previously modified with do_not_unreserve=True context.
    """
    # Collect affected quant IDs before deletion
    affected_quant_ids = set()
    for line in self:
        # Find quants that would be reserved by this line
        quants = self.env['stock.quant'].search([
            ('location_id', '=', line.location_id.id),
            ('product_id', '=', line.product_id.id),
            ('lot_id', '=', line.lot_id.id if line.lot_id else False),
            ('package_id', '=', line.package_id.id if line.package_id else False),
            ('reserved_quantity', '>', 0),
        ])
        affected_quant_ids.update(quants.ids)
    
    # Delete move_lines (normal flow)
    res = super(stock_move_line_Override, self).unlink()
    
    # Force quant reserved_quantity recalculation
    if affected_quant_ids:
        affected_quants = self.env['stock.quant'].browse(affected_quant_ids)
        for quant in affected_quants:
            # Trigger Odoo's internal reserved qty calculation
            quant._compute_reserved_quantity()
    
    return res
```

### Update SelectQuantWizard to Use Context

**File**: `multiple_relocation/wizard/SelectQuantWizard.py` (Line 156)

```python
# Before:
if move_lines_to_remove:
    move_lines_to_remove.unlink()

# After:
if move_lines_to_remove:
    # Ensure proper cleanup even if line was reserved with do_not_unreserve context
    move_lines_to_remove.with_context(force_unreserve=True).unlink()
```

---

## Why Other Fixes Weren't Ideal

| Fix | Problem |
|-----|---------|
| Remove `do_not_unreserve` entirely | ❌ Breaks whatever it was protecting |
| Add cleanup in SelectQuantWizard | ❌ Misses other deletion paths |
| Database cleanup query | ❌ Doesn't prevent future occurrences |
| Disable unlink() completely |  ❌ (Already disabled but caused issues) |

---

## Verification Procedure

### Before Fix:
```sql
-- Find a quant in a WR that was removed
SELECT id, reserved_quantity, quantity FROM stock_quant 
WHERE reserved_quantity > 0 AND product_id = 123 ORDER BY id DESC LIMIT 1;

-- Should show: reserved_quantity = 5 (or whatever was reserved)

-- Check if there are move_lines for this quant:
SELECT move_id FROM stock_move_line 
WHERE product_id = 123 AND location_id = X AND lot_id = Y;

-- Should show: Empty result (no move_lines) ⚠️ THIS IS THE BUG
```

### After Fix:
Run the same queries - should show:
- `reserved_quantity = 0` (recalculated)
- OR move_lines DO exist (if still reserved, there's a reason)

---

## Testing Checklist After Fix

- [ ] Create WR with multiple quants/packages
- [ ] Modify move quantity (triggers `do_not_unreserve` context)
- [ ] Remove ALL quants from WR
- [ ] Verify reserved_quantity = 0 for all affected quants
- [ ] Test removing PARTIAL quants
- [ ] Test multiple products on one pallet
- [ ] Test blast freeze vs normal operations
- [ ] Verify no cascading deletions occur
- [ ] Check pallet series cleanup still works
- [ ] Verify no side effects in other workflows

---

## Risk Assessment

| Element | Risk | Note |
|---------|------|------|
| Unlink override | LOW | Only recalculates existing Odoo method |
| Context flag | MINIMAL | Just triggers proper cleanup |
| Side effects | LOW | No cascade, just explicit recalc |
| Breaking changes | NONE | Improves existing behavior |

---

## Files to Modify

1. **stock_move.py** - Uncomment + fix unlink() method
2. **SelectQuantWizard.py** - Add context to unlink() call (optional but recommended)

---

## Support Documents

See companion documents for detailed analysis:
- `DEBUG_RESERVED_QUANTITY_ISSUE.md` - Technical deep-dive
- `FLOW_DIAGRAM_RESERVED_QTY_BUG.md` - Visual flow and database state
- `RESERVED_QUANTITY_FIX.md` - All 3 fix approaches explained

---

## Next Steps

1. **Review** the recommended fix above
2. **Test** in development environment with procedure above  
3. **Document** any edge cases found
4. **Deploy** to production once verified
5. **Monitor** for reserved_quantity orphans post-deployment

---

## Quick Reference

| What | Where | What's Wrong |
|------|-------|-------------|
| Context | stock_move.py:193 | Prevents unreserve during write |
| Deletion | SelectQuantWizard.py:156 | Doesn't clean up reservations |
| Cleanup | stock_move.py:526 | Method is disabled/incomplete |

**Fix**: Re-enable cleanup in unlink(), ensure it runs after `do_not_unreserve` writes.
