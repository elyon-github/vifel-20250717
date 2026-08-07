# VIFEL — Edge-Case Thinking Playbook

> _Created 2026-07-28. This is a **how-to-reason** guide, not a fact sheet. When you touch
> anything that COUNTS (pallets, kilos), OWNS (client/owner), or PRINTS a number, run it
> through the lenses below before you trust it. Companion to
> `BUSINESS_CONTEXT_AND_LEARNINGS.md` (the domain facts) and `handoff.md` (current state)._

VIFEL's pallet/kilos ledger drives invoices, so a quietly-wrong number is a quietly-wrong
bill. The bugs that hurt here are almost never crashes — they are **plausible numbers that
are subtly wrong**, or **documents that silently disagree with each other**. None of the three
case studies below was ever reported as "a bug" — each looked like a working number and was
only found by patient, deliberate digging (see **How these were actually found**). This
playbook distills the lenses that catch them and the method that surfaces them.

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

8. **Event ORDER is data.** _When two documents touch the same pallet, does the ORDER (and
   exact timing) they're validated in change the count — and is that order enforced, or left
   to the encoder?_ A snapshot field (`reserved_quantity_on_validation`) is computed at the
   instant of validation, so *a document validated a minute too early records a different
   world.* If a correct count depends on "A must be validated before B," that ordering must be
   **guarded**, not assumed. Read the timestamps: a return that lands 15 seconds after a
   withdrawal, or an operation dated after its own validation, is the system telling you the
   sequence broke. Reconciliation only nets to zero when each `+1` has a real matching `−1` —
   check that the events that are *supposed* to cancel actually did.

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

## Case study 3 — the phantom pallet born from a return validated too early

**Symptom.** None visible on the surface. WR/07885 counted **5** withdrawn pallets and every
figure "looked right." Only by walking one pallet's *entire* lifecycle did a **phantom +1**
surface: pallet NB 2317 (PSI FO-021134) had **received 2, withdrawn 1** in the ledger while
being **physically empty** — one pallet the client would be billed for forever.

**Root cause.** A multi-truck withdrawal (WR/07887 + WR/07885 sharing one pallet). WR/07887
did a *partial* withdrawal, and its "Partial Withdraw" return was validated **one minute
later — before the partner WR/07885 emptied the pallet.** That re-added 103.5 kg, so
WR/07885's `reserved_quantity_on_validation` read 103.5 (not 0) → it **failed to count the
pallet it should have** (5 instead of 6), and the return minted a **+1 received with no
matching −1** (the withdrawal it "reversed" never counted −1, because a partial withdrawal
doesn't empty the pallet). The reconciliation the return *assumes* — WR −1, return +1, net 0 —
silently broke.

**Lenses that catch it.** #8 Event-order (the count depended on WR/07885 validating before the
return, but nothing enforced it; the return's 15-seconds-later timestamp was the tell). #1
Frozen-vs-live (`reserved_quantity_on_validation` is a validation-instant snapshot — a return
that mutates the pallet between validations changes what the next snapshot records). #5
Cross-counter (withdrawn side is gated by the emptiness test; the received side has no
equivalent gate, so a return re-receiving a *non-empty* pallet double-counts it).

**Fix.** `stock_picking.py::button_validate` — a **sequencing guard**: a Partial-Withdraw
return cannot be validated while a pending outgoing WR still reserves the same
(pallet, owner, PSI). This forces the partner truck to empty and count the pallet first; the
return validates after, and the two storage cycles stay separate (net 0). **No counting-logic
change** — the existing `resv`-based rule produces the right numbers once the *order* is right.

**How it was verified.** Rolled-back shell test `partial_return_sequence_guard_test.py` (11
checks): the guard detects a pending multi-truck sibling and blocks, releases once no sibling
reserves the pallet, and never gates void/normal single-truck returns.

---

## How these were actually found — the method (read this)

None of the three were reported as "a bug." Each looked like a working number. They surfaced
only through a **deliberate, patient method** — this is the part to internalise:

1. **Distrust the plausible.** A count that "looks about right" is not evidence it *is* right.
   Every one of these passed a casual glance. Treat a clean-looking number on a billing
   document as *unverified*, not *correct*.
2. **Walk one entity's ENTIRE lifecycle, end to end.** The phantom pallet was invisible in any
   single document; it only appeared when we traced **one pallet's** every receipt, withdrawal,
   and return across days and summed them. Pick the smallest concrete unit (one pallet, one
   PSI, one lot) and follow it from birth to death.
3. **Read the timestamps and the seconds.** "15 seconds after," "validated before it was
   operated," "exactly equal to the next withdrawal" — the timeline told the story the columns
   hid. Timing is data.
4. **Look where the logic actually lives — not just the code.** VIFEL's rules span Python,
   Studio **server actions / automations (SA/AR)**, and **stored computed fields**. The field
   that drove everything (`reserved_quantity_on_validation`) is set by an SA, not the module.
   You cannot reason about a number until you've found *every* place that writes it.
5. **Reconstruct the intended reconciliation, then check it held.** Partial-withdraw = WR −1 +
   return +1 = 0. Once we knew what *should* net to zero, the residual +1 was undeniable. Know
   the invariant; then hunt the violation.
6. **Reproduce in a rolled-back shell before believing — and before fixing.** Simulate the
   condition (a pending sibling, a re-reservation) and watch the number move. A bug you can't
   reproduce, you don't understand.

**Why it matters that we chase the *invisible* ones.** These don't crash; they quietly
mis-bill. Left alone they **compound**: every multi-truck partial adds another phantom pallet
to a client's storage ledger; every early return drifts a WR's count; every stranded series
leaks a client's pool. Nobody notices until a billing dispute months later, when the trail is
cold and the trust is spent. The discipline is: **be diligent, be exploratory, and always ask
"if this is wrong and I don't fix it, what does it become at scale, and who eventually pays?"**

---

## The one-line takeaway
A number that is **plausible** is not the same as a number that is **correct** and
**stable**. Before trusting a count or an ownership change, ask: _is it frozen where it should
be, does it cascade where it must, do all the places that compute it agree, and can I explain
why every condition is there?_
