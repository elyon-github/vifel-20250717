# `multiple_relocation` — AI Context Document

> **Module path**: `addons/custom_addons/consultant-test/multiple_relocation/`
> **Odoo version**: 17 Enterprise
> **Author**: Mark Angelo S. Templanza
> **Depends on**: `base`, `stock`, `web`, `report_xlsx`
> **Last updated**: 2026-06-15

---

## Recent change (2026-06-15): Quant correction is now blast-freeze capable

`wizard/stock_quant_correction.py` + `.xml` previously only handled regular pallets
(identity = `package_id` + `x_studio_pallet_series_id`). It now also adjusts
**blast-freeze (BF) pallets**, whose identity is the free-text `bf_pallet_char`
(no package, no PSI). Key points:

- BF-ness per record comes from `stock.quant.location_is_bf`. A `_pallet_label(quant)`
  helper returns PSI for regular pallets and `bf_pallet_char` for BF (fallback
  `Quant #id`) — used in every user-facing message so blank PSI never crashes.
- `default_get` **blocks mixing** BF and regular quants in one correction, and sets
  `is_blast_freeze` on the wizard. Pending-adjustment conflict detection matches
  regular pallets by PSI and BF pallets by `lot_id` (unique per quant here).
- `bf_pallet_char` is threaded through the correction line, the persistent
  `stock.quant.adjustment.line` (`old/new_bf_pallet_char`, `is_blast_freeze`), both
  snapshot builders, `_get_changes`, the HTML change diff, and both history
  move-line builders (`_handle_quantity_adjustment`, `_create_correction_move`) so
  BF identity survives on the audit move lines.
- Views show columns per type via `column_invisible="parent.is_blast_freeze"` (wizard
  + request trees) or per-row `invisible` (reject wizard, line form): regular rows
  show PSI + Pallet #, BF rows show an editable **BF Pallet #** (`bf_pallet_char`).
- The regular/PSI path is unchanged — `bf_pallet_char` is empty on both sides for
  regular quants, so it can never register as a change.

## 1. Purpose (1-paragraph elevator pitch)

`multiple_relocation` is the **core custom inventory module** for VIFEL cold-storage warehouse operations. It extends Odoo's standard `stock` app to support:

- Multi-location stock relocations and transfers
- Receiving Reports (**RR**) and Withdrawal Reports (**WR**) with extensive custom fields
- A **client-scoped pallet-series ID pool** (`JBL-000001`, `BGZ-000007`, etc.) with reuse logic
- Blast-freezer (BF) operations with simpler series semantics
- Bulk-edit wizards for high-volume RR encoding
- Void / return / adjustment workflows that keep `stock.quant` and accounting consistent
- Custom XLSX and HTML reports (delivery slips, count sheets, inventory summaries)

It is the **heaviest module in the repository** (~7.4k LOC across 5 model files + 6 wizard files) and most other custom modules in `consultant-test/` depend on it (directly or indirectly via shared field conventions).

---

## 2. Where Things Live

```
multiple_relocation/
├── __manifest__.py
├── CONTEXT.md                       # Original, more verbose context doc — read for deep dives
├── models/
│   ├── __init__.py                  # Imports: models, stock_quant, stock_move, stock_picking
│   ├── models.py                    # res.partner (pool), product.template, product.product,
│   │                                #   stock.location (vifel_location_name), stock.quant.package,
│   │                                #   client.expiry.table
│   ├── stock_move.py                # TWO classes: StockMove (stock.move) AND
│   │                                #   stock_move_line_Override (stock.move.line) — there is NO
│   │                                #   separate stock_move_line.py file
│   ├── stock_picking.py             # picking_type, transfer_locations (stock.picking) — void,
│   │                                #   location domains, reports
│   └── stock_quant.py               # stock.quant.relocate override + stock.quant fields
├── wizard/
│   ├── FastEncodeRR.py              # "Magic Wizard" — bulk RR line editor
│   ├── ReturnPackageWizard.py       # Return-package workflow
│   ├── SelectQuantWizard.py         # Quant picker for WR
│   ├── SmallWizards.py              # Partial-package warning + misc dialogs
│   ├── stock_quant_correction.py    # Quant correction + adjustment-request model
│   └── stock_quant_relocation_lines.py
├── views/                           # views.xml, search_views.xml, action_views.xml, templates.xml
├── reports/                         # client_summary_xlsx, count_sheet (Python + XML)
├── security/ir.model.access.csv     # Wizard / transient model ACLs
├── controllers/, data/, demo/, static/
```

Static assets (registered in `web.assets_backend`):
- JS: `list_controller_custom_keybinds.js`, `form_controller_custom_keybinds.js`, `magic_wizard_list_controller.js`, `fast_encode_rr_list_controller.js`, `many2many_tags_field.js`
- SCSS: `custom_css.scss`
- OWL templates: `templates.xml`, `magic_wizard_list_view_template.xml`, `fast_encode_rr_list_view_template.xml`

---

## 3. Key Models and What They Add

| Model | Type | Key responsibilities added by this module |
|---|---|---|
| `res.partner` | inherit | Pallet-series **pool methods** (`push_unused_pallet`, `get_smallest_pallet_series_ids`, `generate_new_pallet_series_id`, `get_pallet_series_by_id`) + JSON field `unused_pallet_series_ids` |
| `product.template` / `product.product` | inherit | Brand/variant name composition, duplicate-name onchange check, computed `display_name` |
| `stock.location` | inherit | `vifel_location_name` (clean human label, indexed for name_search) |
| `stock.quant.package` | inherit | Custom display + linking helpers |
| `stock.picking.type` | inherit | Type flags used by RR/WR classification |
| `stock.picking` | inherit | Void / return workflows, location domains (`allowed_value_ids`), `vifel_type_of_operation` (RR/WR/BFRR/BFWR), revision/lock toggles, report buttons |
| `stock.move` | inherit | `regenerate_move_lines(counter)`, `_write_swap_product()` (raw-SQL escape hatch), product/qty change handling |
| `stock.move.line` | inherit | Adds non-studio fields: `original_pallet_series_id`, `adjusted_quantity`, `bf_pallet_char`, `original_record_reference`, `adjustment_batch_number` + many computed/related helpers |
| `stock.quant` | inherit | Mirrors `x_studio_*` fields from move lines, custom reservation guards |
| `stock.quant.relocate` | TransientModel inherit | Multi-line relocation validation (the module's namesake) |
| `client.expiry.table` | new | Per-client brand/expiry rules (used in expiry validation) |

### Pallet Series Pool (the heart of the module)

The pallet-series ID is a **per-client, integer-backed, reusable** identifier formatted as `{CLIENT_PREFIX}-{6-digit-zfill}`. Three pieces of state live on `res.partner`:

| Field | Type | Purpose |
|---|---|---|
| `x_studio_client_unique_code_1` | Char | Prefix (e.g. `JBL`, `BGZ`) — **must be set or pool methods raise UserError** |
| `x_studio_pallet_series_id` | Integer | Monotonic counter — only ever incremented (never decreased) |
| `unused_pallet_series_ids` | JSON (list of int) | Pool of IDs that were freed (deleted line, regenerated, voided) and can be reused |

The pool is a **sorted ascending JSON array of integers** (not full string IDs). Always parse and sort.

```python
# Key API on res.partner (models.py, ~line 17-150)
partner.push_unused_pallet("JBL-000007")             # returns 7 to pool
partner.get_smallest_pallet_series_ids(3)            # pops 3 smallest → ["JBL-000003", "JBL-000007", "JBL-000012"]
partner.generate_new_pallet_series_id()              # pool empty? → increments counter, returns new ID
partner.get_pallet_series_by_id("JBL-000005")        # try exact match in pool; fall back to smallest
```

---

## 4. The Pallet-Series "Disappearing" Bug (CRITICAL CONTEXT)

When you assign `x_studio_pallet_series_id` to `stock.move.line` and **in the same write** also touch `location_dest_id` or `result_package_id`, standard Odoo:

```
stock.move._action_assign()
  → stock.move._do_unreserve()             # DELETES existing move lines (quant no longer matches)
  → stock.move._update_reserved_quantity() # CREATES NEW BLANK move lines
```

All custom `x_studio_*` fields on the deleted lines are **lost forever**. This is the root cause of pallet series visibly "disappearing" after Server Action #347 or the FastEncodeRR wizard runs.

**Workaround pattern** — see `stock.move._write_swap_product()`: detach move lines via raw SQL before the parent write, re-attach after. This bypasses ORM cascade. Apply the same pattern if you find a new code path that loses pallet series.

**Audit trail** — see the sibling `pallet_series_audit` module, which logs every series operation **before** it executes so the path of destruction is traceable even when data is gone.

---

## 5. The `x_studio_` Field Convention

Many custom fields on `stock.move.line`, `stock.quant`, and `stock.picking` were originally created in **Odoo Studio**, so they all carry the `x_studio_` prefix. **The line-number field is literally named `x_studio_` with a trailing underscore** (string `"#"`). This is not a typo.

Frequently-touched move-line fields (used throughout this module and others):

| Field | Type | Meaning |
|---|---|---|
| `x_studio_` | Integer | Line number "#" |
| `x_studio_pallet_series_id` | Char | Current assigned series ID |
| `x_studio_container_number` | Char | Container reference |
| `x_studio_production_date` / `x_studio_expiration_date` | Date | Product dates |
| `x_studio_truck_time` / `x_studio_start_time` / `x_studio_end_time` | Datetime | Operation timestamps |
| `x_studio_truck_number` | Char | Truck plate |
| `x_studio_building_dropped` | Char | Building where pallet was dropped |
| `x_studio_2nd_uom` / `x_studio_total_units` | Float | Secondary qty (boxes/sacks) / unit count (heads) |
| `x_studio_quantity_uom` / `x_studio_min_quantity_uom` | M2O uom.uom | UOM references |
| `x_studio_return_count` | Integer | Return counter |
| `x_studio_number_of_lines` | Integer | (on stock.move) requested line count for regenerate |

Non-studio fields added by this module on `stock.move.line`: `original_pallet_series_id`, `adjusted_quantity` (KG), `bf_pallet_char`, `original_record_reference`, `adjustment_batch_number`.

---

## 6. FastEncodeRR — the "Magic Wizard"

File: `wizard/FastEncodeRR.py` · Models: `stock.move.line.fast_encode_rr` (header) + `stock.move.line.fast_encode_rr.line` (lines)

A bulk editor that lets the user rewrite many RR move lines at once — pallet series, package, location, dates, quantities. The flow handles pallet **grouping** (multiple lines per package share one series), **winner election** (smallest `original_pallet_series_id` wins), and **pool reconciliation** (recycled / restored / newly generated).

Key behavior:
- `transfer_id` is `fields.Integer` (picking ID), **not** a Many2one. Never call `.id` on it.
- Writes happen with `skip_pallet_series_sync=True` in context so the audit module / line-write override doesn't double-log.
- Context keys `audit_picking_id` and `audit_source='wizard'` are injected for the audit trail.
- Blast-freeze (BF) operations skip the complex grouping logic via an early-return path.

---

## 7. Void & Return Workflow (high-level)

```
RR (done) ──void_transfer()──► creates draft outgoing "void WR" that reverses the RR
                              user validates void WR → both marked voided, PKR archived

WR (done) ──void_transfer()──► creates draft "void return RR" via Return Packages wizard
                              return_reason = 'Void Transfer'
                              user validates → both marked voided
```

Flag fields on `stock.picking`: `x_studio_voided`, `is_void_wr`, `void_source_picking_id`, `is_void_return`, `x_studio_for_revision`, `x_studio_edit_record`.

Pre-conditions enforced before allowing a void: quants still at dest, no dependent done WRs, no active returns.

---

## 8. Location Domains

The module heavily computes `allowed_value_ids` on `stock.picking` to filter the picker UI:

- **RR (incoming)**: partner's preferred locations + warehouse locations, excluding blast freezers
- **WR (outgoing)**: only locations where the partner already has quants
- **BF (blast freeze)**: only locations flagged as blast freezer

Helper: `operation_type_checker(picking_type_id) → (is_blast_freeze, is_receiving)`. Computed field `vifel_type_of_operation` returns one of `'RR'`, `'WR'`, `'BFRR'`, `'BFWR'`.

---

## 9. Reports (in this module)

`reports/` contains both the XML `ir.actions.report` definitions and the Python generators:

| File | Output | Notes |
|---|---|---|
| `client_summary_xlsx.py` | XLSX | Per-client inventory summary |
| `count_sheet.py` + `count_sheet_view.xml` | XLSX / HTML | Physical count sheet |
| `inventory_summary_view.xml` | HTML | QWeb HTML inventory summary |

For deeper XLSX work see the `report_xlsx` module (this module depends on it).

---

## 10. Security

`security/ir.model.access.csv` defines ACLs for all **wizard / transient models** (return.package.wizard, select_quant.wizard, stock.move.line.fast_encode_rr, stock.quant.correction.*, stock.quant.adjustment.request/line, etc.). Most are granted to `base.group_user` or `stock.group_stock_user`; adjustment-line manager ops require `stock.group_stock_manager`.

There is also an `inventory_super_admin` group used for unlock/lock toggles on validated RR/WR — referenced from views.

---

## 11. Common Pitfalls (read before editing)

1. **Field name `x_studio_`** is real — trailing underscore. Access via `line.x_studio_` or `line['x_studio_']`.
2. **`original_pallet_series_id` is set once, never overwritten.** It is the canonical origin used by restore logic.
3. **Don't write `result_package_id` / `location_dest_id` together with other move-line edits** unless you're already inside a wizard with `skip_pallet_series_sync` — it triggers `_action_assign` → `_do_unreserve` → data loss.
4. **`unused_pallet_series_ids` is a JSON list of INTEGERS**, not strings. Always `json.loads` defensively and re-sort.
5. **Raw-SQL escape hatch (`_write_swap_product`)** exists deliberately. Don't "fix" it to use the ORM unless you've solved the cascade-delete problem.
6. **`widget="html"` crashes Odoo 17** (WYSIWYG asset load). Use text fields with tree/list views.
7. **Module category XML ID**: use `base.module_category_inventory_inventory`, not `stock.module_category_inventory_inventory` (the latter does not exist).
8. **Server Action #347** ("Assign Pallet Series") is a Studio-created server action that operates on RR pickings. The audit module injects context onto its button via XML inheritance.

---

## 12. Database / Run Info

- **DB**: `vifel_03_20_2026_02` on `localhost:5432`
- **DB user**: `openpg` / `openpgpwd`
- **Odoo config**: `c:\Odoo17E\server\odoo.conf`
- **Upgrade**: `python odoo-bin -c odoo.conf -u multiple_relocation --stop-after-init`

---

## 13. Where to read next

- `../multiple_relocation/CONTEXT.md` — original long-form context inside the module (deeper pool examples, wizard internals, lessons-learned)
- `pallet_series_audit_AI_CONTEXT.md` — sibling module that traces all pallet operations
- `pallet_kilos_record_model_AI_CONTEXT.md` — pallet/kilos ledger that consumes RR/WR data
- `stock_quant_history_AI_CONTEXT.md` — point-in-time quant snapshots used by occupancy reports

---

## 14. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> This document is a **living architectural map**. Whenever you make a change that affects this module's behavior, public surface, or invariants — or whenever the user tells you the requirements have changed — you must **update this file in the same change** so it stays accurate. Specifically:
>
> - **New / removed / renamed model, field, method, wizard, report, view, or security group** → update the relevant section AND the "Where Things Live" tree.
> - **Behavioral change** to pallet-series pool logic, void/return workflow, or the `_action_assign` workaround → update sections 3, 4, and 7 (and add a new pitfall in section 11 if it bites).
> - **New dependency** in `__manifest__.py` → update the header block at the top.
> - **New `x_studio_*` field added by Studio** that this code reads or writes → add it to section 5.
> - **Database, config, or upgrade command changes** → update section 12.
>
> Keep the tone tight and architectural. Do not paste full method bodies — link/refer to file paths with line numbers instead. Update the **Last updated** date at the top each time. If a section becomes inaccurate and you don't know the correct answer, mark it `⚠️ NEEDS VERIFICATION` rather than deleting it.
