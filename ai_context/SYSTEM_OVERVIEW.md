# VIFEL WMS — Verified System Overview

> **Audience**: future Odoo consultants / developers taking over the project.
> **Scope of this overview**: the 4 business-critical custom modules + the live Studio (DB) automation layer.
> **Grounding**: built from the code (AST graph in `graphify-core/`) and read-only inspection of the live DB
> `vifel_06_19_2026`. Claims that contradicted the older `ai_context/*.md` notes were corrected — see
> `VERIFICATION_NOTES.md` for the evidence and the CONFIRMED/OUTDATED list. Navigate the system visually with
> `graphify-core/graph.html`.

---

## 1. What VIFEL is, and why it was built

VIFEL is a **third-party cold-storage warehouse (3PL) management system** on **Odoo 17 Enterprise**. The client
stores frozen/chilled goods on **pallets** on behalf of multiple **owners (clients)** and **bills them by
occupancy** (pallets and kilograms held over time). The customisation exists to make stock Odoo model the
realities of a cold store that vanilla Odoo does not:

- **Pallet identity & a scarce, reusable "pallet-series" pool.** Each physical pallet carries a *pallet series ID*
  drawn from a pool held on `res.partner`. Series are recycled when pallets empty out, so the system must track
  every assignment/return precisely.
- **Blast-freeze (BF) vs. regular handling.** BF pallets (metal, no package, identified by lot + an originating
  "record reference") follow a parallel operation set (BFRR/BFWR) distinct from regular receiving/withdrawal.
- **Occupancy billing.** A running ledger (PKR) of pallets/kilos/units/packaging per (warehouse, BF, owner) feeds
  monitoring, billing and daily-inventory reports; point-in-time snapshots feed occupancy reporting.
- **Forensic auditing.** A known Odoo `_action_assign`/`_do_unreserve` cascade caused pallet series to silently
  "disappear" on reservation; an append-only audit module was built to trace it.

## 2. Architecture: a **dual-layer** system (the single most important thing to know)

VIFEL behaviour is split across **two layers that must be read together**:

1. **Studio / DB layer** (in the database, *not* in the git repo): **27 active `base.automation` rules** firing
   **`ir.actions.server` "Execute Code"** actions, plus **~90 bound/cron/print server actions**. This layer drives
   the document lifecycle (receiving → done → withdrawal), assigns fields, enforces validations, and even creates
   the billing rows (PKR via `BA#6 → SA#297`). Export it with `fetch_database_context.py` (but note its filter is
   under-inclusive — see `VERIFICATION_NOTES.md` §A2).
2. **Python module layer** (this repo): heavier algorithms that are awkward in Studio — relocation, FastEncodeRR,
   void/return WR construction, the PKR balance engine, snapshot generation, XLSX reports, and the pallet-series
   audit + OWL dashboard.

The two layers are coupled by **model + method calls**: Studio actions call module methods and write fields that
module code reads (and vice-versa). `graphify-core/` makes this explicit (server-action nodes → `calls` → code
method nodes; `[model] …` hub nodes link both layers per Odoo model).

## 3. The four core modules

| Module | Role | Key code |
|---|---|---|
| **`multiple_relocation`** | Operational spine. Relocation of quants/packages between locations; RR/WR/BFRR/BFWR flows; the **void & return** workflow; the **FastEncodeRR** fast-entry wizard; `stock.move`/`stock.move.line`/`stock.quant`/`stock.picking` overrides. | `models/stock_picking.py` (void engine, `operation_type_checker`), `stock_move*.py`, `stock_quant.py`, `models.py` (FastEncodeRR, relocate, return-package, correction wizards) |
| **`pallet_kilos_record_model`** (PKR) | Billing/inventory **ledger**: per-(warehouse, blast-freeze, owner) running balance of pallets/kilos/units/packaging. Feeds monitoring/billing/daily-inventory XLSX + "Get Unsynced" + recompute. | `models/models.py` (`PalletKilosRecordModel`, `action_recompute_selected_balances`, `action_get_unsynced`; note a `_dead_…_legacy` engine remains) + `reports/*_xlsx*.py` |
| **`stock_quant_history`** | Point-in-time inventory **snapshots** + occupancy reporting, independent of PKR. Seeds from prior snapshot + replays move lines. | `stock_quant_history_snapshot.py` (`_generate_stock_quant_history`, daily/backfill crons), `stock_quant_history.py`, occupancy wizard/report |
| **`pallet_series_audit`** | Append-only **audit log** of pallet-series lifecycle (pool push/pull, generation) + OWL **timeline dashboard**. Built to trace the disappearing-series bug. | `pallet_series_audit.py` (`log_event`), `res_partner.py` (pool methods), `stock_move*.py` overrides, `static/src/.../timeline_dashboard.js` |

## 4. Core process flows (which layer fires at each step)

### 4.1 Receiving (RR / BF: BFRR)
1. Operator creates a Receiving Report (incoming `stock.picking`); `picking_type_id.is_blast_freeze_operation`
   distinguishes BF. `x_studio_is_a_blast_freezer` mirrors this.
2. On save/create: Studio automations populate and validate — **BA#1** set owner from partner, **BA#42** assign the
   per-line counter `x_studio_`, **BA#22** assign UOM, plus the move/move-line **guard clauses** (BA#19/#20) and
   **FastEncodeRR** (module wizard) for fast multi-line entry + **pallet-series assignment from the res.partner
   pool**.
3. On validation (`state=done`): **BA#2** assigns the transfer/record reference to quants (with the "one pallet →
   one location, no mixed product" guard), **BA#6 → SA#297** creates the **PKR** row(s), **BA#38** re-syncs pallet
   series, **BA#10/#15** update pallet info & counters. Receiving reports print via SA#473/#474 (BF: #520/#521).

### 4.2 Storage, relocation & corrections
- Quants live in internal locations; `stock.location` computes occupancy (`x_studio_occupied_by_1`, pallets,
  total qty). Relocation between locations runs through `multiple_relocation` (`action_relocate_quants`,
  `_perform_relocation`) and the bound **Update Quants (Relocate)** action (SA#513).
- **Correcting pallet details**: the **Correct Quants** action (SA#402, bound on `stock.quant`) opens the
  `stock.quant.correction.wizard` → optional approval workflow (`stock.quant.adjustment.request`) → applies and
  records a correction move. The PKR ledger is adjusted via `_update_pallet_kilos_record`.

### 4.3 Withdrawal (WR / BF: BFWR)
1. Outgoing `stock.picking`; on the move lines, **compute fields** derive withdraw quantities from the source
   quant (`x_studio_withdraw_units`, `x_studio_affected_2nd_uom`, `x_studio_pallet_series_id`, expiry, container,
   etc. — all keyed by matching product+owner+lot on the source location).
2. Variance vs. demand is computed (`x_studio_kg_variance`, `_packaging_variance`, `_min_variance`) and gated by
   per-warehouse thresholds in `x_inventory_static_var`; **BA#17** disables Validate when a discrepancy exists.
3. On done: PKR is decremented (BA#6 path), pallets used for delivery are freed (BA#26), withdrawal reports print
   (SA#475/#476; BF #523/#524).

### 4.4 Void & Return
- **Void** marks a transfer voided, archives its PKR row, and (for RR) builds a **void WR** that checks out the
  matching quants to reverse received inventory — module code: `void_transfer`, `void_transfer_simple`,
  `_create_void_wr_from_rr`, `_void_wr_quant_domain`, `_find_void_wr_quants` (with the package-drift fallback).
  `button_validate` auto-voids WRs created from voided RRs. The old Studio **SA#471 "Void Transfer" is superseded**
  (now unwired — verify before removing).
- **Return**: `ReturnPackageWizard` builds/extends a return picking for selected packages; a void WR can spawn a
  return RR (`_create_return_rr_from_wr`).

### 4.5 Pallet-series pool lifecycle (the scarce resource)
- The pool lives on **`res.partner`** (`generate_new_pallet_series_id`, `get_smallest_pallet_series_ids`,
  `push_unused_pallet`, `get_pallet_series_by_id`). FastEncodeRR draws series on receiving and **pushes unused
  series back** to the owner's pool on cancel/resync.
- Every push/pull/generation is logged via `pallet_series_audit.log_event` (overrides on `res.partner`,
  `stock.move`, `stock.move.line`, injected with audit context from FastEncodeRR) and surfaced on the OWL timeline
  dashboard. This is the forensic trail for the disappearing-series bug.

### 4.6 Occupancy snapshots & billing reports
- **Snapshots** (`stock.quant.history.snapshot`): daily cron (#488) creates a 23:59 Manila snapshot, keeps newest
  60; backfill cron (#489) fills gaps and self-deactivates. Generation seeds from the prior snapshot and replays
  done move lines; never mutates `stock.quant`. **(Both crons are currently `active=False` in this clone — likely
  neutralisation; verify production.)**
- **Occupancy report** (`stock_quant_history`): wizard offers `snapshot` (accurate, auto-generates missing dates)
  or `sql` (on-the-fly, zero storage) modes → occupancy XLSX. This **supersedes** the legacy PKR occupancy report.
- **PKR reports**: monitoring, billing, billing-as-of, daily inventory, daily pallet utilisation — all read the PKR
  running balances / locations.

## 5. Key data & identity rules
- **Regular pallet identity** = `x_studio_pallet_series_id` (PSI) + `result_package_id`/`package_id`. PSI is the
  stable identity but **not globally unique**; package can drift (re-packaging) — handled by the void fallback.
- **BF pallet identity** = `lot_id` + `x_studio_record_reference` (m2o → originating RR) + `location_is_bf`; **no
  package**, free-text `bf_pallet_char`. BF lots are **reused across receipts** (not unique) — hence the record
  reference scoping.
- **Static config** lives in `x_inventory_static_var` (per-warehouse variance thresholds, expiry ranges), managed
  by BA#14/#30.

## 6. Caveats for the next developer
- **Read the DB layer, not just the repo.** ~Half the behaviour is Studio automations/server actions (§2).
- **The DB dump under-reports** (its filter misses `module=NULL` Studio records) — see `VERIFICATION_NOTES.md` §A2.
- **`vifel_06_19_2026` is a dated clone**; crons are disabled in it (§4.6). Don't infer production scheduling.
- **Deprecated noise exists** in the DB: `X_`-prefixed actions, "Test"/"Template" scratch, and ~18 unwired
  server actions (kept in the graph tagged `unwired` for review). Don't assume a server action is live just
  because it exists.
- **PKR engine has a `_dead_…_legacy` method** alongside the current one — confirm which path runs before editing.
