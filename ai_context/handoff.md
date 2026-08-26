# VIFEL Session Handoff

_Last updated: 2026-08-25. Repo: `elyon-github/vifel-20250717`. Debug DB: `vifel_07_21_2026`
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
| `client-trial` | `1b7f951` | **Update 2026-07-28 — two commits since `91e1c18`:** `e048502` (unvoid clears the void child's source-document pointer) and `1b7f951` by Ronafe Bula (**RR/WR PDF pallet count: the withdrawal gate now applies only to outgoing pickings** — both report counters gated every picking type on `reserved_quantity_on_validation == 0 and not same_quant_stocks_picked`, so a received pallet vanished from its RR as soon as any withdrawal was booked against its lot; M/RR/05006 printed 27 of 41. Receipts now count every distinct pallet; the (pallet, PSI) dedupe key is untouched; withdrawals unchanged. Matches `_compute_transacted_pallet_count`, which already branched on direction). Also note: branch `CR-test` carries the Clients-kanban work (`e97bd55`). Earlier state follows: **Update 2026-07-23 — two new commits:** `10f37e0` (inventory-apply perf root cause + `vifel_utility_tools` module + SA paste files) and `91e1c18` (three module fixes: return-RR source location, Pallet Breakdown grouping, FastEncodeRR PSI flicker). See §8 below. Manifest versions still PINNED. Earlier state follows: All session work + ALL FOUR manifest versions PINNED to MAIN's (see §4/§5). Latest adds: **WR/RR PDF pallet count AND the PKR withdrawn count now dedupe by (pallet #, PSI)** — opening-balance pallets accidentally carrying several PSIs count once per PSI (each PSI is a real pallet; the shared pallet # is the import accident). Ledger change is the LIVE loop only — Re-sync's counted_out/wc_n stay per-package on purpose (per-PSI there would flag spurious split culprits; the wipe-and-rebuild residual absorbs the interim gap and zeroes once the pallet clears). Affected on next recompute/Re-sync: 6 WRs of CHEF BUDDY/FOSTER FOODS/MEATS SUPREME/TWINFISH (+1..+2 each). Transacted Pallet Count on the picking still physical. evidence-policy Re-sync (unbacked residuals stay UNRESOLVED — truth retention), M/WR/06825 void-of-return fix (exemption on BOTH self and record), void-mirror guards re-enabled, WR per-pallet report aligned with picklist order (`9ac8f7e`), **RR per-pallet report now uses the same PSI-anchored sort** (all operation types share `get_picklist_sorted_move_line_ids`; prev-row description grouping unified; BF unaffected — no PSI → plain base order), full ai_context audit + BUSINESS_CONTEXT_AND_LEARNINGS.md. NOTE: branch `CR2-test` (from `be0c9a9`) carries the built Client-Specific Requirement Enhancement, pushed `25a29a0`. |
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

**Void identity guard at validation (2026-08-19, `stock_picking.py::button_validate`):**
`button_validate` auto-voided ANY picking carrying `is_void_wr` / `is_void_return`,
without checking it still reverses a voided parent, while the EDIT guard
(`_void_mirror_source`) required the flag AND a resolvable parent. An orphaned void
shell was therefore freely editable AND self-voiding. Found on **M/WR/08389**: a void
shell left over from voiding GRJM's M/RR/05176 was repurposed by staff into a real
MEATS SUPREME withdrawal (2 pallets / 1,310 kg of CHICKEN SKIN FAT, series UK-018312 /
UK-018325 received on M/RR/02131 in May, nothing to do with GRJM's 41 pallets of
SHOESTRING FRENCH FRIES, which M/WR/08439 reversed correctly). Validation stamped it
VOIDED and archived PKR 16627, so the withdrawal never counted while its 310 kg return
(M/RR/05717) still counted as a receipt. Nobody pressed Void: `x_studio_voided` flipped
0 -> 1 in the same write that set the picking Done, which is why the "void the returns
first" guard never fired (it lives in `void_transfer`, never called here).

Fix: `_apply_void_identity_on_validation` + `_void_identity_status` +
`_find_void_identity_by_content`. Auto-void only when identity is **intact**; when the
pointer is lost but client + pallet series still mirror a voided document it is
**recoverable** (link repaired, then auto-voided); when it mirrors nothing it is
**stale** (flag cleared, ledger row kept, chatter note posted). Tests:
`cr2_shell_tests/suite_at_void_identity_guard.py` (11/11; re-arms the incident
in-transaction so it survives the data being repaired). Regression:
`suite_t_merge_void_lifecycle.py` 9/9.

Data repair: `ai_context/sa_fix_stale_void_markers.py`, paste-ready SA on stock.picking,
Inventory Super Admin only (it calls `unvoid_transfer`). No prints, no dry-run flag, no
chatter; it reports via the SA `log` helper and a sticky `display_notification`. It only
unvoids where the tracking proves the auto-void signature, so a deliberate void is
reported and never touched. **Applied on `vifel_08_18_2026`**: M/WR/08389 unvoided and
disarmed (PKR 16627 back to active, 2 pallets / 1,310 kg), and 4 stale flags cleared
(M/WR/08387 168 ENTERPRISES draft, M/WR/08390 PERMEX 2 confirmed, both siblings of the
same 08-01 shell batch; M/RR/00362 COUNTRYWIDE whose parent M/WR/00434 is not voided;
M/RR/04418 MOMMY LOIDA with no parent link at all). 105 healthy void docs untouched.
M/RR/04017 was deliberately left alone as `recoverable`. **Production still needs both
halves**: upgrade `multiple_relocation` for the guard AND run the SA, or repaired
records can be damaged again.

**Partial-Withdraw return sequencing guard (2026-07-29, `stock_picking.py::button_validate`):**
a multi-truck withdrawal's Partial-Withdraw return, if validated BEFORE the partner WR empties
the shared pallet, re-inflates the pallet so the partner reads `reserved_quantity_on_validation
> 0` and fails to count it (undercount), and the return mints an unreconciled +1 received =
a **phantom pallet** (proven on FO-021134/NB 2317 in `vifel_07_29_2026`: WR/07885 counted 5,
should be 6; NB 2317 net +1 while physically empty). Fix: `button_validate` blocks a
`return_reason == 'Partial Withdraw'` return while any pending (not done/cancel) OUTGOING WR
still reserves the same (package, owner, PSI) — the multi-truck sibling that must empty +
count the pallet first. New `_vifel_pending_multitruck_siblings()` helper;
`skip_partial_return_sequence_guard` override. NO counting-logic change — the existing resv
rule produces the right numbers once the order is right. Normal single-truck partials and
void/wrong-details returns are unaffected. Verified `partial_return_sequence_guard_test.py`
(11/11). `EDGE_CASE_THINKING.md` gained lens #8 (event-order), Case study 3, and a "How these
were actually found" method section.

**Client-change PSI reset (2026-07-28, `stock_picking.py::write`):** changing the Client on an
EDITABLE (draft/assigned) normal RR that already had drawn Pallet Series left every line owned
by the new client (AR#1 partner→owner) but still stamped with the OLD client's series — an
owner/PSI mismatch AND a series-pool leak (proven on M/RR/00352, BGZ→168). Now the write()
override snapshots each series→old-owner before super().write, then recycles each series back
to the OLD client's pool (stocked-pallet guard, audit context) and blanks the series + stale
display; a chatter note tells the user to re-assign under the new client. Reservations are
RR-scoped so pallets/locations are kept. Returns/void still BLOCK (existing guard); done RRs
untouched; BF exempt; `skip_client_change_psi_reset` opts programmatic writes out. Verified by
`ai_context/wr_psi_client_change_test.py` (10/10). New `ai_context/EDGE_CASE_THINKING.md`
captures the reusable lenses behind this and the WR-drift fix.

**WR print pallet count = PKR (2026-07-28, `stock_picking.py`):** the WR/RR PDF
withdrawn-pallet counters (`get_pallet_count_for_page` + `preprocess_stock_move_data`)
gated outgoing lines on `reserved_quantity_on_validation == 0 AND not
same_quant_stocks_picked`. That second gate was a LIVE query for pending outgoing
pickings on the same lot, so an already-validated WR's printed count DRIFTED — e.g. a
returned pallet re-reserved on a fresh WR would retroactively drop it from the count
(reproduced on M/WR/07887: printed 2, dropped to 1 while a pending outgoing held the lot).
Dropped the live gate; the WR print now counts on the FROZEN emptying snapshot alone,
matching the PKR ledger and the on-screen Transacted Pallet Count. Verified: 4 previously-
mismatched WRs now equal PKR (07887=2, 08028=7, 08025=1, 07995=14) and 07887 is stable
under a simulated pending outgoing. Incoming (RR) counting is untouched — every pallet
received still counts. Also removed the now-dead per-line `same_quant_stocks_picked`
searches (perf).

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
6. **Client-Specific Requirement Enhancement — BUILT as its own module on `CR2-test`,
   105/105 verified (§7). Next: human UAT click-through, then deploy (§7.5).**

## 7. BUILT: Client-Specific Requirement Enhancement (`vifel_client_requirements`)

_Design settled interactively 2026-07-16/17; client-facing design page + PDF delivered
(artifact `ef072cc7…`, `Downloads/Vifel-Pallet-Merge-Enhancement.pdf`). Client timeline:
Internal Testing Mon Jul 27, UAT Tue Jul 28, go-live Wed Jul 29 (committed latest Fri
Jul 31). Estimate: avg 8.60 mandays._

**Status 2026-07-21 — v2 BUILT on `CR2-test`, 105/105 shell checks green on
`vifel_07_12_2026_2`.** v1 (Jul 20, 73 checks) was functionally correct but its UX
failed in use: an unlabelled `fa-compress` icon at the far right of an
already-scrolling tree, and a dialog stacking two unrelated jobs behind an "… or"
heading, asking "does this fit?" while withholding the line's own Weight/Quantity and
reporting every mistake as a post-click `UserError`. The user asked for a UI/UX
judgment, then for the feature to live in its own installable/removable module.

CR2-test was **re-cut from client-trial `00b6f2b`** (v1 preserved at tag
`cr2-v1-ux-superseded` = `25a29a0` and on `origin/CR2-test`); verified files were
**ported, not retyped**. NOTE: local CR2-test has deliberately diverged from its remote
— **pushing needs an explicit force-push decision from the user.**

Commits: `6e36a47` (A: module extraction) → `a9a6cbf` (B: merge core) →
`a6eb578` (C: UI) → `dbdff50` (D: Magic Wizard initiation) → E (tests + docs).

**Counting refinement (user ruling 2026-07-23):** merge is +0 ONLY when the target pallet
already holds stock. FIRST stock on the empty pinned Fixed pallet is a plain, unflagged
+1 line — otherwise the WR that later empties the pallet (−1 on exhaustion) walks the
ledger negative each empty→fill cycle. Flag decided by stock state at merge time.

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

### 7.2 As-built architecture — plug and play (revised 2026-07-23)

**Everything the feature owns lives in `vifel_client_requirements`.** Core keeps only
five generic extension hooks. Installing the module adds the feature; core carries no
trace of it. Guarded by `suite_f_plug_and_play.py` (25 checks).

Core footprint, in full — 2 files, ~60 lines, mostly docstrings:

| Module | Hook | Neutral default | Why it cannot live in the add-on |
|---|---|---|---|
| `multiple_relocation` `wizard/FastEncodeRR.py` | `_vifel_line_is_merge_locked(line)` | `False` | inside two loops (`action_confirm`, `_validate_result_package_availability`) |
| | `_vifel_apply_merge_locked_line(line, ml)` | `False` | inside `action_confirm`'s main write loop (**299 lines**) |
| | `_vifel_line_write_vals(line)` | `{}` | extra values on the normal write path |
| `pallet_kilos_record_model` `models/models.py` | `_vifel_line_originates_pallet(ml)` | `True` | inside `_populate_operations_data` (**153 lines**) |
| | `_vifel_merge_free_domain()` | `[]` | inside `action_resync_pallet_counts` (**990 lines**) |

An add-on cannot reach into the middle of a loop, and duplicating a 299- or 990-line
method to change three lines would drift from core silently — the thing that actually
breaks a system later. Core asks a neutral question; the module answers it.

**What moved out on 2026-07-23** (was ~230 lines across 8 files in 2 modules): the five
fields (`is_pallet_merge`, `client_lot_no`, `vifel_premerge_*`), the `write()` guard and
un-merge intercept, the Magic Wizard's merge columns and seeding, the Pallet Breakdown and
quant-tree columns, and both context keys. The wizard seeding now backfills in the
transient line's own `create()` rather than duplicating an 86-line method; the two context
keys are injected by overriding the actions and mutating the returned dict.

**Reversal note.** The fields lived in core so that uninstalling could not drop them and
inflate historical pallet counts. The user ruled the module is installed once and **never
uninstalled**, so that risk cannot occur. *If that ruling is ever reversed, move the
fields back to core FIRST* — dropping `is_pallet_merge` silently inflates pallet counts.

### 7.3 Findings that cost real time — do not relearn

1. **MRO is ours-FIRST, not ours-last.** Measured order:
   `vifel_client_requirements` → `pallet_series_audit` → `multiple_relocation`. The audit
   wrapper logs *after* its `super()`, so our early returns (stocked refusal, special-type
   routing) bypass it entirely — a special-type recycle would have vanished from the audit
   trail. `_vifel_audit_type_recycle` logs it explicitly (suite A6).
2. **The Magic Wizard's transient line needs a TWO-STEP write.** `FastEncodeRR.py:965`
   intercepts any write containing `result_package_id` and RE-DERIVES the series from
   pallet-group logic (winner election, sibling sync, restore-original). Right for a user
   retyping a Pallet #, wrong for a merge: it discarded the adopted series. Write the
   package first, then the merge identity in a second write with no `result_package_id`
   key — see `_vifel_sync_from_move_line`. Caught by assertion, not inspection.
3. **Candidate lists explode.** TECHNO FARM (Multiple + Include Regular) has 3,583 stocked
   pallets; the naive per-package `.quant_ids.filtered` loop took 3.77s and produced an
   unusable table. One grouped `search_read` → 0.81s, capped at `CANDIDATE_CAP=300` with
   the true total surfaced and a manual Pallet # picker for anything beyond. No silent
   truncation. Intended clients never hit this (Wonder Meats: 1 pallet).
4. **Merge candidates are owner-scoped, not code-matched.** Matching `prefix == client_code`
   wrongly excluded BGZ FOOD VENTURES' legacy `BGZ-` stock (their code is now `BG`).
5. `stock.quant.copy()` is forbidden by core — build test fixtures with `create`, or use
   the real mixed pallets (TECHNO FARM has 7 from opening balances).
6. `pallet.series.audit.log_event` **silently skips** validated/cancelled/return pickings —
   audit assertions are vacuous unless the test picking is still open.

### 7.4 Verification — 207/207 on `vifel_07_12_2026_2`

Suites live in `ai_context/cr2_shell_tests/suite_*.py`, all rollback-only; pipe each into
`odoo-bin shell`. Re-run them before Internal Testing and after any merge into client-trial.

| Suite | Covers | Checks |
|---|---|---|
| `suite_a_profile_routing` | profile cascade, PSI types, prefix routing, audit | 11 |
| `suite_b_merge_core` | candidates, merge, un-merge, create-special, R6 cap, Fixed mode | 23 |
| `suite_c_pkr_counting` | **+0 pallets / full amounts**, no-op domain, Re-sync idempotence, copy=False | 11 |
| `suite_d_guards_edges` | BF/return/outgoing/validated never offer merge, owner isolation, Lot No. stamping, picklist | 16 |
| `suite_e_ui_structure` | form + buttons registered, single-select, ineligible refused | 5 |
| `suite_f_plug_and_play` | **core carries no trace of the feature**; hooks are neutral and overridden | 25 |
| `suite_g1_fastencode_consumer` | a merge survives the Magic Wizard's deferred confirm | 11 |
| `suite_g2_fastencode_initiation` | merge/un-merge started inside the Magic Wizard | 13 |

Notes for whoever re-runs these: the **merge-free domain is provably a no-op** on real
data (47,843 rows with and without the clause; zero lines flagged), so the counting
changes cannot move a live ledger. A first Re-sync on this debug DB legitimately corrects
one stale row — the suite therefore asserts **idempotence** (a second run changes nothing)
rather than "zero change", which would be a false failure.

### 7.6 Downstream lifecycle verified (2026-07-24) — returns, voids, reports

The three downstream concerns raised in the post-build brainstorm were investigated in
code and VERIFIED, not blindly patched. Finding: the enhancement rides two pre-existing
PHYSICAL invariants, so all three are already correct — no merge-specific fix was needed.

- **Billing + occupancy reports** (`suite_u_merge_reports.py`, 10 checks). Billing xlsx
  (`pallet_kilos_billing_xlsx.py`) READS PKR fields verbatim — already merge-aware, a
  merged line drops its printed received count by 1. Occupancy xlsx
  (`stock_quant_history/occupancy_xlsx_report.py`) counts DISTINCT
  `x_studio_pallet_series_id`; merge guarantees one PSI per pallet, so a merge pallet
  counts once. Two independent bases, both see one pallet.
- **Voids/unvoid** (`suite_t_merge_void_lifecycle.py`, 9). The void WR withdrawn count
  keys on `reserved_quantity_on_validation` (physical emptying), NOT `is_pallet_merge`;
  void WR/return rows are archived from PKR (`models.py:782`); void source uses the
  building preset, not the pinned pallet's PACKAGE reservation. Merge is transparent.
- **Returns** (`suite_s_merge_return_lifecycle.py`, 6). A return lands via
  `_find_psi_remainder_quant`, keyed on (owner, PSI) — it cannot tell a merge pallet from
  any pallet carrying that PSI. Return routing reads the LOCATION reserved flag, not our
  PACKAGE reservation, so the pinned pallet does not misroute a return.
- **Partial-Withdraw return accounting — TRACED, and it is CORRECT (not an over-count;
  corrects an earlier note).** A Partial-Withdraw return carries its own active PKR row
  counting `pallets_received` and lands on the remainder. I first flagged this as a
  possible point-in-time over-count; a direct trace disproves that. Example
  M/WR/00002 -> M/RR/00015: the WR counted 24 pallets withdrawn incl. the partially-
  picked pallet NB 5456 (its WR line had `reserved_quantity_on_validation = 0`, i.e.
  counted -1), and the return re-received exactly that 1 pallet (+1). Net -24 +1 = -23
  pallets, matching the 23 that physically left. The return is proper double-entry: the
  WR is encoded/counted for the full pallets, and the return brings back the portion that
  stayed. Aggregate: 46/72 owners have ledger == physical exactly; the 26 with drift are
  on this DEBUG DB's known unrelated anomalies (RO-006886 doubling, orphan voids), not
  returns. Merge is unaffected either way.

### 7.7 Concurrency / corrections / lifecycle verified (2026-07-24)

Second downstream round. Only concurrency needed a fix; corrections and the lifecycle
were already correct.

- **#4 Concurrency FIXED** (`pallet_merge_wizard.py`, `suite_x_merge_concurrency.py`, 10).
  Two receipts both merging onto the empty pinned Fixed pallet would both "first-stock"
  it (+2 for one physical pallet; Re-sync would not self-heal). Now the birth happens
  once: `_pinned_pallet_already_claimed` flags a later receipt as a merge (+0) if another
  open receipt already put an unflagged line on the pinned pallet, and
  `_lock_pinned_pallet` (SELECT ... FOR UPDATE, SA#297 pattern) serialises true
  simultaneity. Because the flag persists, both live-count and Re-sync then count +1 once.
  Single-document birth is unchanged (suites B/N still +1). Entirely in the module.
- **KNOWN RARE EDGE, documented not fixed (user decision):** if the birthing line is
  DELETED before validation while another receipt already merged onto the pinned pallet,
  the pallet is left with only flagged lines and counts 0 despite physical stock. Extremely
  rare; `pallet_drift` surfaces it; un-merging one line restores the birth. Revisit only if
  the floor ever hits it.
- **#5 Corrections — already merge-transparent** (`suite_v_merge_correction.py`, 7). The
  correction wizard's pallet delta (`_package_change_pallet_delta`) is purely physical
  (source/dest stock, owner-scoped), never reads `is_pallet_merge`. A merge pallet corrects
  like any pallet; the flag on the RR line (history of its +0) is untouched.
- **#7 Lifecycle nets to zero** (`suite_w_merge_lifecycle_resync.py`, 7). Driven through
  the real counting engine: born +1, merges +0, partial WR -0 (remainder left), full WR
  -1 (emptied) = 0. Full-owner Re-sync with a merge present is drift-free and idempotent.

### 7.8 UAT-driven refinements (2026-07-28)

A round of fixes from clicking the feature on `vifel_07_28_2026_2`. All in
`vifel_client_requirements` (plug-and-play intact). Test set now **351 checks / 32 suites**.

- **New Location scoped to the receipt building** (`suite_z`, 5). Starting a new special
  pallet only offers locations `child_of picking.location_dest_id` (e.g. an M/EX receipt →
  under M/EX), enforced in the domain AND `_apply_create_special`. Merging onto an existing
  pallet in another building is unaffected (it adopts the pallet's real location).
- **No pallet/location reuse across a receipt's lines** (`suite_ab`, 8). A new special
  pallet can't reuse a sibling line's pallet (would mix PSIs) or non-aisle bin (two pallets
  in one spot); aisles may still hold several.
- **Batch # / Prodcode** (`suite_y` 11, `suite_y2` 5). New profile toggle
  `vifel_show_batch_no`. Batch # typed on the RR line (Pallet Breakdown + Magic Wizard,
  written back on Confirm) is set at validation into a Prodcode on the quant:
  `DD`+UPPER-mon+`YYYY` (the **EXPIRATION** date, `x_studio_expiration_date`)
  + Batch# + a fixed **M** (the building segment is hardcoded to 'M', not the
  actual building; e.g. `18MAY202699M`; no expiration date means Batch# + M).
  Shown read-only on the WR.
- **Symmetric same-receipt Un-merge** (`suite_aa` 21, `suite_ac` 8). Same-receipt joins stay
  `is_pallet_merge=False` (ledger untouched) but now CAPTURE pre-merge state, so any line on
  a shared pallet shows "Merged" + Un-merge and can be peeled off; the pallet stays +1 until
  a lone owner remains. The "Merged" marker = `is_pallet_merge OR shares-a-pallet`; buttons,
  tint and location-lock all key on it, on BOTH the Pallet Breakdown and the Magic Wizard.
- **Single 'Merge Here' target** (`suite_ad`, 5). Parent-level onchange re-asserts radio
  behaviour so the web client re-renders de-selected rows; `_resolve_merge_target` refuses
  an ambiguous (>1) pick server-side.
- **UI declutter (JS)**: Print dropdown hidden on the Pallet Breakdown; redundant header
  "Spawn Magic Wizard" hidden (the top-left JS Magic Wizard is the entry); the merge dialog's
  X/Escape now re-spawns the Magic Wizard (`from_fast_encode`) instead of dropping the session.
  *JS — confirm visually in a hard-refreshed browser.*
- **Deliverable**: `ai_context/uat/VIFEL_Merge_Pallet_UAT_Test_Script.xlsx` — 15 scenario-based
  UAT cases, Elyon → Vifel branded, status drop-downs + sign-off.

### 7.5 Remaining before go-live
1. **Browser confirmation of the JS bits** — Print hidden, Spawn hidden, merge-dialog X
   re-spawns the Magic Wizard (headless upgrade is clean; visual not yet confirmed).
2. **Human UAT click-through** — run the 15-case UAT script end to end.
3. **SA#348 + SA#333 pastes** are mandatory at go-live (see `ai_context/sa348_*` and `sa333_*`).
3. Prod profiles: Wonder Meats = Can Merge ON / Multiple OFF / pin `R 5666` + `WMF-00230`;
   Consistent = Can Merge ON / Multiple ON (types auto-seed); Show Lot No. per client.
4. Install `vifel_client_requirements`; upgrade `multiple_relocation` +
   `pallet_kilos_record_model`. The new module is uninstalled in prod today, so its own
   version string is free; **do NOT touch the 4 pinned manifest versions** (§5).
5. Optional: add the Lot No. column to the Studio "Inventory Overview" action DB-side.
6. **PASTE `ai_context/sa348_verifier_exempt_merged_lines.py` into Server Action #348
   "X_Verifier Check on Receipt"** — three lines. WITHOUT IT MERGING IS BROKEN from the
   second merge onto a pallet onwards: SA#348's duplicate-PSI-in-stock guard refuses the
   receipt ("Pallet Series Already Exists in Stock"), because a merged line adopts a
   series that is deliberately already in stock. The block already exempts return lines
   for the same reason; merged lines need the identical exemption. The FIRST merge onto
   an empty pinned pallet passes (no stock yet), which is why this only appears later.
7. Optional but recommended: paste `ai_context/studio_psi_display_clear_FIX.py` into the
   Studio compute for `x_studio_pallet_series_display` — it only assigns when the source
   has a value, so clearing a PSI anywhere leaves a stale one displayed (not merge-specific).
8. No new SA/AR beyond the two pastes above — PSI→quant stamping remains a DB automation
   and flows automatically. **(SUPERSEDED by §7.9 — partial-withdrawal SA#333/SA#377 and
   the one-time backfill SA were added after this line was written. Use §7.9's list.)**

### 7.9 Durable merge identity + QA certification (2026-08-04)

Two things landed since §7.8: (1) merge identity is now **durable on the package**
(`stock.quant.package.vifel_is_merge_pallet`, stored) instead of inferred from
historical move-line markers — fixes the reset-SA/recycled-package fragility (A1/A2/D2);
and (2) a **senior-QA certification pass** — 44 rolled-back shell suites, **488 checks
passed / 0 failed / 0 skip-branches used** on `vifel_08_03_2026`, and the UAT script
(v1.1, 24 scenarios) is **24/24 traced to a passing automated check**. Report:
`ai_context/Merge_Pallet_QA_Certification.md`. New suite `suite_ap_uat_traceability.py`
closes the last 3 UAT gaps (MP-B10 column order, MP-D3 stock-view columns, MP-C5
multi-truck emptied-rule). No product defect found; certification changed tests only.

**Complete DB-side AR/SA set for the merge deploy** (replaces §7.5.3/§7.5.6-8):

| # | Object | File to paste | Mandatory? | Why |
|---|---|---|---|---|
| SA#348 | Server Action "X_Verifier Check on Receipt" (stock.picking) | `sa348_verifier_exempt_merged_lines.py` | **YES** | Duplicate-PSI-in-stock + already-reserved guards refuse a merged line (it adopts an in-stock series / a reserved pinned pallet). Breaks from the 2nd merge onward without it. |
| SA#333 | Server Action "Execute Code" (stock.picking) | `sa333_partial_withdraw_merge_pallet.py` | **YES** (if any client withdraws) | Withdrawal guard refuses a WR that leaves stock on the source pallet; a merge pallet deliberately carries several products, so partial withdrawal is legitimate. Exempts via `_vifel_package_allows_partial_withdrawal`. |
| SA#377 / **AR#29** | Server Action for Automation Rule #29 "Stock Move Assign Quants Picked" (stock.move, on create/write) | `sa377_assign_quants_merge_aware.py` | **YES** (if any client withdraws) | The AR overwrites `quant_ids_picked` with the whole pallet on every save, re-adding quants the user removed — blocks partial withdrawal of a merge pallet. |
| NEW SA | Server Action "Backfill Merge-Pallet Identity" (stock.quant.package, Execute Code) — CREATE it | `sa_backfill_merge_pallet_flag.py` | **YES, one-time** | Stamps `vifel_is_merge_pallet` on pallets that are ALREADY merge/condition pallets (pinned Fixed OR stocked-and-marked) so partial withdrawal works the moment the module upgrades. Run ONCE in the upgrade window. Idempotent; no trailing raise. |
| Studio compute | `stock.move.line` field `x_studio_pallet_series_display` compute | `studio_psi_display_clear_FIX.py` | Recommended (not merge-only) | Compute only assigns when source has a value → clearing a PSI (un-merge, Clean reset) strands a stale series in the display column. |

Ordering at go-live: upgrade `vifel_client_requirements` (+ `multiple_relocation`,
`pallet_kilos_record_model`) → run the backfill SA once → paste SA#348 / SA#333 / SA#377
→ (recommended) the PSI-display compute fix. Existing 4 manifest versions stay pinned.
Optional: add Lot No. / Batch # / Prodcode columns to the Studio "Inventory Overview"
action (the module already adds them to the quant views; only needed if a Studio action
overrides that view).

<!-- MERGED FROM client-trial (base-module counting/ownership fixes brought into CR2-test) -->

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

## 9. Update 2026-08-25 - encoder UI and client reports land on CR2-test

CR2-test is the current line: it carries `vifel_client_requirements`,
`vifel_utility_tools`, `pallet_series_audit` and `vifel_health_monitor`. The work
below was built on CR-test and brought over on top of it.

### 9.1 `vifel_encoder_ux` (NEW module)

The encoder-facing screens, as their own installable module rather than woven into
`multiple_relocation`. It adds no field to a stock document and changes no algorithm,
so removing it takes the screens away and leaves receiving, withdrawal, relocation,
voiding and billing untouched.

Contents: Clients hub (Inventory landing page), Clients kanban with clickable count
badges and an A-Z / Most Pending sort toggle, Find Transfer (search by RR/WR number,
Pallet Series ID or Pallet #), the Receiving/Withdrawal picker with create-from-dialog,
client smart buttons on the Contact form, the Client Unique Code uniqueness guard, and
the read-only contact form for Documentation Staff.

- Depends on `multiple_relocation` (reads `documentation_staff_id`,
  `is_blast_freeze_operation`, `bf_pallet_char`). Nothing depends on it.
- Install with `-i vifel_encoder_ux`. On a database that already had these screens
  inside `multiple_relocation`, run `-u multiple_relocation -i vifel_encoder_ux` as ONE
  command so the hand-over happens in a single transaction. CR2-test never had them, so
  a plain install is enough here.
- The wizard keeps its old `_name`, `multiple_relocation.client.transfer.type.wizard`.
  Renaming would rebuild the table plus its ir_model and ACL rows for no gain.
- `vifel_enable_quant_report_button` stays in `multiple_relocation` (the button it feeds
  is there). CR2-test has no quant report button, so that split file is not carried here.

### 9.2 Client reports

Cherry-picked from CR-test (`d7cff37`, `41ef2ac`, `52fb971`):

- **Inbound Log XLSX** (new). Rows are the UNION of receiving lines and live quants,
  keyed `(PSI, Pallet #)` and scoped by `owner_id`, over the Inventory Overview domain.
  This is the tally fix: the report used to be document-driven while the Overview is
  stock-driven, so any pallet without a receipt for that client was invisible. It hid
  2,755,542 kg across 52 clients. Opening-balance pallets now appear marked
  `OPENING BALANCE`.
- **Outbound Log XLSX** columns matched to `Odoo Client Inventory Format.xlsx`.
- **`xlsx_log_style.py`** (new): shared muted house style, sage `#4F6F52` for inbound and
  brick `#8C4A4A` for outbound, plus the INV/ZERO button bar and top totals strip.
- Inbound is full history on purpose (`is_full_history_report`); a date range would cut
  the balance. `date_to` defaults to today in Manila time.
- **Client Inventory Summary** gains a Number of Pallets column with a header total,
  counted DISTINCT over the owner (packages for normal, `bf_pallet_char` for BF). It is
  not a sum of the column: that would double-count the mixed pallets.

One conflict came up, in `pkr_report_wizard.xml`, purely because the CR-test commit that
moved the Report selector above the filters was not picked. Resolved in favour of the
CR-test layout (choose the report, then the filters), which loses nothing: CR2-test had
made no change of its own to that file.

### 9.3 Verified

Clone of `vifel_verify_0821`, `-u pallet_kilos_record_model,multiple_relocation
-i vifel_encoder_ux`: loads with no traceback, no ParseError, no invalid custom views
and no inconsistent module states. Both menus land at sequence 0 and 1, both log report
actions register, and `vifel_client_requirements` / `vifel_utility_tools` stay installed.

### 9.4 Still open

The Stock Inquiry column overlap. The custom list renderer written for it had no visible
effect and was removed; its commit message claims the squeeze is "handled in SCSS
instead", which is **false** - no such rule exists in either stylesheet. It needs a fresh
approach.

## 10. Update 2026-08-26 - banded Inventory Overview + operation state picker

Client request: lay the Inventory Overview operation-type cards in bands under the warehouse
name (Blast Freeze, then Normal) instead of one narrow column, and make clicking an operation
type ask WHICH STATE rather than dumping every transfer of that type on screen. Both live in
`vifel_encoder_ux`.

### 10.1 The grouping is not in any view - it is a saved favourite

`ir_filters` on `stock.picking.type`: id 1 "Inventory Overview" (user NULL, global, default)
and id 2 "Overview" (user 2, default), both `{'group_by': ['warehouse_id']}` with domain
`[("name","!=","Internal Transfers")]`. The action `stock.stock_picking_type_action` (id 267)
had an EMPTY context and the kanban has no `default_group_by`. A default favourite's group_by
beats a view default, so anything built here has to tolerate the favourite being changed or
removed. **`fetch_database_context.py` does not dump views or actions, so this is only
visible in the database.**

### 10.2 Kanban cannot nest groups, so the second level is drawn

`kanban_controller.js:173` sets `maxGroupByDepth: 1`, `dynamic_group_list.js:36` reads
`groupBy[0]`, and `kanban_renderer.xml` iterates a group's RECORDS, never sub-groups. The
warehouse level is already spent. So `static/src/js/overview_kanban.js` extends
`KanbanRenderer` and walks each group's records emitting a band heading wherever
`is_blast_freeze_operation` flips. Records arrive blast-freeze-first via `default_order` on
the primary view, so two bands fall out of the ordering with no extra query.

Degrades rather than breaks: no bands if the field is missing from the datapoint, no bands if
every record is in one band, and the ungrouped case renders exactly as stock does. It is
wrapped so a failure cannot take the view down.

### 10.3 A primary view, not an edit of stock's kanban

`stock.stock_picking_type_kanban` is shared with mrp, repair and stock_picking_batch, which
all extend it. `vifel_encoder_ux.view_picking_type_kanban_vifel_overview` is `mode="primary"`
inheriting it, bound to action 267 through `ir.actions.act_window.view` records owned by this
module. Uninstalling drops the bindings and the standard Overview returns. Verified: core view
683 still has no `js_class`.

The action's context is set to `{'vifel_state_picker': True}`. That writes a field on a core
record, so the key survives uninstall, but it is inert once the override is gone.

### 10.4 State picker

`wizard/picking_type_state_wizard.py`, a dialog reusing the client picker's card design, with
four cards: DRAFT, WAITING, READY, DONE (the client mock had three; READY was added because it
is the state the floor actually works from). WAITING is `state in ('confirmed','waiting')` to
match what the Overview card already calls Waiting. There is no `count_picking_done` field and
the `count_picking_*` fields are non-stored computes, so all four counts use `search_count`.

The click is intercepted by overriding `get_stock_picking_action_picking_type` on
`stock.picking.type`, **gated on the `vifel_state_picker` context key**. Without the key it
calls `super()`, so that method is unchanged everywhere else. The "N To Process" button is
deliberately left alone: it already means Ready.

### 10.5 A real data bug fixed on the way

Tagoloan's picking types 46 and 48 ("Blast Freeze - IN" / "- OUT") carried
`is_blast_freeze_operation = False` while Meycauayan's 45 and 47 carried True. That flag drives
`operation_type_checker` and `vifel_type_of_operation`
(`multiple_relocation/models/stock_picking.py:510-528`), so a blast-freeze transfer raised at
Tagoloan would have been classified **RR instead of BFRR**. It had not bitten because that
warehouse has no transfers at all yet.

`stock.picking.type.vifel_repair_blast_freeze_flags` fixes it, matching by NAME rather than id
so it is portable, and idempotent so it is a no-op on every later update. Run from a
`<function>` in `views/picking_type_overview_views.xml`.

### 10.6 Verified on a clone of `vifel_verify_0821`

Install clean: no traceback, no ParseError, no invalid custom views, no inconsistent states.

- Repair idempotent (4 BF-flagged before and after a second run); both warehouses now order
  blast-freeze first.
- State picker for Meycauayan RECEIVING reads draft 98 / waiting 0 / ready 162 / done 5634,
  and each card opens a list of exactly that many records.
- The override is inert without the context key (returns `stock.picking`, target `current`)
  and returns the wizard with it.
- SCSS bundle compiles, 1.1 MB, containing `o_vifel_overview_kanban`, `o_vifel_band` and
  `o_vifel_state_ready`.
- OWL template inheritance resolves: the banded loop replaces the core loop in OUR template
  only, core `web.KanbanRenderer` and the Clients kanban template are untouched.
- RESOLVED arch carries `js_class="vifel_overview_kanban"` and the `default_order`, and action
  267 serves view 1228 for kanban. This last check is the one that matters: the earlier
  stock.quant column renderer passed its tests and still did nothing because its js_class
  never reached the rendered view.

**NOT verified: how the bands actually look in a browser.** `.o_kanban_dashboard` is written
for a flat layout and the SCSS widens the group column and wraps the cards. Expect the layout
to need iteration against a real screen.

## 11. Update 2026-08-26 - helpdesk tickets linked to transfers

Raise a helpdesk ticket from the transfer it is about, and reach the ones already
raised, without switching apps. Built in `vifel_encoder_ux` at the user's request.

- `helpdesk.ticket.picking_id` (Many2one to stock.picking, indexed,
  `ondelete='set null'`). A ticket outlives the document it complains about:
  cascading would destroy the record of a problem exactly when someone wants it.
- On `stock.picking`: `helpdesk_ticket_ids`, a batched `helpdesk_ticket_count`
  (one grouped query for the whole recordset, same rule as the client kanban
  counts), a **Create Ticket** button in the header and a **Tickets** smart
  button that is hidden at zero.
- Tickets raised from a transfer default to the **IT Support** team, resolved by
  NAME not by id. Team ids differ per database (id 2 on `vifel_08_26_2026`, id 4
  on a fresh install), so a hard-coded id would file tickets under whatever team
  took that number. If the team is missing the default is left off and Odoo's own
  default applies.
- The subject is pre-filled `Issue on <document number>`, and the customer is
  carried over when the transfer has one.
- From the Helpdesk side, `picking_id` is on the ticket form, in the search view
  and as a hidden-by-default list column, so a ticket opened there can be tied
  back by hand.

**`vifel_encoder_ux` now depends on `helpdesk`.** Installing or upgrading it on a
database without Helpdesk installs the whole Helpdesk app as a side effect. That
was agreed, but it is the reason to think twice before adding more app-level
links to this module: the alternative is a small bridge module depending on both.

Verified on a clone of `vifel_verify_0821` (helpdesk pulled in as a dependency):
counts correct and scoped to the right picking, the smart button opens exactly
those tickets, deleting a picking leaves its tickets alive with the link cleared,
IT Support resolved by name over Customer Care, graceful fallback when no such
team exists, and all four inherited views applied.

NOT verified: how the ticket form looks inside a modal (`target='new'`). The
helpdesk form carries a notebook and an Html description field, so it may want to
be a full page instead.
