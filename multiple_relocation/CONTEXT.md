# Multiple Relocation Module — AI Context Document

> **Module**: `multiple_relocation`  
> **Odoo Version**: 17 Enterprise  
> **Location**: `addons/custom_addons/consultant-test/multiple_relocation/`  
> **Depends on**: `base`, `stock`, `web`, `report_xlsx`  
> **Last Updated**: March 20, 2026  

---

## What This Module Does

This is the **core custom inventory management module** for VIFEL cold storage operations. It handles:

- Multi-location stock transfers (Receiving Reports, Withdrawal Reports)
- Pallet series lifecycle with pool-based allocation
- Blast freezer operations
- Void/adjustment/return workflows
- Pallet kilos record integration
- Custom reporting (delivery slips, count sheets, inventory summaries)

It is a **large, complex module** — this document focuses on the areas most likely to cause confusion or bugs, especially the **pallet series system**.

---

## THE CRITICAL BUG: Pallet Series Disappearing

### Root Cause (Confirmed)

When a pallet series ID is assigned to a `stock.move.line` and then certain Odoo standard operations run, the series **disappears** because Odoo **deletes and recreates move lines**.

**The exact chain**:

```
1. User assigns pallet_series_id to move lines (via SA #347 or wizard)
2. The assignment also writes location_dest_id or result_package_id
3. This triggers Odoo's standard _action_assign() on the stock.move
4. _action_assign() calls _do_unreserve() first
5. _do_unreserve() DELETES the existing move lines 
   (because the reserved quant no longer matches after location/package change)
6. All custom x_studio_ fields on those move lines are LOST FOREVER
7. _action_assign() creates BRAND NEW move lines with blank custom fields
8. User sees: "my pallet series disappeared!"
```

**The key method chain** in standard Odoo (`odoo/addons/stock/models/stock_move.py`):
```
stock.move._action_assign()
  → stock.move._do_unreserve()    # DELETES existing move lines
  → stock.move._update_reserved_quantity()  # Creates NEW blank move lines
```

### Where Custom Fields Live

All custom fields on `stock.move.line` use `x_studio_` prefix (Odoo Studio origin):

| Field | Type | Purpose |
|---|---|---|
| `x_studio_` | Integer | Line number "#" (yes, the name is literally `x_studio_` with trailing underscore) |
| `x_studio_pallet_series_id` | Char | Current pallet series (e.g., "JBL-000005") |
| `x_studio_quantity_uom` | M2O uom.uom | Secondary UOM (boxes, sacks, etc.) |
| `x_studio_min_quantity_uom` | M2O uom.uom | Minimum UOM (heads, units) |
| `x_studio_container_number` | Char | Container ID |
| `x_studio_production_date` | Date | Production date |
| `x_studio_expiration_date` | Date | Expiration date |
| `x_studio_truck_time` | Datetime | Truck arrival |
| `x_studio_start_time` | Datetime | Processing start |
| `x_studio_end_time` | Datetime | Processing end |
| `x_studio_truck_number` | Char | Truck plate number |
| `x_studio_building_dropped` | Char | Building reference |
| `x_studio_2nd_uom` | Float | Quantity in boxes/sacks |
| `x_studio_total_units` | Float | Quantity in heads/units |
| `x_studio_return_count` | Integer | Return counter |
| `x_studio_number_of_lines` | Integer | How many lines per move |

Also on `stock.move.line` (non-studio, added by this module):
| Field | Type | Purpose |
|---|---|---|
| `original_pallet_series_id` | Char | Snapshot of first-assigned series (never changes) |
| `adjusted_quantity` | Float | Weight in KG |
| `bf_pallet_char` | Char | Blast freeze pallet identifier |
| `original_record_reference` | M2O stock.picking | Source RR reference |
| `adjustment_batch_number` | Char | Batch grouping for adjustments |

### Current Workaround

The `_write_swap_product()` method in `stock.move` uses **raw SQL** to detach/reattach move lines during product changes, avoiding the ORM cascade-delete:

```python
def _write_swap_product(self, vals):
    # Detach move_lines from move (bypass ORM delete cascade)
    self.env.cr.execute("UPDATE stock_move_line SET move_id = NULL WHERE move_id = %s", [self.id])
    # Write product_id change to move
    super().write(vals)
    # Re-attach with new product
    self.env.cr.execute("UPDATE stock_move_line SET move_id = %s, product_id = %s WHERE ...")
```

This pattern preserves custom fields. **A similar approach should be applied** to the pallet series assignment flow if the disappearing bug persists.

### The Audit Module Solution

The `pallet_series_audit` module (separate module, depends on this one) was built to:
1. **Log every operation** before it happens (so even if data is lost, we have a record)
2. **Trace the exact sequence** of events that led to a series being lost
3. Provide a visual **OWL timeline dashboard** for debugging

See `pallet_series_audit/CONTEXT.md` for full details on that module.

---

## Pallet Series Pool System

### How Series IDs Are Formatted

Format: `{CLIENT_UNIQUE_CODE}-{COUNTER:06d}`  
Examples: `JBL-000001`, `BGZ-000042`, `CFC-000123`

### Where Pool Data Lives

On `res.partner` (the client/owner):

| Field | Type | Purpose |
|---|---|---|
| `x_studio_client_unique_code_1` | Char | Prefix (e.g., "JBL") |
| `x_studio_pallet_series_id` | Integer | Running counter (next series #) |
| `unused_pallet_series_ids` | JSON (Text) | Array of available integer IDs, sorted ascending |

### Pool Methods (on `res.partner`, defined in `models/models.py`)

#### `push_unused_pallet(pallet_series_id)`
- Extracts integer from full ID: `"JBL-000005"` → `5`
- Adds to `unused_pallet_series_ids` array if not already present
- Sorts array ascending
- Called when: lines deleted, regenerated, series cleared

#### `get_smallest_pallet_series_ids(count)`
- Pops first `count` items from the sorted unused pool
- Formats each: `f"{prefix}-{str(num).zfill(6)}"`
- Returns list of full series IDs
- **Raises UserError** if `x_studio_client_unique_code_1` not set on partner
- Called when: assigning series to lines, restoring from pool

#### `generate_new_pallet_series_id()`
- Reads current counter from `x_studio_pallet_series_id`
- Formats: `f"{prefix}-{str(counter).zfill(6)}"`
- Increments counter on partner record
- Returns single series ID string
- Called when: pool is empty and a new series is needed

#### `get_pallet_series_by_id(pallet_series_id)`
- Searches for exact integer in unused pool
- If found: removes from pool, returns as `[formatted_id]`
- If NOT found: falls back to `get_smallest_pallet_series_ids(1)`
- Called when: restoring a specific `original_pallet_series_id`

### Pool Lifecycle Example

```
Initial state: Pool = [3, 7, 12], Counter = 15

1. Assign 3 lines:
   → get_smallest_pallet_series_ids(3) → returns JBL-000003, JBL-000007, JBL-000012
   → Pool = [], Counter = 15

2. Delete line with JBL-000007:
   → push_unused_pallet("JBL-000007") → Pool = [7]

3. Assign 1 new line:
   → get_smallest_pallet_series_ids(1) → returns JBL-000007  
   → Pool = [], Counter = 15

4. Assign 1 more (pool empty):
   → get_smallest_pallet_series_ids(1) → pool empty, calls generate_new
   → generate_new_pallet_series_id() → returns JBL-000015
   → Pool = [], Counter = 16

5. Try to restore original JBL-000003:
   → get_pallet_series_by_id("JBL-000003") → not in pool [3 was consumed in step 1]
   → Falls back to get_smallest_pallet_series_ids(1) → pool empty, generates JBL-000016
```

---

## FastEncodeRR Wizard (The "Magic Wizard")

### Location

`wizard/FastEncodeRR.py` — Model: `stock.move.line.fast_encode_rr`

### Purpose

Bulk editor for RR move lines. Users can edit pallet series, packages, locations, quantities, dates — all at once for all lines on an RR. The wizard handles complex pallet series grouping logic.

### Key Flow: `action_confirm()`

1. **Group wizard lines by pallet_id** — all lines going to the same pallet
2. **Pick winner series**: For each pallet group, find the smallest `original_pallet_series_id` as the "winner"
3. **Check existing**: If pallet already used by other (non-wizard) move lines, use their series
4. **Determine recyclable**: Series that were assigned pre-wizard but won't be used post-wizard → push to pool
5. **Restore logic**: For unique lines (solo in their pallet), try to consume their `original_pallet_series_id` from pool
6. **Generate new**: For lines flagged `needs_new_pallet_series`, pull from pool or generate fresh
7. **Write to move lines**: Apply all changes with `skip_pallet_series_sync` context (prevents audit double-logging)

### Wizard Line Pallet Sync Logic

When user changes `result_package_id` on a wizard line:

```python
_onchange_result_package_id_sync():
    1. Search sibling wizard lines with same pallet → sync series from them
    2. If no sibling, search actual stock.move.line records with same pallet → sync
    3. If unique pallet → _resolve_series_for_unique_line()
```

### Series Resolution for Unique Lines

```python
_resolve_series_for_unique_line():
    1. If original is claimed as winner by another pallet group → needs NEW
    2. If original == pre_wizard (current DB value) → restore it  
    3. If original exists in partner's unused pool → restore it
    4. Else original was consumed → needs NEW
    Returns: (series_id, needs_new_bool)
```

### Important Context Keys Set by Wizard

| Key | Value | Purpose |
|---|---|---|
| `skip_pallet_series_sync` | `True` | Prevents `stock.move.line.write()` from logging redundant events |
| `audit_picking_id` | picking ID | Tells audit module which RR to log against |
| `audit_source` | `'wizard'` | Attributes events to the wizard |

---

## Server Action #347 (Assign Pallet Series)

This is a **server action** (likely created via Odoo Studio) that runs on RR pickings. It:

1. Reads the move lines on the RR
2. For each line without a `x_studio_pallet_series_id`, assigns one from the pool
3. Groups lines by `result_package_id` (pallet) and assigns the same series to all lines in a group

The `stock_picking_views.xml` in `pallet_series_audit` injects audit context onto this button:
```xml
<attribute name="context">{'audit_source': 'server_action', 'audit_picking_id': id}</attribute>
```

---

## Stock Move: `regenerate_move_lines(counter)`

Called when user clicks "Regenerate Pallet Lines" on RR form.

```
Flow:
1. For each move line with a pallet_series_id → push to partner's unused pool
2. Clear reservations on dest location + result package
3. DELETE all existing move lines on the move
4. Create N new blank move lines (N = x_studio_number_of_lines on move)
5. Set x_studio_ (line #) sequentially starting from counter
6. Return updated counter
```

This is a **destructive operation** — all custom field data on old lines is lost. The audit module logs a `cleared` event before deletion happens.

---

## Void & Return Workflow

### RR Void
```
RR (done) → void_transfer()
  → Checks: quants exist at dest, no dependent WRs done, no active returns
  → Creates void WR (draft outgoing) that reverses the inventory
  → User validates void WR → auto-marks both as voided, archives PKR
```

### WR Void
```
WR (done) → void_transfer()
  → Creates void return RR via Return Packages wizard
  → Sets return_reason = 'Void Transfer'
  → User validates void return RR → auto-marks both as voided
```

### Key Fields
| Field | Model | Purpose |
|---|---|---|
| `x_studio_voided` | stock.picking | Manual void mark |
| `is_void_wr` | stock.picking | This is a system-created void WR |
| `void_source_picking_id` | stock.picking | Original RR that was voided |
| `is_void_return` | stock.picking | This is a void return RR |
| `x_studio_for_revision` | stock.picking | Flagged for revision |
| `x_studio_edit_record` | stock.picking | Lock/unlock toggle |

---

## Stock Quant Fields

When a move line is validated (RR completed), the quant inherits these from the move line:

| From move_line | To quant |
|---|---|
| `x_studio_pallet_series_id` | `x_studio_pallet_series_id` |
| `original_pallet_series_id` | `original_pallet_series_id` |
| `x_studio_container_number` | `x_studio_container_number` |
| `x_studio_production_date` | `x_studio_production_date` |
| `x_studio_expiration_date` | `x_studio_expiration_date` |
| `x_studio_building_dropped` | `x_studio_building_dropped` |
| `x_studio_quantity_uom` | `x_studio_quantity_uom` |
| `x_studio_min_quantity_uom` | `x_studio_min_quantity_uom` |
| `bf_pallet_char` | `bf_pallet_char` |

---

## Key Operation Types

The module distinguishes operations using `stock.picking.type`:

| Operation | Direction | Blast Freeze? | Shorthand |
|---|---|---|---|
| Receiving Report | Incoming | No | RR |
| Withdrawal Report | Outgoing | No | WR |
| BF Receiving Report | Incoming | Yes | BFRR |
| BF Withdrawal Report | Outgoing | Yes | BFWR |

Checked via:
```python
is_blast_freeze, is_receiving = self.operation_type_checker(picking.picking_type_id)
# vifel_type_of_operation computed field: returns 'BFRR', 'BFWR', 'RR', or 'WR'
```

---

## Location Domain Rules

The module heavily customizes which locations a user can pick from:

- **RR (incoming)**: Partner's preferred locations + warehouse locations, excluding blast freeze
- **WR (outgoing)**: Locations where partner has quants (occupied locations)
- **BF operations**: Only locations flagged as blast freezer

Computed by `allowed_value_ids` on `stock.picking`.

---

## File Structure

```
multiple_relocation/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── models.py              # res.partner (pool methods), product.template, 
│   │                          #   stock.location, quant.package
│   ├── stock_move.py          # stock.move extensions (regenerate, product swap)
│   ├── stock_move_line.py     UNUSED — see below (move line fields are in models.py)
│   ├── stock_picking.py       # stock.picking (void, location domains, reports)
│   └── stock_quant.py         # stock.quant extensions (custom fields)
│
├── wizard/
│   ├── __init__.py
│   ├── FastEncodeRR.py        # The "Magic Wizard" for bulk RR editing
│   ├── return_package_wizard.py  # Return packages workflow
│   ├── select_quant.py        # Quant picker for WR
│   ├── small_wizards.py       # Various utility wizards
│   ├── stock_quant_correction.py        # Quant correction wizard
│   └── stock_quant_relocation_lines.py  # Relocation wizard
│
├── views/
│   ├── views.xml              # Product, location, partner views
│   ├── search_views.xml       # Search filters
│   ├── action_views.xml       # Window actions
│   └── ...
│
├── security/
│   ├── ir.model.access.csv
│   └── security.xml           # inventory_super_admin group
│
├── reports/                   # XLSX and HTML report generators
│   ├── client_summary_xlsx.py
│   ├── count_sheet.py
│   ├── inventory_summary_view.xml
│   └── count_sheet_view.xml
│
├── static/                    # JS controllers, CSS, images
│   └── src/
│       ├── js/                # list_controller, form_controller, 
│       │                      #   magic_wizard, fast_encode_rr, many2many_tags
│       ├── css/
│       └── xml/               # OWL templates
│
├── data/
│   └── data.xml               # Static config data
│
└── CONTEXT.md                 # ← THIS FILE
```

---

## Common Pitfalls & Lessons Learned

### 1. `x_studio_` Field Name
The line number field is literally named `x_studio_` (with trailing underscore). This is **not a typo**. It was created by Odoo Studio with string="#". Access it carefully:
```python
line.x_studio_  # Works in Python
line['x_studio_']  # Dict access for dynamic lookup
```

### 2. `original_pallet_series_id` Is Set Once
This field is a Char field set when the line is first created/assigned a series. It should **never be overwritten**. It's the "true origin" used for restore logic.

### 3. `transfer_id` on FastEncodeRR Is `fields.Integer`
It stores the picking ID as a plain integer, NOT a Many2one. So:
```python
picking_id = self.transfer_id  # Correct: already an int
# NOT: self.transfer_id.id  # Wrong: would fail
```

### 4. Pool Is JSON, Not a Relational Field
`unused_pallet_series_ids` on `res.partner` is a **JSON array stored as Text**. It holds integer pallet numbers (not the full string IDs). Parse it carefully:
```python
pool = json.loads(partner.unused_pallet_series_ids or '[]')
```

### 5. Product Swap Bypasses ORM
`_write_swap_product()` uses raw SQL to avoid ORM deleting move lines when product changes. This is intentional — the ORM cascade would destroy all custom fields.

### 6. Avoid `_action_assign()` After Custom Writes
Writing `location_dest_id` or `result_package_id` on move lines can trigger `_action_assign()` → `_do_unreserve()` → lines deleted. If you need to write these fields while preserving custom data, use the wizard's approach (context-controlled, with pool push/pull).

### 7. `skip_pallet_series_sync` Context Key
When the wizard writes changes to move lines, it sets `skip_pallet_series_sync=True` in context. This tells the `stock.move.line.write()` override (from the audit module) not to apply automatic series sync logic, since the wizard already handled it.

### 8. Blast Freeze Is Simpler
BF operations skip most of the pallet series grouping/pool logic. The wizard `action_confirm()` has a separate early-return path for blast freeze that just does a simple write.

### 9. `widget="html"` Crashes Odoo 17
Never use `widget="html"` on a form field. It triggers WYSIWYG editor loading which crashes with `web_editor.backend_assets_wysiwyg.min.js` error. Use Text fields with tree/list views instead.

### 10. Category XML ID
For security groups under Inventory category, use `base.module_category_inventory_inventory`, NOT `stock.module_category_inventory_inventory` (the latter doesn't exist and causes a crash).

---

## Database Info

- **Database**: `vifel_03_20_2026_02`
- **DB Server**: localhost:5432
- **DB User**: `openpg` / `openpgpwd`
- **Odoo Config**: `c:\Odoo17E\server\odoo.conf`
- **Upgrade command**: `python odoo-bin -c odoo.conf -u multiple_relocation --stop-after-init`
