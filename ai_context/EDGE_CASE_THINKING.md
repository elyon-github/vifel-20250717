# VIFEL — Edge-Case Thinking Playbook

> _Created 2026-07-28. This is a **how-to-reason** guide, not a fact sheet. When you touch
> anything that COUNTS (pallets, kilos), OWNS (client/owner), or PRINTS a number, run it
> through the lenses below before you trust it. Companion to
> `BUSINESS_CONTEXT_AND_LEARNINGS.md` (the domain facts) and `handoff.md` (current state)._

VIFEL's pallet/kilos ledger drives invoices, so a quietly-wrong number is a quietly-wrong
bill. The bugs that hurt here are almost never crashes — they are **plausible numbers that
are subtly wrong**, or **documents that silently disagree with each other**. The two most
recent (below) were both of that kind. This playbook distills the lenses that catch them.

---

## The 7 lenses

Run a change through these. Each is phrased as the question to ask.

1. **Frozen vs live.** _Is this figure on a validated/immutable document recomputed from
   mutable global state every time it's read?_ A validated document's derived numbers must be
   **frozen at validation** (from a stamped snapshot), never re-derived from data that can
   change afterward. If re-printing the same document can give a different number tomorrow,
   that's the bug.

2. **Identity changes must cascade.** _When an owning field (Client / owner) changes, does
   every owner-scoped resource move with it — or get left behind?_ Series pools, per-client
   counters, prefixes, `owner_id` on child lines, and reservations are all owner-scoped.
   Either re-derive all of them on the change, or **block the change**. A half-applied
   identity change (owner flips, series don't) corrupts attribution and leaks the pool.

3. **Guard-coverage completeness.** _A guard exists for ONE document type — which siblings
   does it miss?_ Returns and void children were guarded against owner changes; the plain RR
   was not, and that gap was the whole bug. Enumerate every document type (RR, WR, return,
   void-WR, void-return, BF) and confirm each is handled or consciously exempt.

4. **Category correctness.** _Is a check mixing two levels of the hierarchy?_ Lot ≠ pallet;
   package ≠ Pallet Series (PSI); a physical pallet can hold several PSIs. A condition that
   answers a **lot-level** question inside a **pallet-level** count is a category error, even
   if it "looks reasonable."

5. **Cross-counter consistency.** _The same quantity is computed in ≥2 places — do they use
   the SAME rule?_ Pallet counts live in the WR/RR **PDF**, the **PKR ledger**, and the
   on-screen **Transacted Pallet Count**. They must agree by construction. When two disagree,
   don't patch one to match — find which rule is right and make all three share it.

6. **Question undocumented conditions.** _Why is this condition here — who added it and what
   problem did it solve?_ Trace provenance with `git log -S "<token>"`. A condition with **no
   recorded rationale** that only ever adds or suppresses a count is suspect: it may be a
   band-aid for one case, or (worse) crept back through a merge conflict. Don't preserve
   mystery logic out of caution — verify it or remove it.

7. **Snapshot before mutate; conserve resources.** _Before deleting/clearing, did you capture
   what you need to put back — and does every drawn resource return to the correct pool?_ PSI
   series are a finite per-client pool: whatever is drawn must be recycled to **that same
   client** when released, or the pool leaks. Snapshot series+owner *before* touching lines.

---

## Case study 1 — the WR pallet count that drifted

**Symptom.** M/WR/07887 printed **2** withdrawn pallets one day and **1** the next, with no
change to the WR itself. The PKR ledger always said 2.

**Root cause.** The WR-print counter gated a pallet as withdrawn on
`reserved_quantity_on_validation == 0 AND not same_quant_stocks_picked`. The second clause was
a **live query** — "is this lot on any pending outgoing picking *right now*?" So after one of
the withdrawn pallets was returned and re-reserved onto a fresh pending WR, re-printing the
old WR **suppressed** that pallet. The count moved because the world moved.

**Lenses that catch it.** #1 Frozen-vs-live (a validated WR's count was recomputed from live
reservations). #4 Category (the gate searched by `lot_id` — a lot-level fact — to decide a
per-pallet count; a lot spans many pallets). #5 Cross-counter (PKR ledger and Transacted
count never used the gate, so the print silently disagreed with billing). #6 Provenance —
`git log -S same_quant_stocks_picked` showed it was added by an outside dev with a vague
message, removed by Elyon days later, then **resurrected through a merge conflict**, then its
`OR` was flipped to `AND`. No commit ever justified it.

**Fix.** `stock_picking.py` — count on the frozen `reserved_quantity_on_validation == 0`
snapshot alone (+ the `(pallet, PSI)` dedupe), matching the ledger. Commit `99d1112`.

**How it was verified.** Audited 120 WRs (print == documented rule, 0 exceptions); confirmed
07887 stays 2 under a *simulated* pending outgoing (no drift); RR counts unchanged.

## Case study 2 — the Client change that stranded the Pallet Series

**Symptom.** On an RR with 5 assigned PSI lines, changing the Client left the lines owned by
the **new** client but still stamped with the **old** client's series (e.g. 168 ENTERPRISES
holding `BG-…` series that belong to BGZ).

**Root cause.** A Studio automation copies partner→owner on save, so `owner_id` flipped — but
nothing re-derived the **series**, which had been drawn from the old client's finite pool. The
old client's numbers stayed marked "used" yet vanished from its documents (**pool leak**), and
the new client held series its own pool never issued (**mis-prefix + misattribution**).

**Lenses that catch it.** #2 Identity-cascade (owner changed; the owner-scoped series pool did
not). #3 Guard-coverage (the owner-change guard covered returns/void but not the plain RR).
#7 Resource conservation (drawn series must return to *their* pool).

**Fix.** `stock_picking.py::write` — on a Client change to an **editable** RR, recycle each
line's series back to the **old** client's pool (with the stocked-pallet guard) and blank the
series + stale display; the user re-runs Assign Pallet Series under the new client. Reservations
are RR-scoped, so pallets/locations are kept. Returns/void still block; done RRs are untouched.

**How it was verified.** Rolled-back shell test `wr_psi_client_change_test.py` (10 checks):
series blanked, recycled to the OLD client's pool, no line left with new-owner+old-series;
plus the return-block and done-RR-untouched regressions.

---

## The one-line takeaway
A number that is **plausible** is not the same as a number that is **correct** and
**stable**. Before trusting a count or an ownership change, ask: _is it frozen where it should
be, does it cascade where it must, do all the places that compute it agree, and can I explain
why every condition is there?_
