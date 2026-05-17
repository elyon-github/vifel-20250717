# -*- coding: utf-8 -*-
"""
fetch_database_context.py
==========================

Connects READ-ONLY to an Odoo 17 PostgreSQL database and dumps:

    1. Server actions       (ir.actions.server)
    2. Automation rules     (base.automation)
    3. Compute fields       (ir.model.fields where compute IS NOT NULL)

into a single Markdown file (`database_context_dump.md`) intended as
*context* for an AI agent (Claude Code or similar) so it can reason
about Studio-created behaviour without having to log into Odoo.

USAGE
-----
    1. Edit the CONFIG block below (especially DATABASE_NAME).
    2. Run from anywhere:    python fetch_database_context.py
       Or with a DB override: python fetch_database_context.py <db_name>
    3. The output file is written next to this script.

REQUIREMENTS
------------
    psycopg2 (already bundled with Odoo's Python — run with the same
    interpreter that runs odoo-bin and you're fine).

SAFETY
------
    This script issues SELECT statements only. It never writes to the DB.
    If you ever extend it, keep that invariant — it's safe to run against
    production exactly because it cannot mutate anything.

NOTES
-----
    - Odoo 17 stores translated fields (name, field_description, help)
      as JSONB. We extract the 'en_US' value.
    - `base_automation` may not exist if the module isn't installed;
      we handle that gracefully and continue.
    - "Custom" filter scope keeps only:
          * records owned by consultant-test modules
          * Studio-created records (state='manual' for fields,
            module='studio_customization' for actions/automations)
          * x_* / x_studio_* names
"""

import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    sys.stderr.write(
        "psycopg2 is required.  Install it (e.g. `pip install psycopg2-binary`) "
        "or run this script with the Python interpreter that runs odoo-bin.\n"
    )
    sys.exit(1)

# Windows consoles default to cp1252 which cannot print Unicode arrows etc.
# Force UTF-8 on stdout/stderr so the progress messages and the written file
# render cleanly regardless of the host's default code page.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, Exception):
    pass


# ──────────────────────────────────────────────────────────────────────
#  CONFIG  —  EDIT ME
# ──────────────────────────────────────────────────────────────────────

# The database to dump.  Override on the command line:
#     python fetch_database_context.py <db_name>
DATABASE_NAME = "VIFEL_05_16_2026_1"

# Connection details (match c:/Odoo17E/server/odoo.conf)
DB_HOST = "localhost"
DB_PORT = 5432
DB_USER = "openpg"
DB_PASSWORD = "openpgpwd"

# Where to write the dump (relative to this script).
# By default writes into ai_context/ alongside the hand-written context docs.
# The folder is auto-created if missing.
OUTPUT_FILE = "ai_context/database_context_dump.md"

# Filter scope:
#   "custom"  → consultant-test modules + Studio records only  (default)
#   "all"     → everything in the database (large)
FILTER_SCOPE = "custom"

# Module names that count as "custom" for the consultant-test deployment.
# Anything owned by one of these modules (via ir.model.data) is kept.
# Extend if you add new custom modules.
CUSTOM_MODULES = (
    "multiple_relocation",
    "pallet_kilos_record_model",
    "pallet_series_audit",
    "stock_quant_history",
    "report_xlsx",
    "app_common",
    "app_odoo_customize",
    "odoo_calculator_tool",
    "studio_customization",  # everything created via Odoo Studio
)

# Truncate very long code blocks above this length (chars) — set to 0 to disable.
MAX_CODE_LEN = 0

# ──────────────────────────────────────────────────────────────────────
#  CLI OVERRIDE
# ──────────────────────────────────────────────────────────────────────
if len(sys.argv) > 1:
    DATABASE_NAME = sys.argv[1]


# ──────────────────────────────────────────────────────────────────────
#  DB CONNECT
# ──────────────────────────────────────────────────────────────────────

def connect():
    print(f"Connecting to '{DATABASE_NAME}' at {DB_HOST}:{DB_PORT} as {DB_USER}...")
    return psycopg2.connect(
        dbname=DATABASE_NAME,
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )


# ──────────────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────────────

def _table_exists(conn, table_name):
    sql = """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (table_name,))
        return cur.fetchone() is not None


def _truncate(text, max_len=MAX_CODE_LEN):
    if not text:
        return text
    if max_len and len(text) > max_len:
        return text[:max_len] + f"\n# ... (truncated — original was {len(text)} chars)"
    return text


def _is_custom(row):
    """Return True if this row should be kept under FILTER_SCOPE='custom'."""
    if FILTER_SCOPE == "all":
        return True

    module = (row.get("module_name") or "").strip()
    if module in CUSTOM_MODULES:
        return True

    # ir_model_fields uses 'state' = 'manual' for Studio fields
    if row.get("state_") == "manual":
        return True

    # Names starting with x_ or x_studio_
    name = (row.get("name") or row.get("field_name") or "")
    if name.startswith("x_"):
        return True

    # Models starting with x_ (Studio custom models)
    model = (row.get("model_name") or "")
    if model.startswith("x_"):
        return True

    return False


# ──────────────────────────────────────────────────────────────────────
#  FETCHERS
# ──────────────────────────────────────────────────────────────────────

def fetch_server_actions(conn):
    """All ir.actions.server with their code, model, and owning module.

    NOTE: In Odoo 17 the server-action records live in the table
    `ir_act_server` (NOT `ir_actions_server` — that's just the model name).
    """
    sql = """
        SELECT
            ias.id,
            COALESCE(ias.name->>'en_US', ias.name::text) AS name,
            ias.state,
            ias.code,
            ias.sequence,
            ias.usage,
            ias.base_automation_id,
            im.model AS model_name,
            COALESCE(ias.help->>'en_US', '') AS help,
            (SELECT imd.module
               FROM ir_model_data imd
              WHERE imd.model = 'ir.actions.server'
                AND imd.res_id = ias.id
              LIMIT 1) AS module_name,
            (SELECT imd.name
               FROM ir_model_data imd
              WHERE imd.model = 'ir.actions.server'
                AND imd.res_id = ias.id
              LIMIT 1) AS xml_id
        FROM ir_act_server ias
        LEFT JOIN ir_model im ON im.id = ias.model_id
        ORDER BY model_name NULLS LAST, ias.id;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    kept = [r for r in rows if _is_custom(r)]
    print(f"  → {len(rows)} total in DB, {len(kept)} kept after scope='{FILTER_SCOPE}'")
    return kept


def fetch_automation_rules(conn):
    """All base.automation rules (if the module is installed)."""
    if not _table_exists(conn, "base_automation"):
        print("  → base_automation table not found (module not installed); skipping")
        return []

    sql = """
        SELECT
            ba.id,
            COALESCE(ba.name->>'en_US', ba.name::text) AS name,
            ba.trigger,
            ba.filter_domain,
            ba.filter_pre_domain,
            ba.trg_date_range,
            ba.trg_date_range_type,
            ba.active,
            im.model AS model_name,
            imf.name AS trg_date_field,
            (SELECT imd.module
               FROM ir_model_data imd
              WHERE imd.model = 'base.automation'
                AND imd.res_id = ba.id
              LIMIT 1) AS module_name,
            (SELECT imd.name
               FROM ir_model_data imd
              WHERE imd.model = 'base.automation'
                AND imd.res_id = ba.id
              LIMIT 1) AS xml_id
        FROM base_automation ba
        LEFT JOIN ir_model im ON im.id = ba.model_id
        LEFT JOIN ir_model_fields imf ON imf.id = ba.trg_date_id
        ORDER BY model_name NULLS LAST, ba.id;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    # Fetch the linked server actions per automation.
    # In Odoo 17 the relationship is a FK on ir_act_server.base_automation_id
    # (NOT a separate link table like 17.x earlier docs suggest).
    link_sql = """
        SELECT ias.base_automation_id AS automation_id,
               ias.id AS action_server_id,
               COALESCE(ias.name->>'en_US', ias.name::text) AS action_name,
               ias.state AS action_state
          FROM ir_act_server ias
         WHERE ias.base_automation_id IS NOT NULL
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(link_sql)
        links = cur.fetchall()
    by_auto = {}
    for ln in links:
        by_auto.setdefault(ln["automation_id"], []).append(
            f"#{ln['action_server_id']} {ln['action_name']} (state={ln['action_state']})"
        )
    for r in rows:
        r["server_actions"] = by_auto.get(r["id"], [])

    kept = [r for r in rows if _is_custom(r)]
    print(f"  → {len(rows)} total in DB, {len(kept)} kept after scope='{FILTER_SCOPE}'")
    return kept


def fetch_compute_fields(conn):
    """All ir.model.fields with a non-empty compute expression."""
    sql = """
        SELECT
            imf.id,
            imf.model AS model_name,
            imf.name AS field_name,
            imf.ttype AS field_type,
            COALESCE(imf.field_description->>'en_US', imf.field_description::text) AS field_description,
            imf.compute,
            imf.depends,
            imf.store,
            imf.readonly,
            imf.related,
            imf.relation,
            imf.state AS state_,
            (SELECT imd.module
               FROM ir_model_data imd
              WHERE imd.model = 'ir.model.fields'
                AND imd.res_id = imf.id
              LIMIT 1) AS module_name
        FROM ir_model_fields imf
        WHERE imf.compute IS NOT NULL
          AND imf.compute <> ''
        ORDER BY imf.model, imf.name;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    kept = [r for r in rows if _is_custom(r)]
    print(f"  → {len(rows)} total in DB, {len(kept)} kept after scope='{FILTER_SCOPE}'")
    return kept


# ──────────────────────────────────────────────────────────────────────
#  WRITERS
# ──────────────────────────────────────────────────────────────────────

def _group_by(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r.get(key) or "<no model>", []).append(r)
    return out


def write_markdown(server_actions, automations, compute_fields, out_path):
    lines = []
    push = lines.append

    push(f"# Database Context Dump — `{DATABASE_NAME}`\n")
    push(f"> **Generated**: {datetime.now().isoformat(timespec='seconds')}  ")
    push(f"> **Filter scope**: `{FILTER_SCOPE}`  ")
    push(f"> **Source**: `{DB_HOST}:{DB_PORT}` as `{DB_USER}`  ")
    push(f"> **Script**: `fetch_database_context.py`\n")
    push("---\n")

    # ── Summary ───────────────────────────────────────────────────
    push("## 1. Summary\n")
    push(f"- **Server actions**: {len(server_actions)}")
    push(f"- **Automation rules**: {len(automations)}")
    push(f"- **Compute fields**: {len(compute_fields)}\n")
    push("---\n")

    # ── Server actions ────────────────────────────────────────────
    push(f"## 2. Server Actions ({len(server_actions)})\n")
    push(
        "Each entry shows the Odoo Studio / module-defined server action: "
        "its state, owning module, XML ID, and (for `state='code'`) the Python source.\n"
    )
    grouped = _group_by(server_actions, "model_name")
    for model in sorted(grouped):
        push(f"### `{model}` ({len(grouped[model])})\n")
        for r in grouped[model]:
            xml = f" · `{r['module_name']}.{r['xml_id']}`" if r.get("xml_id") else ""
            push(f"#### #{r['id']} — {r['name']}  ")
            push(f"`state={r['state']}` · `usage={r['usage'] or '—'}` · "
                 f"`module={r.get('module_name') or '<no module>'}`{xml}\n")
            if r.get("help"):
                push(f"> {r['help'].strip()}\n")
            if r["state"] == "code" and r.get("code"):
                push("```python")
                push(_truncate(r["code"].rstrip()))
                push("```\n")
        push("")
    push("---\n")

    # ── Automation rules ──────────────────────────────────────────
    push(f"## 3. Automation Rules ({len(automations)})\n")
    push(
        "Automated actions (`base.automation`).  Each rule fires its linked "
        "server actions when its trigger condition + domain match.\n"
    )
    if not automations:
        push("_None found (or `base_automation` module not installed)._\n")
    else:
        grouped = _group_by(automations, "model_name")
        for model in sorted(grouped):
            push(f"### `{model}` ({len(grouped[model])})\n")
            for r in grouped[model]:
                xml = f" · `{r['module_name']}.{r['xml_id']}`" if r.get("xml_id") else ""
                status = "" if r["active"] else " · **INACTIVE**"
                push(f"#### #{r['id']} — {r['name']}{status}  ")
                push(f"`trigger={r['trigger']}` · "
                     f"`module={r.get('module_name') or '<no module>'}`{xml}\n")
                if r.get("trg_date_field"):
                    rng = r.get("trg_date_range") or 0
                    typ = r.get("trg_date_range_type") or ""
                    push(f"- **Time trigger**: relative to `{r['trg_date_field']}` "
                         f"({rng:+d} {typ})")
                if r.get("filter_pre_domain"):
                    push(f"- **Pre-domain**: `{r['filter_pre_domain']}`")
                if r.get("filter_domain"):
                    push(f"- **Domain**: `{r['filter_domain']}`")
                if r.get("server_actions"):
                    push("- **Runs**:")
                    for sa in r["server_actions"]:
                        push(f"  - {sa}")
                push("")
        push("")
    push("---\n")

    # ── Compute fields ────────────────────────────────────────────
    push(f"## 4. Compute Fields ({len(compute_fields)})\n")
    push(
        "Fields with a non-empty `compute` expression.  `state=manual` means "
        "Studio-created at runtime; `state=base` means defined in Python code.\n"
    )
    grouped = _group_by(compute_fields, "model_name")
    for model in sorted(grouped):
        push(f"### `{model}` ({len(grouped[model])})\n")
        for r in grouped[model]:
            store = "stored" if r["store"] else "non-stored"
            ro = ", readonly" if r["readonly"] else ""
            related = f" · related=`{r['related']}`" if r.get("related") else ""
            relation = f" · → `{r['relation']}`" if r.get("relation") else ""
            push(f"#### `{r['field_name']}` "
                 f"(`{r['field_type']}`{relation}, {store}{ro}, state=`{r['state_']}`)  ")
            if r.get("field_description"):
                push(f"_{r['field_description']}_  ")
            if r.get("module_name"):
                push(f"`module={r['module_name']}`  ")
            if r.get("depends"):
                push(f"`depends={r['depends']}`{related}\n")
            push("```python")
            push(_truncate(r["compute"].rstrip()))
            push("```\n")
        push("")

    push("---\n")
    push("## 5. AI Agent Maintenance Instructions\n")
    push(
        "> **To the next AI agent reading this file:**\n>\n"
        "> This file is a snapshot of the Odoo database at the timestamp above.  "
        "It is *not* maintained by hand — re-run `fetch_database_context.py` "
        "whenever Studio fields / server actions / automations change so the "
        "context you reason with stays accurate.  Specifically:\n>\n"
        "> - If you see references to Studio-created behaviour (server action #347, "
        "the BA #6 auto-action, an `x_studio_*` compute, etc.) and the answer here "
        "doesn't match what the user describes, **re-run the script first** rather "
        "than guessing.\n"
        "> - When you advise the user to add or modify a Studio field/automation, "
        "remind them to re-run this script so the next session starts with fresh data.\n"
        "> - This file is generated content — do not hand-edit it.  Edit "
        "`fetch_database_context.py` instead and re-run.\n"
        "> - Filter scope and connection settings live in the CONFIG block at the "
        "top of the script."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out_path}  ({out_path.stat().st_size:,} bytes)")


# ──────────────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    out_path = Path(__file__).resolve().parent / OUTPUT_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = connect()
    except psycopg2.OperationalError as e:
        sys.stderr.write(f"\nCould not connect to database '{DATABASE_NAME}':\n{e}\n")
        sys.exit(2)

    try:
        print("Fetching server actions...")
        server_actions = fetch_server_actions(conn)
        print("Fetching automation rules...")
        automations = fetch_automation_rules(conn)
        print("Fetching compute fields...")
        compute_fields = fetch_compute_fields(conn)
    finally:
        conn.close()

    print("\nWriting Markdown dump...")
    write_markdown(server_actions, automations, compute_fields, out_path)
    print("Done.\n")


if __name__ == "__main__":
    main()
