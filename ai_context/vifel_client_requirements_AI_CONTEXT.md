# `vifel_client_requirements` — AI Context Document

_Created 2026-07-21 (branch `CR2-test`). The Client-Specific Requirement Enhancement,
built as its own installable/removable module. Read with
`BUSINESS_CONTEXT_AND_LEARNINGS.md` (§3 identity doctrine, §4 counting, §5 per-client
cases) and `handoff.md` §7 (as-built state, findings, deploy steps)._

## 1. Purpose

Three per-client capabilities agreed with VIFEL:

- **Pallet merging** — an incoming Pallet Breakdown line can land on a pallet **already
  stocked on the floor**. The line adopts that pallet's Pallet Series (PSI) and location,
  and the ledger counts **+0 pallets** for it while its Weight / Quantity / Packs still
  count in full. Two client modes: **Fixed** (one pinned pallet forever — Wonder Meats,
  `R 5666` / `WMF-00230`) and **Multiple** (special PSI types per condition — Consistent:
  MDGM, BOC, TDMG, SDMG, each with its own prefix, counter and recyclable numbers).
- **Client Lot No.** — the client's own lot number on transfer lines, stamped onto stock
  at validation.
- **VIFEL Configuration** — the profile cascade driving all of the above, per client.

## 2. The load-bearing design decision

**The module owns configuration, routing and UI. It never owns the record of what
already happened.**

`is_pallet_merge` and `client_lot_no` are declared in **`multiple_relocation`**
(`models/vifel_client_fields.py`), not here. They are ledger evidence: `is_pallet_merge`
is *why* a line's pallet count is zero, and the PKR ledger reads it on every rebuild. If
the field lived here, uninstalling would drop the column and every historically merged
line would silently recount as a received pallet on the next Re-sync — inflating pallet
counts, and therefore invoices, for work done months earlier. A wrong pallet count is
literally a wrong invoice (`BUSINESS_CONTEXT_AND_LEARNINGS.md` §1).

`suite_f_uninstall_safety.py` fails loudly if anyone ever "tidies" those fields into this
module.

## 3. Where things live

| File | Contains |
|---|---|
| `models/vifel_psi_type.py` | `vifel.psi.type` — prefix, counter, recyclable numbers; `draw_number` / `take_number` / `give_back` |
| `models/res_partner_vifel_config.py` | the profile cascade + auto-seeding in `create`/`write` |
| `models/res_partner_psi_routing.py` | prefix-aware `push_unused_pallet` / `get_pallet_series_by_id`, stocked-guard, audit |
| `models/client_lot_no_gating.py` | `show_client_lot_no` compute + quant stamping at validation |
| `models/stock_move_line_merge.py` | button availability, wizard opener, `action_unmerge_pallet_line` |
| `models/fast_encode_merge.py` | merge / un-merge started inside the Magic Wizard |
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

`ai_context/cr2_shell_tests/suite_*.py` — 8 suites, **105 checks**, all rollback-only:

```
python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
    < ai_context/cr2_shell_tests/suite_c_pkr_counting.py
```

`suite_c` guards the billing doctrine (+0 pallets, full amounts) and proves the merge-free
domain is a **no-op on unflagged data** — the property that makes the counting change safe
on a live ledger. `suite_f` guards the uninstall architecture. Re-run everything before
Internal Testing and after any merge into `client-trial`.

## 6. Not built (deliberate)

- **Create-new-special-pallet inside the Magic Wizard** — that path stays a Pallet
  Breakdown action; the Magic Wizard offers merge-onto-stocked only.
- **No new Studio server actions or automations.** PSI→quant stamping is an existing DB
  automation and the adopted PSI flows through it automatically.
