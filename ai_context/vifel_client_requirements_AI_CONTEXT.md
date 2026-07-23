# `vifel_client_requirements` — AI Context Document

_Created 2026-07-21 (branch `CR2-test`). The Client-Specific Requirement Enhancement,
built as its own self-contained module. Read with
`BUSINESS_CONTEXT_AND_LEARNINGS.md` (§3 identity doctrine, §4 counting, §5 per-client
cases) and `handoff.md` §7 (as-built state, findings, deploy steps)._

## 1. Purpose

Three per-client capabilities agreed with VIFEL:

- **Pallet merging** — an incoming Pallet Breakdown line can land on a pallet **already
  stocked on the floor**. The line adopts that pallet's Pallet Series (PSI) and location,
  and the ledger counts **+0 pallets** for it while its Weight / Quantity / Packs still
  count in full — **but only while the target already holds stock**. The FIRST stock on
  the empty pinned Fixed pallet births the pallet: a plain, unflagged +1 line (user
  ruling 2026-07-23), so the pallet cycles +1 born / −1 emptied / +0 merged-while-stocked. Two client modes: **Fixed** (one pinned pallet forever — Wonder Meats,
  `R 5666` / `WMF-00230`) and **Multiple** (special PSI types per condition — Consistent:
  MDGM, BOC, TDMG, SDMG, each with its own prefix, counter and recyclable numbers).
- **Client Lot No.** — the client's own lot number on transfer lines, stamped onto stock
  at validation.
- **VIFEL Configuration** — the profile cascade driving all of the above, per client.

## 2. The load-bearing design decision — plug and play

**Everything this feature owns lives in this module.** Core keeps only five generic
extension hooks. Installing the module adds the feature; core carries no trace of it.

Verified continuously by `suite_f_plug_and_play.py`: core source contains **zero**
references to `is_pallet_merge`, `client_lot_no`, `vifel_premerge` or
`pallet.merge.wizard`; core neither imports nor XML-refs this module, nor depends on it.

The five hooks exist because the behaviour they gate sits *inside*
`FastEncodeRR.action_confirm` (~300 lines) and `PKR.action_resync_pallet_counts`
(~990 lines). An add-on cannot reach into the middle of a loop, and duplicating either
method to change three lines would guarantee silent drift from core — which is the thing
that actually breaks a system later. Core asks a neutral question; this module answers it.

| Hook (core) | Neutral default | This module returns |
|---|---|---|
| `_vifel_line_is_merge_locked(line)` | `False` | `True` for a merged row |
| `_vifel_apply_merge_locked_line(line, ml)` | `False` | cargo-only write, `True` |
| `_vifel_line_write_vals(line)` | `{}` | the client Lot No. |
| `_vifel_line_originates_pallet(ml)` | `True` | `False` for a merged line |
| `_vifel_merge_free_domain()` | `[]` | `[('is_pallet_merge','!=',True)]` |

**History worth keeping.** Until 2026-07-23 the fields lived in `multiple_relocation`, so
that uninstalling could not drop them and make every historically merged line recount as
a received pallet. The user has ruled the module is installed once and **never
uninstalled**, so that risk cannot occur — and holding the feature's own fields hostage in
someone else's module bought nothing but merge-conflict surface. **If that ruling is ever
reversed, move the fields back to core FIRST**: dropping `is_pallet_merge` silently
inflates pallet counts, and a wrong pallet count is a wrong invoice
(`BUSINESS_CONTEXT_AND_LEARNINGS.md` §1).

## 3. Where things live

| File | Contains |
|---|---|
| `models/vifel_psi_type.py` | `vifel.psi.type` — prefix, counter, recyclable numbers; `draw_number` / `take_number` / `give_back` |
| `models/res_partner_vifel_config.py` | the profile cascade + auto-seeding in `create`/`write` |
| `models/res_partner_psi_routing.py` | prefix-aware `push_unused_pallet` / `get_pallet_series_by_id`, stocked-guard, audit |
| `models/client_lot_no_gating.py` | `show_client_lot_no` compute + quant stamping at validation |
| `models/stock_move_line_merge.py` | button availability, wizard opener, `action_unmerge_pallet_line` |
| `models/fast_encode_merge.py` | Magic Wizard: merge/un-merge, the merge columns, and the three core hooks |
| `models/pkr_merge_counting.py` | the two PKR counting hooks (+0 pallets, full amounts) |
| `models/vifel_client_fields.py` | `is_pallet_merge`, `client_lot_no`, the `vifel_premerge_*` trio |
| `wizard/pallet_merge_wizard.py` `.xml` | `pallet.merge.wizard` + `pallet.merge.candidate` and their form |
| `views/` | VIFEL Configuration tab, Pallet Breakdown buttons, Magic Wizard buttons |

## 4. Pitfalls (read before editing)

1. **Never name a field `pool`.** It shadows `Model.pool` (the registry) and breaks model
   setup with a completely misleading `KeyError: 'partner_id'`. The field is `number_pool`.
2. **MRO is ours-FIRST.** Measured: `vifel_client_requirements` → `pallet_series_audit`
   → `multiple_relocation`. The audit wrapper logs *after* its `super()`, so any early
   return here bypasses it. `_vifel_audit_type_recycle` exists for exactly that reason —
   unaudited recycling is how split-PSI corruption goes untraceable (§3 of the business doc).
3. **The Magic Wizard's transient line needs a two-step write.** `FastEncodeRR.py:965`
   intercepts any write containing `result_package_id` and re-derives the series from
   pallet-group logic. Write the package first, then the merge identity separately — see
   `_vifel_sync_from_move_line`. Do not "simplify" it back into one write.
4. **Merge candidates are owner-scoped, not code-matched.** A client whose code changed
   still has legacy-prefix stock (`BGZ-` under code `BG`) that is perfectly mergeable.
5. **Never recycle a PSI that is live on stocked quants** — the adopted PSI of a merge
   target belongs to the target's stock. `_vifel_series_is_stocked` guards every path.
6. **Candidate lists are capped** (`CANDIDATE_CAP = 300`) with the true total surfaced and
   a manual picker escape hatch. Never make the cap silent.
7. Writes to merged lines carry `skip_pallet_series_sync=True` (and `vifel_pallet_merge`
   for the intentional-merge write) — otherwise `_action_assign` → `_do_unreserve` wipes
   the `x_studio_*` fields (`multiple_relocation` pitfall #3).

## 5. Testing

`ai_context/cr2_shell_tests/suite_*.py` — 16 suites, **207 checks**, all rollback-only:

```
python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
    < ai_context/cr2_shell_tests/suite_c_pkr_counting.py
```

`suite_c` guards the billing doctrine (+0 pallets, full amounts) and proves the merge-free
domain is a **no-op on unflagged data** — the property that makes the counting change safe
on a live ledger. `suite_f` guards the plug-and-play architecture. Re-run everything before
Internal Testing and after any merge into `client-trial`.

## 6. Not built (deliberate)

- **No new Studio server actions or automations.** PSI→quant stamping is an existing DB
  automation and the adopted PSI flows through it automatically.
