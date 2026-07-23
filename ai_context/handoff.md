# VIFEL Session Handoff

_Last updated: 2026-07-23. Repo: `elyon-github/vifel-20250717`. Debug DB: `vifel_07_21_2026`
(Postgres localhost:5432, openpg/openpgpwd). Odoo 17 Enterprise, runs via nodemon
(`python odoo-bin -c odoo.conf`), NOT the Windows service.
**Business rules, per-client special cases, and hard-won learnings live in
`BUSINESS_CONTEXT_AND_LEARNINGS.md` — read it before touching counting, voids, or
client-facing material.**_

## 1. Goal

Make the VIFEL pallet/kilos ledger provably accurate and keep it that way:
fix every identified drift source (adjust-to-0, package swaps, WR races, re-owned
returns, void/unvoid tangles), enforce pallet-series integrity (one series = one
physical pallet) across the correction workflow, and add a permanent Health Monitor
so future drift surfaces within a week instead of at a billing dispute. Secondary:
rehearse the client-trial → MAIN merge safely on disposable branches, with the hard
rule that **MAIN is never written by the assistant — reads only**.

## 2. Current State

**Git (remote):**
| Branch | Tip | State |
|---|---|---|
| `MAIN` | `017ba7e` | Production (user pushed it themselves). UNTOUCHED by assistant, always. Has moved several times since 2026-07-17 (`d8762a3` → `d6753c2` "Merge consultant-test into MAIN" → `017ba7e`) — re-verify with `git ls-remote` rather than trusting this row. |
| `client-trial` | `91e1c18` | **Update 2026-07-23 — two new commits:** `10f37e0` (inventory-apply perf root cause + `vifel_utility_tools` module + SA paste files) and `91e1c18` (three module fixes: return-RR source location, Pallet Breakdown grouping, FastEncodeRR PSI flicker). See §8 below. Manifest versions still PINNED. Earlier state follows: All session work + ALL FOUR manifest versions PINNED to MAIN's (see §4/§5). Latest adds: **WR/RR PDF pallet count AND the PKR withdrawn count now dedupe by (pallet #, PSI)** — opening-balance pallets accidentally carrying several PSIs count once per PSI (each PSI is a real pallet; the shared pallet # is the import accident). Ledger change is the LIVE loop only — Re-sync's counted_out/wc_n stay per-package on purpose (per-PSI there would flag spurious split culprits; the wipe-and-rebuild residual absorbs the interim gap and zeroes once the pallet clears). Affected on next recompute/Re-sync: 6 WRs of CHEF BUDDY/FOSTER FOODS/MEATS SUPREME/TWINFISH (+1..+2 each). Transacted Pallet Count on the picking still physical. evidence-policy Re-sync (unbacked residuals stay UNRESOLVED — truth retention), M/WR/06825 void-of-return fix (exemption on BOTH self and record), void-mirror guards re-enabled, WR per-pallet report aligned with picklist order (`9ac8f7e`), **RR per-pallet report now uses the same PSI-anchored sort** (all operation types share `get_picklist_sorted_move_line_ids`; prev-row description grouping unified; BF unaffected — no PSI → plain base order), full ai_context audit + BUSINESS_CONTEXT_AND_LEARNINGS.md. NOTE: branch `CR2-test` (from `be0c9a9`) carries the built Client-Specific Requirement Enhancement, pushed `25a29a0`. |
| `CR2-test` | `ac053e7` | Client-Specific Requirement Enhancement. Local branch holds the **v2 rebuild** as a standalone module and is DIVERGED from this remote tip — the two are different lines of work, so check `git rev-list --left-right --count` before any push here. Never force-push without deciding deliberately. |
| `consultant-test` (lowercase) | `691b6a7` | Moved since 2026-07-17 (`15465c4`) — user's own work. |
| `Consultant-test` (capital) | `4a21391` | Moved since 2026-07-17 (`ac374a4`) — user's own work. |
| `main` (lowercase) | `d2136dc` | Untouched, never analyzed |
| tag `backup/consultant-test-2026-07-14` | `7c99e3f` | Preserves consultant's 18 commits incl. UNREVIEWED "Added new Client Requirements" (`b575766`) |

Case-variant branches are DISTINCT. Never create local branches of case-twin names on
Windows (NTFS ref collision) — push remote-to-remote by SHA instead.
Push transport: machine SSH key is a READ-ONLY deploy key; pushes work only via
`git push https://github.com/elyon-github/vifel-20250717.git ...` (Windows credential manager).

**Debug DB `vifel_07_12_2026`:** `multiple_relocation` + `pallet_kilos_record_model`
upgraded; `vifel_health_monitor` INSTALLED with committed baseline (~176 open findings;
user already ran Re-sync + neutralized 3 orphan RRs here). Health dashboard live under
Inventory → Reporting → System Health (admin-only).

**Working tree: clean** (only the untracked ESII .docx template). Everything committed
and pushed through `d6591bf` on client-trial.

## 3. Active Files

**All session work is committed and pushed to client-trial** (only the ESII .docx template
stays untracked). Latest additions beyond the earlier list:
- Void-mirror guards: linked void equivalents (void WRs / void returns) block Client/Owner
  changes, KG/Packaging/Packs edits on lines, and adding/removing lines AND operations —
  with exemptions for the void generators, unvoid cleanup, and validation
  (`stock_picking.py`, `stock_move.py`).
- Manual Return Packages wizard no longer appends onto void returns
  (`ReturnPackageWizard.py::_find_existing_return`) — manual returns get their own RR.
- `owner_mismatch` health check (3 angles) + `check_owner_mismatch` registry record.

**Paste files ready in `ai_context/` (DB-side, user pastes in Studio):**
- `sa297_race_fix_reserved_qty_lock.py` → SA#297 (AR#6) — WR pallet-race lock
- `sa317_rr_scoped_requant.py` → SA#317 (AR#15) — RR-only, reference-matched re-update
  (+ AR#15 "Apply on" domain: `[("state","=","done"),("picking_type_code","=","incoming")]`)
- `sa317_BACKUP.txt` — verbatim backup of prod SA#317
- `sa_clean_picking_reset.py` → NEW SA "Clean Picking (Reset to Empty Draft)" — Actions-menu
  reset of unvalidated pickings (recycle PSIs on normal RR w/ stocked-guard pool repair;
  never on returns/WR/BF; frees reservations; severs links both ways; dynamic x_studio
  wipe). Tested 15/15 on debug DB. Restrict to Inventory Super Admin when creating.
- Also parked: hardened AR#17/SA#333 2nd_uom reducer (HEX-015573 fix), SA#478 rev 2

**Test scripts (rolled-back odoo-shell suites, ~55 checks total):** scratchpad
`cascade_test.py`, `gc_group_test.py`, `group_guard_test.py`, `monitor_test.py`
(session temp dir — recreate from git history of this handoff if lost).

## 4. Changes Made

**Ledger accuracy (pallet_kilos_record_model):**
- Re-sync Pallet Counts button: rebuilds received/withdrawn/adjustments per owner,
  events + residual anchor, rebuilds correction audit history; idempotent; perf-tuned
  (one balance rebuild per partition).
- Adjustment audit-trail model (`...adjustment.entry`) + one2many on PKR form.

**Correction wizard (multiple_relocation):**
- Adjust-to-0 releases pallet + posts −1 via record reference (fallback latest-in-partition).
- Package-change pallet delta: split +1 / merge −1 / transfer 0.
- PSI group-move cascade: changing one quant's Pallet # auto-includes all same-series
  siblings, live warning banner, contradiction + reserved guards; BF exempt.
- All-or-nothing per-series approval/rejection guard (anti-split, itemized errors).
- Zeroed quants (KG+packs+units = 0) deleted immediately after apply (audit survives via SET NULL).
- "Adjustment Approvers" group (seeded: Dojello, user 66) drives approve/reject rights
  + notifications (old code notified an arbitrary stock manager).

**Void/unvoid (multiple_relocation):**
- Unvoid neutralizes unvalidated void children: frees reserved bins/pallets, deletes
  moves/lines WITHOUT recycling PSIs to the pool, unbinds + wipes Source/Destination/
  Record Remarks/Other Remarks → plain empty draft. Permanent-void guard fixed to cover
  both link directions (return_id was never checked before).
- Owner-change guard: partner/owner edits blocked on pickings linked as returns
  (unlink-first warning) — closes the M/RR/03721 re-owned-return source. (UNCOMMITTED)

**Picklist:** same-PSI lines always print contiguous (anchored at first appearance);
backend-only in `get_picklist_sorted_move_line_ids`.

**Health Monitor (`vifel_health_monitor`, new module):** 20 read-only checks across
Ledger/Identity/Stock/Process/System incl. owner-mismatch (3 angles; caught M/RR/03721
+ 4 more re-owned returns); findings with auto lifecycle (new→open→resolved) + Ignore;
check-card dashboard; weekly cron Sun 19:00 PH; admin-only; notifies Inventory Super
Admin members on NEW findings only. Full sweep ≈ 2s.

**Git operations (all MAIN-read-only):** `Consultant-test` and `consultant-test` each
reset to MAIN copies (backup tag first); rehearsal merge client-trial→consultant-test
pushed (`15465c4`, ZERO conflicts); manifest versions pinned to MAIN (`0a291aa`) to stop
Odoo.sh auto-updating on merge builds.

## 5. Failed Attempts

- **SSH push → "denied to deploy key"**: the repo's SSH identity is read-only. Fix:
  HTTPS + credential manager. Don't waste time on ssh-agent.
- **Odoo.sh build failure on merge** ("Updating: pallet_kilo… → fail"): platform
  auto-updates any installed module whose manifest version changed. Fix applied in TWO
  passes: versions pinned to MAIN's exact strings for multiple_relocation (`0.1`),
  pallet_kilos_record_model (`0.1`), pallet_series_audit (`17.0.1.0.0`) in `0a291aa`,
  and stock_quant_history (`17.0.1.0.0`) in `b2fb684` — the first sweep MISSED it
  because that manifest uses DOUBLE quotes ("version") and the grep matched single
  quotes only. Lesson: version-diff manifests quote-agnostically. CONSEQUENCE of
  pinning: platform DBs get no new columns until a manual module update —
  `pallet_series_audit` AND `stock_quant_history`/snapshot views will crash there until
  updated once. Real prod deploy must RE-BUMP all four versions so upgrades + the
  stock_quant_history warehouse migration fire deliberately.
- **Re-sync v1 was too slow / failed first-try** (timeout+rollback): fixed by removing
  a dead per-line search and doing ONE balance rebuild per partition.
- **Entry-side re-sync events**: +1 "restock" derivation produced 594 false positives —
  removed; the residual anchor absorbs that side by design.
- **`-X theirs` force-merge idea**: rejected — it blends non-conflicting consultant
  hunks instead of making client-trial the source of truth. Use `-s ours` if a pure
  copy is ever wanted.
- **Monitor test M5 "failure"**: expected 5 orphan voids, found 2 — data had legitimately
  changed (user neutralized 3 RRs); check was right, expectation stale.

## 6. Next Steps

1. **Re-merge `consultant-test`**: reset to MAIN copy (`129650a`) and merge the PINNED
   client-trial (`b2fb684`) so the platform build passes without auto-updates.
2. **User commits the 3 uncommitted files** (own authorship, no co-author line).
3. **Salvage review** of `backup/consultant-test-2026-07-14` — especially `b575766`
   "Added new Client Requirements" and the CI stuck-build fixes; cherry-pick what's real.
4. **Production deploy** (full table in memory `vifel-prod-deploy-checklist`):
   backup → merge → RE-BUMP the 3 pinned versions → upgrade 4 modules
   (multiple_relocation, pallet_kilos_record_model, stock_quant_history ≈37s migration,
   pallet_series_audit) → install vifel_health_monitor (NOT vifel_multi_warehouse) →
   restart → paste SA#297 + SA#317 + AR#15 domain → run Re-sync ONCE → monitor: Run Now,
   set `vifel_health.stamp_cutoff` = deploy date, set `watchdog_cron_ids` to prod's
   snapshot cron, Ignore known baseline findings → smoke tests (RR/WR validate, picklist
   grouping, cascade banner, return owner-change block, void→unvoid neutralize).
5. **Parked decisions**: AR#17/SA#333 reducer paste (HEX-015573 — recommend soon);
   Studio archives #502/#394/#395 (±#506 hardcoded 2280); SA#513 + vifel_multi_warehouse
   install (Tagoloan phase); health-check B6 "stuck 2nd UOM signature" (v1.1 after
   baseline tuning); the 94 split-PSI merge campaign (after deploy + Re-sync).
6. **Client-Specific Requirement Enhancement — fully planned, AWAITING GO SIGNAL (§7)**.

## 7. READY-TO-BUILD: Client-Specific Requirement Enhancement

_Design settled interactively 2026-07-16/17 with the user; client-facing design page +
PDF delivered (artifact `ef072cc7…`, `Downloads/Vifel-Pallet-Merge-Enhancement.pdf`).
Client timeline: dev starts Mon Jul 20, Internal Testing Mon Jul 27, UAT Tue Jul 28,
go-live Wed Jul 29 (committed latest Fri Jul 31). Estimate: avg 8.60 mandays.
**DO NOT implement until the user explicitly says go.** Update this section per phase._

### 7.1 Feature summary (all decisions final)
- **Client Profile** — new "VIFEL Configuration" notebook tab on partner form (extend
  existing inherit `multiple_relocation/views/views.xml:372`). Checkbox cascade, all OFF
  by default, progressive disclosure:
  - `vifel_can_merge_pallets` "Can Merge Pallets" (master switch)
  - `vifel_multiple_pallet_support` "Multiple Pallet Support" (mode switch, EXCLUSIVE):
    OFF → Fixed Merge Pallet: `vifel_fixed_package_id` + `vifel_fixed_psi`, both-or-neither
    constraint (Wonder Meats: R 5666 / WMF-00230, offered forever);
    ON → PSI Types o2m table (fixed fields hidden)
  - `vifel_include_regular_pallets` "Include Regular Pallets" (visible under Multiple only)
  - `vifel_show_lot_no` "Show Lot No." (independent of merging)
- **PSI Types** — new model `vifel.psi.type`: partner_id, name (seeded = prefix), prefix,
  next_number (default 1, editable), pool (Json ints). Unique (partner, prefix). Auto-seed
  MDGM/BOC/TDMG/SDMG on Multiple flipping ON (in write/create, NOT onchange). Format
  `prefix-zfill(6)` → SDMG-000001. Draw: pool smallest-first, else counter++. Special
  numbers never mix with the client's normal pool (prefix-aware routing).
- **Merge** — per-line button in Pallet Breakdown → new transient `pallet.merge.wizard`.
  Available iff: client merge-enabled AND incoming AND non-BF AND not return AND not done.
  Fixed mode: pinned package pre-selected. Multiple mode: stocked packages (qty>0, internal,
  same owner, same warehouse, non-BF) with PSI prefix ∈ client types; + regular stocked if
  Include Regular; fallback regular when types list empty. Window shows target PSI/location/
  KG/2nd-uom ("full" = Documentation Staff judgment, no capacity rule).
  Confirm: adopt target's PSI (single distinct PSI required; empty pinned fixed package →
  profile `vifel_fixed_psi`), location_dest = target quant location, `is_pallet_merge=True`,
  recycle the previously drawn PSI (only if unused elsewhere in picking), free previously
  reserved empty pallet/location, write with `skip_pallet_series_sync=True`, do NOT stamp
  reservation fields on the stocked target, chatter on RR ("…pallet count not incremented").
  "Create new special pallet" path (Multiple; also first-of-type / current-full): pick type
  → draw_number() → user picks EMPTY pallet + location → plain line, counted +1.
- **Un-merge**: `stock_move.py` write override — package changed away on flagged line
  without merge context → clear flag, do NOT recycle adopted PSI, existing
  `original_pallet_series_id` restore machinery runs.
- **Lot No.** — `client_lot_no` (Char, copy=False) on stock.move.line + stock.quant;
  picking compute `show_client_lot_no`; gated column in Pallet Breakdown tree + FastEncodeRR
  wizard; stamped line→quant post-`button_validate` (match product/location/lot/package/
  owner; last-write-wins documented); optional column in quant trees.
- **PKR counting** — merged lines: pallets +0; Weight/Quantity/Heads still count
  (sums at `pallet_kilos_record_model/models/models.py:145-152` untouched).

### 7.2 Code anchors (explored, verified)
- Pool logic `multiple_relocation/models/models.py:17-113` (push_unused_pallet :23,
  get_smallest :45, generate_new :64, get_by_id :77); audit wrapper in
  `pallet_series_audit/models/res_partner.py` (super() chain must stay intact).
- Prior merge art: `stock_move.py:706-943` write override; `FastEncodeRR.py:624-663`
  `_sync_pallet_series_and_location`.
- Guards to relax ONLY for flagged lines: `FastEncodeRR.py:16-66`
  `_validate_result_package_availability`. Empty-pallet dropdown domains (`views.xml:992`,
  `FastEncodeRR.xml:40`) stay unchanged — merge has its own wizard.
- Recycle paths (`FastEncodeRR.py:184-201`, `:344-374`, `stock_move.py:851-858`) all funnel
  through `push_unused_pallet` → harden THERE: prefix-aware routing to type pools + global
  guard "never recycle a PSI present on stocked quants". Same for `get_pallet_series_by_id`.
- PKR: live received loop `models.py:214-217`; Re-sync counted_in `:1164-1173`; residual
  rc_n `:1601-1611` → all three get `('is_pallet_merge','!=',True)` / skip. Withdrawn/
  returns/OB/void unchanged (copy=False keeps void mirrors unflagged).
- ACLs: add `vifel.psi.type` + `pallet.merge.wizard` to
  `multiple_relocation/security/ir.model.access.csv`.
- PSI→quant stamping is a DB automation — adopted PSI flows automatically. NO new SA/AR.

### 7.3 Build phases
- **A (Mon–Tue): profile + types + Lot No.** — partner fields/constraint; `models/vifel_psi_type.py`
  (draw_number/take_number/give_back with stocked-guard); seeding hook; prefix-aware routing
  in push_unused_pallet/get_pallet_series_by_id; Lot No. fields + stamping + columns;
  VIFEL Configuration tab; ACLs.
- **B (Wed–Thu, risk center): merge core** — is_pallet_merge field+column; PalletMergeWizard
  (+view+button+availability compute); confirm logic; create-new-special path; guard
  exemptions; FastEncodeRR locks flagged lines; un-merge handling.
- **C (Thu–Fri): PKR** — skip flagged lines in the three counting spots; confirm void/return
  paths unchanged.
- **D (Fri + Mon Jul 27): tests + docs** — shell driver `merge_test.py` (commit-only-if-all-
  pass): fixed/multiple merge e2e; seeding idempotent; pool-first draw; give_back routing
  (deleted line/un-merge → own type pool, never normal; stocked never recycled, all 3 paths);
  Include Regular widens; empty types fallback; cross-owner/BF/return blocked; un-merge
  restore; Lot No. flow; void/unvoid merge RR; picklist contiguity; health checks
  pallet_drift/kg_pack_drift/split_psi = 0; full 72-owner Re-sync sweep 0 regressions.
  py_compile; local commits per phase (user authorship, NO push unless told; manifest
  versions stay pinned — re-bump at deploy only).

### 7.4 Deploy additions (on top of §6.4 checklist)
- Upgrade multiple_relocation + pallet_kilos_record_model.
- Prod profiles: Wonder Meats = Can Merge ON / Multiple OFF / pin R 5666 + WMF-00230;
  Consistent = Can Merge ON / Multiple ON (types auto-seed); Show Lot No. per client.
- Optional: add Lot No. column to the Studio "Inventory Overview" action DB-side.

---

## 8. Update 2026-07-23 — inventory-apply performance, new module, three UI/data fixes

_Debug DB for this work: `vifel_07_21_2026`. Commits `10f37e0` and `91e1c18` on
client-trial. Every measurement below was taken in odoo-shell inside rolled-back
transactions unless stated otherwise._

### 8.1 Inventory Adjustment "Apply" was unusable past ~800 quants (root cause + fix)
~15 **stored** `x_studio_` computes on `stock.move.line` run
`for quants in location.quant_ids:` for lines with **no picking**. A POSITIVE inventory
adjustment sources from the virtual "Inventory adjustment" location (`loc#14`, 23k+ quants
and growing), so every created line scanned all of them, ~15 times over.
**Measured 1226 → 109 ms/line = 11.3x** (~16.4 min → ~1.5 min for 800 quants),
correctness 30/30. Profiler: ~60 s of an 84 s apply in `flush_all → _recompute_all`,
~70 s cumulative in `safe_eval`, **only ~1.8 s in SQL** — a CPU/ORM problem, not a query one.
Controlled proof: positive adj (source loc#14) 1330 ms/line vs negative adj (source = a
normal storage location) 149 ms/line.

- Fix + per-field paste code: `studio_computes_inventory_apply_perf_FIX.md`,
  `studio_move_line_computes_{BACKUP,REVISED}.txt`,
  `sa_apply_move_line_picking_guard.py` (server action, idempotent, self-backing-up).
- **CORRECTION to the first diagnosis:** BA#42/SA#432 was blamed initially; measured in
  isolation it is only **~6% (1.1x)**. Worth applying (`sa432_line_id_picking_scoped.py`)
  but it is NOT the cure.
- **STILL NOT FIXED:** the same flaw in two Python computes,
  `multiple_relocation/models/stock_move.py` `_compute_container_number` (~447) and
  `_compute_x_studio_building_dropped` (~461).

### 8.2 New module `vifel_utility_tools`
Auto-creates products from the `NAME (BRAND)` convention during `stock.quant` import,
gated on the `import_file` context (inert everywhere else). **Never modifies an existing
template** — every unmatched name gets a new one, so an unbranded product can never be
renamed into a branded one (Odoo reuses the single variant when an attribute line has one
value; writing two values at once ARCHIVES the original — both measured). New templates
inherit catalogue defaults incl. `tracking='lot'`. 19/19 shell tests.
Spec: `vifel_utility_tools_PLAN.md`; suite: `utility_tools_tests/`.
NOTE: standard `name_create` is already broken on this DB (computed `name` →
`NotNullViolation`), which is why the import's "Create new values" option never worked.

### 8.3 Three module fixes (`91e1c18`)
- **Return RR source location** — `_create_new_return_with_packages` builds the RR with
  `picking_id.copy()` and never overrode `location_id`, so void-created returns inherited
  the WR's INTERNAL source ("M"). New `_return_source_location_id()` used by both creation
  paths (also replaces a hardcoded id `4`). Verified Partners/Vendors, 4/4.
- **Pallet Breakdown grouping crashed** — the Detailed Operations trees set
  `default_order="x_studio_, ..."`; Odoo 17 `read_group` rejects order terms that are not a
  groupby field or aggregate. `read_group` override on `stock.move.line` drops invalid
  terms; ungrouped ordering untouched. 12/12.
- **FastEncodeRR PSI flicker** — `_resolve_series_for_unique_line` excluded the line by
  `{self.id}`, but in an onchange `self.id` is a `NewId`, so the line never excluded itself,
  judged its own original series "claimed", and previewed a fresh counter number
  (7S-000049) that snapped back to 7S-000044 on save. Now also matches the `_origin` id.
  Display-only — no pool number was ever consumed.

### 8.4 Health-monitor findings investigated (NOT yet fixed)
- **HEXAGON KG −125 — CLOSED.** `M/WR/06655` recorded 500 kg but removed 375; a correct
  325→200 correction was applied against a snapshot its own conflict check had flagged
  `deleted`; `M/WR/06727` then took the full 200 → quant went to −125. The ledger was
  right all along; the check's `quantity > 0` filter hid the negative and made it look like
  ledger drift.
- **Pallet drift** — the ledger credits receipts per **pallet #** (`models.py:227`) but
  debits withdrawals per **(pallet #, PSI)** (`models.py:191`). Any pallet # carrying 2 PSIs
  (the OB import accident) is credited once and debited twice → permanent −1.
  MEATS SUPREME is exactly this. HEXAGON's −2 is different and REAL: two phantom pallets
  (`NP 1324`, `NP 1209`) that got stock back via a direct `package_id` write with no move
  line. APENA is partly each and still not fully explained.
- **Health checks measure differently from the ledger** — `_check_pallet_drift` counts
  `DISTINCT package_id` (should be `(package_id, PSI)`), and both drift checks filter
  `quantity > 0` so negative quants are invisible. A dry-run showed naively switching the
  unit alone makes things WORSE (2 new findings, 0 resolved) — fix the received side first.
- **The underlying leak:** quantity edits on **done** documents re-apply stock with no
  unlock flag required (`x_studio_edit_record` was False on the G 602 edit).

### 8.5 Open / next
1. Two Python computes in §8.1 still unguarded (perf fix ~90% applied).
2. `_neutralize_void_child` does not clear `x_studio_last_operation_source_document`, so an
   unvoided parent leaves the child still pointing at it (SA#483 DOES clear it — the two
   cleanup paths disagree). One line in `unbind_vals`; NOT applied.
3. Stale drafts `M/RR/04839`–`04842` still carry `src=M` (created before the fix).
4. PSI `25820` sits in 168 ENTERPRISES' pool from an SA#483 run made before the
   return-guard ordering was fixed.
5. Sweep `quantity` vs `reserved_quantity_on_validation` across all WRs to size whether
   the post-validation edit problem is systemic or a one-off.

### 8.6 Environment
`openpyxl==3.1.2` installed into BOTH Odoo 17 interpreters
(`C:\Odoo17E\server\.venv` and `C:\Odoo17E\python`) — fixes the xlsx import error.
Caution: `nodemon.json` launches bare `python`, which on PATH resolves to
**`C:\Odoo18\python\python.exe`**; VS Code's terminal activates the `.venv` instead.
Its `-u pallet_kilos_record_log` looks like a typo for `pallet_kilos_record_model`.
