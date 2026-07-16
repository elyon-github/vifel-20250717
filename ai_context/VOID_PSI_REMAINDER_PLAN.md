# Plan: Void-return lands on the PSI remainder (same pallet #, location, lot)

> **STATUS: ✅ IMPLEMENTED** (verified 2026-07-17: `_find_psi_remainder_quant` live in
> `multiple_relocation/models/stock_picking.py` and `wizard/ReturnPackageWizard.py`).
> Kept for the rationale/rule reference. Follow-up SA#478 rev 2 historical-duplicate
> cleanup remains a parked paste (see handoff.md §6.5).

## Problem (confirmed 2026-07-06)
Voiding a WR restores stock through a void return RR
(`_create_return_rr_from_wr` → Return Packages wizard). The destination
pallet #/location are chosen by reservation/occupancy heuristics that never
ask "does this PSI still have a remaining quant in stock?". For partial
withdrawals (standard for Special No-RR-Return clients like Mommy Loida),
the remainder is still on the original pallet — but the restored stock can
land on a NEW pallet # in an aisle: same PSI, two pallets, two locations.
Downstream: phantom pallet in re-sync residuals, occupancy errors, AR#17
reducer hitting the wrong quant, SA#478-style duplicates made by the
system itself.

## Verified foundations
- Merge machinery already works when all 5 quant keys match
  (product, lot, owner, package, location): KG merges natively;
  2nd UOM and packs are incrementally added by AR#2/SA#293
  (`quant.x_studio_2nd_uom + line.x_studio_2nd_uom`, same for units).
- Lot is preserved on void returns: void path passes original `lot_id`
  (stock_picking.py:1080), wizard writes it with `is_return=True`
  (ReturnPackageWizard.py:756-762), and lot-assigner AR#10/SA#309 skips
  `is_return` lines.
- So the ONLY broken merge key is pallet # + location selection.

## The rule
1. **PSI-remainder-first**: if an internal quant with the same OWNER + PSI
   and qty > 0 exists, the return line MUST target that quant's
   `package_id` and `location_id`. No reservation/occupancy checks — the
   pallet is physically standing there. (If several remainder quants:
   prefer the one on the WR line's original package, else largest qty.)
2. **No remainder** (pallet was fully withdrawn): prefer the WR line's
   original `package_id` + `location_id` when the package holds no other
   owner's stock and the bin is free; only then fall back to the current
   aisle heuristics.
3. BF pallets (`bf_pallet_char`, no package): unchanged — identity is the
   char, no package/location merge problem.

## Checklist

### Implementation (multiple_relocation)
- [ ] 1. Add shared helper `_find_psi_remainder_quant(owner, psi, prefer_package=None)`
      on `stock.picking` (or a small mixin both call sites import):
      searches `stock.quant` [owner, x_studio_pallet_series_id=psi,
      quantity>0, location internal], prefer_package first, else largest
      quantity; returns quant or empty.
- [ ] 2. `_create_return_rr_from_wr` (models/stock_picking.py ~1029):
      before the existing heuristics, call the helper per move line;
      if found → `location_dest_id = quant.location_id.id`,
      `pallet_result_id = quant.package_id.id`, skip heuristics.
- [ ] 3. Same-rule insertion in
      `ReturnPackageWizard._compute_location_and_packages`
      (wizard/ReturnPackageWizard.py) so MANUAL partial returns behave
      identically.
- [ ] 4. No-remainder fallback: try original WR-line package + location
      (package free of other owners' stock) before the aisle fallback,
      in both call sites.
- [ ] 5. Race hardening: move `is_return: True` and `lot_id` into the
      move-line CREATE values in ReturnPackageWizard (lines ~748/~910)
      instead of the post-create write, so AR#10 can never stamp a fresh
      lot in between.
- [ ] 6. Guard interplay: returned-to location must still be a LEAF bin —
      remainder quants always are; assert nothing conflicts with the
      leaf-location constraint (state='done' only, so fine).
- [ ] 7. `py_compile` both files; bump `multiple_relocation` version
      (17.0.1.0.2).

### Verification (on vifel_07_05_2026 or fresher clone)
- [ ] 8. Scenario A (the reported bug): no-RR-return client, partial WR
      (half a pallet), validate, VOID it, validate the void return →
      restored quant sits on the SAME pallet #, location, lot as the
      remainder; ONE quant with summed KG, 2nd UOM, packs.
- [ ] 9. Scenario B: full-pallet WR voided (no remainder) → stock returns
      to the original pallet # and bin (or aisle only if bin taken).
- [ ] 10. Scenario C: manual partial return (Return Packages wizard,
      normal client) → same remainder-first landing.
- [ ] 11. PKR chain: after A, the WR row's counts unchanged (partial = 0
      pallets), Re-sync reports no new residual for the client, and
      `transacted_pallet_count` consistent.
- [ ] 12. Read-only sweep: count existing same-PSI-multiple-pallets
      duplicates created by past voids (query PSI with >1 stocked package,
      cross-ref void return RRs) → hand list to SA#478 rev 2 cleanup run.

### Deploy / follow-ups
- [ ] 13. Upgrade module on debug DB → user acceptance → hold for
      MAIN deploy instruction (no push without explicit go).
- [ ] 14. SA#478 rev 2 paste (already in ai_context) to clean up the
      historical duplicates found in step 12.
- [ ] 15. Add note to vifel_studio_patches plan: no DB-side change needed
      for this fix (pure code), but SA#478 rev 2 + SA#297 owner-scoped
      stamp remain pending pastes.
