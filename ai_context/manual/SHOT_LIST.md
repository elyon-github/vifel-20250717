# VIFEL Merge Pallet — User Manual · Screenshot Shot List

This is your capture checklist. Drop each image into `screenshots/` using the
**filename shown** (so I can place it automatically). Each item shows the caption it
will get and what to make sure is visible / highlighted.

## How to capture (please read once)
- **Format:** PNG preferred (JPG fine). Crisp — aim for ~1200 px wide or more.
- **Naming:** use the exact `NN-NN_slug.png` filename listed. Missing shots are fine —
  I'll leave a labelled placeholder box where they go.
- **Highlighting:** you don't need to annotate — I can add arrows/among/number badges and
  callouts in the doc. But if a button is easy to miss, a quick red circle helps.
- **Framing:** crop to the relevant panel when you can (whole window is OK too). Keep
  zoom consistent within a chapter.
- **Data:** real data is fine; if anything is sensitive, blur it before sending.
- **Titles:** the caption is pre-written below — if the screen/label differs from what I
  wrote, just tell me and I'll correct it (that also helps me get the wording right).

Legend: ☐ = still needed. Mark ☑ when captured. "(confirm)" = I'm unsure of the exact
screen/label — a note from you will fix it.

---

## Chapter 2 — Client Configuration
- ☐ `02-01_client-open.png` — *Open the client record (Contacts).*
- ☐ `02-02_vifel-config-tab.png` — *The "VIFEL Configuration" tab on the client form.* (confirm tab name)
- ☐ `02-03_can-merge-toggle.png` — *Turning on "Can Merge Pallets".*
- ☐ `02-04_mode-choice.png` — *Choosing the mode — Fixed vs Multiple Pallet Support.*
- ☐ `02-05_fixed-pallet-fields.png` — *Fixed mode: the pinned Fixed Merge Pallet + its PSI.*
- ☐ `02-06_multiple-psi-types.png` — *Multiple mode: the auto-created PSI types (e.g. MDGM, SDMG, TDMG, BOC).*
- ☐ `02-07_include-regular.png` — *The "Include Regular Pallets" option.*
- ☐ `02-08_lot-batch-toggles.png` — *The "Show Lot No." / "Show Batch #" toggles.*
- ☐ `02-09_client-saved.png` — *The saved, configured client.*

## Chapter 3 — Encoding Lot No. & Batch # (→ Prodcode)
- ☐ `03-01_rr-open.png` — *Open a Receiving Report and go to the Pallet Breakdown.* (confirm screen name)
- ☐ `03-02_lot-no-field.png` — *Entering the Lot No. on a line.*
- ☐ `03-03_batch-no-field.png` — *Entering the Batch # on a line.*
- ☐ `03-04_magic-wizard-lot-batch.png` — *The same Lot No. / Batch # fields inside the Magic Wizard.*
- ☐ `03-05_rr-validate.png` — *Validating the receipt.*
- ☐ `03-06_quant-prodcode.png` — *The stored stock (Inventory) showing the generated Prodcode.*
- ☐ `03-07_prodcode-on-wr.png` — *The Prodcode shown (read-only) on a withdrawal line.*
- (I'll explain the Prodcode format in text: expiration date + Batch # + building "M".)

## Chapter 4 — Receiving & Merge (Overview)
- ☐ `04-01_rr-lines.png` — *A receipt with lines in the Pallet Breakdown.*
- ☐ `04-02_merge-button.png` — *The Merge button on a line (where it appears).*
- ☐ `04-03_magic-wizard-open.png` — *The Magic Wizard opened on a line.*

### 4A — Merge Type 1: Fixed Merge Pallet
- ☐ `04A-01_fixed-wizard.png` — *The merge dialog in Fixed mode (the pinned pallet pre-selected).*
- ☐ `04A-02_fixed-confirm.png` — *Confirming — the line moves onto the fixed pallet.*
- ☐ `04A-03_fixed-result.png` — *The line now shown as Merged on the fixed pallet.*

### 4B — Merge Type 2: Multiple Special Pallet
- ☐ `04B-01_candidates.png` — *The merge dialog in Multiple mode — the candidate pallets list.*
- ☐ `04B-02_merge-existing.png` — *Merging onto an existing stocked pallet ("Merge Here").*
- ☐ `04B-03_same-receipt.png` — *Joining another line on the same receipt.*
- ☐ `04B-04_new-special.png` — *Starting a new special pallet (pick PSI type, empty pallet, location).*
- ☐ `04B-05_confirm-result.png` — *Confirming — the staged result on the line.*

### 4C — Un-merge
- ☐ `04C-01_unmerge-button.png` — *The Un-merge button on a merged line.*
- ☐ `04C-02_unmerge-result.png` — *The line after un-merging.*

## Chapter 5 — Withdrawal (WR)
- ☐ `05-01_wr-open.png` — *Open / create the Withdrawal.*
- ☐ `05-02_select-stocks-button.png` — *The "Select Stocks" button on the line.*
- ☐ `05-03_select-stocks-wizard.png` — *The Select Stocks window listing the pallet's quants.*
- ☐ `05-04_partial-quantity.png` — *Reducing the quantity for a partial withdrawal.*
- ☐ `05-05_removal-confirm.png` — *The "Confirm Stock Removal" dialog.*
- ☐ `05-06_multi-truck.png` — *A second truck (WR) withdrawing from the same pallet.* (confirm how you start truck 2)
- ☐ `05-07_wr-validate.png` — *Validating the withdrawal.*
- (I'll explain the rule in text: a shared pallet counts on the truck that empties it.)

## Chapter 6 — Reporting & Pallet Count
- ☐ `06-01_rr-print.png` — *The printed Receiving Report with its pallet count.*
- ☐ `06-02_wr-print.png` — *The printed Withdrawal Report with its withdrawn count.*
- ☐ `06-03_pallet-ledger.png` — *The Pallet / Kilos record (the running count).* (confirm exact report name)
- ☐ `06-04_occupancy-or-billing.png` — *Occupancy / billing report, if you want it included.* (optional)

---

### When you've dropped some in
Tell me which chapters you've filled (even partially) and I'll draft those chapters and
render pages for you to review. We don't need everything at once — I can build chapter by
chapter as screenshots arrive.
