# `stock_quant_history` — AI Context Document

> **Module path**: `addons/custom_addons/consultant-test/stock_quant_history/`
> **Origin**: OCA fork — `https://github.com/OCA/stock-logistics-reporting`
> **Authors**: Foodles (Pierre Verkest), OCA + heavy local customization for VIFEL
> **License**: AGPL-3.0
> **Odoo version**: 17 Enterprise (`version 17.0.1.0.0`)
> **Depends on**: `report_xlsx`, `stock`
> **Last updated**: 2026-05-16

---

## 1. Purpose (1-paragraph elevator pitch)

`stock_quant_history` produces **point-in-time snapshots of `stock.quant`** for any date in the past, by replaying done `stock.move.line` records backwards from the current quants — or forwards from the most recent prior snapshot. Each snapshot is a `stock.quant.history.snapshot` header plus many `stock.quant.history` rows that mirror the relevant `stock.quant` fields (including a wide set of VIFEL-specific `x_studio_*` columns like pallet series, container number, expiry dates, building, owner, etc.). The module ships with **two crons** (daily auto-snapshot of yesterday + auto-deactivating 60-day backfill) and an **Occupancy Report wizard** that can either generate snapshots on demand or compute occupancy on-the-fly from move lines.

This is the data backbone for any "what did inventory look like on date X?" question in VIFEL.

---

## 2. Where Things Live

```
stock_quant_history/
├── __manifest__.py
├── README.rst, readme/                            # OCA-style README
├── i18n/                                          # Translations
├── pyproject.toml
├── models/
│   ├── stock_quant_history.py                     # stock.quant.history (the snapshot row model)
│   └── stock_quant_history_snapshot.py            # stock.quant.history.snapshot (header + generator + crons)
├── wizard/
│   ├── occupancy_report_wizard.py                 # stock.quant.history.occupancy.wizard
│   └── occupancy_report_wizard.xml
├── reports/
│   ├── occupancy_xlsx_report.py                   # report.stock_quant_history.occupancy_xlsx
│   ├── client_summary_xlsx_history.py             # report.stock_quant_history.inventory_summary_xlsx
│   ├── inventory_summary_view.xml
│   └── occupancy_report_view.xml
├── data/ir_cron.xml                               # Daily + backfill crons
├── security/ir.model.access.csv                   # stock.group_stock_manager only
├── views/
│   ├── stock-quant-history.xml                    # stock.quant.history search/tree/form
│   └── stock-quant-history-snapshot.xml           # snapshot search/tree/form + list controller
├── static/src/js/
│   ├── occupancy_report_button.js                 # OWL ListController for snapshot tree
│   └── occupancy_report_button.xml
└── tests/
```

Asset bundle `web.assets_backend` loads the snapshot list controller (it adds the "Occupancy Report" button on the snapshot list view).

---

## 3. Data Model

### `stock.quant.history.snapshot` (header)
| Field | Type | Notes |
|---|---|---|
| `name` | computed | `"Snapshot YYYY-MM-DD HH:MM"` in Manila TZ format |
| `inventory_date` | Datetime (UTC stored, **displayed Manila**) | The instant the snapshot represents |
| `generated_date` | Datetime | When `_generate_stock_quant_history` finished (Manila TZ) |
| `state` | Selection `draft / generated` | |
| `stock_quant_history_ids` | O2M `stock.quant.history` | The frozen rows |
| `previous_snapshot_id` | M2O `self` | Snapshot used as the starting point — speeds up generation |

`_order = "inventory_date desc"`. Class-level constant `MANILA_TZ = timezone('Asia/Manila')` is used **for all date math** — UTC is only the storage representation.

### `stock.quant.history` (row)
Mirrors `stock.quant` plus a `snapshot_id` FK. Selected columns:

**Identity**: `snapshot_id`, `inventory_date` (related, stored), `product_id`, `product_tmpl_id` (related), `product_uom_id` (related), `company_id` (related), `location_id`, `lot_id`, `package_id`, `owner_id`.

**Quantity**: `quantity` (Float, stored).

**VIFEL `x_studio_*` mirrors** (all readonly): `x_studio_record_reference` (M2O `stock.picking`), `x_studio_stock_code`, `x_studio_return_count`, `x_studio_pallet_series_id`, `x_studio_production_date`, `x_studio_expiration_date`, `x_studio_loading_dock_no`, `x_studio_source`, `x_studio_gate_pass`, `x_studio_truck_time`, `x_studio_start_time`, `x_studio_end_time`, `x_studio_truck_number`, `x_studio_2nd_uom`, `x_studio_quantity_uom`, `x_studio_total_units`, `x_studio_min_quantity_uom`, `x_studio_special_holding`, `x_studio_sh_reason`, `x_studio_container_number`.

**Derived**: `is_a_blast_freeze` (related to `location_id.x_studio_is_a_blast_freezer`, stored — used for partition queries).

`_order = "snapshot_id, inventory_date, product_id, lot_id, location_id"`.

---

## 4. How a Snapshot Is Generated

Entry point: `snapshot._generate_stock_quant_history()` (Snapshot model). Algorithm:

1. **Find base snapshot** — the most recent `generated` snapshot with `inventory_date <= self.inventory_date` (in Manila TZ).
2. **Seed rows from base** — for each row in the base snapshot, create a fresh `stock.quant.history` row in this snapshot and copy `quantity` + all `x_studio_*` fields. (Implemented via a custom `DefaultDict` keyed on `(product, lot, location)` so duplicates merge naturally.)
3. **Replay move lines since base** — search `stock.move.line` with `state='done', date <= self.inventory_date, product_id.type='product'` and `date > previous_snapshot.inventory_date` if there is one.
4. For each move line: subtract from `location_id` row, add to `location_dest_id` row (after UOM conversion via `product_uom_id._compute_quantity`). Skip locations whose `usage in ('supplier','customer','inventory')` (see `_ignored_location_usage`).
5. **Hydrate `x_studio_*` for new rows** by searching the live `stock.quant` for a match on `lot_id`; if found, copy fields; otherwise walk done `stock.move.line` records with the same `lot_id` (ordered ascending by `date`, stopping just before `inventory_date`) and copy from the latest match.
6. **Cleanup**: raw SQL `DELETE FROM stock_quant_history WHERE quantity = 0 AND snapshot_id = %s` to skip persisting zero-stock rows.
7. Set `state='generated'`.

### Notes
- All datetime math goes through `MANILA_TZ` then back to UTC for storage.
- `previous_snapshot_id` is set on the new snapshot before generation so re-running a draft snapshot is idempotent.
- The custom `DefaultDict` subclass calls `__missing__` with the *tuple of args* as the key, passing them positionally to the factory — see top of `stock_quant_history_snapshot.py`.

---

## 5. The Two Crons (data/ir_cron.xml)

### Daily snapshot (`ir_cron_daily_snapshot`)
- Runs daily; method `_cron_generate_daily_snapshot`
- For yesterday in Manila: creates a snapshot at 23:59:59 (Manila → UTC), generates it.
- Then **cleans up**: keeps only the newest `MAX_SNAPSHOTS = 60`; older ones `.unlink()` (cascade removes their history rows).
- **Idempotent**: if a snapshot exists for yesterday and is already `generated`, it skips. If it exists but `draft`, it just generates it.

### Backfill (`ir_cron_backfill_snapshots`)
- Runs every 20 minutes; method `_cron_backfill_snapshots`
- Walks backward from today up to `MAX_SNAPSHOTS - 1` days; collects up to `BACKFILL_BATCH = 5` missing dates per run and generates them at 23:59:59 Manila.
- **Auto-deactivates itself** by writing `active=False` on its own `ir.cron` record once all 60 days are covered (or once a backfill batch leaves zero remaining).

### Critical invariants
- These crons **only create `stock.quant.history.snapshot` + `stock.quant.history`** rows. They **NEVER** touch `stock.quant` or `stock.move.line` — those are read-only source-of-truth.
- The 23:59:59 Manila timestamp is intentional: it represents end-of-day for that calendar day.

---

## 6. The Occupancy Report Wizard

Model: `stock.quant.history.occupancy.wizard` — opened from a button on the snapshot list view (`PkrListController`-style OWL controller in `static/src/js/occupancy_report_button.js`).

Fields: `date_from`, `date_to` (required), `partner_ids` (optional filter), `computation_method` selection:

| Method | Behavior |
|---|---|
| `snapshot` | **Auto-generates missing snapshots** for every date in `[date_from, date_to]`, then queries the resulting `stock.quant.history` rows filtered by `owner_id != False` (and `partner_ids` if set), and hands them to `action_report_occupancy_xlsx`. Accurate; uses storage. |
| `sql` | Builds report data **on-the-fly** from the nearest base snapshot + move-line deltas without writing any records. Fast; zero storage cost. The wizard passes an empty `stock.quant.history` recordset so the report itself does the SQL work. |

Both branches end with `self.env.ref('stock_quant_history.action_report_occupancy_xlsx').report_action(records, data=data)` — the `data` dict carries `method`, `partner_ids`, `date_from`, `date_to`, and (snapshot mode) `snapshot_ids` + `history_ids`.

---

## 7. Reports

| XML ID | Report model | Notes |
|---|---|---|
| `stock_quant_history.action_report_occupancy_xlsx` | `report.stock_quant_history.occupancy_xlsx` | Main occupancy XLSX — multi-day per-building grid with title bar, meta row, sub-headers, alternating row formats. Heavy `xlsxwriter` formatting code. |
| `stock_quant_history.action_report_inventory_summary_xlsx` (declared in `reports/inventory_summary_view.xml`) | `report.stock_quant_history.inventory_summary_xlsx` | Inventory summary XLSX based on quant-history rows. |

Both inherit `report.report_xlsx.abstract` (see [`report_xlsx_AI_CONTEXT.md`](report_xlsx_AI_CONTEXT.md)).

---

## 8. Views

- `views/stock-quant-history.xml` — search view with filters on `product_id`, `x_studio_pallet_series_id`, `package_id`, `x_studio_container_number`, `location_id` (with `operator="child_of"`), `lot_id`, plus date filter (`default_period="this_month"`) and group-by helpers (owner, container, pallet, snapshot, date, product).
- `views/stock-quant-history-snapshot.xml` — snapshot tree/form views + the OWL list controller hookup (`js_class="stock_quant_history_snapshot_list_button"`) that adds the Occupancy Report button.

---

## 9. Security

`security/ir.model.access.csv`:

| Model | Group | Access |
|---|---|---|
| `stock.quant.history` | `stock.group_stock_manager` | **Read-only** (no create/write/unlink — history rows are produced only by the generator) |
| `stock.quant.history.snapshot` | `stock.group_stock_manager` | Full CRUD |
| `stock.quant.history.occupancy.wizard` | `stock.group_stock_manager` | Full CRUD (transient) |

No custom group is declared. Only stock managers can use this module.

---

## 10. Common Pitfalls

1. **Timezone trap**: `inventory_date` is stored as naive UTC but **always interpreted as Manila** in the generator/cron logic. Comparing `inventory_date` with `datetime.now()` (UTC) gives wrong results — always localize via `pytz_utc.localize(...).astimezone(MANILA_TZ)`.
2. **`MAX_SNAPSHOTS = 60` and `BACKFILL_BATCH = 5`** are class constants on the snapshot model. Increasing `MAX_SNAPSHOTS` retroactively without re-enabling the backfill cron will *not* fill in older dates — the backfill auto-deactivates once it sees 0 missing within the current window.
3. **`_ignored_location_usage()`** returns `['supplier', 'customer', 'inventory']`. Comment in code: "If you overwrite or change this list you'll probably want to regenerate all your snapshots." Treat as load-bearing.
4. **The `DefaultDict` subclass** at the top of `stock_quant_history_snapshot.py` is **not** Python's `collections.defaultdict`. It passes the key tuple as positional args to the factory — needed because the factory creates an Odoo record with `(product, lot, location)`.
5. **Zero-quantity rows are deleted via raw SQL** at the end of generation. Don't add post-cleanup logic that assumes those rows still exist.
6. **`stock.quant.history.create()` runs `sudo()`** in the generator. Don't try to use it as an audit point — security context is bypassed.
7. **Concurrent generation** of the same snapshot date is not strictly protected; rely on cron's `doall=False` + idempotent skip-if-generated checks instead of locks.
8. **The on-the-fly SQL method** (`computation_method='sql'`) hands an *empty recordset* to the report. The report code in `occupancy_xlsx_report.py` is responsible for doing the SQL — don't assume `records` is populated in that branch.
9. **`is_a_blast_freeze` is a stored related field** — backfilling old snapshots after changing the underlying `location.x_studio_is_a_blast_freezer` will not recompute it automatically. Re-run snapshot generation if classifications change.
10. **OCA upstream**: this module started as OCA's `stock_quant_history` and was extended locally. Cherry-picking OCA updates requires careful three-way merging because of the many added `x_studio_*` mirror fields and the cron behavior.

---

## 11. Database / Run Info

- **DB**: `vifel_03_20_2026_02` on `localhost:5432`
- **Upgrade**: `python odoo-bin -c odoo.conf -u stock_quant_history --stop-after-init`
- **Manual snapshot trigger** (for ad-hoc use): create a `stock.quant.history.snapshot` with `inventory_date` set, then call `action_generate_stock_quant_history()` on it (or just press "Generate" in the UI).
- **Cron names**: `Inventory Snapshot: Daily Generation + Cleanup`, `Inventory Snapshot: Backfill (5 per run)` — visible in Settings → Technical → Scheduled Actions.

---

## 12. Where to read next

- `report_xlsx_AI_CONTEXT.md` — the abstract XLSX report base class every report here inherits
- `pallet_kilos_record_model_AI_CONTEXT.md` — sibling ledger that aggregates RR/WR outcomes (different angle: per-transfer rollup vs. per-quant snapshot)
- `multiple_relocation_AI_CONTEXT.md` — owns the `x_studio_*` field landscape that this module mirrors

---

## 13. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> This module straddles OCA upstream + local VIFEL extensions, so updates need extra care. Whenever you modify it (or hear that requirements have changed), update this document in the **same change** so the next agent can trust it. Specifically:
>
> - **New / removed `x_studio_*` mirror field** on `stock.quant.history` → update section 3 AND the field-copy logic referenced in section 4. Missing mirror fields break the occupancy report silently (blank columns).
> - **Change to `_generate_stock_quant_history`** algorithm → update section 4. This is the module's core invariant.
> - **Cron schedule change, `MAX_SNAPSHOTS` change, or `BACKFILL_BATCH` change** → update section 5 and the relevant pitfall in section 10.
> - **New `computation_method` on the wizard** or change to existing branches → update section 6.
> - **New report or modified report XML ID** → update section 7.
> - **Security / group change** → update section 9.
> - **Upgrade from upstream OCA** → bump the `version` in the header, re-verify sections 3-5, note any merge conflicts addressed.
>
> Keep the tone tight and architectural. Use file paths; do not paste long method bodies. Update the **Last updated** date at the top each time. If a section becomes uncertain, mark it `⚠️ NEEDS VERIFICATION` rather than removing it.
