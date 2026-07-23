# Inventory Adjustment "Apply" is unusable at 800+ quants — root cause + paste-ready fix

> Investigated 2026-07-21 on DB `vifel_07_06_2026` (Odoo 17 E). All measurements were taken in
> odoo-shell inside savepoints that were rolled back — no data was changed.
> Related paste file: `sa432_line_id_picking_scoped.py` (a **minor** contributor, ~6%; see §6).

## 1. Symptom

`stock.inventory.adjustment.name.action_apply` (the "Apply" button used when importing quant
opening balances) is fine for small batches but unusable past ~800 quants. It has been getting
slower over time.

## 2. Root cause

A **positive** inventory adjustment creates, per quant, a `stock.move` + `stock.move.line`
whose **source location is the virtual "Inventory adjustment" location, `loc#14`**.

`loc#14` currently holds **22,929 quants** and grows with every adjustment ever applied.

About **15 stored computed fields** on `stock.move.line` (Studio `x_studio_*` fields, plus two
Python computes in `multiple_relocation`) recompute on every created line and do this:

```python
if record['picking_code'] == 'outgoing' or not record['picking_code']:   # <-- inventory lines match
    for quants in location.quant_ids:                                    # <-- iterates ALL 22,929
        if match product + owner + lot: ...
```

Inventory-adjustment lines belong to **no picking**, so `picking_code` is empty and
`or not picking_code` drags every one of them into the expensive branch. Three fields
(`x_studio_max_2nd_uom`, `x_studio_max_quant`, `x_studio_max_total_units`) have **no guard at
all**, and two (`x_studio_affected_2nd_uom`, `x_studio_withdraw_units`) run a **nested search**
on top of the loop.

Cost model: **lines x quants-in-loc#14**. That is why it degrades as loc#14 fills up.
The data pulled is meaningless anyway — matching quants inside the virtual inventory-loss
location is not real stock.

### Evidence

| Probe | Result |
|---|---|
| cProfile, 20 quants (84 s) | ~60 s in `flush_all -> _recompute_all`; ~70 s cumulative in `safe_eval` (Studio compute code); **only ~1.8 s in SQL**; 11.2M ORM field reads for 20 lines |
| Positive adj (source = loc#14, 22.9k quants) | **1330 ms/line** |
| Negative adj (source = storage loc, few hundred quants) | **149 ms/line** |

Same code, same computes — the only variable is the source location's quant count. **8.9x.**

## 3. The fix (one rule)

**Do not run these computes for move lines that belong to no picking.**
Minimal and surgical: add `record.picking_id and` to the existing guard (this preserves the
defensive `or not picking_code` behaviour for real RR/WR lines, which is presumably there for
onchange/new-record cases), or add an early skip where there is no guard.

### Measured result (validated, correctness 30/30 before AND after)

| | ms/line | 800 quants (projected) |
|---|---|---|
| Before | 1226.4 | ~16.4 min |
| After  | 109.0  | ~1.5 min |
| | **11.3x faster** | |

Correctness check = every adjusted quant reached its counted quantity.

## 4. Studio fields to edit (`stock.move.line`)

### 4a. Fields that already have the guard — add `record.picking_id and`

Applies to: `x_studio_affected_2nd_uom`, `x_studio_container_number`,
`x_studio_expiration_date`, `x_studio_min_quantity_uom`, `x_studio_production_date`,
`x_studio_quantity_uom_delivery`, `x_studio_return_count`, `x_studio_sh_reason`,
`x_studio_withdraw_units`.

Change the guard line from:

```python
if record['picking_code'] == 'outgoing' or not record['picking_code']:
```

to:

```python
# picking_id guard: inventory-adjustment / scrap lines belong to no transfer and must not
# scan the virtual location's 22k+ quants (see ai_context/studio_computes_inventory_apply_perf_FIX.md)
if record.picking_id and (record['picking_code'] == 'outgoing' or not record['picking_code']):
```

Leave the `else:` branch exactly as it is. Lines with no picking now fall to the `else`
(empty/0), which is correct for an inventory adjustment.

### 4b. `x_studio_special_holding` — guard only the loop, keep the first assignment

```python
for record in self:
    if record['x_studio_sh_reason']:
        record['x_studio_special_holding'] = 1
    else:
        record['x_studio_special_holding'] = 0

    # picking_id guard - skip the quant scan for picking-less (inventory adjustment) lines
    if record.picking_id and (record['picking_code'] == 'outgoing' or not record['picking_code']):
        location = self.env['stock.location'].browse(record['location_id'].id)

        for quants in location.quant_ids:
            if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                record['x_studio_special_holding'] = quants.x_studio_special_holding
```

### 4c. The three UNGUARDED fields — add an early skip

`x_studio_max_2nd_uom`, `x_studio_max_quant`, `x_studio_max_total_units` currently scan the
location for EVERY line, including inventory lines. Add the skip as the first statement in the
loop. Example for `x_studio_max_quant` (the other two are identical apart from the field
assigned — `x_studio_2nd_uom` and `x_studio_total_units` respectively):

```python
for record in self:
    # picking_id guard - inventory-adjustment / scrap lines have no transfer to size against
    if not record.picking_id:
        continue

    location = self.env['stock.location'].search([('id', '=', record['location_id'].id)])

    if location.quant_ids:
        for quants in location.quant_ids:
            if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                record['x_studio_max_quant'] = quants.quantity
```

### 4d. Already safe — do not touch

`x_studio_pallet_series_id` guards on `== 'outgoing'` only (no `or not picking_code`), so it
already skips inventory lines.

## 5. Python module computes (`multiple_relocation`)

`models/stock_move.py` — the `stock.move.line` class defines two computes with the same flaw
(`_compute_container_number` ~line 447, `_compute_x_studio_building_dropped` ~line 461). They
showed up in the profile at ~6.6 s each per 20 lines. Same one-line change:

```python
    @api.depends('quant_id')
    def _compute_container_number(self):
        for record in self:
            # picking_id guard: inventory-adjustment lines must not scan the virtual location
            if record.picking_id and (record['picking_code'] == 'outgoing' or not record['picking_code']):
                ...unchanged...
            else:
                record['x_studio_container_number'] = ''
```

(Identical treatment for `_compute_x_studio_building_dropped`, whose `else` branch already
clears `x_studio_building_dropped` and `original_record_reference`.)

NOTE: `x_studio_container_number` has BOTH a Studio compute and this Python compute — worth a
separate look at which one actually wins at runtime.

## 6. What is NOT the cause (checked and cleared)

- **BA#6 / SA#297 (PKR ledger create)** — does not fire; inventory moves have no picking.
- **BA#42 / SA#432** ("Assign ID"): real but **minor**. Its per-line search degrades to an
  unindexed `picking_id IS NULL` seq-scan (~72 ms/line, 53k rows). Measured end-to-end benefit
  of fixing it alone: **1.1x (~6%)**. Worth applying (see `sa432_line_id_picking_scoped.py`)
  but it is NOT the cure. This corrects the first-pass diagnosis in this investigation.
- **Python overrides** in `multiple_relocation` / `pallet_series_audit` on
  `stock.move.create`, `stock.move.line.write`, `stock.quant.write/create` — all fast-exit on
  this path.
- **SQL / indexing in general** — only ~1.8 s of an 84 s apply was in the database. This is a
  CPU/ORM recompute problem, not a query problem.

## 7. Optional complementary cleanup

`loc#14` holding 22,929 quants is itself bloat (historic zero-quantity inventory-loss quants).
Purging/archiving them would cut the scan cost even without the compute edits — but they
regrow with every adjustment, so the compute guard is the durable fix. Do not rely on cleanup
alone.

## 8. How to verify after applying

1. Import/adjust 800+ quants — should finish in ~1-2 min instead of ~16 min.
2. Encode a normal WR: `Max` columns, Actual KG/Packaging/Packs, container number, expiry,
   production date, PSI must all populate exactly as before (unchanged code path — those lines
   have a picking).
3. Validate an RR and a WR; confirm PKR rows and pallet counts are unaffected.
