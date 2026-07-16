# VIFEL Session Handoff

_Last updated: 2026-07-14. Repo: `elyon-github/vifel-20250717`. Debug DB: `vifel_07_12_2026`
(Postgres localhost:5432, openpg/openpgpwd). Odoo 17 Enterprise, runs via nodemon
(`python odoo-bin -c odoo.conf`), NOT the Windows service._

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
| `MAIN` | `129650a` | Production. UNTOUCHED, always. |
| `client-trial` | `b2fb684` | All session work + ALL FOUR manifest versions PINNED to MAIN's (see §4/§5) |
| `consultant-test` (lowercase) | `15465c4` | Rehearsal merge of the PRE-pin client-trial — STALE, needs re-merge |
| `Consultant-test` (capital) | `ac374a4` | User's own rehearsal merge (17:42 Jul 14) |
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

**Working tree: 3 files modified, NOT committed** (user commits under own authorship):
see §3. Everything else committed through `0a291aa`.

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
