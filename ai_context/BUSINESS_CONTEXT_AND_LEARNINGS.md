# VIFEL — Business Context & Hard-Won Learnings

> _Created 2026-07-17. This captures the BUSINESS knowledge behind the code — the process
> on the warehouse floor, the identity/counting doctrine, per-client special cases, and
> operational lessons that cost real debugging time. Read together with `handoff.md`
> (current state), `SYSTEM_OVERVIEW.md` (architecture), and `EDGE_CASE_THINKING.md` (the
> **how-to-reason** playbook — 7 lenses for counting/ownership bugs, with worked case
> studies). Update when the business rules themselves change, not on every code commit._

## 1. The business in one page

VIFEL is a **third-party cold-storage warehouse (3PL)** in the Philippines. It stores frozen
goods on **pallets** for many **client-owners** and **bills by occupancy** (pallets + kilos
held over time). Everything in the customization exists to answer two questions provably:
*whose stock is on which physical pallet right now* and *how many pallets/kilos has each
client had in storage over time*. Billing disputes are the failure mode all integrity work
guards against — a wrong pallet count is literally a wrong invoice.

People in the process (use these words in client-facing material):
- **Documentation staff** — encode RRs/WRs in Odoo (Pallet Breakdown, Magic Wizard). NOT
  called "warehouseman" in client docs.
- **Checker** — physically verifies against the printed **Tally Sheet** / **Picklist**.
- **Inventory Super Admin / Adjustment Approvers** (currently only Dojello, user 66) —
  approve pallet-detail corrections.

## 2. Document flow on the floor

**Receiving (RR):** create RR → encode pallet lines in **Pallet Breakdown** (PSI + pallet #
+ temporary aisle location) → print **Tally Sheet** + **Pallet Tag Form** → Checker verifies
physically → encode returned Tally Sheet corrections (Magic Wizard) → complete Client Window
Details → Verify Transfer → validate. On validation the Studio layer stamps quants
(record reference, PSI) and creates the PKR row.

**Withdrawal (WR):** encode → print **Picklist** (sorted so same-PSI lines are contiguous —
one physical pallet is picked as one block) → Checker picks → update Actual Values
(gold-highlighted columns) especially for partial withdrawals/returns → validate.
**Multiple concurrent WRs on the same pallet are normal business** (several trucks loading
one client's stock) — this is why `reserved_quantity_on_validation` stamping had a race
(fixed by sorted FOR UPDATE lock, SA#297).

**Returns:** a WR can spawn a return RR (goods came back). Returns must land on the **PSI
remainder** (same pallet/location/lot) when a remainder exists — otherwise the same PSI ends
up on two pallets (phantom pallet). Business rule: an RR return's Client/Owner must NEVER be
changed while linked (that produced cross-owner stock, M/RR/03721).

**Void/unvoid:** voiding an RR builds a mirroring void WR (and vice versa). Business rule:
the void equivalent must mirror the voided document EXACTLY (same client, KG, packaging,
packs, lines) — operators must not "reuse" a void doc as a vehicle for edits. You cannot
unvoid a WR whose equivalent return RR is already validated. Unvoiding neutralizes
unvalidated children into empty drafts; their PSIs are NOT recycled into the pool.

## 3. Identity doctrine (the invariants everything depends on)

- **One physical pallet = one PSI = one package (Pallet #).** PSI format
  `<CLIENT-CODE>-NNNNNN` (e.g. `AHA-000001`) drawn from a per-client pool on res.partner;
  numbers recycle when freed, BUT a number present on stocked quants must never re-enter
  the pool (split-PSI corruption).
- **Pallet # (package) names** like `R 366` come from a pre-created pool of empty packages;
  RR encoding only ever SELECTS empty pallets (never creates packages).
- **BF (blast freezer) is a parallel world:** no package, no PSI — identity is free-text
  **Pallet Text** (`bf_pallet_char`) + lot + originating record reference. BF is strictly
  **1-in / 1-out** (verified 0/797 violations). BF lots are REUSED across receipts — never
  match BF stock by lot alone, always scope by record reference.
- Corrections that move one quant of a PSI must move ALL quants of that PSI together
  (PSI cascade + all-or-nothing approval) — otherwise the physical pallet and the system
  disagree about what's on it.
- **"Talon-talon" (jumping numbers) is a FEATURE of recycling, not a loss** (user-confirmed
  2026-07-17, corrects the meeting transcript's "IDs are lost" claim): documents are never
  deleted, only move LINES — a deleted line's PSI returns to the pool, and draws are
  smallest-first. Timing then produces e.g. RR-C carrying 6–10 AFTER RR-B got 11–13, or one
  RR showing 4,5,11,12,13 (pool leftovers + counter continuation). Trade-off axis of the
  Pallet Series ID Controversy (meeting 2026-07-15, in the NotebookLM knowledge base):
  compact number space via recycling VS strict chronology via never-recycle + void-tagged
  gaps. Decision deferred; UI simplification prioritized. Nothing downstream breaks either
  way — PSI is an identity, never a sequence, everywhere in code.
- **Mark's proposal (on record in the meeting): system-guided reuse + supervised
  acknowledgment.** System suggests latest+1 as starting pallet AND proactively offers
  previously deleted IDs for reuse ("RR2 starts at 4,5 instead of jumping to 6"); a
  supervisor explicitly acknowledges, keeping an audit trail. Rejects gaps instead of
  void-labeling them. Objections: simultaneous-container timing race, checker confusion,
  human-decision error risk → "revisit later". KEY INSIGHT: the built pool already reuses
  deleted PSIs smallest-first — Mark's proposal is mostly a UX layer (visible reuse prompt +
  acknowledgment, e.g. via FastEncodeRR `_preview_next_series`) over existing machinery,
  not a rebuild. CAVEATS: (a) reuse repairs the sequence FORWARD only — numbers already
  issued to a concurrent RR can't be recalled, so gaps are reduced, never guaranteed gone
  (promise "gaps close quickly", not "no gaps"); (b) a reuse prompt MUST carry the
  stocked-quant guard (never offer a number present on stocked quants) or it actively
  invites split PSIs — same hole as the unguarded ondelete auto-push; (c) reuse needs a
  scope rule (same shipment/day), else weeks-old numbers resurface on unrelated RRs and
  look as odd as the jumps; (d) physical tag order inverts vs arrival order (checker
  confusion objection is legitimate).
- **Void/cancelled idea (Ma'am Erika, check-ledger analogy) — room reaction:** accepted on
  data/identity grounds, stalled on FLOOR VISIBILITY: Rocky — "hahanapin nila ang 10" (the
  racks guy still hunts the number); "paano si checker nakikita?"; recall double-count risk
  for voided-but-tagged numbers; "human decides = more prone to error". Mark's close: tech
  manageable, "clarity sa taong gumagalaw" unresolved → postponed for front-end work.
  **Converged best-solution (2026-07-18 brainstorm, after eliminating dock printing/rollback/
  reuse/renumber/blank tags against floor constraints):** (1) AUTOMATIC void on printed-line
  deletion (no human judgment — answers the error objection) with destroyed-tags ☑;
  (2) cancelled series PRINTED ON FLOOR DOCUMENTS (Tally Sheet/Picklist show "38–40 —
  CANCELLED, do not locate" — answers Rocky/checker objections); (3) smart sibling-draft-
  aware Start-PSI suggestion + supervisor-gated override (answers simultaneous containers);
  (4) "Nasaan yung series?" lookup + owner timeline (answers audits + recall). Key argument
  for the team: every alternative is PROVABLY impossible under print-at-unload + concurrent
  RRs; this package answers each objection raised in the meeting in the room's own words.
- **★ CURRENT #1 SOLUTION (user-designated 2026-07-18): void/cancelled PSI.** Core insight:
  it's mostly REMOVAL — stop recycling (all paths funnel through `push_unused_pallet`, flip
  that one choke point to "record CANCELLED"), generation counter-only from the client
  profile. Decisions: bulk-cancel existing pools at cutover; cancelled ledger fed from
  pallet_series_audit (queryable for tally-sheet printing + lookup); update Clean Picking SA
  to cancel instead of recycle. FLOOR FACT (user 2026-07-18): **deletions ALWAYS happen
  after tags are printed** (checker count arrives post-attach) → auto-compaction and
  counter-rollback DROPPED — never legally fire. Final rule, no exceptions:
  **"Every freed number cancels. Nothing ever renumbers. The counter only moves forward."**
  (Chicken 1-5/Beef 6-10/Pork 11-15, delete chicken #5 → tally prints
  "1-4 · [5 — CANCELLED] · 6-15" — 14 valid + 1 cancelled, count matches, no hunt.)
  - One mechanism, two labels: post-print deletion → "CANCELLED — tags destroyed ☑";
    encode-phase release (wizard regroup frees a loser series before first print) →
    "unused — never printed" (no checkbox, no paper existed).
  - DROPPED (user 2026-07-18): the "simultaneous containers collide at start 1" problem and
    its fix (draft-aware suggestion + supervisor Start-PSI override) — that problem only
    exists in the TEAM'S manual-start proposal track. Under #1 the PSI stays automated,
    drawn atomically from the single owner counter → concurrent RRs simply draw
    consecutive ranges; no collision, no start field needed.
  - **Product-blank tags (user idea 2026-07-18, inverts the team's blank-tag proposal):**
    Pallet Tag Form keeps PSI/owner/container PRINTED, leaves product (+ its PD/ED dates)
    handwritten at attach time. Floor attaches tags 1..N in unload order and writes what
    they see → product-mix corrections (the most common checker fix) become simple product
    edits on the line, ZERO cancellations, sequence stays perfect 1..N; only total-count
    shortfalls cancel, and those are naturally TAIL numbers (leftover papers). Politically:
    adopts the team's blank-tag idea but blanks the safe descriptive field, not the
    identity. TO VERIFY with floor: (1) handwriting product+dates acceptable (less than
    their own all-blank proposal), (2) tags attached in unload order not product blocks,
    (3) pre-validation product edit on encoded lines is clean (it is, PSI untouched).
  - **KEY CLOSURE (user 2026-07-18): product-blank tags SOLVE the post-print mid-deletion
    problem entirely.** Numbers aren't reserved per product, so the physical pallets always
    consume 1..N contiguously — a mid-sequence hole is impossible by construction. The
    "auto re-compute" is therefore NOT PSI renumbering (never happens, printed numbers
    frozen) but PRODUCT RE-MAPPING across fixed PSIs (line 5 chicken→beef edits, matching
    what the pens already wrote at attach); only leftover TAIL papers cancel (destroyed ☑).
    One-breath rule: "Numbers march forward and never move. Tags print numbers, pens write
    products. Products re-map to match the pens. Freed numbers cancel — labeled."
    Standard Assign Pallet Series flow unchanged — draws just come counter-only.
  - **CORRECTION WORKFLOW FACT (user 2026-07-18): Pallet Tag Forms always print at pallet-
    line ESTIMATION; the Tally Sheet returns to Documentation with dead lines CROSSED OUT —
    crossing IS the deletion instruction.** Implications: checker habit unchanged (they
    cross exactly as today; only the system's post-delete behavior changes to cancel+label);
    the in-line CANCELLED label works at any position. Product-blank tags' role:
    mix shift (same total) → floor pens actual product, checker ANNOTATES (not crosses),
    documentation EDITS the product — no deletion, no cancel.
    **TAIL-CASCADE RULE (user-confirmed): with product-blank tags attached in numeric
    unload order, shortages SLIDE TO THE TAIL** — chicken short of #5 → beef starts at 5,
    boundaries annotate (only block-boundary lines change product: ~2 annotations), and the
    truly-deleted number is the leftover TAIL paper (#15) → crossed → cancelled. Checker
    burden tiny (annotate boundaries + cross tail). Mid-sequence holes structurally
    impossible UNDER THE DISCIPLINE "attach in order, write what you see"; if the floor
    grabs product-blocks of tags instead, shortages stay mid-sequence (still handled by
    the label, tail elegance lost). This discipline is THE load-bearing floor-fact to
    confirm when presenting.
  - **FINAL PAPER DESIGN (user-corrected to the tally sheet, 2026-07-18): the TALLY SHEET's
    product column prints BLANK too — same principle as the tags.** Design principle, final:
    **"No paper ever pre-commits a product to a number. Numbers printed by the system;
    products written by the people looking at the pallet."** Tally prints numbered lines
    (# / PSI / blank product / blank actuals). Checker walks pallets in tag order, fills
    each line from the tag's pen + actuals (her normal work), and **crosses whatever lines
    remain unfilled** (the leftover tail) — crossing rule = "cross what you couldn't fill",
    zero judgment, no boundary-spotting for anyone. Returned tally = line-by-line truth;
    documentation encodes from it as today (product edits + delete crossed → auto-cancel).
    Double-penning (tag by floor, tally by checker) = two independent recordings that must
    agree — built-in verification, catches misreads on the spot. Estimate reverts to its
    true role: a count for printing enough papers, never a claim that can be wrong.
  - **FINAL SCOPE (corrected by user 2026-07-18): the algorithm RETURNS in its true form —
    the RE-SEAT TOOL.** Reason: Pallet Breakdown lines belong to per-product MOVES — a line
    can't simply flip product; making pallet 5 beef = remove from chicken move + add to
    beef move, which naively is a MID-SEQUENCE DELETE that would cancel a number standing
    live in the racks. The re-seat tool: takes tally truth (or per-product actual counts),
    re-seats lines BETWEEN moves preserving PSI values exactly (atomic, flagged like
    skip_pallet_series_sync so cancellation NEVER fires on re-seated numbers), deletes only
    truly-unfilled TAIL lines → only those cancel. Documentation-side only (preview:
    "PSI 5→Beef, PSI 10→Pork, 15 cancel — Confirm"); invisible to floor/checker. PSI
    RENUMBERING remains forbidden everywhere, forever. Build inventory: push_unused_pallet
    flip + auto-cancel + destroyed-tags ☑ + blank product columns (Tag Form, Tally Sheet)
    + in-line CANCELLED + lookup/timeline + the re-seat tool. Start-PSI override stays
    deleted (no collision problem in automated draws). **ROLE (user 2026-07-18):
    DOCUMENTATION STAFF owns move-line deletion AND the destroyed-tags ☑ — no supervisor
    step anywhere in the flow** (same person encodes the tally, deletes crossed lines,
    confirms papers destroyed — one role, one sitting).
  - **STATUS 2026-07-18: #1 PARKED (complete design above, incl. issues register).
    SOLUTION #2 proposed (user):** void/cancelled core (no reuse, cancel+label, counter
    forward) + **manual PSI & Product editing in Pallet Breakdown, FENCED to the document's
    own allocation** — Odoo suggests the start, the RR owns block [start .. start+lines-1],
    edits can only rearrange within the block (no collisions/theft possible — "manual
    freedom with a bounded blast radius"). vs #1: NO blank papers, NO floor change, no bulk
    re-seat tool (documentation hand-edits to match the returned tally; product edit still
    = move re-parent under the hood); trade-off: mid-sequence cancels return (labeled holes
    inside documents vs #1's tail-only). **#2 CONVERGED (user answers 2026-07-18):**
    editable until VALIDATION (even post-print); deletion → COMPACTION algorithm re-assigns
    remaining lines sequentially within the block, tail cancels; swaps allowed
    (no-duplicate guard); block extension on extra pallets needs confirmation. Papers stay
    fully printed as today. **THE TENSION (raised in advance this time): post-print
    compaction = paper must follow system → re-print shifted tags + physical RE-TAG WALK
    (one mid-block deletion re-numbers every line after it — 10 pallets re-tagged to close
    one gap).** #1 and #2 are exact DUALS: #1 = pens at unload daily, papers never wrong;
    #2 = papers fully printed, re-tag walks on corrections, divergence window until swap.
    Mitigations for #2: re-print only shifted lines; system-generated re-tag WORKLIST with
    pallet locations; corrections usually land while pallets still in temp aisles.
    DECIDING FLOOR QUESTION for #2: will the team reliably do the re-tag walk every
    correction? (If skipped when busy → permanent system/paper mismatch → worse than
    either clean option.) The withdrawal-picks-by-paper risk lives in the swap window.
    **★★ FINAL CONVERGENCE (user 2026-07-18): #1 + #2 MERGE.** User pulled #1's blank
    product columns into #2 → tail-cascade returns → mid-sequence deletion impossible →
    **compaction algorithm, re-tag walk, and re-print flow ALL DELETED from scope.**
    Merged solution = #2's fence/block/counter/cancel + #1's blank papers/pens/attach-in-
    order + small re-seat (product re-mapping between moves only — no PSI, no paper
    changes; pens already wrote truth). Checker's job, final: "fill what you see, cross
    what's left" (crossing the tail is the only physical possibility). Single remaining
    price: handwritten product+dates and attach-in-order discipline (#1's price) — paid
    once, buys zero re-tag walks forever. The "duals" collapsed; one solution remains.
    **TEMPLATE FRAMING (user 2026-07-18, the final mental model): the estimate is just a
    LINE COUNT ("we need 15") — the per-product division at encode is a placeholder so
    papers can print; the returned Tally Sheet is where the document gets written for
    real** (products set from the pens, tail crossed → cancel). Encoding corrections isn't
    error-fixing, it's filling in a template that was always meant to be completed later.
    Only the TOTAL matters at estimate time → floor guidance: "when unsure, round up"
    (long = cheap labeled tails; short = block-extend with confirm). EXTENDED (user): ALL
    columns blank at encode — Pallet #, Location, Product, Qty, UOM, KG all come from the
    returned TS; papers print numbers only. **UX (user 2026-07-18): per-line "Merge with
    Existing PSI" button** → wizard lists ONLY this document's PSIs (fence built into the
    picker); selecting one adopts PSI + Pallet # + Location together (same-pallet rule holds
    by construction — prevention, not rejection). Mirrors the client pallet-merge wizard
    pattern (handoff §7) — one consistent merge UX across the system. Demos artifact:
    psi-sol2-demos.html (scratchpad) — Demo 1 tail-delete, Demo 2 mixed pallet.
  - **TALLY ENCODE SCREEN — ★ PARKED (user 2026-07-18, keep in notes; await go signal):
    Magic Wizard 2.0** — OWL
    transcription surface where "the screen IS the Tally Sheet"; single atomic apply into
    stock.move.line (one choke point for fence/guards/cancel — kills the scattered
    write/onchange/ondelete bug class). **CORRECTION (user): the estimate is DR-informed,
    not invented — the Delivery Receipt is in hand at encoding with products + total KG;
    only the PALLET-level breakdown is unknown until unload.** Design upgrades from this:
    Phase 1 = "encode from the DR" (products/KG inherited, pallet counts estimated);
    TS transcription = CONFIRM-FIRST (rows pre-filled from the DR draft, Enter confirms,
    type only deviations — 35 Enters + 5 corrections beats 40 transcriptions); totals strip
    reconciles against BOTH the checker's TS totals AND the DR's declared KG (real
    receiving variance surfaces at encode time, not at billing).
    Encoder requirements spec (from role-play, feeds
    the design): (1) DR-based creation — no per-pallet guessing; (2) paper-mirror grid —
    row N = TS line N, unsortable; (3) keyboard-first Excel-style entry, eyes on paper;
    (4) one-key strike with plain-language consequence ("025 will be CANCELLED — no one
    will hunt for it"); (5) live per-product totals reconciling against checker's totals;
    (6) ALL validation errors at once with row numbers, before commit; (7) same pallet #
    typed twice = mixed pallet automatically (type the truth, no ritual); (8) draft
    persistence across interruptions. Key human insight for the pitch: today "doing it
    right still gets me blamed" (correct deletion → talon-talon investigation lands on the
    encoder) — the cancel label is emotional relief, not just audit tooling. Sequence:
    AFTER the PSI core ships (apply method calls it).
    **DUPLICATES CORRECTION (user 2026-07-18): the guard is CONSISTENCY, not uniqueness —
    standard ruling holds inside the fence: same PSI ⇔ same Pallet # + same Location
    (mixed pallet); one series = one physical pallet.** Consequences: (a) block sized by
    LINE count but distinct PSIs ≤ lines (mixed pallets) — numbers freed by grouping during
    encoding stay AVAILABLE TO THE DOCUMENT until validation (the document-scoped
    allocation, concrete reason found), unused block numbers tail-cancel at validation;
    (b) compaction moves PALLET-GROUPS not lines (all same-PSI lines shift together —
    cascade rule, never split a series); (c) tag counts / re-print worklists count
    distinct PSIs (one tag per physical pallet), not lines.
    (1) CRITICAL: FastEncodeRR churn vs no-reuse — wizard push/restore breaks under naive
    flip; need DOCUMENT-SCOPED allocation (numbers owned by the RR until print; internal
    shuffles free; nothing cancels pre-print). (2) CRITICAL: cancel-trigger exemption
    matrix — fire ONLY on incoming/non-return/unvalidated; WR lines, unvoid neutralization,
    returns, Clean Picking SA must stay silent or live stock gets cancelled. (3) CRITICAL:
    counter draw race — partner row-lock (FOR UPDATE) on every draw (SA#297 lesson; counter
    becomes single identity source). (4) Guard manual PSI typing against cancelled ledger +
    stocked quants; cancelled ledger must be a real queryable model (owner, number, source,
    destroyed ☑). (5) Re-seat tool must adjust move demands (variance gate) + skip-flags so
    ARs (series sync, SA#432 line counter) don't fire mid-shuffle. (6) Under-estimates
    interleave product blocks (chicken 1-5+16) — accepted, state in proposal. (7) Reprints
    exclude cancelled lines; add "print unprinted only" mode. (8) Timeline cutoff date —
    pre-cutover gaps stay unexplained (health-monitor stamp_cutoff pattern). (9) Field-by-
    field audit of Tag Form + Tally templates (dates/lot handwritten too). (10) Tagoloan:
    one owner counter interleaves ranges across warehouses — decide, don't discover.

## 4. Counting doctrine (the ledger, PKR)

Running identity per (owner, warehouse, BF): `total = beginning + received − withdrawn + adjustment`.

- **Received pallets** = unique result packages per RR (BF: unique Pallet Text).
- **Withdrawn pallets** = unique packages per WR **only when the pallet is exhausted**
  (`reserved_quantity_on_validation == 0`). Partial withdrawal = KG/packaging out, pallet
  stays counted in storage.
- So a pallet is counted **once when born, once when emptied** — everything between changes
  amounts only. (The upcoming merge feature extends this: merge RRs are +0 pallets by design.)
- KG/packaging/heads sum per line UNCONDITIONALLY — never tie amount sums to the pallet
  uniqueness test.
- **OB (opening balance)** rows: `record_reference = False`, created by import; OB-origin
  stock is detected STRUCTURALLY (documentless, batch-less arrival from inventory usage) —
  never by matching reference text (that's how "R 366" was misdiagnosed).

**Truth-retention policy (user-mandated, core doctrine):** the ledger is rebuilt ONLY from
transaction-backed evidence — approved adjustment audit lines posted to their linked rows,
residuals only with OB evidence. **KG residuals are NEVER force-balanced**; a difference no
transaction explains stays visible as "UNRESOLVED" (e.g. FOODASIA −1173.05 KG = a real
user-side error that must remain investigable). Never scatter synthetic per-row values to
make totals look right (the VERDURE −350 lesson: totals passed, every row was garbage).

## 5. Per-client special cases (business, not code)

- **Special No-RR-Return clients** (e.g. Mommy Loida): partial withdrawals are their norm —
  remainders stay on the original pallet; void-return landing must respect that.
- **Wonder Meats** (upcoming merge feature, Fixed mode): ONE pinned pallet forever —
  Pallet # `R 5666`, PSI `WMF-00230`. Every merge request offers exactly that pallet.
- **Consistent** (upcoming, Multiple mode): normal receiving uses their normal PSI pool;
  damaged/special stock instead merges onto **condition pallets** with per-type series —
  seeded types **MDGM, BOC, TDMG, SDMG**, each with its own forward-only numbering
  (`SDMG-000001`) + its own recycle pool. The PSI prefix IS the condition record.
- **Merge business rules:** same owner only; never BF; never returns; "is the pallet full?"
  is the **Documentation Staff's judgment** (window shows Weight/Quantity/location; no
  system capacity); merge transactions are excluded from the pallet transaction count but
  their amounts fully count. **+0 applies ONLY while the target already holds stock**
  (user ruling 2026-07-23): the FIRST stock on the empty pinned Fixed pallet BIRTHS the
  pallet — a plain, unflagged +1 line — because the WR that later exhausts it counts −1,
  and flagging the birth +0 would walk the ledger negative on every empty→fill cycle.
  The flag is decided by the pallet's stock state at merge time, so the pinned pallet
  cycles +1 (born) / −1 (emptied) / +0 (merged while stocked), keeping the
  born-once/emptied-once identity intact.
- Client profile config is Vifel-side/Elyon-side ("your team never touches settings") —
  encoders only ever see one Merge button.

## 6. Client-communication learnings (presentations, docs, PDFs)

- **Vocabulary the client actually uses:** Weight (KG) — not "KG/kilos" alone; Quantity —
  the 2nd UOM/packaging; Heads/Packs — units; Pallet # ; PSI; RR/WR/BF; PKR Log
  (Pallet Kilos Record Log); Inventory Overview; Pallet Breakdown; Picklist; Tally Sheet;
  Documentation Staff. Say "reusable/recycled PSI numbers", never "pool".
- **Never expose internal tooling** to clients: health checks/monitor, race conditions,
  Studio/SA/AR numbers. Say "all reports recognize it" instead.
- Flowcharts: top-to-bottom, START/END pills, one decision per diamond, count effects as
  separate colored pills (+1 / +0 / −1), hand-broken short lines (no one-word wraps),
  real client examples (Wonder Meats / Consistent), every part fits one page/screen.
- Branding: header "Vifel - Odoo Warehouse Management System · Enhancement"; prepared-by
  Mark Angelo Templanza — Elyon Technical Consultant; Elyon logo bottom-right footer;
  page numbers bottom-center. **POV: Elyon implements/tests/configures — not "Vifel".**
- Timeline framing: commit externally to the max estimate, target the average internally;
  book UAT with the client in advance; never promise a time of day ("to be confirmed").

## 7. Operational/engineering learnings (cost real time — don't relearn)

- **Dual-layer system**: day-to-day behavior largely lives in DB Studio automations/server
  actions, NOT the repo. Always check both layers; the context dump under-reports
  (module=NULL Studio records).
- **Odoo.sh auto-updates any module whose manifest version changes** in a push — versions
  on client-trial are PINNED to MAIN's exact strings (quote styles differ per manifest —
  diff quote-agnostically!). Real deploy must deliberately RE-BUMP.
- **Git**: machine SSH key is a read-only deploy key — push via HTTPS. MAIN is
  assistant-read-only, always. Case-variant branches (MAIN/main, Consultant-test/
  consultant-test) are distinct — never check out case twins locally on Windows.
- **Odoo shell testing harness** is the verification workhorse: driver scripts via
  `python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0`,
  commit-only-if-all-pass, full 72-owner sweeps before declaring a ledger change safe.
- **`record.copy()` copies one2many operations** — context-based guard exemptions must be
  applied to BOTH the source and the copy (M/WR/06825 lesson).
- **Search user-provided identifiers fuzzily**: users write "VE-01970", the DB says
  "VE-001970" — a not-found is not proof of absence.
- **When a test "fails", check whether the data legitimately changed** before blaming the
  code (monitor M5: expectation was stale, check was right).
- Artifact pages (claude.ai) are sandboxed: no print dialog, no downloads — deliver PDFs
  as local files (headless Edge + PyMuPDF stamping for page numbers/logos).
