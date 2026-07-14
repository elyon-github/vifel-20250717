# Multi-Warehouse Migration Plan — Vulnerability Audit & Phased Roadmap

> **Scope**: All custom modules under `addons/custom_addons/vifel-20250717/` (except `app_common`, `app_odoo_customize`, `odoo_calculator_tool`).
> **Goal**: Treat each warehouse as **completely separate data** — isolation of clients, pallets, audit logs, ledgers, snapshots, reports, and user access — while removing the many places where the code silently assumes "one warehouse".
> **Operating assumption (confirmed with user)**: each `res.partner` (client) is assigned to exactly one warehouse via `res.partner.x_studio_warehouse`. Users are **restricted** to one or more warehouses via a new warehouse-aware security layer.
> **Policy decision (user, 2026-07-04)**: a Contact exists in **exactly one warehouse, ever**. If the same real-world client also transacts with another warehouse, a **separate Contact is created there**. Cross-warehouse duplicates-by-name are therefore *by design*, and contacts must never be merged across warehouses.
> **Last updated**: 2026-07-04 (reviewed against code + production clone `vifel_06_30_2026_1`; contact-per-warehouse policy added)

---

## 0. Executive Summary

The codebase is **half-aware of multi-warehouse**: partners carry an `x_studio_warehouse` Studio field, pickings carry `x_studio_warehouse_sh` (warehouse short-handle code), and the pallet-kilos ledger already partitions running balances by `warehouse`. But the **enforcement is missing in three areas that matter most**:

1. **No security record rules** scope any model by warehouse. Any user with model access sees every warehouse's data.
2. **Cross-warehouse reads** happen in queries that should be scoped (audit log, pallet series pool, snapshot generator, several wizards).
3. **Cron jobs and shared sequences operate globally** — one daily snapshot covers all warehouses, one sequence numbers all adjustment forms regardless of warehouse, etc.

The migration is achievable in **3 phases over a single sprint cycle** without a "big-bang" rewrite. Phase 1 (foundations) is low-risk and unblocks everything else. Phase 2 (data scoping) is where the most regressions could appear and needs careful test coverage. Phase 3 (UX + reports) is polish.

### 0.1 Current state — verified 2026-07-04 against production clone `vifel_06_30_2026_1`

| Fact | Status | Implication |
|---|---|---|
| **A second warehouse already exists in production config**: `Tagoloan` (code `T`, id 2) alongside `Meycauayan` (`M`, id 1). Tagoloan has **7 picking types + 9 locations provisioned**, but 0 partners assigned and 0 operations (all 9,602 done pickings are `M`). | ⚠️ **Raises urgency** | Multi-warehouse is no longer hypothetical — Phases 1–2 should complete **before Tagoloan onboards**, or every 🔴/🟠 item below becomes live exposure on day one. |
| Record rules: only the stock **multi-company** defaults exist (rules #67/#73/#74/#75). Zero warehouse-scoped `ir.rule`. | Confirms **C1** | — |
| All **62 owners with on-hand stock have `x_studio_warehouse` set**. | Migration §4 step 2 largely **done** | Constraint (Phase 1.3) still pending. |
| `adjustment.form.series` (#34) and `relocate.form.series` (#35) both exist as **single global sequences** (no prefix). | Confirms **H6/H7** | — |
| Latest snapshot's 21,073 history rows are all warehouse `M`; generator and crons are global. | Confirms **C3/C4** | — |
| `x_warehouse_building` **already has** an `x_studio_warehouse` m2o (3 building rows). | §2.1 row resolved ✅ | Searches still need the warehouse filter (H2). |
| `res.users.x_studio_warehouse` exists but is the **inherited partner field** (no user-level column) — it is *not* a usable per-user warehouse restriction. | — | The planned `allowed_warehouse_ids` M2M is still required; beware confusing the two. |
| The module's new **Get Unsynced** (`action_get_unsynced`, models.py:916) already filters by `location_id.warehouse_id` per partition. | ✅ warehouse-safe | Positive baseline for Phase 2 patterns. |

---

## 1. Vulnerability Audit — Ranked by Risk

Risk legend:
- 🔴 **Critical** — actively leaks or corrupts data across warehouses today; must fix before rollout.
- 🟠 **High** — works correctly today only by coincidence (one warehouse in DB); will break on second warehouse install.
- 🟡 **Medium** — usable but degraded UX or potential for confusion.
- 🟢 **Low** — cosmetic / non-blocking.

### 🔴 Critical

| # | Module | File / Line | Issue | Why it matters |
|---|---|---|---|---|
| C1 | (all) | (no record rules anywhere) | **No `ir.rule` records** scope any custom model by warehouse. | A stock user assigned to WH-A can read/write `stock.picking`, `stock.quant`, `pallet.series.audit`, `stock.quant.history`, `pallet_kilos_record_model` rows from WH-B. |
| C2 | `multiple_relocation` + `pallet_series_audit` | `multiple_relocation/models/models.py:23,45,64` and `pallet_series_audit/models/res_partner.py:12,31,52` (pool methods exist in **both** modules — the audit module's override is the live one) | Pool state (`unused_pallet_series_ids`, `x_studio_pallet_series_id` counter, `x_studio_client_unique_code_1`) lives on `res.partner` with **no warehouse partition**. | *(2026-07-04: **downgraded to guard-rail work** by the contact-per-warehouse policy — each warehouse's client is a separate partner, so pools cannot collide **provided the policy is enforced**. Remaining work: (a) constraint making `x_studio_warehouse` required + immutable once the partner has transactions; (b) block cross-warehouse contact merges; (c) note that the same PSI string (e.g. `ACM-000005`) may legitimately exist in both warehouses if the duplicate contacts share a client code — all PSI lookups must stay location/warehouse-scoped. Pool draws happen via FastEncodeRR module code — old SA#347 deprecated, see M9.)* |
| C3 | `stock_quant_history` | `models/stock_quant_history_snapshot.py:91-340` (`_generate_stock_quant_history`) | Each snapshot covers the **entire `stock.move.line` table** for all warehouses. Domain is `state=done AND date <= inventory_date AND product.type=product` — no warehouse filter. | One snapshot row mixes WH-A and WH-B quants. `MAX_SNAPSHOTS=60` is per-DB, not per-warehouse, so older WH-A snapshots get dropped by WH-B activity. |
| C4 | `stock_quant_history` | `data/ir_cron.xml` + `_cron_generate_daily_snapshot`, `_cron_backfill_snapshots` | Crons generate **one snapshot per calendar day, globally**. Backfill auto-deactivates once "all 60 days" are filled — meaning the first warehouse using it satisfies the condition for everyone. | Adding a second warehouse later won't trigger backfill for the new warehouse. |
| C5 | `pallet_series_audit` | `models/pallet_series_audit.py` (no partner/warehouse on header) | Audit header is keyed on `picking_id` only. Lookups via the smart button work, but the **menu / search views** in `views/audit_views.xml` show every warehouse's audit logs to anyone with `group_pallet_audit`. | Cross-warehouse forensic data leak. |

### 🟠 High

| # | Module | File / Line | Issue |
|---|---|---|---|
| H1 | `multiple_relocation` | `models/stock_move.py:82` *(line ref refreshed 2026-07-04)* | Hardcoded package lookup by name: `[('name', 'ilike', 'GENERIC METAL PALLET')], limit=1`. First match wins regardless of warehouse. |
| H2 | `multiple_relocation` | `wizard/stock_quant_relocation_lines.py:42` *(refreshed)* | `self.env['x_warehouse_building'].search([], limit=1)` — picks an **arbitrary** building when computing default. No warehouse filter. *(2026-07-04: `x_warehouse_building.x_studio_warehouse` exists — the filter just needs to be added.)* |
| H3 | `multiple_relocation` | `models/stock_picking.py:2843, 2858` *(refreshed)* | `("warehouse_id.code", "=", record.x_studio_warehouse_sh)` — depends on `x_studio_warehouse_sh` being filled. If unset, the domain matches nothing → empty location dropdown silently. |
| H4 | `multiple_relocation` | `models/stock_picking.py:2852` *(refreshed)* | `('warehouse_id.id', '=', record.partner_id.x_studio_warehouse.id)` — silent NPE / wrong-warehouse picks if `partner.x_studio_warehouse` is missing. |
| H5 | `multiple_relocation` | `models/stock_move.py:1108, 1186` | `('x_studio_warehouse.id', '=', record.owner_id.x_studio_warehouse.id)` — same silent failure mode as H4. |
| H6 | `multiple_relocation` | `wizard/stock_quant_correction.py:265-267, 992-994` *(refreshed)* | Sequence code `'adjustment.form.series'` used globally. All warehouses share one numbering. |
| H7 | `multiple_relocation` | `models/stock_quant.py:444` *(refreshed)* | Sequence code `'relocate.form.series'` shared globally — same as H6. |
| H8 | `pallet_kilos_record_model` | `models/models.py:303-582` (`_recalculate_running_balances`) | Algorithm IS partitioned by `(warehouse, is_blast_freezer)` ✅ but the `manual_recalculate_all()` / `resync_all_2()` maintenance entry points iterate every warehouse with no permission check — anyone who can call them rewrites every warehouse's balances. |
| H9 | `pallet_kilos_record_model` | `wizard/pkr_report_wizard.py` | Report wizard has `partner_ids` and `building_ids` filters but **no `warehouse_ids`**. Generated reports mix data from any warehouse the user can read. |
| H10 | `stock_quant_history` | `wizard/occupancy_report_wizard.py` | Same as H9 — no warehouse filter on the wizard. Both `_action_report_snapshot` and `_action_report_sql` operate across all warehouses. |
| H11 | `stock_quant_history` | `security/ir.model.access.csv` | Only `stock.group_stock_manager` can use snapshot model — meaning every manager sees every warehouse. No per-warehouse manager role. |
| H12 | `multiple_relocation` | `models/stock_picking.py:1110,1117,1158` (`order='create_date desc', limit=1` patterns) | "Find the latest X" queries with no warehouse filter — return latest from any warehouse. Used in BF dock assignment, last-pallet lookups, etc. |
| H13 | `multiple_relocation` + `pallet_kilos_record_model` | various reports/wizards using `timezone('Asia/Manila')` / `MANILA_TZ` / `UTC+8` | Hardcoded timezone. If a future warehouse operates in a different TZ, all date math breaks. *(2026-07-04: both existing warehouses — Meycauayan and Tagoloan — are in the Philippines, so this stays Manila-safe for the current roadmap; see §6 Q4.)* |
| H14 | `pallet_kilos_record_model` | `models/models.py:100-105` (`_get_static_var`) — **NEW 2026-07-04** | XLSX config vars (`Max Pallets`, `Max Kilograms`) fetched by `x_name ilike` with **no warehouse filter**, `limit=1` — first match wins across warehouses, even though `x_inventory_static_var` already carries `x_studio_warehouse`. Report headers/limits will show the wrong warehouse's config once T is live. |

### 🟡 Medium

| # | Module | File / Line | Issue |
|---|---|---|---|
| M1 | `multiple_relocation` | `wizard/FastEncodeRR.py` | `transfer_id` is `fields.Integer` storing a picking ID — no warehouse derivable from it without a `.browse()`. Refactor friction for tooling that wants to know "which warehouse is this wizard for?" |
| M2 | `multiple_relocation` | `models/stock_picking.py:67,290,421,523,555,575,611,658,966,975` (many `limit=1` searches) | Most lookups assume "there's only one of these per company" — without warehouse scoping, the first match wins regardless of warehouse. |
| M3 | `pallet_kilos_record_model` | `views/views.xml` | Tree is `default_order="start_time desc"` with no warehouse group/filter shown by default. Users will visually mix warehouses unless they manually filter. |
| M4 | `pallet_series_audit` | `views/audit_views.xml` (3 menus under Inventory → Pallet Series Audit) | Menus show every warehouse's audit events; no warehouse filter chip. |
| M5 | `stock_quant_history` | `views/stock-quant-history.xml` | Search view groups by snapshot, owner, package — no warehouse group, no warehouse filter. |
| M6 | `multiple_relocation` | `models/stock_picking.py` `vifel_type_of_operation` (RR/WR/BFRR/BFWR) | Computed from `picking_type_id` — relies on operators having created the right picking types per warehouse. No safety net if multiple warehouses each have a "WR" picking type — labels collide. |
| M7 | `pallet_kilos_record_model` | `import_opening_balances_from_quants(quant_ids)` | Trusts the caller's quant selection. A user could (accidentally or intentionally) include quants from another warehouse. *(2026-07-04: **largely mitigated** — import now groups per (owner, warehouse, BF) partition with a double-import guard and per-partition recalc, so a cross-warehouse selection creates correctly-partitioned rows instead of corrupting one. Residual: selection scope itself waits on C1 record rules.)* |
| M8 | `pallet_kilos_record_model` | Studio automation AR#6 → SA#297 | *(2026-07-04: verified in Studio — there are in fact **25 active automation rules** on the stock models, all global. However their code derives the warehouse from the record itself (e.g. SA#297 uses `record.location_dest_id.warehouse_id`), so they are global-but-warehouse-safe **by construction**. Keep as a watch item: any new Studio rule must follow the same derive-from-record pattern.)* |
| ~~M9~~ | ~~`multiple_relocation`~~ | ~~Server Action #347 ("Assign Pallet Series")~~ | **RESOLVED-BY-OBSOLESCENCE 2026-06-24**: SA#347 is renamed `X_Assign Pallet Series ID` — deprecated and unwired (no binding/automation/view reference). Pallet-series assignment runs via FastEncodeRR module code (see C2). No warehouse work needed here; archive the dead action during cleanup. |
| M10 | `pallet_kilos_record_model` | production data — **NEW 2026-07-04** | **2,877 active PKR rows have `is_blast_freezer = NULL`** (pre-refactor code still live in prod). The ORM treats `= False` as including NULL, so balances hold today — but any raw-SQL/BI report or exact comparison splits partitions. Backfill `NULL → False` (all verified genuinely regular) when deploying the refactor, **before** per-warehouse reporting. |
| M11 | `multiple_relocation` | `reports/client_summary_xlsx.py:71-76` — **NEW 2026-07-04** | The Client Inventory Summary fix (2026-07-03) re-queries each owner's **complete internal stock with no warehouse filter**. Safe under the one-warehouse-per-owner assumption; must add `('location_id.warehouse_id', ...)` scoping when Tagoloan goes live. |
| M12 | Studio (DB) | SA#513 "Update Quants (Relocate)" — **NEW 2026-07-04** | Re-stamps quant fields from the **latest move line by `lot_id`** (`order='date desc', limit=1`) with no warehouse filter — H12-family pattern on the Studio side. If a lot ever exists in two warehouses, relocation copies the wrong warehouse's details. |
| M13 | `pallet_kilos_record_model` + `multiple_relocation` reports | `reports/pallet_kilos_xlsx.py:611-615`, `reports/pallet_kilos_billing_xlsx.py:160-169,433-442`, `reports/client_summary_xlsx_history.py` — **NEW 2026-07-04** | Reports bucket rows by **`owner_id.name` (string)**. Under the contact-per-warehouse policy, the same client name will legitimately exist as two partners (one per warehouse) — name-keyed grouping **merges them into one sheet/balance** for any cross-warehouse selection. Re-key grouping by `owner_id` (id), render the name + warehouse in the header. |

### 🟢 Low

| # | Module | File / Line | Issue |
|---|---|---|---|
| L1 | (all) | Module names (e.g. `pallet_kilos_record_model.pallet_kilos_record_model`) | Cosmetic — won't break multi-warehouse, but renaming-by-warehouse is awkward. Leave alone. |
| L2 | `report_xlsx` | (whole module) | OCA library — no warehouse awareness needed; downstream reports handle filtering. |
| L3 | Comments and docstrings referencing "VIFEL" | various | Branding-specific. If new warehouses are different brands, refresh strings later. |

---

## 2. Data Model Changes Required

### 2.1 New / extended fields

| Model | Field | Type | Notes |
|---|---|---|---|
| `res.users` | `allowed_warehouse_ids` | M2M `stock.warehouse` | Source of truth for "which warehouses can this user access". Read by all record rules. Existing `app_common/res_users.py` is a good extension point. |
| `res.users` | `default_warehouse_id` | M2O `stock.warehouse` | UX default for forms/reports; must be in `allowed_warehouse_ids`. |
| `res.partner` | `x_studio_warehouse` | M2O `stock.warehouse` (already exists) | **Make required** for clients used as picking partners. Already populated for production data; add a constraint. |
| `pallet.series.audit` | `warehouse_id` | M2O `stock.warehouse`, related from `picking_id.picking_type_id.warehouse_id`, stored, indexed | Enables record rule + menu filtering. |
| `stock.quant.history.snapshot` | `warehouse_id` | M2O `stock.warehouse`, required | Make snapshot per-warehouse. Migration: per-warehouse re-generation of historical snapshots (see §3.2). |
| `stock.quant.history` | `warehouse_id` | M2O `stock.warehouse`, related from `location_id.warehouse_id`, stored, indexed | For per-warehouse search/group. |
| `pallet_kilos_record_model.report.wizard` | `warehouse_ids` | M2M `stock.warehouse` | Wizard filter; defaults to user's `allowed_warehouse_ids`. |
| `stock.quant.history.occupancy.wizard` | `warehouse_ids` | M2M `stock.warehouse` | Same as above. |
| `x_warehouse_building` (Studio) | `warehouse_id` | M2O `stock.warehouse`, indexed | Likely already exists in the Studio model; if not, add via Studio + script. All searches must include `('warehouse_id','in', allowed)`. |

### 2.2 New sequences

Replace the two global sequences with **per-warehouse sequences** via either:

- **Option A (cleaner)**: a new `M2M`/`O2M` on `stock.warehouse` like `adjustment_form_sequence_id`, and a helper `partner.warehouse_id._get_sequence('adjustment')`.
- **Option B (cheaper)**: keep a single `ir.sequence` per code, add a per-warehouse `prefix` (e.g. `WH-A/ADJ/`) using `ir.sequence.date_range` semantics, and rely on prefix uniqueness.

Recommended: **Option A** for clarity. Updates needed in:
- `models/stock_quant.py:387`
- `models/stock_picking.py:2499-2500`
- `wizard/stock_quant_correction.py:223, 914, 981`

### 2.3 New security groups

| Group | Inherits | Purpose |
|---|---|---|
| `multi_wh_user` | `stock.group_stock_user` | Can read/write data only for `allowed_warehouse_ids`. Record rules attached. |
| `multi_wh_manager` | `stock.group_stock_manager` | Same as above + can run maintenance crons / sequences for assigned warehouses. |
| `multi_wh_admin` | `multi_wh_manager` | Cross-warehouse god mode — for the central VIFEL ops team. **Required** for global crons / OB imports / migration scripts. |

### 2.4 New record rules

| Model | Rule | Domain | Applies to |
|---|---|---|---|
| `stock.picking` | "Restrict pickings to assigned warehouses" | `[('picking_type_id.warehouse_id', 'in', user.allowed_warehouse_ids.ids)]` | `multi_wh_user`, `multi_wh_manager` |
| `stock.quant` | same | `[('location_id.warehouse_id', 'in', user.allowed_warehouse_ids.ids)]` | same |
| `stock.move`, `stock.move.line` | same | derive via `picking_id.picking_type_id.warehouse_id` | same |
| `pallet.series.audit`, `pallet.series.audit.line` | same | via the new `warehouse_id` field | `group_pallet_audit` |
| `stock.quant.history`, `stock.quant.history.snapshot` | same | via the new `warehouse_id` field | snapshot manager group |
| `pallet_kilos_record_model.pallet_kilos_record_model` | same | uses existing `warehouse` field | base.group_user |
| `res.partner` | "Restrict partners to assigned warehouses" | `[('x_studio_warehouse', 'in', user.allowed_warehouse_ids.ids)]` for `is_company`/customer partners only | mind impact on non-warehouse partners (suppliers, employees) — restrict by a partner category filter |

---

## 3. Phased Roadmap

### Phase 1 — Foundations (low-risk, no behavior change) — 🛠 IMPLEMENTED 2026-07-04, pending staging validation

Goal: introduce the warehouse field plumbing and the security framework **without** activating restrictive record rules yet.

1. ✅ `res.users.allowed_warehouse_ids` + `default_warehouse_id` — implemented in the **new module
   `vifel_multi_warehouse`** (NOT app_common: it is vendored; the warehouse security layer lives in one
   dedicated module so Phase 2's record rules land in the same place).
2. ✅ `warehouse_id` (related, stored, indexed) added to `pallet.series.audit`(+`.line`) and
   `stock.quant.history`; plain nullable M2O on `stock.quant.history.snapshot`. Big-table backfill via
   `stock_quant_history/migrations/17.0.1.1.0/pre-migrate.py` (pre-created column ⇒ no ORM recompute).
3. ✅ Partner guard-rails in `vifel_multi_warehouse/models/res_partner.py`. NOTE: `customer_rank` does not
   exist in this DB (no sale/account) — the client marker is **`x_studio_client_unique_code_1` set** (all 62
   stock owners have it; the same field Studio's `check_partner_code` uses). Implemented: required-warehouse
   for coded clients, immutability once history exists (bypass: context flag or `multi_wh_admin`), and the
   cross-warehouse merge block.
4. ✅ **⤷ FINAL DESIGN (user decision, 2026-07-04): groups dropped entirely — GLOBAL record rules.**
   Record rules were pulled forward from Phase 2 AND simplified: no security groups, no per-warehouse
   groups. `security/multi_warehouse_rules.xml` ships **global** `ir.rule`s (apply to every internal user)
   scoping stock.picking, stock.picking.type, stock.quant, stock.move, stock.move.line, stock.location,
   stock.warehouse, the PKR ledger, pallet.series.audit(+line), stock.quant.history(+snapshot), and
   res.partner. The domain reads `user.allowed_warehouse_ids` — a plain editable M2M on res.users —
   with two escape hatches: **empty list ⇒ unrestricted** (admins/back-office + the rollout lever) and
   **warehouse-less records stay visible** to everyone. §2.3 (groups) is superseded/obsolete; §2.4's table
   is superseded by the shipped rules file. C1 **implemented (pending staging validation)**.
5. ✅ `warehouse_ids` optional filter added to both report wizards (empty = all; PKR wizard filters the record
   domain; occupancy wizard filters snapshot-path history + passes `warehouse_ids` to the SQL path, which
   scopes its internal-location set — deep replay scoping arrives with the Phase 2 snapshot rewrite).

Also delivered: `TransactionCase` suite (`vifel_multi_warehouse/tests/`, 13 tests + TESTING.md) and the
Studio package `ai_context/STUDIO_PHASE1_PACKAGE.md` (reference scan: all archive candidates unreferenced;
SA#513 patch; warehouse-safety inventory of the live Studio layer — SAFE/NEEDS-SCOPING classification).

**Test gate**: existing single-warehouse deploys keep working unchanged. CI smoke-tests every wizard, RR/WR validation, audit log creation, snapshot generation.

### Phase 2 — Data Scoping (medium-risk, where regressions hide)

Goal: convert per-warehouse fields into enforced isolation.

1. Activate the **record rules** (§2.4). Roll out gradually: enable for `pallet.series.audit` and `stock.quant.history` first (read-only models), then for `stock.picking` / `stock.quant` / `stock.move.line`. Use feature flag in `ir.config_parameter` so you can disable per-rule if regressions appear.
2. Fix **per-warehouse sequences** (§2.2) — update all 4 call sites listed in H6/H7.
3. Fix **hardcoded package lookups** (H1): change `'GENERIC METAL PALLET'` to a per-warehouse config (a related field on `stock.warehouse.bf_pallet_package_id`).
4. Fix **silent-failure domain filters** (H2, H3, H4, H5): replace blank fallbacks with assertions or `raise UserError("Warehouse not configured")` so misconfiguration is loud.
5. Convert **snapshot generation** to per-warehouse (C3 / C4). Two options:
   - **Per-warehouse cron**: loop over warehouses inside `_cron_generate_daily_snapshot`; create one snapshot per warehouse per day. `MAX_SNAPSHOTS` becomes per-warehouse.
   - **Per-warehouse `_generate_stock_quant_history`**: add a `warehouse_id` parameter and filter the move-line query by `('location_id.warehouse_id', '=', warehouse_id)` AND `('location_dest_id.warehouse_id', '=', warehouse_id)` — but careful: inter-warehouse transfers will need both warehouses to record it.
6. Add a **warehouse pre-check helper** on `res.partner` (e.g. `_get_warehouse() → stock.warehouse`) that raises a `UserError` if the field is unset. Use it everywhere `partner.x_studio_warehouse.id` is read raw.
7. Update `pallet.series.audit.log_event()` to derive and store `warehouse_id` from `picking_id` for every new row (so existing audit lookups remain by picking, but the new field exists for searching/filtering).

**Test gate**: install in a 2-warehouse test DB; run a script that creates an RR in WH-A and verifies a WH-B user cannot see it, the audit log, the snapshot row, the kilos record, etc.

### Phase 3 — UX, Reports, Polish

Goal: surface the warehouse cleanly to users and remove confusion.

1. Add warehouse columns / group-by filters to all custom list/search views (M3, M4, M5).
2. Default report wizards (`pkr_report_wizard`, `occupancy_report_wizard`) to the user's `default_warehouse_id` when opened; restrict choices to `allowed_warehouse_ids`.
3. Add a **warehouse switcher** to the navbar (Odoo's company switcher can be cloned to a "warehouse switcher" using `user.with_context(default_warehouse_id=...)`).
4. Refresh the OWL **Pallet Series Audit timeline dashboard** to display the warehouse name in the header.
5. Document operations:
   - Onboarding a new warehouse (steps: create `stock.warehouse`, set `x_studio_warehouse` on partners, create picking types, create per-warehouse sequences, assign users).
   - Migrating an existing partner from WH-A to WH-B (what to flush in the audit log, what to do with in-flight RRs).
6. Optional but recommended: introduce a **per-warehouse cron schedule policy** so backfill / cleanup crons can run at warehouse-local times once you have warehouses in multiple TZs (H13).

---

## 4. Migration / Data-Backfill Plan

Order matters — run these in sequence in a staging DB first.

1. **Pre-flight**: take a full PG dump.
2. Assign every existing `res.partner` (customer) a `x_studio_warehouse` if missing. Use the dominant warehouse by RR history as a heuristic. Manually correct edge cases.
3. Backfill `warehouse_id` on:
   - `pallet.series.audit` and `.line` ← from `picking_id.picking_type_id.warehouse_id`
   - `stock.quant.history` ← from `location_id.warehouse_id`
   - `stock.quant.history.snapshot` ← **regenerate per warehouse** (delete current snapshots, run the new per-warehouse generator for the last 60 days per warehouse). Heavy operation, run off-hours.
4. Re-issue sequences with per-warehouse prefixes; renumber existing `name` fields is **NOT** advised — leave history as-is, start fresh per warehouse going forward.
5. Assign each existing user to one or more warehouses via `allowed_warehouse_ids`. Default policy: ops users get their home WH; admin users get all.
6. Enable record rules. Watch logs for `AccessError` spikes — fix attribution issues found.
7. Verify the BA 6 server action and SA #347 still operate per-warehouse correctly. May need to clone the server actions per warehouse (Odoo Studio).

---

## 5. Test Plan (high-level)

Tests should run in a 2-warehouse staging DB (WH-A + WH-B) with one user assigned to each warehouse only.

- **Isolation tests**: WH-A user cannot read WH-B's `stock.picking`, `stock.quant`, `pallet.series.audit`, `stock.quant.history`, `pallet_kilos_record_model` rows.
- **Pool collision test**: WH-A and WH-B both have a partner with `x_studio_client_unique_code_1='ACM'`. Generating series in WH-A should not interfere with WH-B's counter or pool.
- **Snapshot test**: cron generates 2 snapshots per day (one per warehouse). Backfill stops only when both warehouses are filled.
- **Report test**: WH-A user opens pallet-monitoring report — sees only WH-A data. Multi-WH admin opens the same report — sees all by default.
- **Sequence test**: adjustment-form numbers don't collide across warehouses.
- **BF test**: WH-A's "GENERIC METAL PALLET" replacement is found correctly when validating a BF RR; WH-B's separate BF package is found correctly.
- **Negative tests**: a partner without `x_studio_warehouse` raises a clear `UserError`, not a silent empty domain.

---

## 6. Open Questions for Stakeholders

**Still open:**

2. **Backwards compatibility for historical reports** — when a multi-WH admin runs a report covering pre-migration data (before `warehouse_id` was backfilled), should rows with `warehouse_id IS NULL` be shown, hidden, or attributed to a "Legacy" pseudo-warehouse?
3. **Inter-warehouse transfers** — are these expected? If yes, they need a special record-rule exception so both warehouses can see the same picking from their side. *(Contact-per-warehouse policy suggests NO — goods moving between warehouses would be a WR at one + an RR for the other warehouse's contact — but confirm.)*
6. **`MAX_SNAPSHOTS = 60` becoming per-warehouse** — does that mean 60 days per warehouse (60 × N total storage), or 60 days globally with the cron picking which day to snapshot?

**Answered:**

1. **Studio server actions** *(answered 2026-06/07)* — SA#347 is deprecated/unwired (M9); the 25 active automation rules stay **global** and derive the warehouse from the record they fire on (M8). No per-warehouse cloning; new rules must follow the derive-from-record pattern.
4. **Timezone (H13)** *(answered 2026-07-04)* — both existing warehouses (Meycauayan, Tagoloan) are in the Philippines → `Asia/Manila` holds for the current roadmap. Add the per-warehouse TZ field opportunistically, default Manila.
5. **Pool defense-in-depth (C2)** *(answered 2026-07-04)* — resolved by the **contact-per-warehouse policy**: one Contact exists in exactly one warehouse; a client transacting with a second warehouse gets a separate Contact there. Pool stays on `res.partner`; enforce the policy with a constraint instead of re-keying the pool.
7. **Partner record rule** *(answered 2026-07-04)* — clients are **fully partitioned** per warehouse (each warehouse has its own Contact). Rule domain `[('x_studio_warehouse', 'in', user.allowed_warehouse_ids.ids)]` for customer partners is the intended end state; cross-warehouse visibility is not required.

---

## 7. Estimated Effort (rough order of magnitude)

| Phase | Eng days | Risk |
|---|---|---|
| Phase 1 (foundations) | 4-6 days | Low |
| Phase 2 (data scoping + record rules + snapshot rewrite) | 10-14 days | Medium-High |
| Phase 3 (UX, reports, docs) | 4-6 days | Low |
| Migration + staging validation | 3-5 days | Medium |
| **Total** | **~21-31 days** | |

Most of Phase 2's risk is concentrated in the **stock.quant.history snapshot generator** (C3/C4) and the **record-rule activation** — both have wide blast radius and need staged rollout with feature flags.

> **⚠️ Priority note (2026-07-04)**: `Tagoloan` (warehouse T) is already provisioned in production (picking types + locations exist, no operations yet). **Phases 1 and 2 should be completed and validated before the first Tagoloan client is onboarded** — after that point, every unfixed 🔴/🟠 item becomes live cross-warehouse exposure rather than a theoretical risk.

---

## 8. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> This is a living planning document. It will lose accuracy as the migration proceeds — every fix removes an item from the vulnerability table, and every new feature may add to it. Whenever you modify this codebase or the user reports that requirements have shifted, update this document in the **same change**. Specifically:
>
> - **A vulnerability is fixed** → strike it through in §1 with the date and PR/commit reference; do not delete it (history matters for the audit trail). When a whole risk tier empties, collapse the table.
> - **A new vulnerability is discovered** → add it to the appropriate risk tier in §1 with file:line references.
> - **A model gets a new `warehouse_id` field or a record rule is enabled** → update §2 and §3 to reflect what's now done vs. pending.
> - **Phase 1 / Phase 2 / Phase 3 completion** → mark phase as `✅ DONE` in §3 with date.
> - **Stakeholder answer to an open question** → move it out of §6 into the relevant section as a decision; keep an "Answered" subsection in §6 with the date.
> - **Effort estimates revised** → update §7 with the new numbers and a note explaining why.
>
> Keep the tone analytical and concrete. Always cite file:line when adding a finding. Use the risk legend in §1 consistently. Update the **Last updated** date at the top each time. If a section becomes uncertain, mark it `⚠️ NEEDS VERIFICATION` rather than removing it.
>
> When the migration is complete, **do not delete this document** — convert it into a post-mortem with a final "lessons learned" section so future warehouse onboardings can use it as a checklist.
