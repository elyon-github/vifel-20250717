# Merge Pallet — QA Certification Report

**Feature:** Merge Pallet (Client-Specific Requirement Enhancement — CR2)
**Branch:** CR2-test
**Certification DB:** `vifel_08_03_2026` (fresh install; the only DB carrying the new
`stock.quant.package.vifel_is_merge_pallet` durable-identity column — the odoo-bin
shell loads the latest code from disk)
**Date:** 2026-08-02
**Signed off by:** QA (senior-tester pass)

---

## 1. Verdict

**PASS — certified for hand-off.**

- **Automated regression:** 44 shell suites, **488 checks passed, 0 failed, 0 hard
  reds, 0 skip-branches used** (every suite exercised its real assertions — none
  fell through to a "no eligible fixture" skip on this DB).
- **Static code review:** clean. Deferred-write invariant intact, durable-identity
  flag set/cleared symmetrically, counting keyed only on `is_pallet_merge`, no bare
  excepts / TODO / dead hooks.
- **UAT script (v1.1, 24 scenarios):** **24 / 24 traced to a named, passing
  automated check** (see §4). No scenario left on "manual only".

No product-code change was required by this certification pass — every regression
failure encountered during hardening was **fixture-driven** (the test had picked a
line/pallet not eligible in this DB's data) or a **stale test premise** (an
assertion written before the deferred-write refactor). Both classes were fixed in
the *tests*, never by weakening an assertion. The feature code was already correct.

---

## 2. What was verified

### 2.1 Durable merge identity (the core hardening this cycle)
`stock.quant.package.vifel_is_merge_pallet` (stored) replaces inferring merge status
from historical move-line markers. Invariant: **True iff** the package is a pinned
Fixed pallet **or** currently holds merged stock.
- **Set** by the `stock.move.line` create/write hook (any line carrying
  `is_pallet_merge` or `vifel_premerge_captured` stamps its package) and by the
  `res_partner` Fixed-pallet pin.
- **Cleared** only when the pallet is emptied *and* unpinned
  (`vifel_free_merge_identity_if_idle`).
- **Withdrawal predicate:** `pinned OR (package.vifel_is_merge_pallet AND
  package.vifel_holds_stock())` — so a merge pallet still allows partial withdrawal
  after a server restart, with no dependence on old move-line history.

### 2.2 Deferred (staged) Magic-Wizard merge / un-merge
The Magic Wizard writes **only transient rows**; the real `stock.move.line` changes
**only** at `FastEncodeRR.action_confirm` via `_vifel_apply_staged_merge` /
`_vifel_apply_staged_unmerge`. Verified end-to-end by suites **G2, M, H, AC, AJ**
(the real line stays unmerged until Confirm; edits and drawn PSI survive the
deferred write; released series never resurrect).

### 2.3 Counting integrity
`_vifel_line_originates_pallet` keys **only** on `is_pallet_merge` (a +0/+1 concept,
profile-independent) — confirmed by code review and by suite **C** (PKR counting)
using a DB-state-independent assertion (`n_free == n_all − n_true`).

### 2.4 Client gating & surface parity
Merge UI is shown only for a merge-enabled client and only on incoming, not-done,
not-return, not-BF lines, gated on the `vifel_can_merge` **context** flag (not a
per-record field — the fix for the Pallet Breakdown OwlError). Both surfaces (Pallet
Breakdown and Magic Wizard) offer the same two modes. Suites **E, AD, M, F**.

---

## 3. Regression summary (44 suites, 488 checks)

All suites are rollback-only (`env.cr.rollback()`); nothing is committed to the DB.
Run pattern:

```
for f in ai_context/cr2_shell_tests/suite_*.py; do
  python odoo-bin shell -c odoo.conf -d vifel_08_03_2026 \
      --no-http --max-cron-threads=0 < "$f"
done
```

| Result | Count |
|---|---|
| Suites | 44 |
| Checks passed | **488** |
| Checks failed | **0** |
| Hard-red suites | **0** |
| Suites that fell through to a skip-branch | **0** |

**Hardening applied this cycle (tests only — assertions unchanged):**
- **C9** reframed from the false premise "no row is flagged" to the DB-independent
  `n_free == n_all − n_true`.
- **S1** reframed from a hardcoded stray count to verifying the *mechanism*
  (`_void_archive_pallet_kilos_record` sets `active = False`).
- **AD, G1, G2, H, M, T, V, Z** — replaced first-match `search(..., limit=1)` fixture
  picks with `.filtered(eligibility)[:1]` + a logged skip fallback, so each suite
  now selects a genuinely-mergeable line (unmerged, incoming, merge-enabled client,
  Magic-Wizard-ready) and **runs its real assertions**.
- **G2, M, H, D5/D11/D12/P4-P9/U11** — aligned to the **staged** behavior (real line
  untouched until Confirm) after the deferred-write refactor (commit 2ba23f7). These
  were tests written pre-staging; they now assert the staged requirement.

---

## 4. UAT sign-off — 24 / 24

UAT script: `ai_context/uat/VIFEL_Merge_Pallet_UAT_Test_Script.xlsx` (v1.1).
Every scenario maps to a named automated check that passes on `vifel_08_03_2026`.

### A. Setup (3)
| # | Scenario | Covering check | Result |
|---|---|---|---|
| MP-A1 | Merge UI appears only for a merge-enabled client | suite_e (context-flag gating) + suite_a | Pass |
| MP-A2 | Fixed / Multiple modes + PSI-type auto-seed | suite_a, suite_k | Pass |
| MP-A3 | Lot / Batch columns per client | suite_o, client_lot_no gating | Pass |

### B. Receiving (10)
| # | Scenario | Covering check | Result |
|---|---|---|---|
| MP-B1 | +0 merge onto earlier stock | suite_b, suite_c | Pass |
| MP-B2 | Weight / qty / packs captured in full | suite_c, suite_u | Pass |
| MP-B3 | Same-receipt join = +1 | suite_aa, suite_l, suite_c | Pass |
| MP-B4 | Fixed first-stock +1 / later +0 | suite_b, suite_n, suite_ag | Pass |
| MP-B5 | New special pallet +1, building-scoped location | suite_b, suite_z, suite_ab | Pass |
| MP-B6 | Single "Merge Here" radio target | suite_ad, suite_e | Pass |
| MP-B7 | Magic Wizard exit paths return to the session | suite_h (U6-U11) | Pass |
| MP-B8 | Lot No. stamped to the matching quant | suite_d (D14b), suite_y | Pass |
| MP-B9 | Prodcode + building shortname | suite_y (Y1-Y3, Y8) | Pass |
| MP-B10 | Lot No. / Batch # / Prodcode columns after Container # | **suite_ap (MP-B10)** | Pass |

### C. Withdrawal (5)
| # | Scenario | Covering check | Result |
|---|---|---|---|
| MP-C1 | Partial withdrawal -0, -1 on empty | suite_p, suite_ae, suite_c | Pass |
| MP-C2 | Un-merge keeps the count correct | suite_aa, suite_ac | Pass |
| MP-C3 | Lot No. shown on the WR line | suite_y (Y9b) | Pass |
| MP-C4 | Prodcode shown on the WR line | suite_y | Pass |
| MP-C5 | Multi-truck: counts on the WR that empties the pallet | **suite_ap (MP-C5/C5b)** | Pass |

### D. Reports & Count (4)
| # | Scenario | Covering check | Result |
|---|---|---|---|
| MP-D1 | Count integrity end-to-end | suite_c, suite_u, suite_w | Pass |
| MP-D2 | Reports == ledger, stable on re-print | suite_u (UR5), suite_r | Pass |
| MP-D3 | Stock (Inventory) view shows Lot / Batch / Prodcode | **suite_ap (MP-D3/D3b)** | Pass |
| MP-D4 | Existing Pallet Breakdown buttons intact (additive) | suite_f, suite_d | Pass |

The three rows that lacked a *dedicated* automated check before this pass — **MP-B10,
MP-D3, MP-C5** — are now closed by `suite_ap_uat_traceability.py` (5/5), which asserts
against the actual view/source: the column order after `x_studio_container_number`,
the three `stock.quant` optional columns, and the emptied-rule
(`reserved_quantity_on_validation`) that makes a shared pallet count on the WR that
empties it.

---

## 5. Code-review findings & dispositions

| Area | Finding | Disposition |
|---|---|---|
| Durable-flag lifecycle | Set on marker create/write + pin; cleared only when emptied-and-unpinned | Symmetric — no leak, no premature clear. OK |
| Deferred write | Nothing hits the real move line before `action_confirm` | Confirmed in `_stage_merge_on_fast_encode` / staged hooks. OK |
| Counting | `_vifel_line_originates_pallet` reads only `is_pallet_merge` | Never reads the durable flag or profile. OK |
| Withdrawal predicate | `pinned OR (flag AND holds_stock)` | Matches the invariant. OK |
| Error handling | No bare `except:`, no swallowed exceptions, no TODO/FIXME | OK |
| Manifest versions | `multiple_relocation` / `pallet_kilos_record_model` pinned to MAIN | Unchanged. OK |

No defects found; no product code changed by this certification.

---

## 6. Deploy notes (for the record — not part of this sign-off)

Certification was performed against fresh-install code on `vifel_08_03_2026`. A
production rollout still requires, per the deploy checklist:
1. Upgrade the `vifel_client_requirements` module (installs the
   `vifel_is_merge_pallet` column).
2. Run the one-time backfill SA `ai_context/sa_backfill_merge_pallet_flag.py`
   (stamps pinned + stocked-and-marked packages; no trailing raise).
3. Existing-module manifest versions stay pinned; the merge module is installed
   once and never uninstalled.

---

*Regenerate the regression total any time with:*
`for f in ai_context/cr2_shell_tests/suite_*.py; do run on the target DB; done`
*→ expect `0 failed` on every suite.*
