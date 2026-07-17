# VIFEL — Business Context & Hard-Won Learnings

> _Created 2026-07-17. This captures the BUSINESS knowledge behind the code — the process
> on the warehouse floor, the identity/counting doctrine, per-client special cases, and
> operational lessons that cost real debugging time. Read together with `handoff.md`
> (current state) and `SYSTEM_OVERVIEW.md` (architecture). Update when the business rules
> themselves change, not on every code commit._

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
  their amounts fully count.
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
