# Starter Prompts — First Message in a New AI Session

> **What this file is for**: When you open a fresh AI session (new dev machine, new conversation, new branch), the AI starts with zero context about this codebase. Paste one of the prompts below as your **first message** to make it read [`../Skill.md`](../Skill.md), follow the onboarding flow, and ask you about the environment before doing anything risky.
>
> Pick the variant that matches what you're about to do. When in doubt, use the **default**.

---

## Default — when starting fresh

Use this when you don't have a specific task in mind yet, or when you just want the AI to be ready.

```
Read consultant-test/Skill.md and follow the onboarding flow before
answering anything else. When you reach Step 2, ask me for the
environment details you need — don't assume paths or credentials.
```

That's it. The Skill file does the rest: it tells the AI to read the 6 docs in order, discover the env from you, run the dump script, and only then engage with your task.

---

## Variant A — when you already have a task in mind

Use this when you know exactly what you want done. The AI will still run through the flow first, but it'll keep your task in mind while reading the docs and may surface relevant context earlier.

```
Read consultant-test/Skill.md and follow the onboarding flow.
Ask me about the environment in Step 2.

Then, the task: <describe what you want done>
```

Replace `<describe what you want done>` with the actual task — e.g. *"add a per-warehouse filter to the occupancy report wizard"* or *"fix the bug where pallet series JBL-000042 keeps disappearing on RR validation"*.

---

## Variant B — read-only question (skip env setup)

Use this when you only need information from the docs, not a code change. Skips the database-dump step entirely.

```
Read consultant-test/Skill.md sections 1, 4, 5 (skip env setup —
read-only question). Then: <your question>
```

Replace `<your question>` with something like *"how does the pallet-series pool decide which series ID to recycle?"* or *"what does `_recalculate_running_balances` actually do?"*.

---

## What to expect after the prompt

Whichever variant you used, the AI will:

1. **Read the 6 docs** in [`../ai_context/`](../ai_context/) (~2-3 minutes)
2. **Ask you for** Odoo path, `odoo.conf` path, Python interpreter, active DB name
3. **You answer** those (or paste your `odoo.conf` contents)
4. **AI runs** `fetch_database_context.py` (or asks you to run it)
5. **AI has full context** — ready for the actual work

---

## Push-back lines (when the AI skips ahead)

The most common cold-start failure mode is the AI **guessing** paths or skipping the discovery step. If that happens, paste one of these:

| Symptom | Pushback |
|---|---|
| AI uses a path like `c:/Odoo17E/server/...` without asking | `Re-read Skill.md Step 2 — don't assume paths, discover.` |
| AI starts modifying code before reading the docs | `Stop. Go back to Skill.md Step 1 and read all 6 docs before touching code.` |
| AI doesn't run / ask about `fetch_database_context.py` and the task involves a Studio field | `You need the live Studio dump for this — re-run fetch_database_context.py first.` |
| AI proposes a change that contradicts a known vulnerability | `Cross-check against multi_warehouse_PLAN.md §1. Does this make C1/C2/etc. worse?` |

---

## When to add a new starter prompt to this file

If you find yourself repeatedly typing the same task-shaped prompt (e.g. *"do a security review of …"*, *"explain this XLSX report …"*), promote it to a named variant here. Keep variants short and self-contained — they're for copy-paste, not reading.

If a variant grows beyond ~10 lines, it probably belongs in its own file under `prompts/`, not bloating this one.

---

**Last updated**: 2026-05-16
