# The pallet-field chain — where a per-pallet value has to be carried

> **Read this before adding ANY new per-pallet field**, and before touching a
> hand-maintained field list. **Last updated**: 2026-08-22.
> Companions: `multiple_relocation_AI_CONTEXT.md`, `BUSINESS_CONTEXT_AND_LEARNINGS.md`.

## Why this document exists

Remarks was added in August 2026 by copying the client Lot No. pattern. Doing that
surfaced a bug nobody had noticed: **relocation silently dropped `client_lot_no`,
`batch_no` and `prodcode`**. A pallet moved between bins kept its identity but lost the
client's own reference to it.

Nothing was wrong with the relocation code. The value was lost because relocation copies
a **hand-maintained list of field names** (`_RELOCATION_STUDIO_FIELDS`), and whoever
added those three fields never knew that list existed.

That is the failure mode this document prevents. A per-pallet value in VIFEL does not
live in one place. It crosses record boundaries repeatedly, and **almost every crossing
is a hand-written list or dict that has to be edited by hand.** Miss one and the value
disappears at exactly one point in the lifecycle, which is very hard to notice and often
only shows up in a billing dispute months later.

## The two kinds of per-pallet value

Knowing which kind you are adding tells you which hops apply.

**Kind A — typed on the line, stamped to stock.** The operator types it on a RECEIVING
line; at validation it is written onto the quant. Examples: `client_lot_no`, `batch_no`,
`vifel_remarks`. Truth lives on the **quant** once received.

**Kind B — derived or read back.** Never typed. Computed from the quant for display on a
WITHDRAWAL line. Examples: `vifel_lot_no_display`, `prodcode`, `vifel_remarks_display`,
and the Studio computes (`x_studio_container_number`, `x_studio_withdraw_units`).

A Kind A field normally needs a Kind B partner (so withdrawals can show it) **and** a
stored snapshot partner (so the value outlives the quant). That is three fields, and it
is the shape both Lot No. and Remarks use.

## The chain, hop by hop

### Hop 1 — receiving line to quant (the stamp)
Runs in `stock.picking.button_validate`, **after** `super()`, because the destination
quant must already exist.

| Field family | Method |
|---|---|
| Remarks | `multiple_relocation/models/stock_picking.py::_vifel_stamp_remarks` |
| Lot No. | `vifel_client_requirements/models/client_lot_no_gating.py:133::_vifel_stamp_client_lot_no` |
| Batch # / Prodcode | same file, `:197::_vifel_stamp_batch_prodcode` |

Quant key: `product_id` + **`location_dest_id`** + `lot_id` + **`result_package_id`** +
`owner_id`. Several lines can land on one quant: last write wins, deliberately.

**Never gate the stamp on a display flag.** A value the user entered is always persisted;
the per-client profile flags govern whether a COLUMN is shown, nothing else. Gating the
write would silently drop data.

### Hop 2 — quant back to a withdrawal line (the read-back)
Non-stored computes. Quant key is the mirror image: `product_id` + **`location_id`** +
`lot_id` + **`package_id`**. **Getting these two keys the wrong way round is the classic
bug in this family.**

- `stock_move.py::_compute_vifel_remarks_readback`
- `vifel_client_fields.py:71::_compute_vifel_quant_readback` (Lot No. + Prodcode)
- Studio-era equivalents, stored and older: `_compute_container_number`,
  `_compute_x_studio_building_dropped` in `stock_move.py`

### Hop 3 — snapshot before the quant dies
A full withdrawal destroys the source quant, so a live read-back blanks after validation.
The snapshot runs in `_action_done` **before** `super()`, which is where the quant is
consumed. Ordering is the entire point.

- `stock_picking.py::_action_done` → `_vifel_freeze_remarks_readback`
- `client_lot_no_gating.py:94::_action_done` → `vifel_client_fields.py:117::_vifel_freeze_wr_readback`

Both snapshot writers are idempotent: they never overwrite a value already captured.

### Hop 4 — relocation, quant to a NEW quant
`multiple_relocation/models/stock_quant.py`, `_relocation_studio_vals`.

- `_RELOCATION_STUDIO_FIELDS` — the core list. Studio and core field names go here.
- `_vifel_relocation_extra_fields()` — neutral hook returning `[]`. An optional add-on
  overrides it with the names of fields it owns, because core must not name the feature
  module's fields (guarded by `suite_f_plug_and_play.py` check F14).

**This is the hop that was broken.** Missing fields are skipped silently by the existing
`if not field: continue` guard, so a typo or omission never raises.

### Hop 5 — corrections / pallet adjustments
`multiple_relocation/wizard/stock_quant_correction.py`.

The correction itself writes **in place** on the existing quant
(`:1139::_apply_changes` → `quant.write(update_vals)`), so a corrected pallet **keeps**
every field nobody explicitly changed. There is no carry-over needed for the stock
itself, which is why corrections did not lose Remarks or Lot No.

Remarks is also **correctable** here, which matters because it is read-only everywhere
else once the receipt is validated (the RR column locks at `state == 'done'`, the quant
lists are read-only). The wizard is mostly declarative: a correctable field is one entry
in each of the two `field_mapping` dicts (`:1114` wizard, `:1930` audit line) plus an
`old_`/`new_` pair on `stock.quant.adjustment.line`. Follow `x_studio_container_number`.

A Remarks-only correction is inert for the ledger, and that is not luck:
`_calculate_adjustment_values` keys only on `quantity`, `x_studio_2nd_uom`,
`x_studio_total_units` and `package_id`, and `_psi_cascade_plan` skips any line whose
`package_id` is unchanged. Keep it that way.

Corrections also build **history move lines** for the audit trail, from TWO separate
hand-maintained dicts:
- `:558` inside `_handle_quantity_adjustment`
- `:640` inside `_create_correction_move`

Both copy roughly twenty `x_studio_*` fields plus `bf_pallet_char`, and both now also
carry `vifel_remarks` plus `_vifel_correction_line_extra_vals()`, the neutral hook the
add-on fills with `client_lot_no` / `batch_no`.

⚠️ **The dynamic loop does not help.** `_create_correction_move` has a loop that copies
CHANGED fields whose name starts with `x_studio_`, but it is gated on
`hasattr(stock.move.line, field_name)`. The quant field is `x_studio_remarks` while the
move-line field is `vifel_remarks`, and no `x_studio_remarks` exists on
`stock.move.line`, so it skips it. **Whenever the two models name a field differently,
that loop is blind to it** and the value must be added to both dicts by hand.
(An earlier revision of this document claimed a changed `x_studio_remarks` rode the loop.
That was wrong.)

**`prodcode` can never ride a history line**: on `stock.move.line` it is a non-stored
compute, so it is not writable. Same for `vifel_lot_no_display`.

**Do NOT add keys to the two quant snapshot builders** (`:382` and `:1889`). They must
stay byte-identical, and a new key would make every EXISTING stored snapshot differ from
its rebuilt version, flipping every open adjustment request to "Pallet Changed".
`write_date` is already in the snapshot, so conflict detection already covers any edit.

### Hop 6 — withdrawal to a return RR line
A return re-receives stock. On a withdrawal the value lives on the QUANT, not the move
line, and the source quant is often already depleted when the return is built, so the
return builder has to fetch it from the ORIGINAL receiving line.

Two hooks in `multiple_relocation/wizard/ReturnPackageWizard.py` do this:
`_vifel_return_wizard_line_vals` and `_vifel_return_move_line_vals`, called from four
places inside the wizard (`:310`, `:344`, `:827`, `:991`) **plus a fifth, hand-built call
site in `stock_picking.py::_create_return_rr_from_wr`** — see hop 8b, which is where a
missed one actually bit. Core fills them with Remarks, reading
`move_line.vifel_remarks_display` (which already prefers the stored snapshot, so it
resolves after the source quant is consumed); `return_lot_batch.py` extends them through
`super()` for Lot No. / Batch #. **Fill the hooks rather than editing the four call
sites** — that is the whole reason they exist.

### Hop 7 — the Magic Wizard round trip
`FastEncodeRR` reads move lines into a transient model and writes them back. A new field
needs BOTH directions, and the write side has **five** paths:

1. load: `stock_move.py::action_open_fast_encode_wizard`, the `line_vals` dict
2. write, normal: `FastEncodeRR.py::action_confirm`, the `write_vals` dict
3. write, blast freeze: the early-return dict in the same method
4. write, merge-locked line: `fast_encode_merge.py::_vifel_apply_merge_locked_line`
5. write, staged merge: `fast_encode_merge.py::_vifel_apply_staged_merge`

Paths 4 and 5 live in the add-on and carry their own cargo dicts. Path 3 bypassed the
`_vifel_line_write_vals` hook entirely until 2026-08-22, which is why **Lot No. and
Batch # were silently dropped on every BFRR confirm**. It now routes through the hook.

### Hop 8 — void WRs and void returns
The picking shell is built with `record.copy()`, and every field in this family is
`copy=False`, so **nothing rides the copy**. But the copy is not how the lines get their
values, and the two void directions differ. Do not reason about this hop from `copy()`.

**Voiding an RR → void WR (outgoing).** `_create_void_wr_from_rr` **deletes the copied
moves and rebuilds them from the quants** via `_checkout_quants_to_picking`, whose
move-line vals set `product_id` + `location_id` + `lot_id` + `package_id` + `owner_id`.
That is exactly the identity hop 2 keys on, so the read-back resolves and Remarks appears
on the void WR with no extra work. Verified live: a stamped quant showed
`vifel_remarks_display` on its void WR line.

**Voiding a WR → void return RR (incoming).** `_create_return_rr_from_wr` **builds the
Return Packages wizard lines BY HAND** ("replicating `_compute_location_and_packages`
logic") instead of going through the wizard's own builder. That makes it a **fifth write
path** in this family, separate from the four call sites listed in hop 6, and it silently
bypassed `_vifel_return_wizard_line_vals`. A void return RR therefore arrived with an
empty Remarks / Lot No. while the withdrawal it mirrors carried them. Fixed 2026-08-22 by
spreading the hook into that hand-built dict; note `self` there is a `stock.picking`, so
the hook is called on `self.env['return.package.wizard']`.

The lesson generalises: **a "replicating X's logic" comment is a warning sign.** It means
a second copy of a value-carrying dict exists somewhere the hook does not reach.

Note `copy()` also copies one2many operations, so context-based guard exemptions must be
set on BOTH the source and the copy (the M/WR/06825 lesson).

### Hop 9 — occupancy snapshots (`stock_quant_history`)
This hop is **not** hand-maintained like the others. It discovers fields dynamically in
`stock_quant_history_snapshot.py::_get_quant_copy_fields`, and the rule is narrow:

> copy a `stock.quant` field if its name **starts with `x_studio_`** (or is one of the
> hardcoded `_EXTRA_COPY_FIELDS = ("owner_id", "package_id")`), the type is a copyable
> scalar, **and a field of the same name exists on `stock.quant.history`**.

Two consequences that decide whether your new field appears in occupancy history:

1. **Naming is load-bearing here.** `x_studio_remarks` is carried (verified: it is one of
   the 26 discovered fields, and history rows carry real values). It qualifies only
   because we reused the Studio-named quant field. Had Remarks been added to the quant as
   `vifel_remarks`, it would have been **silently excluded** by the prefix test. A
   non-`x_studio_` field must be declared on `stock.quant.history` AND added to the extra
   list, or it never reaches history.
2. **The move-line replay has the same name-mismatch blind spot as hop 5.**
   `_generate_stock_quant_history` seeds from the previous snapshot / live quant, then
   replays done move lines through `_move_line_metadata_vals` →
   `_copy_field_values(move_line, copy_fields)`, which reads **quant-named** fields off a
   **move line** and silently skips any the move line does not have. 5 of the 26 names are
   absent on `stock.move.line`, `x_studio_remarks` among them (the move-line field is
   `vifel_remarks`). So metadata taken from a replayed move line carries no Remarks.

The table is large (~1.25M rows), so adding a column here is a migration, not a tweak.
See the `warehouse_id` precedent in `stock_quant_history.py`, backfilled by raw SQL in
`migrations/17.0.1.1.0/pre-migrate.py` because the ORM could not recompute row by row.

## Status matrix

| Hop | `x_studio_*` studio set | `client_lot_no` / `batch_no` / `prodcode` | `vifel_remarks` |
|---|---|---|---|
| 1 receiving stamp | n/a (Studio automations) | yes | yes |
| 2 WR read-back | yes | yes | yes |
| 3 snapshot at validation | n/a | yes | yes |
| 4 relocation | yes | yes (since 2026-08-22) | yes |
| 5 correction, quant in place | yes | yes | yes |
| 5b correction history lines | yes | yes, via hook (since 2026-08-22) | yes (since 2026-08-22) |
| 5c correctable in the wizard | yes | no (not correctable) | yes (since 2026-08-22) |
| 6 return | partial | yes | yes (since 2026-08-22) |
| 7 Magic Wizard (5 paths) | yes | yes | yes |
| 8 void WR (from RR) | yes | yes | yes, via the hop 2 read-back |
| 8b void return RR (from WR) | yes | yes (since 2026-08-22) | yes (since 2026-08-22) |
| 9 occupancy snapshot, from the quant | yes | yes (since 2026-08-22) | yes |
| 9b occupancy snapshot, from a replayed move line | yes | yes | yes, via alias map |

## Closed gaps (kept as worked examples)

**G1 — correction history move lines omitted the fields. CLOSED 2026-08-22.** Both dicts
now carry `vifel_remarks` directly and spread `_vifel_correction_line_extra_vals()`,
which `vifel_client_requirements/models/correction_lot_batch.py` fills with
`client_lot_no` / `batch_no`. `prodcode` is excluded by construction (non-stored compute).

**G2 — returns did not carry Remarks. CLOSED 2026-08-22.** The two return hooks are now
filled from core, and `return_lot_batch.py` still chains through `super()`.

Both were found by walking this document's hop list against a newly added field, which is
exactly what it is for. Tests: `cr2_shell_tests/suite_av_remarks_correction_return.py`.

**G3 — occupancy history carried no Lot No. / Batch # / Prodcode. CLOSED 2026-08-22,
forward-only.** They failed both halves of the hop 9 rule. Now
`vifel_client_requirements/models/history_lot_batch.py` declares the three on
`stock.quant.history` and extends the new `_extra_copy_fields()` hook, and
`vifel_client_requirements` gained a `stock_quant_history` dependency. `prodcode` IS
carryable here because on the quant it is a plain stored Char, unlike on
`stock.move.line`. The ~1.25M existing rows stay blank by decision; values appear from
the next snapshot onward.

**G4 — the hop 9 move-line replay dropped name-mismatched fields. CLOSED 2026-08-22.**
`_copy_field_values` now consults `_quant_field_aliases()` and falls back to the
alias name on the source, while still keying the result by the target name.
`x_studio_remarks` → `vifel_remarks` is the first entry.

## Open gaps

None currently tracked. When one is found, record it here with a severity and the fix
shape rather than leaving it implicit.

## Checklist for adding a new per-pallet field

1. Decide Kind A or Kind B, and which module owns it. Universal and ungated goes in
   `multiple_relocation`; per-client and profile-gated goes in `vifel_client_requirements`.
2. If it is stamped onto the quant, decide whether to REUSE an existing Studio field.
   Check `ir_model_fields` first: Remarks reused `stock.quant.x_studio_remarks` and
   avoided rendering two identical columns.
3. Add the three fields (typed / display / snapshot) and set `copy=False` on all of them.
4. Walk hops 1 through 9 above and decide explicitly for each: carried, or deliberately
   not. Write the decision down.
5. Never name an add-on's field inside core. Add a neutral hook instead.
6. Put the column last, and gate it on `picking_code` rather than on a client flag unless
   it is genuinely per-client.
7. Add a suite under `ai_context/cr2_shell_tests/`, and include a check that the value
   **survives validation** and **survives relocation**. Model it on
   `suite_au_remarks_lifecycle.py`.
8. Re-run `suite_f_plug_and_play.py`. F14 fails loudly if core learned a forbidden name.

## How to check a hop is really covered

The cheap trick that found the relocation bug: set the value on a real record, call the
carry-over method directly, and assert the destination has it. No UI needed.

```python
q.x_studio_remarks = 'X'
vals = q._relocation_studio_vals()
assert vals.get('x_studio_remarks') == 'X'
```

`suite_au_remarks_lifecycle.py` does this for hops 1 through 5 and 7. Fixture selection
matters: pick stock that STILL EXISTS. A receipt whose pallet was long since withdrawn
has no destination quant left to stamp, and the resulting failure says nothing about the
code.
