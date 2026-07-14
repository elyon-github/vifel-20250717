# VIFEL — Verification Notes (code + live DB vs. the curated docs)

> **Generated**: 2026-06-24 · **DB verified against**: `vifel_06_19_2026` (latest dated clone)
> **Method**: read-only SQL on the live DB + AST/graph of the 4 core modules. Where a hand-written
> `ai_context/*.md` claim disagreed with reality, reality (code/DB) wins and is recorded here.
> This file seeds the eventual turnover document. Re-verify before trusting any single line.

---

## A. Two systemic findings (read these first)

### A1. The business logic lives mostly in the **Studio DB layer**, not in the Python modules
The four custom modules (`multiple_relocation`, `pallet_kilos_record_model`, `stock_quant_history`,
`pallet_series_audit`) are real and important, but the **operational behaviour of day-to-day warehouse work is
driven by Studio `base.automation` rules + `ir.actions.server` records stored in the database**, not by module
code. In `vifel_06_19_2026`:
- **27 active automation rules** (24 on the stock models) — each fires an "Execute Code" server action.
- **126 server actions** on the operational models; ~91 are live/used, the rest deprecated/standard/scratch.
- Example: **PKR rows are created by `BA#6 → SA#297` ("Pallet Kilos Record - Create Record Per Move")**, a Studio
  automation that calls `env['pallet_kilos_record_model.pallet_kilos_record_model']` — *not* by a module method.

Implication for turnover: you cannot understand VIFEL from the Python repo alone. The DB automations are
first-class source code and must be exported/version-controlled (see `fetch_database_context.py`).

### A2. `fetch_database_context.py`'s "custom" filter is **badly under-inclusive**
The dump filters by `ir_model_data.module ∈ CUSTOM_MODULES`. But almost all Studio records have **`module = NULL`**
(created directly in Studio, never assigned to a module). Result: the generated `database_context_dump.md`
reports only **2 automations + 15 server actions**, hiding the real **27 automations + ~91 used actions** —
including BA#6 (PKR engine) and the entire pallet-series action family. **Do not trust the dump's counts.**
*Fix later (not done this phase — read-only):* widen the filter to also keep records whose model is an OPS model
(stock.*, pallet.*, x_inventory_static_var, …) or that are active automations / their linked actions.

---

## B. Specific claims — CONFIRMED / OUTDATED / MISSING

| Claim (from docs/memory) | Status | Evidence (live DB / code) |
|---|---|---|
| Server action **#347 "Assign Pallet Series ID"** is the pallet-series assigner | **OUTDATED** | #347 exists but renamed **`X_Assign Pallet Series ID`** — `X_` = deprecated, **unwired** (no binding/automation/cron/view). Not in the active path. |
| **BA#6** auto-creates the PKR row on validation | **CONFIRMED** | `base_automation` #6 active=true → `SA#297` (state=code) calls `env['pallet_kilos_record_model…']`. Trigger `on_state_set`. |
| `x_studio_record_reference` exists on `stock.quant` | **CONFIRMED** | `ir_model_fields`: m2o→`stock.picking` on `stock.quant` **and** `stock.quant.history`; a `char` of the same name on `stock.move.line`. |
| `stock_quant_history` snapshot engine (DefaultDict seed + move-line replay, MAX_SNAPSHOTS=60, backfill self-deactivates) | **CONFIRMED** | matches `stock_quant_history_snapshot.py` (`_generate_stock_quant_history`, `_cron_generate_daily_snapshot`, `_cron_backfill_snapshots`). |
| Backfill cron "runs **every 20 minutes**" (`stock_quant_history_AI_CONTEXT.md`) | **OUTDATED** | cron #489 is **every 10 minutes** in the DB. |
| Void/return flow `_void_wr_quant_domain` / `_find_void_wr_quants` / `_create_void_wr_from_rr` | **CONFIRMED** | present in `multiple_relocation/models/stock_picking.py` (graph community "Void WR Engine"). |
| Studio **SA#471 "Void Transfer"** is the void mechanism | **OUTDATED / superseded** | SA#471 is **unwired** (orphan). Void now runs in module code (`void_transfer_simple`, `void_transfer`, `button_validate` auto-void). Treat SA#471 as legacy — verify before deleting. |
| **BA#42 "Assign ID on move-line create"** assigns the pallet series | **OUTDATED (mislabel)** | SA#432 assigns the **per-picking line counter `x_studio_`** (max+1), *not* a pallet series. |
| "Set Pallet Series" / "Change Pallet Series" are code actions | **PARTLY OUTDATED** | SA#463/#499 are **`object_write`** field-setters (not Python); SA#467 clears the series fields. Real assignment for receiving is via the res.partner pool + FastEncodeRR (module code) + the `x_studio_pallet_series_id` compute on move.line. |
| The `_action_assign`/`_do_unreserve` cascade-delete → "disappearing pallet series" bug | **CONFIRMED (as rationale)** | documented in `multiple_relocation/CONTEXT.md`; motivated `pallet_series_audit`. Not re-tested live this phase. |

---

## C. Crons are **inactive in this clone** (verify production separately)
All operational `ir.cron` records in `vifel_06_19_2026` are `active=False`: Cleanup Quant (#351), Recompute
Expiration (#411), Aging Days (#417), Unreserve Locations (#447), **Daily Snapshot (#488)**, **Backfill (#489)**,
**Audit Cleanup (#493)**, Clean Unreserved (#509). This is almost certainly **Odoo clone-neutralisation** (crons
auto-disabled when a DB is duplicated), **not** a production fact. Confirm cron state on the real production DB
before concluding snapshots/cleanups aren't running there.

---

## D. Excluded DB records (for the focused graph) — full audit trail
Kept in the graph: **25 active automations + 91 used/unwired server actions + 12 model hubs**. Excluded:
- **24 archived automations** (inactive): BA#5,7,9,11,12,13,16,21,23,24,28,31,32,35,36,37,39,41,43,45,50,52
  + 2 generic `mail.activity` (BA#40,46). Their 18 orphaned "Execute Code" children are excluded with them.
- **10 standard-Odoo** server actions (`module=stock`): #239/#240 Inventory, #244 Set-to-on-hand, #245 Set-to-0,
  #247 Revert Adjustment, #253 Validate, #254 Unreserve, #255 Lock/Unlock, #256 Scrap, #269 Routes.
- **10 `X_`-deprecated**: #300,#301,#302,#311,#320,#334,#347,#348 (+ bound-but-deprecated #306,#319).
- **3 scratch/test**: #340 Test Fill Demand, #451 Test Server Action, #472 Template.
- **18 "unwired/verify"** (no automation/binding/cron/view-ref) — **included in the graph, tagged `unwired`** per
  decision, because several look meaningful and need human judgement: #471 Void Transfer (superseded?), #372 Assign
  Location, #499 Set Pallet Series ID, #511 Re-set Pallet Series ID, #338 Reserve/Unreserve Pallets for BF, #448
  FIX LOCATION, #470 FIX QUANT AVAIL, #529 CHANGE OWNER, #519 Change Customer, #516 Picking, #508 Unreserve
  Quantity, #480 Set to Done, #481 Set Done Move Lines, #497 Set Product to New, #373 Transfer Pallet to Transfer
  Record, #341 Auto-Fill Details, #392 Clean Packages, #468 Remove Return from WR Connection.
