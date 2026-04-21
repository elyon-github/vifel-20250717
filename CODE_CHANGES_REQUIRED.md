# Code Changes Required - Remediation Plan

## Summary
Three files need modifications. This document shows exact code changes needed.

---

## Change #1: Un-disable and Fix unlink() in stock_move.py

**File**: `multiple_relocation/models/stock_move.py`  
**Lines**: 526-531 (currently disabled)  
**Status**: REQUIRED

### Current Code (BROKEN):
```python
    # def unlink(self):
    #     # Get related stock moves before deleting move lines
    #     moves = self.mapped('move_id')

    #     # Proceed with the deletion
    #     res = super(stock_move_line_Override, self).unlink()
```

### New Code (FIXED):
```python
    def unlink(self):
        """Override unlink to cleanup reserved quantities.
        
        Handles the case where move_lines were created/modified with 
        do_not_unreserve=True context. When these lines are deleted,
        their quants may be left with orphaned reserved_quantity values.
        This method ensures those quantities are recalculated.
        """
        # Collect quant IDs that may have orphaned reservations
        affected_quant_ids = set()
        
        for line in self:
            # Find quants that match this move_line's attributes
            domain = [
                ('location_id', '=', line.location_id.id),
                ('product_id', '=', line.product_id.id),
                ('reserved_quantity', '>', 0),
            ]
            
            # Add optional lot/package filters
            if line.lot_id:
                domain.append(('lot_id', '=', line.lot_id.id))
            else:
                domain.append(('lot_id', '=', False))
            
            if line.package_id:
                domain.append(('package_id', '=', line.package_id.id))
            else:
                domain.append(('package_id', '=', False))
            
            quants = self.env['stock.quant'].search(domain)
            affected_quant_ids.update(quants.ids)
        
        # Proceed with normal deletion
        result = super(stock_move_line_Override, self).unlink()
        
        # Force recalculation of reserved_quantity for affected quants
        # This ensures orphaned reservations (from do_not_unreserve context) are cleaned up
        if affected_quant_ids:
            affected_quants = self.env['stock.quant'].browse(affected_quant_ids)
            for quant in affected_quants:
                quant._compute_reserved_quantity()
        
        return result
```

---

## Change #2: Update SelectQuantWizard.py to Use Context

**File**: `multiple_relocation/wizard/SelectQuantWizard.py`  
**Lines**: 154-157  
**Status**: RECOMMENDED (improves reliability)

### Current Code:
```python
                if move_lines_to_remove:
                    move_lines_to_remove.unlink()
```

### Improved Code:
```python
                if move_lines_to_remove:
                    # Force cleanup context to ensure do_not_unreserve reservations are handled
                    move_lines_to_remove.with_context(force_unreserve=True).unlink()
```

---

## Change #3: Add Context Handler in stock_move.py (Optional Enhancement)

**File**: `multiple_relocation/models/stock_move.py`  
**New Code Section**: Add to stock_move_line_Override class  
**Status**: OPTIONAL (provides better logging/tracking)

### Add This Method:
```python
    def unlink(self):
        """Override unlink with context awareness.
        
        This new version checks context flags to determine
        proper cleanup behavior.
        """
        # Check if we should force cleanup (from SelectQuantWizard)
        force_unreserve = self.env.context.get('force_unreserve', False)
        
        # Collect affected quants for cleanup
        affected_quant_ids = set()
        
        for line in self:
            # Only cleanup if:
            # 1. force_unreserve context is set, OR
            # 2. This is from a normal workflow (not blocked by context)
            domain = [
                ('location_id', '=', line.location_id.id),
                ('product_id', '=', line.product_id.id),
                ('reserved_quantity', '>', 0),
            ]
            
            # Lot and package filters
            if line.lot_id:
                domain.append(('lot_id', '=', line.lot_id.id))
            else:
                domain.append(('lot_id', '=', False))
            
            if line.package_id:
                domain.append(('package_id', '=', line.package_id.id))
            else:
                domain.append(('package_id', '=', False))
            
            quants = self.env['stock.quant'].search(domain)
            
            # Only add to cleanup list if they may be orphaned
            if force_unreserve or not line.move_id:
                affected_quant_ids.update(quants.ids)
        
        # Delete move_lines
        result = super(stock_move_line_Override, self).unlink()
        
        # Cleanup affected quants
        if affected_quant_ids:
            affected_quants = self.env['stock.quant'].browse(list(affected_quant_ids))
            for quant in affected_quants:
                quant._compute_reserved_quantity()
        
        return result
```

---

## Deployment Sequence

### Phase 1: Code Changes
1. Backup `stock_move.py` 
2. Apply Change #1 (mandatory)
3. Apply Change #2 (recommended) 
4. Apply Change #3 (optional, for future-proofing)

### Phase 2: Testing
```bash
# Run stock-related tests
python -m pytest odoo/addons/stock/tests/ -v

# Run custom module tests  
python -m pytest addons/custom_addons/consultant-test/tests/ -v
```

### Phase 3: Data Verification
```sql
-- Check for any remaining orphaned reservations
SELECT COUNT(*) as orphaned_count
FROM stock_quant sq
WHERE sq.reserved_quantity > 0
AND NOT EXISTS (
    SELECT 1 FROM stock_move_line sml
    WHERE sml.product_id = sq.product_id
    AND sml.location_id = sq.location_id
    AND sml.lot_id = sq.lot_id
    AND sml.package_id = sq.package_id
    AND sml.state NOT IN ('done', 'cancel')
);

-- If count > 0, run cleanup:
-- See RESERVED_QUANTITY_FIX.md "Cleanup Routine" section
```

### Phase 4: Deployment
1. Deploy to production
2. Monitor logs for any unlink-related errors
3. Run data verification query weekly for first month

---

## Rollback Plan

If issues occur:

1. **Revert Change #2**: Just removes context hint (safe)
2. **Revert Change #3**: Not yet added (safe)
3. **Partial Revert of #1**: Keep orphaned check, comment out quant recalc if causing issues

**Important**: Do NOT revert to completely disabling unlink() - the bug will return.

---

## Validation Matrix

After applying changes, verify:

| Test Case | Expected | How to Verify |
|-----------|----------|---------------|
| Pick + Remove ALL quants | reserved_qty = 0 | SQL query on affected quant |
| Pick + Remove SOME quants | reserved_qty recalc'd for removed | Check WR still shows correct reserved |
| Normal workflow (no removal) | No impact | Existing tests should pass |
| Blast freeze transfers | Works correctly | Create BF transfer with removals |
| Multiple products/pallets | Each cleaned independently | Complex WR scenario |
| Concurrent operations | No race conditions | Load test with parallel WRs |

---

## Code Review Checklist

Before deploying, verify:

- [ ] All commented code is properly uncommented
- [ ] Indentation is correct (4 spaces, no tabs)
- [ ] No syntax errors: `python -m py_compile multiple_relocation/models/stock_move.py`
- [ ] Import statements still valid (no new imports added)
- [ ] Method names match class inheritance
- [ ] Context keys are spelled correctly
- [ ] SQL domain logic is correct
- [ ] Comments are updated and clear

---

## Common Issues & Resolutions

| Issue | Cause | Solution |
|-------|-------|----------|
| `AttributeError: '_compute_reserved_quantity'` | Method doesn't exist | Use `quant._get_available_quantity()` instead |
| Cascade deletion errors | Unlink touching too much | Remove pallet cleanup from unlink() |
| Performance slowdown | Recalc on every unlink | Add caching/batching |
| Quants still orphaned | Recalc didn't run | Check context, increase scope |

---

## Post-Deployment Monitoring

### Week 1:
- Check error logs daily for unlink-related issues
- Run SQL validation query twice
- Monitor picking/receiving performance

### Week 2-4:
- Weekly checks of validation query
- Monitor no regressions in batch operations

### Month 2+:
- Monthly validation query
- Document any edge cases found

---

## Success Criteria

✅ All of the following must be true:
1. No orphaned quant reservations remain (validation query = 0)
2. All WR removals properly clean up reserved_qty
3. No regression in existing workflows
4. No performance degradation in stock operations
5. Error logs show no unlink-related issues

Then the fix is **SUCCESSFUL**.
