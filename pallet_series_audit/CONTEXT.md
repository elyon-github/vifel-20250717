# Pallet Series Audit Module — AI Context Document

> **Module**: `pallet_series_audit`  
> **Odoo Version**: 17 Enterprise  
> **Location**: `addons/custom_addons/consultant-test/pallet_series_audit/`  
> **Depends on**: `multiple_relocation`  
> **Last Updated**: March 20, 2026  

---

## Purpose

This module provides a **complete audit trail** for every pallet series ID operation that happens on Receiving Report (RR) transfers. It was built primarily to debug and trace the root cause of **pallet series IDs "disappearing"** during standard Odoo operations (see the `multiple_relocation/CONTEXT.md` for the full root cause analysis).

It tracks: assignments, reassignments, clears, restores, pool push/pull, generation of new series, line deletions, pallet package changes — everything that touches a `x_studio_pallet_series_id` on a `stock.move.line`.

---

## Architecture Overview

```
┌───────────────────────────────────────────────┐
│               stock.picking (RR)              │
│  ┌─────────────────────────────────────────┐  │
│  │  Smart Button: "Pallet Audit"           │  │
│  │  (visible only to group_pallet_audit)   │  │
│  └────────────────┬────────────────────────┘  │
└───────────────────┼───────────────────────────┘
                    │ One audit header per RR
                    ▼
┌───────────────────────────────────────────────┐
│          pallet.series.audit (Header)         │
│  picking_id (unique), partner_id              │
│  event_count, unique_series_count             │
│  ┌─────────────────────────────────────────┐  │
│  │  line_ids → pallet.series.audit.line    │  │
│  │  (one record per event, chronological)  │  │
│  └─────────────────────────────────────────┘  │
│  [Open Visual Timeline] → OWL JS Dashboard   │
└───────────────────────────────────────────────┘
```

### How Events Get Logged

The central logging API is `PalletSeriesAudit.log_event(picking_id, vals)`. It is called from **inherited model overrides** that intercept operations:

| Override Location | What It Catches |
|---|---|
| `stock.move.line.write()` | Series changes, pallet package changes |
| `stock.move.line.unlink()` | Line deletions with series on them |
| `stock.move.regenerate_move_lines()` | Bulk clear before regeneration |
| `res.partner.push_unused_pallet()` | Series returned to pool |
| `res.partner.get_smallest_pallet_series_ids()` | Series consumed from pool |
| `res.partner.generate_new_pallet_series_id()` | Brand new series generated |
| `res.partner.get_pallet_series_by_id()` | Exact series restored from pool |
| `FastEncodeRR.action_confirm()` | Context injection for wizard source |

### Context Keys (Important)

The audit system uses `self.env.context` to propagate info across nested calls:

| Key | Type | Purpose |
|---|---|---|
| `audit_picking_id` | `int` | Which picking to log against |
| `audit_source` | `str` | What triggered the event (see Source Types) |
| `skip_pallet_series_sync` | `bool` | Prevents double-logging when wizard writes |

---

## Event Types

| Type | Label | Color (Kanban) | When Logged |
|---|---|---|---|
| `assigned` | Assigned | 10 (green) | First series assignment to a blank line |
| `reassigned` | Reassigned | 4 (blue) | Series changed but not restored to original |
| `cleared` | Cleared | 1 (red) | Series removed (set to falsy) |
| `synced` | Synced | 4 (blue) | Series synced from sibling in same pallet group |
| `restored` | Restored | 4 (blue) | Series reset back to `original_pallet_series_id` |
| `recycled` | Recycled | 4 (blue) | Reserved for future use |
| `pushed_to_pool` | Pushed to Pool | 2 (orange) | Series returned to partner's unused pool |
| `pulled_from_pool` | Pulled from Pool | 10 (green) | Series consumed from partner's unused pool |
| `generated_new` | Generated New | 10 (green) | Brand new series from partner's counter |
| `line_deleted` | Line Deleted | 1 (red) | Move line with series was deleted |
| `pallet_assigned` | Pallet Changed | 3 (yellow) | `result_package_id` changed on a move line |

## Source Types

| Source | Label | What Triggers It |
|---|---|---|
| `server_action` | Assign Pallet Series (SA) | Server Action #347 button on RR |
| `wizard` | Magic Wizard | FastEncodeRR wizard confirm |
| `generate_lines` | Generate Lines | Regenerate move lines button |
| `write_override` | Pallet Change | Direct `stock.move.line.write()` |
| `ondelete` | Line Delete Handler | `stock.move.line.unlink()` |
| `regenerate` | Regenerate Move Lines | `stock.move.regenerate_move_lines()` |
| `pool_operation` | Pool Operation | `res.partner` pool methods |
| `system` | System | Background/automatic operations |

---

## File-by-File Reference

### Models

#### `models/pallet_series_audit.py`
- **PalletSeriesAudit** (`pallet.series.audit`): Header model, one per RR.
  - `log_event(picking_id, vals)`: Central API. Auto-creates header on first call. Skips done/cancelled/non-RR/returns. Uses `sudo()`. Has race condition protection (try/except around create with re-search fallback).
  - `action_view_timeline()`: Opens the OWL client action dashboard.
  - `_compute_stats()`: Computes `event_count`, `unique_series_count`, `last_event_date`.
- **PalletSeriesAuditLine** (`pallet.series.audit.line`): Event line model.
  - Key fields: `pallet_series_id`, `event_type`, `source`, `line_number`, `move_line_id`, `result_package_name`, `previous_series`, `new_series`, `pool_delta`, `pool_size_after`, `notes`.
  - Computed: `kanban_color`, `event_label`, `series_display`.

#### `models/stock_move_line.py`
- Inherits `stock.move.line`. Contains the heaviest audit logic.
- `_safe_line_number(line)`: Safe accessor for `x_studio_` (line #) with try/except.
- `write(vals)`: Snapshots old series + old package BEFORE `super().write()`. Post-write detects series changes AND pallet package changes separately. Logs appropriate event type.
- `unlink()`: Before deletion, logs `line_deleted` for any line with a pallet series.

#### `models/stock_move.py`
- Inherits `stock.move`.
- `regenerate_move_lines(counter)`: Logs `cleared` event listing all series being removed, injects `regenerate` source context.

#### `models/stock_picking.py`
- Inherits `stock.picking`.
- `pallet_audit_count`: Computed field for smart button.
- `action_view_pallet_audit()`: Opens audit record or empty list.

#### `models/res_partner.py`
- Inherits `res.partner`. Overrides 4 pool methods:
  - `push_unused_pallet()` → logs `pushed_to_pool`
  - `get_smallest_pallet_series_ids()` → logs `pulled_from_pool` per series
  - `generate_new_pallet_series_id()` → logs `generated_new`
  - `get_pallet_series_by_id()` → logs `pulled_from_pool` with exact/fallback note

#### `wizard/fast_encode_rr.py`
- Inherits `stock.move.line.fast_encode_rr`.
- `action_confirm()`: Injects `audit_picking_id` and `audit_source='wizard'` into context before calling `super()`.

### Views

#### `views/audit_views.xml`
- Search view with filters by event type, source, series, picking.
- Kanban view: color-coded cards ordered by `event_date asc`.
- Tree view: read-only with decorations (success/danger/info/warning based on event type).
- Form view: read-only detail with groups for Event, Details, Pool, Notes.
- Header form: embedded event tree, "Open Visual Timeline" button.
- **3 menu items** under Inventory → Pallet Series Audit (all restricted to `group_pallet_audit`).
- **3 actions**: audit headers list, audit lines (all), series trace action.

#### `views/stock_picking_views.xml`
- Smart button `oe_stat_button` with `fa-history` icon, restricted to `group_pallet_audit`.
- Context injection: adds `audit_source` and `audit_picking_id` to the SA #347 button on RR form.

### Security

#### `security/security.xml`
- Group: `group_pallet_audit` under category `base.module_category_inventory_inventory`.
- Admin (`base.user_admin`) auto-added.

#### `security/ir.model.access.csv`
- `group_pallet_audit` → read-only on both models.
- `stock.group_stock_manager` → full CRUD on both models.

### Static Assets (OWL Timeline Dashboard)

#### `static/src/js/timeline_dashboard.js`
- **OWL Component**: `PalletSeriesTimeline`, registered as `pallet_series_audit.timeline_dashboard` client action.
- Loads audit header + all event lines via ORM.
- **4 view modes**: Timeline, By Series, By Line #, By Pallet.
- **Filters**: Event type dropdown, source dropdown, text search (series, pallet, line, notes).
- **Quick stats bar**: Clickable event type badges with counts.
- **Collapsible groups** in grouped views.
- **UTC+8 timezone**: All dates converted from Odoo UTC to UTC+8 display.
- Key maps: `EVENT_COLORS` (11 event types → bg/fg/icon/label), `SOURCE_LABELS` (8 sources).

#### `static/src/xml/timeline_dashboard.xml`
- Header: back button, RR name, partner badge, status badge, 4 stats (Events, Series, Pallets, Lines).
- Quick stats bar, toolbar with 4 mode buttons + 2 filter dropdowns + search.
- Legend with color dots + UTC+8 note.
- Active filter indicator.
- Timeline mode: vertical dot-line with cards.
- Grouped modes: collapsible group cards with mini-rows.

#### `static/src/scss/timeline_dashboard.scss`
- Full styling for all dashboard elements.
- `.psa-timeline-dashboard` has `overflow-y: auto` for vertical scrolling.

---

## Manifest (`__manifest__.py`)

```python
{
    'name': 'Pallet Series Audit',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Audit trail for pallet series ID operations on RR transfers',
    'depends': ['multiple_relocation'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/audit_views.xml',
        'views/stock_picking_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pallet_series_audit/static/src/js/**/*',
            'pallet_series_audit/static/src/xml/**/*',
            'pallet_series_audit/static/src/scss/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
```

---

## Known Gotchas / Lessons Learned

1. **`widget="html"` crashes Odoo 17**: Using `widget="html"` on a field triggers WYSIWYG editor loading which crashes with `web_editor.backend_assets_wysiwyg.min.js` error. Never use it.

2. **`x_studio_` is the actual field name**: The line number "#" field on `stock.move.line` is literally `x_studio_` — yes, with trailing underscore. Defined as `fields.Integer(string="#", group_operator=False)`.

3. **Race condition on first log**: Two concurrent writes can both try to create the header. Fixed with try/except + savepoint rollback + re-search fallback in `log_event()`.

4. **`transfer_id` on FastEncodeRR is `fields.Integer`**: Not a Many2one. Use it directly as an int, not `self.transfer_id.id`.

5. **Category XML ID**: Must use `base.module_category_inventory_inventory`, NOT `stock.module_category_inventory_inventory`.

6. **OWL template registration**: The JS component uses `static template = "pallet_series_audit.TimelineDashboard"` which must match the `t-name` in the XML template exactly.

7. **Browser cache**: After any JS/XML/SCSS change, user must clear browser cache (`Ctrl+Shift+Delete`) or the old assets remain.

8. **Upgrade command**: `python odoo-bin -c odoo.conf -u pallet_series_audit --stop-after-init`
