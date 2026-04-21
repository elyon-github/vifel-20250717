# Reserved Quantity Not Computing - Root Cause Analysis

## Issue Description
When quants are picked in a Warehouse Receipt (WR), and then removed/unlinked, the stock.quant's `reserved_quantity` field is not being recalculated for some specific quants (not all).

## Root Cause Found

### Location: `multiple_relocation/models/stock_move.py` (Line 188-194)

The problem is in the `write()` method override for `StockMove`:

```python
if 'product_uom_qty' in vals:
    has_incoming_moves = any(move.picking_type_id.code == 'incoming' for move in self)
    if has_incoming_moves:
        # Set context to prevent unreservation for incoming moves
        return super(StockMove, self.with_context(do_not_unreserve=True)).write(vals)
```

### Why This Is Problematic

1. **Context Inheritance Issue**: When `do_not_unreserve=True` context is set on the stock.move write operation, this context may persist through the ORM transaction.

2. **Move Line Cascading Effects**: When a stock.move's `product_uom_qty` is modified, Odoo's core stock module automatically:
   - Adjusts or regenerates move_lines
   - Updates quant reservations
   
   With `do_not_unreserve=True`, these automatic operations skip the unreservation cleanup.

3. **Deletion Without Unreserving**: Later, when [SelectQuantWizard.py](SelectQuantWizard.py) removes move_lines:
   ```python
   move_lines_to_remove.unlink()
   ```
   
   These move_lines have no mechanism to unreserve their quants if they were affected by the `do_not_unreserve` context earlier.

4. **Selective Impact**: This only affects quants from:
   - Move lines that were created/modified when the `do_not_unreserve` context was active
   - Specific products or packages that match the product_uom_qty change logic

## The `quant_ids_picked` Mechanism

The custom `quant_ids_picked` field tracks which quants are being "picked" in a move:

```python
quant_ids_picked = fields.Many2many('stock.quant', string="Quant IDs", copy=False)
```

This is used in [SelectQuantWizard.py](SelectQuantWizard.py) to manage which quants are selected. However, when quants are removed from `quant_ids_picked` via:

```python
move.write({'quant_ids_picked': [(3, quant.id) for quant in quants_to_remove]})
```

The removal from Many2many doesn't trigger the same unreservation logic as deleting move_lines. Some quants may:
- Have move_lines deleted but be trapped in "reserved" state
- Have been reserved during a `do_not_unreserve=True` operation but not properly cleaned up on deletion

## Secondary Issue: Commented Unlink Method

In [stock_move.py line 526-531](stock_move.py#L526-L531), there's a commented-out `unlink()` method:

```python
# def unlink(self):
#     # Get related stock moves before deleting move lines
#     moves = self.mapped('move_id')
#
#     # Proceed with the deletion
#     res = super(stock_move_line_Override, self).unlink()
```

This suggests cleanup logic WAS attempted but then disabled. This might have been trying to handle quant unreservation but was removing it because it caused side effects.

## Why Some Quants Are Affected

The issue affects only "specific quants" because:
1. Quants from move lines that were modified while `product_uom_qty` was being changed with `do_not_unreserve=True` context
2. Quants that don't have a corresponding move_line after the deletion (orphaned reservations)
3. Quants where the Many2many removal and move_line deletion don't align properly

---

## Recommended Fix

See: `RESERVED_QUANTITY_FIX.md` for the solution recommendations.
