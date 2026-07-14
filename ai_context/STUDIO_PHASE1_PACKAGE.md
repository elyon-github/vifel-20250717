# Studio Phase-1 Package — reference scan, archive list, patches (FOR REVIEW)

> Generated 2026-07-04 against `vifel_06_30_2026_1` (read-only). Nothing here has been applied.
> Apply order: review §1 → approve §2 archive → paste §3 patch → schedule §4 items.

## 1. Reference scan — archive candidates are ALL unreferenced ✅

Checked each candidate against `ir_ui_view.arch_db`, other `ir_act_server.code`, `base_automation`,
`ir_ui_menu`, and `ir_model_data`:

| Action | Referenced by views / menus / other actions / automations? | Binding | Verdict |
|---|---|---|---|
| SA#347 `X_Assign Pallet Series ID` | none | none | dead — safe to leave as-is (already X_, unbound) |
| SA#502 `Get Unsynced` (old DB version) | none | **bound** to PKR model | unbind — replaced by module action `action_get_unsynced_pkr` |
| SA#460 `Fix Pallet Kilos` (hardcodes 48 pallets / 33,924 kg) | none | none | rename to `X_Fix Pallet Kilos` (one-off patch tool) |
| SA#394 `Re-fix Pallet Kilos Overall Kilos` | none | **bound** to PKR model | unbind — replaced by module `Recompute Balances` |
| SA#395 `Re-fix Pallet Kilos Overall Kilos 2` | none | **bound** to PKR model | unbind — replaced by module `Recompute Balances` |
| **SA#506 `Remove Adjustment`** *(new finding)* | none | **bound** to PKR model | `object_write` that hardcodes `adjustment_kilos = 2280` — a one-off patch. Recommend unbind + X_ rename. **Your call.** |

**No re-pointing needed anywhere** — nothing in Studio references these actions.

Also verified (no conflict with the new partner guard): SA#415 writes `x_studio_preferred_locations`,
SA#484 writes `is_company` — neither touches `x_studio_warehouse`.

## 2. Archive script (run in odoo shell per DB, AFTER approval)

```python
# ir.actions.server has no `active` field: archiving = unbind (removes the
# Action-menu entry) + X_ name prefix per house convention. Idempotent.
for aid in (502, 394, 395, 506):          # drop 506 here if you keep it
    a = env['ir.actions.server'].browse(aid)
    if a.exists():
        vals = {'binding_model_id': False}
        if not (a.name or '').startswith('X_'):
            vals['name'] = 'X_' + a.name
        a.write(vals)
a = env['ir.actions.server'].browse(460)   # unbound already: rename only
if a.exists() and not (a.name or '').startswith('X_'):
    a.write({'name': 'X_' + a.name})
env.cr.commit()
```

## 3. SA#513 "Update Quants (Relocate)" — warehouse-scoped replacement (paste into the action)

```python
for record in records:
    domain = [('lot_id', '=', record.lot_id.id),
              ('x_studio_pallet_series_id', '!=', False)]
    # Multi-warehouse: only consider move lines from THIS quant's warehouse.
    wh = record.location_id.warehouse_id
    if wh:
        domain.append(('picking_id.picking_type_id.warehouse_id', '=', wh.id))
    move_line = env['stock.move.line'].search(domain, order='date desc', limit=1)
    if not move_line and wh:
        # Fallback to the old unscoped behavior so single-warehouse data
        # keeps working even if a line predates warehouse-typed pickings.
        move_line = env['stock.move.line'].search(
            [('lot_id', '=', record.lot_id.id),
             ('x_studio_pallet_series_id', '!=', False)],
            order='date desc', limit=1)
        log('SA#513: warehouse-scoped lookup empty for quant %s; used unscoped fallback' % record.id)
    record.write({
        'x_studio_return_count': move_line.x_studio_return_count,
        'x_studio_pallet_series_id': move_line.x_studio_pallet_series_id,
        'x_studio_container_number': move_line.x_studio_container_number,
        'x_studio_production_date': move_line.x_studio_production_date,
        'x_studio_expiration_date': move_line.x_studio_expiration_date,
        'x_studio_2nd_uom': move_line.x_studio_2nd_uom,
        'x_studio_quantity_uom': move_line.x_studio_quantity_uom,
        'x_studio_total_units': move_line.x_studio_withdraw_units,
        'x_studio_min_quantity_uom': move_line.x_studio_min_quantity_uom
    })
```
*(Note: this preserves the existing `total_units = withdraw_units` mapping, which is a separate known
bug from the PKR audit — fix independently if desired.)*

## 4. Warehouse-safety inventory (active automations + bound/cron actions with their own `search()`)

21 of 95 live actions run their own searches. Classification:

**SAFE (search scoped by the triggering record's ids/lot/location, or warehouse-filtered already):**
AR#2/SA#293 (package by id) · AR#4/SA#295 (quant by move-line location) · AR#6/SA#297 (PKR by record) ·
SA#325 (picking type **with** warehouse filter) · AR#38/SA#416 (PKR by record) · AR#42/SA#432 (lines by
picking) · SA#425 (PKR by record) · SA#160/#168 (pricelists, N/A) · AR#46/SA#440 (mail, N/A).

**SAFE-BY-NATURE (global hygiene crons; re-review in Phase 2 cron policy):**
SA#351 Cleanup Quant · SA#417 Re-Compute Aging Days · SA#509 Clean Unreserved Quants.

**NEEDS-SCOPING when Tagoloan goes live (patches to prepare in Phase 2, behavior-neutral if applied now):**
- **AR#15/SA#317** — re-stamps quants found **by lot only** (also the known 2nd_uom clobber). Add
  warehouse/location scoping derived from `record`.
- **AR#17/SA#333** — "other quants same package" search spans all internal locations of every warehouse.
- **AR#29/SA#377** — quant search by lot+product+internal; BF lots are reused, so cross-warehouse hits are
  possible for BF.
- **SA#447 Unreserve Locations Ignored (cron)** — unreserves locations/lines/packages globally.
- **SA#513** — fixed by §3 above.

**VERIFY (mention warehouse, likely fine):** SA#423 Set Location Building · SA#507 Check Location Missing.
