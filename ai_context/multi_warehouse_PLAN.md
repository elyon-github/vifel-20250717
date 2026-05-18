# Multi-Warehouse Migration Plan — Vulnerability Audit & Phased Roadmap

> **Scope**: All custom modules under `addons/custom_addons/consultant-test/` (except `app_common`, `app_odoo_customize`, `odoo_calculator_tool`).
> **Goal**: Treat each warehouse as **completely separate data** — isolation of clients, pallets, audit logs, ledgers, snapshots, reports, and user access — while removing the many places where the code silently assumes "one warehouse".
> **Operating assumption (confirmed with user)**: each `res.partner` (client) is assigned to exactly one warehouse via `res.partner.x_studio_warehouse`. Users are **restricted** to one or more warehouses via a new warehouse-aware security layer.
> **Last updated**: 2026-05-16

---

## 0. Executive Summary

The codebase is **half-aware of multi-warehouse**: partners carry an `x_studio_warehouse` Studio field, pickings carry `x_studio_warehouse_sh` (warehouse short-handle code), and the pallet-kilos ledger already partitions running balances by `warehouse`. But the **enforcement is missing in three areas that matter most**:

1. **No security record rules** scope any model by warehouse. Any user with model access sees every warehouse's data.
2. **Cross-warehouse reads** happen in queries that should be scoped (audit log, pallet series pool, snapshot generator, several wizards).
3. **Cron jobs and shared sequences operate globally** — one daily snapshot covers all warehouses, one sequence numbers all adjustment forms regardless of warehouse, etc.

The migration is achievable in **3 phases over a single sprint cycle** without a "big-bang" rewrite. Phase 1 (foundations) is low-risk and unblocks everything else. Phase 2 (data scoping) is where the most regressions could appear and needs careful test coverage. Phase 3 (UX + reports) is polish.

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
| C2 | `multiple_relocation` | `models/models.py:21,45,64,77` (res.partner pool methods) | Pool state (`unused_pallet_series_ids`, `x_studio_pallet_series_id` counter, `x_studio_client_unique_code_1`) lives on `res.partner` with **no warehouse partition**. | Currently safe ONLY because each partner is supposed to belong to one warehouse. If a partner is ever re-assigned or shared, two warehouses can collide on `JBL-000005`. |
| C3 | `stock_quant_history` | `models/stock_quant_history_snapshot.py:91-340` (`_generate_stock_quant_history`) | Each snapshot covers the **entire `stock.move.line` table** for all warehouses. Domain is `state=done AND date <= inventory_date AND product.type=product` — no warehouse filter. | One snapshot row mixes WH-A and WH-B quants. `MAX_SNAPSHOTS=60` is per-DB, not per-warehouse, so older WH-A snapshots get dropped by WH-B activity. |
| C4 | `stock_quant_history` | `data/ir_cron.xml` + `_cron_generate_daily_snapshot`, `_cron_backfill_snapshots` | Crons generate **one snapshot per calendar day, globally**. Backfill auto-deactivates once "all 60 days" are filled — meaning the first warehouse using it satisfies the condition for everyone. | Adding a second warehouse later won't trigger backfill for the new warehouse. |
| C5 | `pallet_series_audit` | `models/pallet_series_audit.py` (no partner/warehouse on header) | Audit header is keyed on `picking_id` only. Lookups via the smart button work, but the **menu / search views** in `views/audit_views.xml` show every warehouse's audit logs to anyone with `group_pallet_audit`. | Cross-warehouse forensic data leak. |

### 🟠 High

| # | Module | File / Line | Issue |
|---|---|---|---|
| H1 | `multiple_relocation` | `models/stock_move.py:81-82` | Hardcoded package lookup by name: `[('name', 'ilike', 'GENERIC METAL PALLET')], limit=1`. First match wins regardless of warehouse. |
| H2 | `multiple_relocation` | `wizard/stock_quant_relocation_lines.py:36` | `self.env['x_warehouse_building'].search([], limit=1)` — picks an **arbitrary** building when computing default. No warehouse filter. |
| H3 | `multiple_relocation` | `models/stock_picking.py:2376, 2391` | `("warehouse_id.code", "=", record.x_studio_warehouse_sh)` — depends on `x_studio_warehouse_sh` being filled. If unset, the domain matches nothing → empty location dropdown silently. |
| H4 | `multiple_relocation` | `models/stock_picking.py:2385` | `('warehouse_id.id', '=', record.partner_id.x_studio_warehouse.id)` — silent NPE / wrong-warehouse picks if `partner.x_studio_warehouse` is missing. |
| H5 | `multiple_relocation` | `models/stock_move.py:1108, 1186` | `('x_studio_warehouse.id', '=', record.owner_id.x_studio_warehouse.id)` — same silent failure mode as H4. |
| H6 | `multiple_relocation` + `wizard/stock_quant_correction.py:223,914,981` | Sequence code `'adjustment.form.series'` used globally. All warehouses share one numbering. |
| H7 | `multiple_relocation` | `models/stock_quant.py:387` | Sequence code `'relocate.form.series'` shared globally — same as H6. |
| H8 | `pallet_kilos_record_model` | `models/models.py:303-582` (`_recalculate_running_balances`) | Algorithm IS partitioned by `(warehouse, is_blast_freezer)` ✅ but the `manual_recalculate_all()` / `resync_all_2()` maintenance entry points iterate every warehouse with no permission check — anyone who can call them rewrites every warehouse's balances. |
| H9 | `pallet_kilos_record_model` | `wizard/pkr_report_wizard.py` | Report wizard has `partner_ids` and `building_ids` filters but **no `warehouse_ids`**. Generated reports mix data from any warehouse the user can read. |
| H10 | `stock_quant_history` | `wizard/occupancy_report_wizard.py` | Same as H9 — no warehouse filter on the wizard. Both `_action_report_snapshot` and `_action_report_sql` operate across all warehouses. |
| H11 | `stock_quant_history` | `security/ir.model.access.csv` | Only `stock.group_stock_manager` can use snapshot model — meaning every manager sees every warehouse. No per-warehouse manager role. |
| H12 | `multiple_relocation` | `models/stock_picking.py:1110,1117,1158` (`order='create_date desc', limit=1` patterns) | "Find the latest X" queries with no warehouse filter — return latest from any warehouse. Used in BF dock assignment, last-pallet lookups, etc. |
| H13 | `multiple_relocation` + `pallet_kilos_record_model` | various reports/wizards using `timezone('Asia/Manila')` / `MANILA_TZ` / `UTC+8` | Hardcoded timezone. If a future warehouse operates in a different TZ, all date math breaks. |

### 🟡 Medium

| # | Module | File / Line | Issue |
|---|---|---|---|
| M1 | `multiple_relocation` | `wizard/FastEncodeRR.py` | `transfer_id` is `fields.Integer` storing a picking ID — no warehouse derivable from it without a `.browse()`. Refactor friction for tooling that wants to know "which warehouse is this wizard for?" |
| M2 | `multiple_relocation` | `models/stock_picking.py:67,290,421,523,555,575,611,658,966,975` (many `limit=1` searches) | Most lookups assume "there's only one of these per company" — without warehouse scoping, the first match wins regardless of warehouse. |
| M3 | `pallet_kilos_record_model` | `views/views.xml` | Tree is `default_order="start_time desc"` with no warehouse group/filter shown by default. Users will visually mix warehouses unless they manually filter. |
| M4 | `pallet_series_audit` | `views/audit_views.xml` (3 menus under Inventory → Pallet Series Audit) | Menus show every warehouse's audit events; no warehouse filter chip. |
| M5 | `stock_quant_history` | `views/stock-quant-history.xml` | Search view groups by snapshot, owner, package — no warehouse group, no warehouse filter. |
| M6 | `multiple_relocation` | `models/stock_picking.py` `vifel_type_of_operation` (RR/WR/BFRR/BFWR) | Computed from `picking_type_id` — relies on operators having created the right picking types per warehouse. No safety net if multiple warehouses each have a "WR" picking type — labels collide. |
| M7 | `pallet_kilos_record_model` | `import_opening_balances_from_quants(quant_ids)` | Trusts the caller's quant selection. A user could (accidentally or intentionally) include quants from another warehouse. |
| M8 | `pallet_kilos_record_model` | `models/models.py:434-466` (BA 6 — Background Automated action) | Cited in code comments ("BA 6 fires on ALL state='done' transitions"). Server actions in Odoo Studio are global — likely fire across all warehouses without scoping. Needs Studio inspection. |
| M9 | `multiple_relocation` | Server Action #347 ("Assign Pallet Series") | Studio server action — likely operates on any RR regardless of warehouse. Audit context injection added but no warehouse check. |

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

### Phase 1 — Foundations (low-risk, no behavior change)

Goal: introduce the warehouse field plumbing and the security framework **without** activating restrictive record rules yet.

1. Add `res.users.allowed_warehouse_ids` + `default_warehouse_id` via extension in `app_common/models/res_users.py`.
2. Add `warehouse_id` (related, stored, indexed) to `pallet.series.audit`, `pallet.series.audit.line`, `stock.quant.history`, `stock.quant.history.snapshot`. Backfill via SQL migration: `UPDATE x SET warehouse_id = (resolved expression)`.
3. Add `partner.x_studio_warehouse` required-constraint **for customer partners only** (define a sql check or python constraint that allows nulls for non-customer partners).
4. Create the three security groups (`multi_wh_user`, `multi_wh_manager`, `multi_wh_admin`).
5. Add the `warehouse_ids` filter to both report wizards (Phase 1: filter is optional and defaults to "all"; Phase 3 will tighten it).

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

1. **Studio server actions (SA #347, BA 6)** — are these expected to be cloned per warehouse, or stay global with internal warehouse-aware logic added? Cloning is simpler but means more Studio bookkeeping.
2. **Backwards compatibility for historical reports** — when a multi-WH admin runs a report covering pre-migration data (before `warehouse_id` was backfilled), should rows with `warehouse_id IS NULL` be shown, hidden, or attributed to a "Legacy" pseudo-warehouse?
3. **Inter-warehouse transfers** — are these expected? If yes, they need a special record-rule exception so both warehouses can see the same picking from their side.
4. **Timezone per warehouse (H13)** — confirm if all current/planned warehouses operate in `Asia/Manila`. If yes, this stays as-is and we add the per-warehouse TZ field but default everyone to Manila.
5. **`unused_pallet_series_ids` pool on res.partner (C2)** — even though each partner is supposed to be one-warehouse, do we want defense-in-depth (move the pool to `(partner, warehouse)` key) or accept the assumption?
6. **`MAX_SNAPSHOTS = 60` becoming per-warehouse** — does that mean 60 days per warehouse (60 × N total storage), or 60 days globally with the cron picking which day to snapshot?
7. **Partner record rule** — does VIFEL want clients fully partitioned, or visible-but-read-only across warehouses (e.g. so a WH-A user can see WH-B's clients but cannot create RRs against them)?

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
