# `pallet_series_audit` — AI Context Document

> **Module path**: `addons/custom_addons/consultant-test/pallet_series_audit/`
> **Odoo version**: 17 Enterprise
> **Author**: Mark Angelo S. Templanza
> **Depends on**: `multiple_relocation`
> **Last updated**: 2026-05-16

---

## 1. Purpose (1-paragraph elevator pitch)

`pallet_series_audit` is a **forensic logging layer** that captures every operation that touches an `x_studio_pallet_series_id` on a `stock.move.line` — assignments, reassignments, clears, restores, deletions, package changes, and pool push/pull events on `res.partner`. It exists primarily to debug the "**pallet series disappearing**" bug documented in `multiple_relocation` (where standard Odoo's `_action_assign → _do_unreserve` deletes move lines and erases their custom fields). The audit log is **append-only**, written *before* each operation runs (so even if data is destroyed there is a record of what happened), and is visualized via a dedicated **OWL timeline dashboard**.

---

## 2. Where Things Live

```
pallet_series_audit/
├── __manifest__.py
├── CONTEXT.md                                # Original verbose context — read for deep dives
├── models/
│   ├── pallet_series_audit.py                # Header (pallet.series.audit) + Line (pallet.series.audit.line)
│   ├── res_partner.py                        # Wraps 4 pool methods to log pool events
│   ├── stock_move.py                         # Wraps regenerate_move_lines() to log bulk clears
│   ├── stock_move_line.py                    # Wraps write() / unlink() — the heaviest hook
│   └── stock_picking.py                      # Smart button: pallet_audit_count + action_view_pallet_audit
├── wizard/fast_encode_rr.py                  # Injects context into FastEncodeRR.action_confirm
├── views/
│   ├── audit_views.xml                       # Header form / kanban / tree / search + 3 menus + actions
│   └── stock_picking_views.xml               # Smart button + context injection on SA #347 button
├── security/
│   ├── security.xml                          # group_pallet_audit (under base.module_category_inventory_inventory)
│   └── ir.model.access.csv                   # group_pallet_audit RO, stock.group_stock_manager full
├── data/cron.xml                             # (cron declarations — see section 8)
└── static/src/
    ├── js/timeline_dashboard.js              # OWL component + client action
    ├── xml/timeline_dashboard.xml            # OWL template (t-name=pallet_series_audit.TimelineDashboard)
    └── scss/timeline_dashboard.scss
```

Static assets are loaded via globbed bundles (`static/src/js/**/*`, `xml/**/*`, `scss/**/*`) in `web.assets_backend`.

---

## 3. Data Model

### `pallet.series.audit` (header)
One row per RR picking. Created lazily on first event via `log_event()`.

| Field | Type | Notes |
|---|---|---|
| `picking_id` | M2O `stock.picking` | **Unique** — one audit header per RR |
| `partner_id` | M2O `res.partner` | Owner — denormalized for filtering |
| `line_ids` | O2M `pallet.series.audit.line` | Chronological events |
| `event_count`, `unique_series_count`, `last_event_date` | computed | For kanban / list display |

Key methods:
- `log_event(picking_id, vals)` — **central API**. `@api.model`, uses `sudo()`, auto-creates the header on first call, has try/except + re-search fallback for the create-race condition.
- `log_event` skips events when the picking is **done / cancelled / non-RR / a return** (no point logging if no further changes are expected).
- `action_view_timeline()` — opens the OWL client action `pallet_series_audit.timeline_dashboard`.

### `pallet.series.audit.line` (event)
One row per event.

| Field | Type | Notes |
|---|---|---|
| `audit_id` | M2O header | parent |
| `event_type` | Selection | see [Event Types](#4-event-types--source-types) |
| `source` | Selection | see [Source Types](#4-event-types--source-types) |
| `pallet_series_id` | Char | The series ID being acted on |
| `previous_series`, `new_series` | Char | For reassignments / restores |
| `line_number` | Integer | Mirror of `stock.move.line.x_studio_` |
| `move_line_id` | M2O `stock.move.line` | (may dangle after unlink — that is OK) |
| `result_package_name` | Char | Pallet (package) name |
| `pool_delta`, `pool_size_after` | Integer | For pool push/pull events |
| `notes` | Text | Free-form context |
| `event_date` | Datetime | Chronological ordering |
| `kanban_color`, `event_label`, `series_display` | computed | Display helpers |

---

## 4. Event Types & Source Types

### Event types (11)
| Type | Color | When |
|---|---|---|
| `assigned` | 10 (green) | First series assignment to a blank line |
| `reassigned` | 4 (blue) | Series changed but not restored to its original |
| `cleared` | 1 (red) | Series removed (set to falsy) |
| `synced` | 4 (blue) | Series copied from a sibling in the same pallet group |
| `restored` | 4 (blue) | Series reset back to `original_pallet_series_id` |
| `recycled` | 4 (blue) | Reserved for future use |
| `pushed_to_pool` | 2 (orange) | Series returned to partner's unused pool |
| `pulled_from_pool` | 10 (green) | Series consumed from partner's unused pool |
| `generated_new` | 10 (green) | Brand-new series minted from partner's counter |
| `line_deleted` | 1 (red) | Move line with a series was deleted |
| `pallet_assigned` | 3 (yellow) | `result_package_id` changed on a move line |

### Source types (8)
| Source | Trigger |
|---|---|
| `server_action` | Server Action #347 button on RR (label "Assign Pallet Series") |
| `wizard` | FastEncodeRR confirm |
| `generate_lines` | Regenerate Lines button |
| `write_override` | Direct `stock.move.line.write()` |
| `ondelete` | `stock.move.line.unlink()` |
| `regenerate` | `stock.move.regenerate_move_lines()` |
| `pool_operation` | `res.partner` pool methods |
| `system` | Background / automatic |

---

## 5. How Events Get Logged (interception points)

| Override | What it catches | Notes |
|---|---|---|
| `stock.move.line.write()` | Series changes AND pallet-package changes | Snapshots old series / old package **before** `super().write()`, then diffs and emits the appropriate event(s). Respects `skip_pallet_series_sync` context to avoid double-logging from wizards. |
| `stock.move.line.unlink()` | Line deletion with series on it | Logs `line_deleted` for each line with a non-empty `x_studio_pallet_series_id` BEFORE deletion runs. |
| `stock.move.regenerate_move_lines(counter)` | Bulk pre-regeneration clear | Logs one `cleared` event listing all series that are about to be removed, with `source='regenerate'`. |
| `res.partner.push_unused_pallet()` | Series returned to pool | Logs `pushed_to_pool` with `pool_size_after`. |
| `res.partner.get_smallest_pallet_series_ids()` | Pool consumption | Logs one `pulled_from_pool` per series returned. |
| `res.partner.generate_new_pallet_series_id()` | Brand-new series | Logs `generated_new`. |
| `res.partner.get_pallet_series_by_id()` | Exact-match restore | Logs `pulled_from_pool` with a note indicating exact-match vs fallback. |
| `FastEncodeRR.action_confirm()` | Wizard entry point | Injects `audit_picking_id` + `audit_source='wizard'` into context, then `super()`. |

The `_safe_line_number(line)` helper wraps access to the literally-named `x_studio_` field with try/except.

---

## 6. Context Propagation (critical to understand)

Three context keys flow through `self.env.context`:

| Key | Type | Purpose |
|---|---|---|
| `audit_picking_id` | `int` | Which RR to log against. Required by `log_event()`. |
| `audit_source` | `str` | One of the 8 source types — labels the trigger. |
| `skip_pallet_series_sync` | `bool` | Wizards / bulk writers set this so `stock.move.line.write()` does NOT re-log already-handled events. |

Most overrides accept these from `self.env.context.get(...)` with sensible defaults (`'system'` for missing source, `False` for missing picking → skip log).

---

## 7. UI Surfaces

### Smart button on RR form
`views/stock_picking_views.xml` injects an `oe_stat_button` with `fa-history` icon onto `stock.picking` form. Visible only to `group_pallet_audit`. Shows `pallet_audit_count` events; clicking calls `action_view_pallet_audit()`.

### Context injection on SA #347
The same XML inherits the "Assign Pallet Series" server-action button (`name="347"`) and rewrites its `context` attribute to inject `{'audit_source': 'server_action', 'audit_picking_id': id}`.

### Audit views (`views/audit_views.xml`)
- **Search** with filters by event type, source, series, picking
- **Kanban** color-coded by event type, ordered `event_date asc`
- **Tree** read-only with row decorations (success/danger/info/warning) driven by event_type
- **Form** read-only with grouped sections (Event / Details / Pool / Notes)
- **Header form** with embedded event tree and an "Open Visual Timeline" button → opens the OWL dashboard
- **3 menu items** under Inventory → Pallet Series Audit, all restricted to `group_pallet_audit`

### OWL Timeline Dashboard (`static/src/js/timeline_dashboard.js`)
Client-action component `pallet_series_audit.timeline_dashboard` rendering template `pallet_series_audit.TimelineDashboard`. Features:
- 4 view modes: **Timeline**, **By Series**, **By Line #**, **By Pallet**
- Filters: event-type dropdown, source dropdown, free-text search (series / pallet / line / notes)
- Quick-stats bar with clickable badges
- Collapsible groups in grouped modes
- UTC+8 timezone display (Odoo stores UTC)
- Maps: `EVENT_COLORS` (11 types → bg/fg/icon/label), `SOURCE_LABELS` (8 sources)

---

## 8. Cron

`data/cron.xml` declares scheduled actions for the audit module (e.g. periodic housekeeping / aggregate refresh). When modifying cron behavior, check the actual XML for current `interval_*`, `nextcall`, and `code` fields — they are environment-dependent and may be tuned for prod vs dev.

---

## 9. Security

| Group | Access |
|---|---|
| `group_pallet_audit` (custom, under `base.module_category_inventory_inventory`) | RO on both `pallet.series.audit` and `pallet.series.audit.line`; gates the smart button and menus. Admin (`base.user_admin`) is auto-added. |
| `stock.group_stock_manager` | Full CRUD on both models. |

ACLs live in `security/ir.model.access.csv`.

---

## 10. Common Pitfalls

1. **`widget="html"` crashes Odoo 17** (`web_editor.backend_assets_wysiwyg.min.js` error). Don't use it on any audit field. Tree/list views are safer.
2. **`x_studio_` is a real field name** with trailing underscore (line number "#"). The `_safe_line_number` helper exists to wrap access defensively.
3. **Race condition on first-time header creation** is handled via savepoint + re-search fallback in `log_event()`. Don't remove that pattern even if it looks "defensive enough" — concurrent SA #347 + wizard runs trip it.
4. **`transfer_id` on FastEncodeRR is `fields.Integer`**, not a Many2one. The wizard hook in this module uses it directly as an int.
5. **Module category XML ID**: `base.module_category_inventory_inventory`, NOT `stock.module_category_inventory_inventory` (the latter does not exist — using it crashes module install).
6. **OWL template `t-name` must match `static template`** declared on the JS class (`"pallet_series_audit.TimelineDashboard"`). A mismatch silently hides the dashboard.
7. **Browser cache** — after any JS/XML/SCSS edit, hard-reload (`Ctrl+Shift+R`) or `Ctrl+Shift+Delete`. Old assets stick.
8. **Don't make events writable from the UI.** The audit table is append-only by design; any tool that mutates rows defeats its forensic purpose.
9. **Skipping logs**: `log_event` is silently a no-op for done/cancelled/non-RR/return pickings. If a logged event seems missing, check the picking state and type first.

---

## 11. Database / Run Info

- **Upgrade**: `python odoo-bin -c odoo.conf -u pallet_series_audit --stop-after-init`
- **DB**: `vifel_03_20_2026_02` on `localhost:5432`
- After any JS/SCSS/XML change, clear browser cache.

---

## 12. Where to read next

- `multiple_relocation_AI_CONTEXT.md` — the parent module whose operations are being audited; understand the pool methods and `x_studio_` field landscape first
- `../pallet_series_audit/CONTEXT.md` — original, file-by-file reference inside the module (more verbose than this doc)
- `pallet_kilos_record_model_AI_CONTEXT.md` — sibling ledger that also tracks RR/WR outcomes (different angle: aggregates, not events)

---

## 13. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> This audit module is intentionally surgical — every override here was added because something silently broke. Whenever you modify it, or whenever the user tells you that auditing requirements have changed, update this document in the **same change**. Specifically:
>
> - **New event type or source type** → update section 4 and the relevant intercept in section 5.
> - **New override** on `stock.move.line`, `stock.move`, `stock.picking`, `res.partner`, or any wizard → add a row to the table in section 5 and any propagation changes to section 6.
> - **Change to `log_event()`** (signature, skip rules, race handling) → update sections 3 and 10.
> - **OWL dashboard changes** (new view mode, new filter, new event color) → update section 7.
> - **Security group / ACL change** → update section 9.
> - **Cron declaration change** in `data/cron.xml` → update section 8 with the new behavior.
> - **New manifest dependency or asset bundle** → update the header block + section 2.
>
> Keep the tone tight and architectural. Use file paths and method names; don't paste full method bodies. Update the **Last updated** date at the top each time. If a section becomes uncertain, mark it `⚠️ NEEDS VERIFICATION` rather than removing it.
