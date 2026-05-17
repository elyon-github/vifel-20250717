# Skill: Consultant-Test Onboarding Flow

> **Purpose**: This file is the **first thing an AI agent (Claude Code or equivalent) should read** when starting work on the VIFEL `consultant-test` Odoo 17 codebase in any environment — fresh dev machine, new branch, new conversation, anything.
>
> **For the user**: Keep this file pushed to the repo. To start a new AI session, grab a copy-paste prompt from [`prompts/starter_envionment_command.md`](prompts/starter_envionment_command.md) and use it as your first message. The default is just: *"Read consultant-test/Skill.md and follow the onboarding flow before answering anything else."*
>
> **For the AI agent**: Follow the steps below **in order** before answering the user's first substantive question. Do not skip steps — each one removes a class of likely mistakes you'd otherwise make from cold-start guessing.

---

## What This Repo Is

VIFEL cold-storage warehouse operations on **Odoo 17 Enterprise**, primarily a custom inventory module suite. Five custom modules under `addons/custom_addons/consultant-test/` that you will actively work on:

| Module | One-liner |
|---|---|
| `multiple_relocation` | Core custom inventory — RR/WR transfers, pallet-series pool, void/return, FastEncodeRR wizard. **Biggest, most complex.** |
| `pallet_kilos_record_model` | Per-transfer pallet/kilos ledger with per-warehouse running balances + XLSX reports |
| `pallet_series_audit` | Forensic logger for every pallet-series operation — debugs the "series disappearing" bug |
| `stock_quant_history` | Point-in-time stock.quant snapshots with cron-driven daily + backfill generation |
| `report_xlsx` | OCA library — the XLSX abstract report base class everything else inherits |

**Three modules you should NOT modify** (they're orthogonal and stable): `app_common`, `app_odoo_customize`, `odoo_calculator_tool`.

---

## The Flow (Do These In Order)

### Step 1 — Read the architectural overviews

In this order, read just enough of each to build a mental model. Don't read implementation files yet.

All AI context docs live under [`ai_context/`](ai_context/). Read in this order:

1. **[ai_context/multiple_relocation_AI_CONTEXT.md](ai_context/multiple_relocation_AI_CONTEXT.md)** — start here, everything else builds on its conventions (especially the `x_studio_*` field landscape and the pallet-series pool API on `res.partner`).
2. **[ai_context/pallet_series_audit_AI_CONTEXT.md](ai_context/pallet_series_audit_AI_CONTEXT.md)** — sibling that tracks the disappearing-series bug. Read it second because section 4 of `multiple_relocation_AI_CONTEXT.md` references it.
3. **[ai_context/pallet_kilos_record_model_AI_CONTEXT.md](ai_context/pallet_kilos_record_model_AI_CONTEXT.md)** — the ledger downstream of RR/WR validations.
4. **[ai_context/stock_quant_history_AI_CONTEXT.md](ai_context/stock_quant_history_AI_CONTEXT.md)** — snapshot system used by occupancy reports.
5. **[ai_context/report_xlsx_AI_CONTEXT.md](ai_context/report_xlsx_AI_CONTEXT.md)** — only if the task involves XLSX output. Otherwise skim.
6. **[ai_context/multi_warehouse_PLAN.md](ai_context/multi_warehouse_PLAN.md)** — open vulnerability audit + multi-warehouse migration roadmap. **Always read §1 (vulnerability table)** so you know what's known-broken before touching code.

### Step 2 — Discover the environment (do NOT assume paths)

Every developer's machine is different. Paths, OS, shell, Python interpreter, and DB credentials all vary. **Discover them — do not hardcode.** Ask the user if anything is unclear before running commands that depend on a value you guessed.

What you need to know before Step 3:

| Thing | How to discover it |
|---|---|
| **Odoo install path** | Ask the user, or look for the directory containing `odoo-bin` / `odoo.conf`. Common: `~/odoo`, `/opt/odoo`, `C:\Odoo17E\server`. |
| **`odoo.conf` location** | Usually next to `odoo-bin`, or `/etc/odoo/odoo.conf`, or `~/.odoorc`. Read it for the DB credentials. |
| **Repo path** | The user typically opens the shell in or near `addons/custom_addons/consultant-test/`. Use `pwd` (Unix) or `Get-Location` (PowerShell). |
| **Python interpreter** | The one with `psycopg2` installed — usually Odoo's own venv. Try `python --version` first; if `psycopg2` import fails, ask which interpreter to use. |
| **PG credentials** | Read from `odoo.conf` (`db_host`, `db_port`, `db_user`, `db_password`). Defaults to `localhost:5432` for a local install but never assume. |
| **Active DB name** | Run `psql -l` (see snippet below) and ask the user which one is the current target. There are usually several dated DBs. |

Sample discovery commands (adapt to the user's shell — bash vs PowerShell):

```bash
# Bash / WSL / Linux / macOS
which python && python -c "import psycopg2, sys; print(sys.executable)"
PGPASSWORD=<pw> psql -h <host> -p <port> -U <user> -l
```

```powershell
# PowerShell (Windows)
Get-Command python | Select-Object Source
$env:PGPASSWORD = "<pw>"; psql -h <host> -p <port> -U <user> -l
```

If a command fails, **stop and ask the user**. Do not try to fix the environment yourself. The most common root causes:
- Wrong working directory → ask the user to `cd` to the repo and re-run
- Odoo at a different path → ask for the absolute path to `odoo-bin`
- PG credentials changed → ask for the current `odoo.conf` snapshot
- `psycopg2` missing → ask which Python venv to use (do **not** `pip install` globally on someone else's machine)
- Wrong DB name → list DBs and ask which is active

### Step 3 — Generate the live database context dump

The hand-written context files describe the *code*. They cannot describe **Studio-created server actions, automation rules, and compute fields** because those live in the database, not the codebase. Generate a snapshot:

```bash
# 1. Open fetch_database_context.py and confirm:
#    - DATABASE_NAME matches the active DB (discovered in Step 2)
#    - DB_HOST, DB_PORT, DB_USER, DB_PASSWORD match this environment

# 2. Run it from the repo root
python fetch_database_context.py
# Or pass a DB name as an arg:
python fetch_database_context.py <db_name>

# Output: ai_context/database_context_dump.md  (git-ignored, regenerate any time)
```

**Always re-run this script** at the start of a new session, OR when:
- The user mentions a Studio field/action/automation by name and the dump is stale
- The user says they changed something in Odoo's Studio UI
- You're about to advise the user on Studio-related work
- A `compute` or `automated action` is mentioned and you don't see it in the dump

The dump is **the single source of truth for runtime Studio behavior**. It is git-ignored (see `.gitignore`) so do not commit it.

**Reading the dump effectively**: it's organized as Server Actions → Automation Rules → Compute Fields, grouped by model. If you know the model name, scan that subsection first. If you know a field/action name, search the file directly — every entry includes its module owner (`studio_customization` means Studio-created, anything else is a custom module).

### Step 4 — Find which task you're being asked to do

Once you've read the context files and have a fresh dump, briefly internalize:
- **Which module(s)** does the user's question touch?
- **What part of the lifecycle** (creation, write, validation, void, report)?
- **Is Studio behavior involved** (server actions, automations, computed fields)? If yes, the dump is mandatory reading for the relevant model.
- **Does the multi-warehouse plan flag this area** as 🔴 critical or 🟠 high vulnerability? If yes, surface that to the user before proposing changes.

### Step 5 — Ask the user any clarifying questions

Common things to clarify before writing code:

| Topic | Why ask |
|---|---|
| **Which warehouse / partner / picking is in scope?** | Most data is multi-tenant; assumptions are dangerous. |
| **Is this a one-off fix or a recurring pattern?** | One-off scripts can be permissive; reusable code must respect the pool/audit/snapshot invariants. |
| **Should the fix be in `multiple_relocation` (Python) or Studio?** | Studio changes don't show up in git; ask whether to make the change in code or in Studio + re-dump. |
| **What DB are we operating against?** | If they're on a fresh staging DB, behavior may differ from prod. Verify the `DATABASE_NAME` matches their intent. |

---

## Quick Reference — Mental Model

### Pallet series ID (the most fragile concept)

- Format: `{CLIENT_PREFIX}-{6-digit-zfill}` e.g. `JBL-000005`, `BGZ-000042`
- Pool lives on `res.partner`:
  - `x_studio_client_unique_code_1` (prefix — **must be set or pool methods raise UserError**)
  - `x_studio_pallet_series_id` (monotonic counter, integer)
  - `unused_pallet_series_ids` (JSON list of integers, sorted ascending)
- 4 methods on `res.partner`: `push_unused_pallet`, `get_smallest_pallet_series_ids`, `generate_new_pallet_series_id`, `get_pallet_series_by_id`
- **The Disappearing Bug**: writing `pallet_series_id` together with `location_dest_id` or `result_package_id` triggers Odoo's `_action_assign → _do_unreserve` cascade which deletes move lines and erases all `x_studio_*` fields. Workaround: detach lines via raw SQL (`_write_swap_product` pattern). Audit module logs everything *before* it happens so you can trace the loss.

### The `x_studio_` convention

- Many custom fields on `stock.move.line`, `stock.quant`, `stock.picking` use the `x_studio_` prefix (Studio-created).
- **`x_studio_` is a real field name** with trailing underscore — it's the line number "#". Not a typo.
- Access via `line.x_studio_` or `line['x_studio_']`.

### Operation types

- `RR` (Receiving Report, incoming) · `WR` (Withdrawal Report, outgoing) · `BFRR` / `BFWR` (blast freezer variants)
- Classified via `picking_type_id`; helper: `vifel_type_of_operation` computed field returns the 4-letter code.

### Cross-module data flow

```
RR / WR validation (multiple_relocation)
  ├─→ stock.move.line write     ─→ pallet_series_audit logs event
  ├─→ stock.quant inherits      ─→ stock.quant.history snapshot picks up
  └─→ ledger row created        ─→ pallet_kilos_record_model recalculates balances
         │
         └─→ reports (XLSX via report_xlsx) read from the ledger / snapshots
```

### Environment-independent invariants

These are **true across every dev environment** for this project. The actual paths and credentials vary — discover them in Step 2.

- **Odoo version**: 17 Enterprise
- **PostgreSQL** is the only supported DB. Connection params live in the user's `odoo.conf` — read them, don't assume.
- **Active DB**: varies per developer / staging / prod. Always list with `psql -l` and confirm with the user before connecting.
- **Upgrade a module**: `python odoo-bin -c <odoo.conf> -u <module_name> --stop-after-init` (path to `odoo-bin` and `odoo.conf` are env-specific)
- **Timezone**: Business datetime math uses `Asia/Manila` (UTC+8). PostgreSQL storage is UTC. Always convert at the boundary.
- **Module install order**: `report_xlsx` → `multiple_relocation` → `pallet_kilos_record_model` → `pallet_series_audit` → `stock_quant_history` (dependencies enforce this; if you're scripting installs, use `-i a,b,c` and let Odoo resolve order).

### Always-loaded files

You don't need to read these unless the task touches them — but know they exist:

- `multiple_relocation/CONTEXT.md` — original verbose deep-dive (kept in sync with `_AI_CONTEXT.md`)
- `pallet_series_audit/CONTEXT.md` — same for the audit module
- `multiple_relocation/models/models.py` — pool methods (~lines 17-150)
- `multiple_relocation/models/stock_move.py` — `_write_swap_product` (raw-SQL escape hatch)
- `pallet_kilos_record_model/models/models.py` — `_recalculate_running_balances` (the fragile balance engine)

---

## Top Pitfalls (don't relearn these the hard way)

1. **`widget="html"` crashes Odoo 17** — loads WYSIWYG editor, blows up with `web_editor.backend_assets_wysiwyg.min.js` error. Use Text + tree/list views.
2. **Don't write `result_package_id` / `location_dest_id` together with custom field edits** unless you're inside a wizard that sets `skip_pallet_series_sync=True`. See "Disappearing Bug" above.
3. **`original_pallet_series_id` is set once, never overwritten** — it's the canonical origin used for restore logic.
4. **`x_studio_` is the real field name** (trailing underscore). Not a typo.
5. **`FastEncodeRR.transfer_id` is `fields.Integer`** (a picking ID), not a Many2one. Never call `.id` on it.
6. **`unused_pallet_series_ids` is a JSON list of INTEGERS**, not strings.
7. **Module category XML ID**: `base.module_category_inventory_inventory`, NOT `stock.module_category_inventory_inventory` (the latter does not exist).
8. **Always filter `pallet_kilos_record_model` queries by `active=True`** — voided records corrupt running balances if included.
9. **Always re-run `fetch_database_context.py`** after Studio changes — there is no other source for that data.
10. **Don't hand-edit `database_context_dump.md`** — it's regenerated and git-ignored. Edit the script instead if the format needs to change.
11. **No record rules scope models by warehouse** today — any user with model access sees every warehouse. Surfaced in `multi_warehouse_PLAN.md` §1 as 🔴 Critical (C1).
12. **`_order` on `pallet_kilos_record_model` must match its `_recalculate_running_balances` search order** (`start_time asc, id asc`). Changing one without the other corrupts balances.

---

## Odoo 17 Best Practices (apply these when writing/reviewing code)

General Odoo 17 patterns. Most are universal; the VIFEL-specific ones live in the AI_CONTEXT files.

### Models & ORM

1. **Extend with `_inherit = 'model.name'`**, not `_name`. Use `_name` only when creating a genuinely new model.
2. **List every accessed field in `@api.depends(...)`** — missing dependencies silently break recompute invalidation.
3. **`store=True` on computed fields only when you need to search/sort/aggregate** on them. Otherwise leave non-stored — it costs you nothing and avoids stale data.
4. **Always specify `ondelete=` on Many2one** (`'cascade'`, `'restrict'`, `'set null'`). The default is `'set null'` which is rarely what you want.
5. **`@api.constrains` for invariants** (server-side guarantees). **`@api.onchange` for UI-only suggestions** — never rely on it for data integrity.
6. **When overriding `create()` / `write()` / `unlink()`, always call `super()`** and return its result.
7. **`required=True` + `default=`** is usually better UX than `required=True` alone (saves the user a field).
8. **Don't write to a stored compute field's own dependencies inside its compute** — infinite-loop / unstable behavior.

### Performance & data access

9. **Avoid `search()` inside loops.** Pre-fetch one recordset, then use `.mapped()`, `.filtered()`, set membership, or `read_group()` for aggregates.
10. **Batch writes**: `recordset.write({...})` over the whole recordset, not per-record loops.
11. **`flush_model()` / `flush_recordset()` before raw SQL** that reads what you just wrote — ORM caches don't sync to PG automatically.
12. **Index high-cardinality columns** that show up in WHERE/ORDER BY (e.g. `start_time`, `picking_id`, `warehouse_id`). Add `index=True` to the field definition.

### Views (Odoo 17 specifics)

13. **`attrs` and `states` attributes are DEPRECATED in 17.** Use direct Python expressions: `invisible="state == 'done'"`, `readonly="x_studio_voided"`, `required="partner_id"`.
14. **`widget="html"` crashes Odoo 17** (already in pitfalls, repeating here as best-practice: prefer Text + tree/list views).
15. **`tracking=True` on a field** logs changes to the chatter (replaces the old `track_visibility='onchange'`).
16. **Use `Command` for x2many writes** in Odoo 17: `Command.create({...})`, `Command.set([ids])`, `Command.link(id)`, `Command.unlink(id)` — clearer than the old `(0, 0, {...})` / `(6, 0, [ids])` tuples (which still work).

### Security & context

17. **`sudo()` bypasses ALL ACLs and record rules.** Use sparingly; always leave a comment explaining WHY.
18. **`with_context(key=value)` instead of mutating `self.env.context`** — context is immutable for a reason.
19. **Validate inputs in wizards even if the form view restricts them** — the form is UI, not security.

### Logging & debugging

20. **`_logger.info / warning / error`** — never `print()` in server-side code. Module-level `_logger = logging.getLogger(__name__)`.
21. **Use `_logger.exception(...)`** inside `except:` blocks — it captures the traceback automatically.

### Datetime

22. **All `Datetime` fields store UTC.** Convert to user / business TZ only at the boundary (UI, reports, integrations). For VIFEL: convert via `pytz.timezone('Asia/Manila')`.
23. **Use `fields.Datetime.now()` not `datetime.now()`** in default factories — Odoo handles naive/UTC correctly.

---

## Studio vs. Code — When to Use Which

Studio (the Odoo UI customizer) and code (Python modules in `custom_addons`) overlap. Picking the right one matters for review, version control, and re-deployability.

| Use **Code** (Python in `custom_addons`) when... | Use **Studio** when... |
|---|---|
| Logic spans multiple models or modules | Adding a single field for a one-off display |
| Needs unit tests | Prototyping a feature you'll throw away |
| Needs source-control review | A customer-specific tweak that won't generalize |
| Touches crons, security rules, low-level ORM hooks | The Studio UI can express it cleanly in 2 minutes |
| Performance-critical (SQL, batched writes) | A new menu entry / kanban tweak |

**Rules of thumb**:
- **Never duplicate logic** in both Studio and code — pick one source of truth per behavior.
- **Studio changes do NOT appear in git.** They live in the database (and partially in `studio_customization` module's XML). Re-run `fetch_database_context.py` after every Studio session to refresh the AI context dump.
- **Server actions and compute fields** can go either way. Pick based on review needs: if the team must approve the change, write it in code.
- **When a Studio field grows complex compute logic**, move it to code (`_inherit` the model, add the field, mark Studio's version as deprecated). Studio compute fields are limited and hard to test.
- **Migrations and crons must be code.** Studio cannot reliably express either.

---

## What to Tell the User Before Writing Code

Before any non-trivial change, surface to the user:

1. **Which AI_CONTEXT.md section** is relevant (helps them verify your understanding).
2. **Which `database_context_dump.md` entries** (server actions / automations) might be affected.
3. **Any vulnerabilities from `multi_warehouse_PLAN.md`** that this change might worsen or fix.
4. **Whether the change belongs in code or in Studio** — they have different ownership and review processes.

When the user confirms, then implement.

---

## Maintenance Instructions for This Skill File

> **To the next AI agent reading this Skill:**
>
> This onboarding flow is itself a living artifact. Update it whenever:
>
> - A new AI_CONTEXT.md is created → add it to Step 1.
> - A new helper script lives in `consultant-test/` → add it to Step 3 (or a new step).
> - A new module is added under `consultant-test/` → update the "What This Repo Is" table.
> - A pitfall from the AI_CONTEXT files becomes important enough to deserve top-of-mind flagging → add to the "Top Pitfalls" list (but keep that list short — currently 12 items, hard cap at 15).
> - Odoo releases a new major version → revisit the "Odoo 17 Best Practices" section; deprecations and patterns change between versions.
> - A best-practice item proves stale (e.g. `Command` API changes in Odoo 18+) → mark with `⚠️ NEEDS VERIFICATION` rather than deleting.
> - The vulnerability situation in `multi_warehouse_PLAN.md` changes drastically (e.g. all 🔴 fixed) → update the "Top Pitfalls" #11 entry and Step 1's emphasis on reading the plan.
> - Discovery commands stop working on a developer's OS / shell → update Step 2 with the corrected snippets (bash + PowerShell coverage at minimum).
>
> **Hard constraint: do NOT hardcode environment paths or credentials in this file.** Step 2 is intentionally discovery-based for that reason. If you find yourself wanting to write `c:\foo\bar` or `password=...`, you're about to make the file misleading on every other developer's machine.
>
> Do not turn this file into a dump of everything. Its value is in being **short, ordered, and procedural**. If a section grows past ~50 lines, push the detail into the relevant `_AI_CONTEXT.md` and leave a one-line pointer here.
>
> Keep the **flow steps in order** (Step 1 → 5). Don't reorder them — the order encodes which mistakes the user has seen agents make in the past.

---

**Last updated**: 2026-05-16 (added env-discovery flow, Odoo 17 best practices, Studio-vs-code guide)
**Maintained by**: Mark Angelo S. Templanza + AI agents working in this repo
