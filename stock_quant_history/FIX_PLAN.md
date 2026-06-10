# stock_quant_history — Accuracy Fix Plan

> Status: **IMPLEMENTED & VALIDATED** 2026-06-10 against DB `VIFEL_05_17_2026_3`.
> Originally investigated on snapshot 4411; regenerated and validated on the
> current latest snapshot 4412 (inventory_date 2026-06-10 10:00 UTC / 18:00 Manila).

## RESULTS (2026-06-10)

After implementing the fix and regenerating the latest snapshot:

| Source | Records | Total Qty |
|---|---|---|
| Snapshot 4412 (regenerated) | 20,098 | 13,970,411.605 |
| Live stock.quant (internal, non-zero) | 20,098 | 13,970,411.605 |
| **Delta** | **0** | **0.000** |

Per-key reconciliation: **0 mismatched keys, 0 phantom rows, 0 missing rows.**
Metadata cross-check vs stock.quant: pallet series 20,098/20,098, owner
20,098/20,098, expiration date 20,098/20,098. The 4 newly-mirrored fields
populate (x_studio_building 20,098, x_studio_inbound_date 7,275,
x_studio_tally_sheet 12,114). Dynamic discovery logged 9 unmirrored source
fields safely skipped.

The previous +2,760,000 phantom-qty discrepancy is eliminated.

**Validated:** seed path (Approach B, RC-1/RC-4), dynamic field copy (RC-5),
new schema fields + sh_reason text (D2/D5), timezone fix compiles (RC-3).
**Not yet runtime-validated against live data:** the replay path A1/A2 passes
(RC-2) — they only execute for historical (non-current) snapshots, which the
daily cron produces going forward. Covered by design + recommended unit tests
(see §7). Follow-up D4 (block direct quant writes) still open.

---


---

## 1. Problem statement

The latest snapshot over-reports inventory vs the live `stock.quant` /
Normal Inventory View:

| Source | Records | Total Qty |
|---|---|---|
| Snapshot (owner filter) | 24,424 | 16,730,342 |
| stock.quant (internal, non-zero) | 20,098 | 13,970,411 |
| **Delta** | **+4,326** | **+2,760,000** |

Zero move lines exist after the snapshot date, so this is **not** time drift —
it is a reconstruction defect.

---

## 2. Root causes (confirmed)

### RC-1 — Direct quant writes with no real move line (PRIMARY: 4,151 lots, ~2.66M qty)
Inventory removed/changed directly on `stock.quant` with **no outbound
stock.move.line**. The snapshot replays move lines forward from zero, adds the
inbound, never sees the removal → ghost stock. Traced example: `ASADO SIOPAO
JUMBO` lot `…208484` — one inbound adjustment move (+11.8 → M/A/9/Aisle 2);
stock.quant now shows 0 there, -11.8 at Inventory-adjustment virtual location.

### RC-2 — Pallet-detail adjustments via the approval workflow (SECONDARY: ~259 lots + all metadata)
`multiple_relocation`'s adjustment workflow
(`stock.quant.adjustment.request` / `.line`, batch number = `adjustment_batch_number`)
applies changes by:
- **Quantity change** → creates a *real non-zero* move line (inventory↔internal). ✅ Snapshot already replays these.
- **Metadata change** (pallet #, prod/exp date, container, owner, UoM…) → creates a
  **zero-quantity** correction move line carrying the *new* `x_studio_*` values,
  then `quant.write(update_vals)` mutates the quant directly.
  ➜ Snapshot's loop sees qty 0, does nothing, and **discards the new metadata**.
- **Lot/product change** → creates a brand-new `stock.lot`, `_write()`s the
  original receipt move line to the new lot/product, and writes the quant.
  ➜ Snapshot still has the qty under the **old** lot key → phantom + missing.

### RC-3 — Timezone bug in previous-snapshot lookup (LATENT)
`stock_quant_history_snapshot.py` ~line 123 compares the UTC-stored
`inventory_date` column against a **Manila-local naive** datetime
(`inventory_date_manila`), an 8-hour skew. Masked today (single snapshot) but
will mis-chain once daily snapshots accumulate.

### RC-4 — Inverse of RC-1 (MINOR: 24 lots, ~6K qty)
Quants added directly with no move line → snapshot misses them (under-report).

### RC-5 — x_studio field coverage is brittle (CROSS-CUTTING)
See §3. The field list is hardcoded in 3 places and already misses ~14 fields.

---

## 3. The x_studio field problem (explicit, per request)

x_studio fields have **two origins** (`ir_model_fields.state`):
- `base` — declared in Python (codebase)
- `manual` — created in Odoo Studio, exists only in the DB

Findings:
- **stock.quant**: 34 x_studio fields. The pallet fields the report cares about
  (`x_studio_pallet_series_id`, `x_studio_2nd_uom`, `x_studio_production_date`,
  `x_studio_quantity_uom`, …) are **manual (Studio)**. Only 3 are `base`.
- **stock.quant.history**: those same fields were **re-declared in code** (`base`)
  in `stock_quant_history.py`, plus a `manual` `x_studio_is_blast_freezer`.
- **stock.move.line**: 54 x_studio fields (base + manual mix).

Consequences:
1. **Hardcoded copy lists** in `create_quant_history`, the previous-snapshot
   duplication block, and the related-quant block (3 copies, ~24 fields each) drift
   from reality. **~14 stock.quant x_studio fields are not mirrored** to history
   (e.g. `x_studio_building`, `x_studio_inbound_date`, `x_studio_remarks`,
   `x_studio_tally_sheet`, `x_studio_opening_balance_record_reference`).
2. **Dual definition** (Studio source ↔ code target) must be hand-synced; a Studio
   type/edit on the source silently desyncs.
3. **Type mismatch already exists**: `x_studio_sh_reason` is `text` on stock.quant,
   `char` on stock.quant.history.
4. A new Studio field added tomorrow on stock.quant will **never** appear in
   snapshots until someone (a) re-declares it in code on the history model and
   (b) edits all 3 hardcoded lists.

**Chosen strategy:** replace hardcoded lists with **runtime dynamic discovery** —
intersect `env['stock.quant']._fields` with `env['stock.quant.history']._fields`,
keep the `x_studio_*` (and shared standard) keys that exist on **both**, coerce
relational values to ids, and copy that set everywhere. This is origin-agnostic
(works for base *and* manual) and self-heals when Studio fields are added —
provided the target history model has a matching column. For target columns we
have two options (see §5, Decision D2).

---

## 4. Solution options considered

### Approach A — Patch the move-line replay (incremental deltas only)
Add post-passes to the existing algorithm:
- A1: read approved `stock.quant.adjustment.line` in range, remap qty from
  `old_lot/old_product` key to `new_lot/new_product` key.
- A2: read zero-qty `is_quant_detail_adjusted` move lines in range, overwrite
  metadata on the matching history record (latest wins).
- Does **not** fix RC-1/RC-4 (direct writes with no move line at all).
- Pros: minimal change, preserves incremental design. Cons: leaves the biggest
  bucket (RC-1, 2.66M qty) unsolved.

### Approach B — Seed each snapshot from a *reconciled* baseline
For the **current-day** snapshot, seed directly from live `stock.quant`
(the source of truth) instead of pure forward-replay. Historical snapshots keep
replaying move lines *backwards* from that trusted baseline.
- Fixes RC-1 and RC-4 for "today" immediately (snapshot == stock.quant by
  construction). Backward reconstruction still needs A1/A2 for older dates.
- Pros: today's number is exactly right; aligns with how users validate ("does it
  match current inventory?"). Cons: changes the generation model; backward
  deltas must be sign-correct.

### Approach C — Full reconciliation pass (truth-up)
After replay, diff the freshly built "today" snapshot against live stock.quant and
write correction rows for any residual delta.
- Pros: guarantees today matches. Cons: a band-aid for historical dates; hides
  rather than explains deltas.

### Approach D — Dynamic x_studio handling (orthogonal, applies to all)
Replace the 3 hardcoded field lists with runtime discovery (§3). Independent of
A/B/C and should land regardless.

### Recommended combination: **B (for today) + A1/A2 (for history) + D (throughout) + RC-3 fix**
- "Today" snapshot is seeded from stock.quant → exact match, kills RC-1/RC-4.
- Older snapshots rebuilt by replaying backwards, now also honoring adjustment
  lot-remaps (A1) and metadata moves (A2).
- Dynamic field copy (D) removes the brittleness and the 14-field gap.
- Timezone fix (RC-3) makes multi-snapshot chaining correct.

---

## 5. Key design decisions (LOCKED 2026-06-10)

- **D1 — Baseline direction.** ✅ **Approach B.** Seed the current-day snapshot
  directly from live `stock.quant`; reconstruct older dates backward with the
  adjustment passes. Kills RC-1/RC-4 for today by construction.

- **D2 — Target columns for newly-discovered Studio fields.** ✅ **Skip unmatched
  + add 4 high-value now.** Dynamic copy only writes fields present on *both*
  models (no schema churn, origin-agnostic). In this PR also declare the 4 useful
  missing ones (`x_studio_building`, `x_studio_inbound_date`, `x_studio_remarks`,
  `x_studio_tally_sheet`) as code fields on stock.quant.history. Any other
  unmatched Studio field is skipped and logged once.

- **D3 — Backfill / regeneration.** ✅ Delete + regenerate snapshot 4411 after
  code lands, then re-run the reconciliation query to prove the delta is gone.

- **D4 — Prevent future RC-1 at source.** ⏭ Follow-up (separate change in
  `multiple_relocation`), not this PR. Approach B makes today exact regardless.

- **D5 — sh_reason type mismatch.** ✅ Align `x_studio_sh_reason` to `text` on
  stock.quant.history to match the source.

---

## 6. Implementation steps (once §5 decided)

1. **Add dynamic field-copy helper** on the snapshot model
   `_get_quant_copy_fields()` → dict of {field_name: coercer}, computed by
   intersecting `stock.quant._fields` ∩ `stock.quant.history._fields`, filtered to
   x_studio_* + shared standard fields (owner_id, package_id), with relational
   coercion to `.id`. Replace all 3 hardcoded blocks with this helper.

2. **Fix RC-3 timezone** — use `self.inventory_date` (UTC) in the previous-snapshot
   `search`, drop `inventory_date_manila` from the comparison.

3. **Approach B seed** — when generating a snapshot whose date is "current"
   (no later moves exist / inventory_date ≥ latest move date), build rows directly
   from `stock.quant` (internal, type=product) using the dynamic field set, instead
   of replaying from zero.

4. **A1 lot/product remap pass** — after replay, for approved
   `stock.quant.adjustment.line` in (prev_date, inventory_date], move qty from the
   old (product, lot, location) key to the new one.

5. **A2 metadata pass** — for `is_quant_detail_adjusted` zero-qty move lines in
   range, overwrite the dynamic metadata field set on the matching existing history
   record (order by date asc, latest wins; do not create new rows).

6. **D2(i)+ selected new fields** — declare the 4 high-value missing x_studio
   fields on stock.quant.history; align `x_studio_sh_reason` to text (D5).

7. **Zero-cleanup** — keep the existing `DELETE … WHERE quantity = 0` after all
   passes (now also removes old-lot keys emptied by A1).

8. **Regenerate** snapshot 4411 (D3) and re-validate.

---

## 7. Test / validation plan

- **Reconciliation query** (already built): snapshot vs stock.quant by
  (product, lot, location); assert `|delta| < rounding` for all rows after fix.
- **Targeted unit cases** in `tests/test_stock_quant_history.py`:
  - direct quant write with no move line → snapshot matches quant (RC-1).
  - approved metadata-only adjustment → snapshot carries new pallet #/dates (RC-2).
  - approved lot/product change → qty under new lot, none under old (RC-2).
  - Studio field added at runtime (simulate via `_fields`) is copied (RC-5/D).
  - multi-snapshot chain across the Manila/UTC midnight boundary (RC-3).
- **Manual UI check**: Reporting → History vs Reporting → Normal Inventory View
  with the same domain filters; totals should match within rounding.

---

## 8. Risks & mitigations

- **Backward delta sign errors** (Approach B reconstruction): cover with the
  multi-date chain test; validate an older date against a known-good manual count.
- **Performance**: dynamic field discovery is O(1) per generation (cached dict);
  extra passes are bounded by adjustment volume in the window. Acceptable.
- **Studio field with no history column** (D2): skipped safely; logged once so we
  can decide to add it later. No crash.
- **Approval edits applied after their effective date**: A1/A2 key off
  `request_id.approved_date` / move `date`; if business backdates, document that the
  move `date` is authoritative for placement.
