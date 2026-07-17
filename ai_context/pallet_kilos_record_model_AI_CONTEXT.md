# `pallet_kilos_record_model` — AI Context Document

> **Module path**: `addons/custom_addons/vifel-20250717/pallet_kilos_record_model/`
> **Odoo version**: 17 Enterprise
> **Depends on**: `report_xlsx`, `stock` (and implicitly the data produced by `multiple_relocation`)
> **Last updated**: 2026-06-17

---

## Recent change (2026-06-17): owner-level balance engine + occupancy report retired + new server actions

- **Balance engine simplified to owner-level.** `_recalculate_running_balances` now delegates to
  `_recompute_owner_running_balances`, which computes each row directly as
  `total_X = beginning_X + (X_received − X_withdrawn) + adjustment_X` (beginning = previous record's total for the same
  owner, carried in-memory in processing order). The **per-building breakdown is retired**: `total_balances` is written
  as `{}` and is no longer read by anything. This eliminates the two old imbalance bugs (pallet-drop fallback in
  `_calculate_building_operations_for_record`; equal-split adjustments) and the same-`start_time` tiebreaker mismatch.
  The old per-building implementation remains as dead code `_dead_recalculate_running_balances_legacy` (no longer
  called); `_calculate_building_operations_for_record` and the `building_operations_temp` write are now vestigial.
  Verified on `vifel_06_17_2026`: warehouse-wide `overall_*` unchanged, pallets unchanged, every row internally
  consistent; the only owner-total changes were 47 FOSTER FOODS rows that the old engine had **understated** (proven:
  new latest total = independent cumulative of all their net ops).
- **Principle: never force-balance.** The engine/recompute fix *internal ledger drift only* (cumulative of recorded
  operations). They never compare to or force physical stock. Genuine ledger-vs-stock gaps are surfaced by Get Unsynced.
- **Legacy occupancy report removed** (`xlsx_occupancy_report` + `occupany_xlsx_report.py`) — it was the only reader of
  the per-building `total_balances`, was not in the wizard `REPORT_MAP`, and is superseded by the independent
  `stock_quant_history` occupancy report.
- **Two new Action-menu server actions** (`data/pkr_server_actions.xml` + model methods): **Recompute Balances**
  (`action_recompute_selected_balances`) rebuilds every selected row's (warehouse, BF) partition from the stored
  operation totals (balances-only/fast); **Get Unsynced** (`action_get_unsynced`) reimplements the old DB action #502
  read-only and accurately — per (owner, warehouse, is_blast_freezer), it includes BF stock and sums on-hand
  `stock.quant.quantity` from internal locations. Retire the old DB action #502 per DB to avoid a duplicate.

---

## 1. Purpose (1-paragraph elevator pitch)

`pallet_kilos_record_model` is the **per-transfer pallet/kilos ledger** for VIFEL cold-storage operations. Every validated Receiving Report (RR) or Withdrawal Report (WR) produces one row in this ledger capturing pallets received/withdrawn, kilos, packaging, units, return totals, adjustments, and a **chronologically maintained running balance** per (warehouse, blast-freezer, owner, building). The ledger drives several XLSX reports (pallet monitoring, billing, daily inventory, daily pallet utilization) consumed by ops/billing.

The module is essentially a **denormalized analytics table** that is rebuilt incrementally whenever transfers are created, edited, deleted, or backdated.

---

## 2. Where Things Live

```
pallet_kilos_record_model/
├── __manifest__.py
├── models/
│   └── models.py                              # Single model: pallet_kilos_record_model.pallet_kilos_record_model
├── wizard/
│   ├── pkr_report_wizard.py                   # XLSX report-generation wizard (4 report types)
│   └── pkr_report_wizard.xml
├── reports/
│   ├── pallet_kilos_xlsx_report.xml           # 6 ir.actions.report XML definitions
│   ├── pallet_kilos_xlsx.py                   # Pallet Monitoring XLSX
│   ├── pallet_kilos_billing_xlsx.py           # Billing XLSX (two variants)
│   ├── daily_inventory_xlsx.py                # Daily Inventory XLSX
│   ├── daily_pallet_utilization_xlsx.py       # Daily Pallet Utilization XLSX (snapshot)
│   └── occupany_xlsx_report.py                # Occupancy XLSX (legacy — newer one lives in stock_quant_history)
├── views/views.xml                            # Search / tree / form + menu (tree uses js_class="pkr_list_report_button")
├── security/ir.model.access.csv               # group_user has full CRUD
├── controllers/controllers.py                 # Entirely commented out (placeholder)
├── static/src/js/pkr_report_button.js + .xml  # OWL ListController that opens the wizard
└── demo/, __pycache__/
```

There is no `data/`, no security XML group, and no MD docs — this module's complexity is concentrated in **one ~985-line model file**.

---

## 3. The Core Model

`pallet_kilos_record_model.pallet_kilos_record_model` (yes, the model name repeats the module name). One record per validated transfer.

### Identity / source fields
| Field | Type | Notes |
|---|---|---|
| `report_no` | Char | Human report reference |
| `owner_id` | M2O `res.partner` | Client owner — indexed |
| `warehouse` | M2O `stock.warehouse` | Indexed |
| `record_reference` | M2O `stock.picking` | The original transfer — indexed |
| `readjustment_document` | M2O `stock.picking` | If set, **replaces** record_reference for all computations |
| `effective_document` | M2O `stock.picking` (computed, stored) | `readjustment_document or record_reference` |
| `operation_type_id` | M2O `stock.picking.type` (related, stored) | From effective_document |
| `active` | Boolean | Soft-archive flag — **always filter `active=True`** in balance queries |
| `is_blast_freezer` | Boolean (stored, indexed) | Partitioning key for balance series |
| `start_time` | Datetime (stored, **indexed — critical**) | Used as the ordering key for running balances |

### Operation totals (populated, not computed)
| Field | Notes |
|---|---|
| `pallets_received`, `pallets_withdrawn` | Counts of unique packages or `bf_pallet_char` values per transfer |
| `kilos_received`, `kilos_withdrawn` | Sum of `move_line.quantity` |
| `packaging_received/withdrawn` | Sum of `x_studio_2nd_uom` / `x_studio_affected_2nd_uom` |
| `units_received/withdrawn` | Sum of `x_studio_total_units` / `x_studio_withdraw_units` |

### Returns & adjustments (manual)
`return_id`, `return_heads`, `return_packaging`, `return_pallets`, `return_kilos`, and the parallel `adjustment_*` fields. Returns are auto-populated from `effective_document.return_ids` filtered by `state='done' AND return_reason='Partial Withdraw' AND NOT x_studio_voided`. Adjustments are user-entered and trigger a re-rollup on write.

### Running balances (the hard part)
- **Per-record**: `total_balance_in_units / _packaging / _kilos / _pallets`, `beginning_balance_in_pallets / _kilos`
- **Warehouse-wide**: `overall_pallets`, `overall_kilos`
- **Per-building JSON**: `total_balances` (JSON blob keyed by building name with the same six numbers per building)
- **Working scratch**: `building_operations_temp` (JSON) — populated in-memory during `_populate_operations_data`

### Rates (related to partner)
`holding_rate`, `handling_rate` from `owner_id.x_studio_holding_rate / _handling_rate`.

### Vehicle metadata
`truck_type` (selection), `trucks_plate`, `gate_pass` (mirrored from `effective_document.x_studio_*`).

---

## 4. How Records Are Built — the Three Populators

All called explicitly from `create()` / `write()` / `resync_all()`. Each iterates `self` and writes back.

| Method | What it does |
|---|---|
| `_populate_vehicle_data()` | Copy truck_type, plate, gate_pass, start/end time from `effective_document` |
| `_populate_operations_data()` | Walk `effective_document.move_line_ids`, sum kilos/packaging/units, **count unique pallets** (via `result_package_id` or `bf_pallet_char`), build per-building dict, write into operation totals, set `is_blast_freezer` |
| `_populate_returns_data()` | Sum `move_line_ids` of every done partial-withdraw return |

The `building_name` helper falls back to `"MAIN"` if `location.x_studio_building` is empty.

---

## 5. The Running-Balance Engine: `_recalculate_running_balances`

This is the heart of the module — ~280 lines that rebuild every balance from a given anchor forward.

**Signature**: `_recalculate_running_balances(warehouse_id, blast_freezer_flag, from_datetime=None, from_create_date=None)`

**Algorithm** (simplified):
1. Build domain: `warehouse + is_blast_freezer + active=True`, optionally `start_time >= from_datetime`
2. Fetch affected records ordered by `start_time asc, id asc` (**must match `_order`**)
3. Seed warehouse-wide `running_pallets / _kilos` from the most recent prior record (or 0)
4. For each owner in scope, seed `owner_building_balances[owner_id]` from their most recent prior record's `total_balances` JSON (or `{}`)
5. **In-memory cache** (`calculated_balances`) holds freshly-written-but-not-yet-persisted balances so multiple records sharing the same owner stay consistent within the batch
6. For each record (in order):
   - Add `pallets_received - pallets_withdrawn + adjustment_pallets` to warehouse running totals
   - Look up previous owner record (using `start_time, id` tiebreaker), preferring the in-memory cached value if present
   - Apply the current transfer's building-level deltas (`incoming → +`, `outgoing → -`)
   - Apply adjustments proportionally across buildings that have non-zero balances
   - Stash the new per-building totals into `calculated_balances[record.id]`
   - Append an update dict
7. Batch `write()` all updates at the end

**Important invariants**
- `_order = 'start_time asc, id asc'` — **must match the search order in the recalc loop**
- The `active=True` filter is **critical** — without it, archived voided records pollute the balance
- Opening-balance records have `remarks='imported via opening balance'` and use building `"EXPANSION"`; they have no `effective_document`

### Triggers
| Trigger | Call |
|---|---|
| `create()` after populators | `_recalculate_running_balances(wh, bf, start_time)` |
| `write()` of `record_reference` or `readjustment_document` | re-run all three populators |
| `write()` of any `adjustment_*` field | recalc from `start_time` |
| `write()` of `start_time` | recalc from `min(old, new)` |
| `unlink()` | recalc from the deleted record's `start_time` |
| `manual_recalculate_all()` / `resync_all()` / `resync_all_2()` | Maintenance entry points |

---

## 6. The Void Guard in `create()`

```python
if source_picking.is_void_wr or source_picking.is_void_return:
    record.active = False   # immediately archive
    return record
```

Background automated action (BA 6) fires on **all** `state='done'` transitions including void WRs / void return RRs that will be auto-voided right after. Without this guard you get phantom ledger entries.

---

## 7. Opening Balances from Quants

`import_opening_balances_from_quants(quant_ids)` (called from a button / quant action):

1. Group selected `stock.quant` records by `(owner_id, warehouse_id, building_name)`
2. Aggregate totals per `(owner, warehouse)`
3. Create one PKR record per `(owner, warehouse)` at `now() - 5 days` (UTC+8), with:
   - `record_reference = False`
   - `remarks = 'imported via opening balance'`
   - `pallets_received` filled from unique package count
   - `total_balances` JSON pre-seeded with per-building opening figures
4. After all created, recalc warehouse-wide from beginning (`from_datetime=None`)

Returns an `ir.actions.client display_notification` toast.

---

## 8. The Report Wizard

`pallet_kilos_record_model.report.wizard` — opened by the OWL list controller's "Generate Report" button (`static/src/js/pkr_report_button.js`).

```python
REPORT_MAP = {
    'pallet_monitoring':       'pallet_kilos_record_model.pallet_kilos_inventory',
    'pallet_kilos_billing':    'pallet_kilos_record_model.pallet_kilos_billing_inventory_2',
    'daily_inventory':         'pallet_kilos_record_model.xlsx_daily_inventory',
    'daily_pallet_utilization':'pallet_kilos_record_model.xlsx_daily_pallet_utilization',
}
SNAPSHOT_REPORTS = {'daily_pallet_utilization'}  # don't need date range — pass wizard itself
```

`date_from`/`date_to` are required for everything except snapshot reports; `partner_ids` and `building_ids` are optional filters. The wizard searches matching PKR records, errors if empty, and forwards them to the `ir.actions.report`.

### Report XML IDs declared in `reports/pallet_kilos_xlsx_report.xml`
| XML ID | report_name | Generator |
|---|---|---|
| `pallet_kilos_inventory` | `pallet_kilos_report_xlsx` | `pallet_kilos_xlsx.py` → `PalletKilosXlsx` |
| `pallet_kilos_billing_inventory` | `pallet_kilos_billing_report` | `pallet_kilos_billing_xlsx.py` → `PalletKilosXlsx` |
| `pallet_kilos_billing_inventory_2` | `pallet_kilos_billing_report_2` | `pallet_kilos_billing_xlsx.py` → `PalletKilosXlsx_2` |
| `xlsx_daily_inventory` | `daily_inventory_report_xlsx` | `daily_inventory_xlsx.py` |
| `xlsx_occupancy_report` | `occupancy_report` | `occupany_xlsx_report.py` (legacy, prefer `stock_quant_history`) |
| `xlsx_daily_pallet_utilization` | `daily_pallet_utilization_xlsx` | `daily_pallet_utilization_xlsx.py` |

---

## 9. Security

`ir.model.access.csv` grants **full CRUD to `base.group_user`** on both the model and the report wizard. There is no group/permission gating beyond that. Tighten if needed for production.

---

## 10. View Customizations

`views/views.xml` defines search/tree/form/menu. Notable bits:
- Tree view uses `js_class="pkr_list_report_button"` → renders a "Generate Report" button via the OWL `PkrListController`
- Tree is `create="0"` — records are only created from `stock.picking` validation flow
- Form is `create="0"` and most fields are `readonly="1"`
- Search filters: by owner, operation type, warehouse + group-by helpers

---

## 11. Common Pitfalls

1. **`_order` must match the search order in `_recalculate_running_balances`** — both are `'start_time asc, id asc'`. Changing one without the other corrupts balances.
2. **Never compute `pallets_*` or `kilos_*` as a true `@api.depends` computed field** — they are populated imperatively because the source data (move-line custom fields) doesn't trigger recomputes.
3. **Always set `start_time` and `warehouse` on create** — without them, no balance recalculation runs.
4. **Backdated inserts trigger a full forward recalc** from the inserted `start_time`. This is intentional and can be slow for large warehouses.
5. **`active=False` filtering in `_recalculate_running_balances`** is non-negotiable. Voided records contribute zero to running balances.
6. **Reading `building_operations_temp`** — it's a JSON field set during `_populate_operations_data`. If you call recalc without populators first, it may be stale; the helper `_calculate_building_operations_for_record` is the safe fallback.
7. **The controller file is a commented-out Telegram/AI stub** — ignore it. There is no live HTTP surface in this module.
8. **`x_inventory_static_var`** is a Studio-defined master-data model used for "Max Pallets / Max Kilograms" lookups (`_get_static_var`).

---

## 12. Database / Run Info

- **DB**: `vifel_03_20_2026_02` on `localhost:5432`
- **Upgrade**: `python odoo-bin -c odoo.conf -u pallet_kilos_record_model --stop-after-init`

---

## 13. Where to read next

- `multiple_relocation_AI_CONTEXT.md` — source of the move-line custom fields and the void/return flow that feeds this ledger
- `stock_quant_history_AI_CONTEXT.md` — alternative point-in-time inventory data source (snapshot model) used by newer reports
- `report_xlsx_AI_CONTEXT.md` — the XLSX abstract report mechanism every report in this module is built on

---

## 14. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> Keep this document accurate as the module evolves. Whenever you touch this module or hear that requirements have shifted, update the relevant section in the **same change** so the next agent (and you, next time) can trust what is written here. Specifically:
>
> - **Field added / removed / renamed** on `pallet_kilos_record_model` → update section 3 and any related rule in section 11.
> - **Change to `_recalculate_running_balances`** or to `_order` → re-read section 5, update the algorithm summary and invariants. This method is fragile — explicit notes here prevent regressions.
> - **New populator method or new `_populate_*` trigger** → add to section 4 and the trigger table in section 5.
> - **New report type** added to `REPORT_MAP` or new entry in `pallet_kilos_xlsx_report.xml` → update section 8.
> - **New void/active-flag logic** in `create()` / `write()` → update sections 6 and 11.
> - **Security tightening** (new group, restricted access) → update section 9.
> - **Dependency or run-command change** → update the header and section 12.
>
> Keep the tone tight and architectural. Reference file paths with line numbers when useful, but do not paste long code blocks. Update the **Last updated** date at the top each time. If a section becomes uncertain, mark it `⚠️ NEEDS VERIFICATION` rather than removing it.

---

## Update 2026-07-17 — the Re-sync engine (major addition since this document)

`action_resync_pallet_counts` is now the canonical repair tool (details in `handoff.md`):
wipe-and-rebuild per (owner, warehouse, BF) partition — received/withdrawn counts from
document events (received = unique result_package per RR; withdrawn = unique package per WR
where reserved_quantity_on_validation == 0; BF by unique bf_pallet_char), adjustment
packaging/heads/kilos rebuilt ONLY from approved `stock.quant.adjustment.line` records posted
to their LINKED rows (never synthesized), per-lot gap analysis is explanation-only (the
VERDURE −350 scatter incident is why), residual anchor on the OB row with structural OB
detection (batch-less documentless arrivals from inventory usage — not reference-text match).

**Evidence policy (truth retention)**: packaging/units residuals are force-balanced ONLY
with transaction evidence (OB basis); KG residuals are NEVER posted — they remain visible as
"UNRESOLVED kilos" remarks (e.g. FOODASIA −1173.05 KG is a real unexplained error, kept
visible by design). 6 partitions legitimately show UNRESOLVED drift after the 72-owner sweep.

Also: PKR create() archives void transfers; `pallets_received`/`pallets_withdrawn` populate
rules documented in handoff §7.2 will gain an `is_pallet_merge` exclusion when the
Client-Specific Requirement Enhancement ships (merge RRs count +0 pallets, KG still counts).
