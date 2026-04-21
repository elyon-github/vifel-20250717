# Reserved Quantity Bug - Flow Diagram & Data Consistency Analysis

## The Bug Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ NORMAL FLOW (Without Bug)                                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  WR (Warehouse Receipt) Created                                         │
│         ↓                                                               │
│  Move Lines Created + Quants Reserved                                   │
│  Stock.quant: reserved_quantity = 5 ✓                                   │
│         ↓                                                               │
│  User Removes Quants/Move Lines                                         │
│         ↓                                                               │
│  move_lines.unlink()                                                    │
│         ↓                                                               │
│  Odoo Core: Auto-unreserves quants                                      │
│  Stock.quant: reserved_quantity = 0 ✓ (recalculated)                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ BUGGY FLOW (With do_not_unreserve Context)                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  WR (Warehouse Receipt) Created                                         │
│         ↓                                                               │
│  Someone modifies stock.move.product_uom_qty                            │
│  (via form UI or server action)                                         │
│         ↓                                                               │
│  StockMove.write() triggered with product_uom_qty in vals               │
│         ↓                                                               │
│  ⚠️  CONTEXT SET: do_not_unreserve=True                                 │
│  super(StockMove, self.with_context(do_not_unreserve=True)).write(vals) │
│         ↓                                                               │
│  Odoo Core receives write() with do_not_unreserve context                │
│  Adjusts move_lines WITHOUT unreserving quants                          │
│         ↓                                                               │
│  Move Lines Stay Reserved Even Though Modified                          │
│  Stock.quant: reserved_quantity = 5 (was NOT cleaned up) ⚠️              │
│         ↓                                                               │
│  Later: User Removes Quants/Move Lines via SelectQuantWizard             │
│         ↓                                                               │
│  move_lines_to_remove.unlink()                                          │
│         ↓                                                               │
│  Stock.quant: reserved_quantity = 5  ❌ NOT RECALCULATED                │
│  (Odoo doesn't recalculate because move_lines are deleted)              │
│         ↓                                                               │
│  DATA INCONSISTENCY: Reserved qty > 0 but no move_lines exist!          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Who Calls `product_uom_qty` Write?

These operations trigger the do_not_unreserve context:

1. **Server Actions** - In stock_picking.py validation logic
2. **Form Updates** - UI updates to WR move quantities
3. **Regenerate Move Lines** - When users re-generate lines
4. **SelectQuantWizard** - When finalizing quant selections
5. **Any automation** - Custom workflows modifying WR quantities

---

## Why Only Some Quants Are Affected

The bug affects "specific quants" because:

### Affected ❌
- Quants in move_lines that were **modified after** a `do_not_unreserve=True` write
- Quants that became **orphaned** (no move_line but still reserved)
- Quants from packages/products that matched the write() trigger

### Not Affected ✓
- Quants created before any `do_not_unreserve` write
- Quants in untouched move_lines
- Quants that never went through adjustment with context
- Non-incoming pickings (the context only applies to incoming)

---

## Database State Issue

### What's Stored (Stock Server):

```sql
-- stock.quant table
SELECT id, product_id, location_id, quantity, reserved_quantity, lot_id, package_id
FROM stock_quant
WHERE product_id = 123;

id  | product_id | location_id | quantity | reserved_quantity | lot_id | package_id
----+------------+-------------+----------+-------------------+--------+------------
45  | 123        | 10          | 100      | 5                 | 99     | 555        ← PROBLEM: reserved=5
46  | 123        | 10          | 95       | 0                 | 100    | 556
```

Users see:
- Quant 45: "Reserved: 5" in UI ❌
- But there are NO stock.move.line records reserving it
- Available Qty calculation: 100 - 5 = 95 (WRONG, should be 100)

### Affected Calculations:

```
Quant.available_quantity = quantity - reserved_quantity
  = 100 - 5 = 95  ❌ (Should be 100)

Stock Picking Validation:
  "Cannot pick more than available: 95" ❌ (Should allow 100)

Forecasting/Reports:
  Shows "5 units in transit" that don't actually exist ❌
```

---

## Code Locations Contributing to Bug

| File | Line | Component | Impact |
|------|------|-----------|--------|
| `stock_move.py` | 193 | `do_not_unreserve=True` context | **SETS trap** - prevents cleanup on write |
| `SelectQuantWizard.py` | 149 | `quant_ids_picked` removal | Removes tracking but quants still reserved |
| `SelectQuantWizard.py` | 156 | `move_lines_to_remove.unlink()` | **TRIGGERS bug** - orphaned reservation |
| `stock_move.py` | 526-531 | Commented unlink() | **DISABLED fix** - was meant to handle this |

---

## Why Commenting Out Unlink() Made It Worse

The previously disabled unlink() method suggests someone tried to fix this before:

```python
# def unlink(self):
#     # Get related stock moves before deleting move lines
#     moves = self.mapped('move_id')
#     res = super(stock_move_line_Override, self).unlink()
```

This probably caused **unexpected side effects** like:
- Cascading deletions of stock.moves
- Double-unreservation errors
- Pallet series cleanup issues

**But**: It needed a more targeted approach, not complete removal.

---

## The Fix Approach

### Why Explicit Cleanup Works:

1. **Targeted**: Only cleans up when unlink() is called
2. **Safe**: Won't trigger cascades or side effects
3. **Idempotent**: Can be called multiple times safely
4. **Debuggable**: Clear logging of what was cleaned

```python
def unlink(self):
    # 1. Find affected quants BEFORE deletion
    affected_quants = self._get_affected_quants()
    
    # 2. Delete move_lines (ORM)
    res = super().unlink()
    
    # 3. Recalculate reserved_qty AFTER deletion
    # This ensures orphaned reservations are caught
    for quant in affected_quants:
        quant._compute_reserved_quantity()
    
    return res
```

This way:
- Move lines are deleted (normal Odoo behavior)
- Reserved quantities are explicitly recalculated
- No cascades or side effects
- Data consistency is restored

---

## Prevention

To prevent future occurrences:

```python
# When using context like do_not_unreserve, ALWAYS:
try:
    move.with_context(do_not_unreserve=True).write(product_uom_qty=new_qty)
finally:
    # Cleanup after context operations
    quants = move.move_line_ids.mapped('quant_ids')
    for quant in quants:
        quant._compute_reserved_quantity()
```

Or better: **Avoid context if possible** - be explicit instead:

```python
# Instead of:
move.with_context(do_not_unreserve=True).write(vals)

# Do:
move._write_without_cascade(vals)  # Custom explicit method
```
