// VIFEL Merge Pallet - USER MANUAL (Chapter 2 preview) - Elyon → Vifel, Vifel navy.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, Footer, AlignmentType, LevelFormat, TabStopType,
  HeadingLevel, BorderStyle, WidthType, ShadingType, VerticalAlign,
  PageNumber, PageBreak,
} = require("docx");

const DIR = __dirname;
const ASSET = (f) => path.join(DIR, "..", "blueprint", "assets", f);
const SHOT = (f) => path.join(DIR, "annotated", f);

const NAVY = "002880", NAVY_D = "001B57", GREEN = "0A9E0A";
const INK = "1E1E1E", GREY = "5A5A5A", RULE = "C9CFE4";
const HEADFILL = "E9ECF7", BOX = "EEF1FA";
const CW = 9360;

const T = (text, o = {}) => new TextRun({ text, font: "Arial", ...o });
const P = (children, o = {}) =>
  new Paragraph({ children: Array.isArray(children) ? children : [children], ...o });
const body = (text, o = {}) =>
  P([T(text, { size: 21, color: INK })], { spacing: { after: 120, line: 268 }, ...o });
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [T(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [T(text)] });

// natural sizes of the annotated PNGs
const DIM = {
  "02-01a_open_contacts.png": [1120, 345], "02-01b_pick_client.png": [1902, 360],
  "02-02_config_tab.png": [1264, 290], "02-03_can_merge.png": [1252, 445],
  "02-05_fixed_mode.png": [1226, 215], "02-06_multiple_mode.png": [1259, 535],
  "02-07_include_regular.png": [1252, 260], "02-08a_documents.png": [530, 190],
  "02-08b_save.png": [780, 76],
  "03-00a_open_inventory.png": [900, 345], "03-00b_receiving.png": [770, 300],
  "03-00c_new_rr.png": [900, 205], "03-00d_select_client.png": [1160, 445],
  "03-02_lot_batch_breakdown.png": [1908, 447], "03-04_magic_wizard.png": [1882, 710],
  "03-06_validate_done.png": [1249, 176], "03-06b_quant_prodcode.png": [1470, 505],
  "03-07_prodcode_wr.png": [1894, 350], "02-08a_documents_ctx.png": [532, 196],
  "04-01_merge_button.png": [1300, 242], "04-03_magic_merge.png": [1495, 467],
  "04A-01_fixed_dialog.png": [1840, 625], "04A-03_fixed_result.png": [1580, 570],
  "04B-01_multiple_lines.png": [1260, 227], "04B-02_merge_existing.png": [1860, 690],
  "04B-04_new_special.png": [955, 327], "04B-05_result.png": [1913, 540],
  "04C_unmerge.png": [540, 74], "05_wr_readonly.png": [1894, 350],
};
function pngSize(p) {                       // read actual PNG dimensions (shadow-safe)
  const b = fs.readFileSync(p);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}
function shot(file, maxW = 596) {
  const p = SHOT(file);
  const [w, h] = pngSize(p);
  const dw = Math.min(maxW, w), dh = Math.round(h * (dw / w));
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 40, after: 40 },
    children: [new ImageRun({
      type: "png", data: fs.readFileSync(p),
      transformation: { width: dw, height: dh },
      altText: { title: file, description: file, name: file },
    })],
  });
}
const caption = (text) =>
  P([T(text, { size: 17, italics: true, color: GREY })],
    { alignment: AlignmentType.CENTER, spacing: { after: 180 } });

const frontTitle = (text) =>
  P([T(text, { size: 30, bold: true, color: NAVY })],
    { spacing: { before: 60, after: 200 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 10, color: NAVY, space: 6 } } });
const tocMain = (num, title) =>
  new Paragraph({ spacing: { after: 70, line: 276 },
    tabStops: [{ type: TabStopType.LEFT, position: 720 }],
    children: [T(num, { size: 22, bold: true, color: NAVY }), T("\t" + title, { size: 22, color: INK })] });
const tocSub = (num, title) =>
  new Paragraph({ spacing: { after: 46, line: 264 }, indent: { left: 720 },
    tabStops: [{ type: TabStopType.LEFT, position: 1320 }],
    children: [T(num, { size: 20, color: GREY }), T("\t" + title, { size: 20, color: GREY })] });

// numbered step heading: navy "Step N" + title
const step = (n, title) =>
  P([T("Step " + n + "  ", { size: 22, bold: true, color: NAVY }),
     T("· " + title, { size: 22, bold: true, color: NAVY_D })],
    { spacing: { before: 140, after: 60 } });

function callout(titleText, items) {
  const inner = [
    P([T(titleText, { size: 20, bold: true, color: NAVY, allCaps: true })], { spacing: { after: 90 } }),
    ...items.map((it) => new Paragraph({
      numbering: { reference: "cbul", level: 0 }, spacing: { after: 50, line: 252 },
      children: [T(it, { size: 20, color: INK })] })),
  ];
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CW, type: WidthType.DXA },
      borders: { top: { style: BorderStyle.SINGLE, size: 14, color: NAVY },
                 bottom: { style: BorderStyle.SINGLE, size: 1, color: RULE },
                 left: { style: BorderStyle.SINGLE, size: 1, color: RULE },
                 right: { style: BorderStyle.SINGLE, size: 1, color: RULE } },
      shading: { fill: BOX, type: ShadingType.CLEAR },
      margins: { top: 140, bottom: 140, left: 200, right: 200 },
      children: inner })] })],
  });
}
const spacer = (h = 160) => P([T("", {})], { spacing: { after: h } });

// compact reference table
const _cB = { style: BorderStyle.SINGLE, size: 1, color: RULE };
const _allB = { top: _cB, bottom: _cB, left: _cB, right: _cB };
function tbl(widths, rows) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((cells, ri) => new TableRow({
      tableHeader: ri === 0,
      children: cells.map((c, ci) => new TableCell({
        width: { size: widths[ci], type: WidthType.DXA },
        borders: _allB, margins: { top: 80, bottom: 80, left: 130, right: 130 },
        verticalAlign: VerticalAlign.CENTER,
        shading: { fill: ri === 0 ? HEADFILL : (ri % 2 === 0 ? "F5F7FC" : "FFFFFF"),
                   type: ShadingType.CLEAR },
        children: [P([T(c.t, { size: 20, bold: ri === 0 || c.bold || false,
                               color: ri === 0 ? NAVY : (c.color || INK) })],
          { alignment: c.align || AlignmentType.LEFT, spacing: { after: 0, line: 252 } })],
      })),
    })),
  });
}
const img = (file, w, h) => new ImageRun({
  type: "png", data: fs.readFileSync(ASSET(file)),
  transformation: { width: w, height: h },
  altText: { title: "logo", description: "logo", name: "logo" } });

// ---------------- COVER ----------------
const cover = [
  P([img("elyon_logo.png", 224, 63)], { alignment: AlignmentType.CENTER, spacing: { after: 40 } }),
  P([T("USER MANUAL", { size: 18, color: GREEN, bold: true, characterSpacing: 40 })],
    { alignment: AlignmentType.CENTER, spacing: { after: 460 } }),
  new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CW, type: WidthType.DXA },
      borders: { top: { style: BorderStyle.SINGLE, size: 2, color: NAVY },
                 bottom: { style: BorderStyle.SINGLE, size: 2, color: NAVY },
                 left: { style: BorderStyle.SINGLE, size: 2, color: NAVY },
                 right: { style: BorderStyle.SINGLE, size: 2, color: NAVY } },
      shading: { fill: NAVY, type: ShadingType.CLEAR },
      margins: { top: 460, bottom: 460, left: 380, right: 380 },
      children: [
        P([T("PALLET MERGE ENHANCEMENT", { size: 50, bold: true, color: "FFFFFF" })], { spacing: { after: 120 } }),
        P([T("User Manual", { size: 30, color: "FFFFFF" })], { spacing: { after: 60 } }),
        P([T("Inventory Supervisor & Documentation Staff Guide", { size: 18, color: "C7D0EE", characterSpacing: 20 })]),
      ] })] })],
  }),
  spacer(520),
  P([T("PREPARED FOR", { size: 17, bold: true, color: GREY, characterSpacing: 60 })],
    { alignment: AlignmentType.CENTER, spacing: { after: 120 } }),
  P([img("vifel_logo.png", 232, 108)], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
  P([T("Vifel Ice Plant & Cold Storage, Inc.", { size: 24, bold: true, color: NAVY })],
    { alignment: AlignmentType.CENTER, spacing: { after: 560 } }),
  P([T("05 August 2026", { size: 20, bold: true, color: NAVY })],
    { alignment: AlignmentType.CENTER, spacing: { before: 80, after: 30 },
      border: { top: { style: BorderStyle.SINGLE, size: 10, color: NAVY, space: 12 } } }),
  spacer(120),
  P([T("Prepared by ", { size: 18, color: GREY }),
     T("Elyon Solutions International Inc.", { size: 18, bold: true, color: INK })],
    { alignment: AlignmentType.CENTER }),
];

// ---------------- CONTENTS ----------------
const toc = [
  frontTitle("Contents"),
  tocMain("", "How to use this manual"),
  tocMain("2", "Client Configuration"),
  tocSub("2.1", "Open the client"),
  tocSub("2.2", "Open the VIFEL Configuration tab"),
  tocSub("2.3", "Turn on merging"),
  tocSub("2.4", "Choose how the client merges"),
  tocSub("2.5", "Document options (Lot No. / Batch # / Prodcode)"),
  tocSub("2.6", "Save"),
  spacer(60),
  tocMain("3", "Encoding Lot No. & Batch # (→ Prodcode)"),
  tocSub("3.1", "Before you start"),
  tocSub("3.2", "Open a new Receiving Report"),
  tocSub("3.3", "Enter Lot No. & Batch #"),
  tocSub("3.4", "Validate - the Prodcode is generated"),
  spacer(60),
  tocMain("4", "Receiving & Merge"),
  tocSub("4.1", "Start a merge"),
  tocSub("4.2", "Merge Type 1 - Fixed Merge Pallet"),
  tocSub("4.3", "Merge Type 2 - Multiple Special Pallets"),
  tocSub("4.4", "Un-merge"),
  spacer(60),
  tocMain("5", "Withdrawal & Pallet Counting"),
  tocSub("5.1", "How pallets are counted"),
  tocSub("5.2", "Lot No., Batch # & Prodcode on the withdrawal"),
];

// ---------------- HOW TO USE ----------------
const howto = [
  P([new PageBreak()]),
  h1("How to use this manual"),
  body("This manual walks you through the Merge Pallet feature one screen at a time. It is written for the Inventory Supervisor and Documentation Staff - each task is broken into short, numbered steps with a matching screenshot, so you can follow along directly on your own screen."),
  spacer(40),
  callout("Reading the screenshots", [
    "A red box shows exactly where to look or click on the screen.",
    "A blue numbered circle matches the numbered Step in the text beside it.",
    "Screens are cropped to the part that matters - your screen shows more around it.",
    "Labels in bold (e.g. Can Merge Pallets) are the exact words you will see in the system.",
  ]),
  spacer(40),
  callout("Who does what", [
    "Client configuration (Chapter 2) is set up by the Inventory Supervisor.",
    "Encoding receipts (RR) and withdrawals (WR) is done by Documentation Staff.",
  ]),
  spacer(60),
  body("Chapter 2 below - Client Configuration - is the one-time setup that turns merging on for a client. The chapters that follow cover encoding Lot No. & Batch #, merging during receiving, withdrawal, and reporting."),
];

// ---------------- CHAPTER 2 ----------------
const ch2 = [
  P([new PageBreak()]),
  h1("Chapter 2 · Client Configuration"),
  body("Merging is set up per client. Nothing changes for a client until it is switched on here - so this is where every merge client begins. It is done once, and only revisited if the client's setup changes."),
  callout("Who does this · before you start", [
    "Responsible role: the Inventory Supervisor sets up client configuration. Documentation Staff who need a client configured should ask the Inventory Supervisor.",
    "It is done once per client (and again only if the client's setup changes).",
    "Have the client's merge details ready: whether they use one fixed pallet or several special pallet types, and whether they track Lot No. / Batch #.",
  ]),

  h2("2.1  Open the client"),
  step(1, "Open Contacts"),
  body("From the Odoo home screen, click Contacts."),
  shot("02-01a_open_contacts.png"),
  caption("Figure 2.1 - The Contacts app on the Odoo home screen."),
  step(2, "Open the client you want to set up"),
  body("Search for the client by name, then click their card to open it."),
  shot("02-01b_pick_client.png"),
  caption("Figure 2.2 - Search for the client in the Contacts list."),

  h2("2.2  Open the VIFEL Configuration tab"),
  step(3, "Go to VIFEL Configuration"),
  body("On the client form, scroll down to the row of tabs and click VIFEL Configuration. All merge settings live on this tab."),
  shot("02-02_config_tab.png"),
  caption("Figure 2.3 - The VIFEL Configuration tab on the client form."),

  h2("2.3  Turn on merging"),
  step(4, "Tick Can Merge Pallets"),
  body("Under PALLET MERGING, tick Can Merge Pallets. A new section, HOW THIS CLIENT MERGES, appears below - that is where you choose the merge style."),
  shot("02-03_can_merge.png"),
  caption("Figure 2.4 - Turning on Can Merge Pallets reveals the merge options."),

  h2("2.4  Choose how the client merges"),
  body("There are two merge styles. The Multiple Pallet Support switch decides which one this client uses - follow Option A or Option B, not both."),

  P([T("Option A - Fixed Merge Pallet  (switch OFF)", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 120, after: 60 } }),
  body("Leave Multiple Pallet Support unticked. Every merge for this client goes onto one dedicated pallet."),
  step(5, "Leave Multiple Pallet Support OFF"),
  step(6, "Enter the Fixed Merge Pallet and Fixed Merge PSI"),
  body("Type the client's dedicated pallet number in Fixed Merge Pallet, and its series in Fixed Merge PSI."),
  shot("02-05_fixed_mode.png"),
  caption("Figure 2.5 - Fixed mode: one dedicated pallet and its PSI."),

  P([T("Option B - Multiple Special Pallets  (switch ON)", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 160, after: 60 } }),
  body("Tick Multiple Pallet Support. The client's special pallet types appear in the Pallet Types table, each with its own prefix and running number (for example MDGM, SDMG, TDMG, BOC)."),
  step(5, "Tick Multiple Pallet Support"),
  step(6, "Review the Pallet Types"),
  body("The standard types are created automatically. You normally do not need to change them."),
  shot("02-06_multiple_mode.png"),
  caption("Figure 2.6 - Multiple mode: the client's special pallet types."),
  step(7, "Optional - Include Regular Pallets"),
  body("Tick Include Regular Pallets only if this client may also merge onto ordinary stock pallets, not just their special ones."),
  shot("02-07_include_regular.png"),
  caption("Figure 2.7 - Include Regular Pallets (optional)."),

  h2("2.5  Document options (Lot No. / Batch # / Prodcode)"),
  step(8, "Set the DOCUMENTS options"),
  body("Under DOCUMENTS, tick Show Lot No. and Show Batch # / Prodcode if this client tracks them. These control the fields you will encode during receiving (covered in Chapter 3)."),
  shot("02-08a_documents.png"),
  caption("Figure 2.8 - Document tracking options for the client."),

  h2("2.6  Save"),
  step(9, "Save the client"),
  body("Click the save (cloud) icon at the top of the form. The client is now ready to use merging."),
  shot("02-08b_save.png"),
  caption("Figure 2.9 - Save the client with the cloud icon."),

  spacer(60),
  callout("What's next", [
    "Chapter 3 - Encoding Lot No. & Batch # (→ Prodcode).",
  ]),
];

// ---------------- CHAPTER 3 ----------------
const ch3 = [
  P([new PageBreak()]),
  h1("Chapter 3 · Encoding Lot No. & Batch # (→ Prodcode)"),
  body("Some clients track a Lot No. and a Batch # on every pallet they receive. You type these while encoding the Receiving Report; when the receipt is validated, the system automatically builds a Prodcode from them and keeps it with the stock. This chapter shows the whole flow."),
  callout("Who does this · before you start", [
    "Responsible role: encoding receipts (RR) and withdrawals (WR) is done by Documentation Staff. Client configuration (Chapter 2) is the Inventory Supervisor's task.",
    "The client must have Show Lot No. and Show Batch # / Prodcode switched on - set once by the Inventory Supervisor in the client's VIFEL Configuration (Chapter 2).",
  ]),
  shot("02-08a_documents_ctx.png", 360),
  caption("Reminder - the client's Lot No. / Batch # options, set in Chapter 2."),

  h2("3.1  Before you start"),
  body("Make sure the receipt is for a client that has Lot No. / Batch # enabled. If it is not, ask your Inventory Supervisor to switch it on (see Chapter 2)."),

  h2("3.2  Open a new Receiving Report"),
  step(1, "Open Inventory"),
  body("From the Odoo home screen, click Inventory."),
  shot("03-00a_open_inventory.png"),
  caption("Figure 3.1 - The Inventory app."),
  step(2, "Open RECEIVING"),
  body("On the Inventory Overview, click the RECEIVING operation type."),
  shot("03-00b_receiving.png", 470),
  caption("Figure 3.2 - The RECEIVING operations card."),
  step(3, "Create a new receipt"),
  body("Click New to start a new Receiving Report."),
  shot("03-00c_new_rr.png"),
  caption("Figure 3.3 - Start a new Receiving Report."),
  step(4, "Select the client and encode as usual"),
  body("Choose the client in the Customer field, then fill in the Receiving Report as you normally would. Follow the on-screen “Steps to Begin” note - set the Destination Location and remember to save (Alt + S)."),
  shot("03-00d_select_client.png"),
  caption("Figure 3.4 - Select the client, then encode the receipt as usual."),

  h2("3.3  Enter Lot No. & Batch #"),
  body("You can enter Lot No. and Batch # in either of two places - use whichever you prefer. Both write to the same lines."),
  P([T("Option A - in the Pallet Breakdown", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 120, after: 60 } }),
  step(5, "Type Lot No. and Batch # on each line"),
  body("In the Detailed Operations (Pallet Breakdown) grid, fill the Lot No. and Batch # columns for each pallet line."),
  shot("03-02_lot_batch_breakdown.png"),
  caption("Figure 3.5 - Lot No. and Batch # columns in the Pallet Breakdown."),
  P([T("Option B - in the Magic Wizard", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 160, after: 60 } }),
  step(6, "Enter them in the Magic Wizard"),
  body("Click Magic Wizard to open Fast Encode RR Lines, then fill the Lot No. and Batch # columns there. Click Confirm when done."),
  shot("03-04_magic_wizard.png"),
  caption("Figure 3.6 - Lot No. and Batch # in the Magic Wizard."),

  h2("3.4  Validate - the Prodcode is generated"),
  step(7, "Validate the receipt"),
  body("Finish and validate the Receiving Report. Once it reaches Done, the stock is created."),
  shot("03-06_validate_done.png"),
  caption("Figure 3.7 - The receipt validated (Done); the stock is created."),
  step(8, "Open Location Related Stocks to see the Prodcode"),
  body("Click Location Related Stocks on the receipt. Each stored pallet now carries its Prodcode, built automatically from the Expiration Date and the Batch #, followed by a fixed letter M - for example 01JAN2027 + 25 + M."),
  shot("03-06b_quant_prodcode.png"),
  caption("Figure 3.8 - The Prodcode stored on each pallet (Location Related Stocks)."),
  body("The Prodcode stays with the stock and is also shown, read-only, on the withdrawal's Pallet Breakdown."),
  step(9, "See the Prodcode on a withdrawal"),
  shot("03-07_prodcode_wr.png"),
  caption("Figure 3.9 - The Prodcode (read-only) on a later withdrawal."),

  spacer(60),
  callout("What's next", [
    "Chapter 4 - Receiving & Merge (Fixed and Multiple).",
  ]),
];

// ---------------- CHAPTER 4 ----------------
const ch4 = [
  P([new PageBreak()]),
  h1("Chapter 4 · Receiving & Merge"),
  body("During receiving you can merge a pallet line onto another pallet, so several products or batches share one physical pallet. How the merge behaves depends on the client's setup (Chapter 2): a Fixed client uses one dedicated pallet; a Multiple client has several special pallets. Either way the merge starts the same, and any merge can be reversed with Un-merge."),
  callout("Who does this · before you start", [
    "Responsible role: Documentation Staff merge pallets while encoding the receipt.",
    "The client must have Can Merge Pallets switched on (set by the Inventory Supervisor - Chapter 2).",
    "Merging onto a pallet that already holds stock does not add to the pallet count (+0). The first stock on an empty pallet, or a brand-new special pallet, counts as one received pallet (+1).",
  ]),

  h2("4.1  Start a merge"),
  body("The merge starts the same way for every client. On the receipt's Pallet Breakdown, find the line you want to merge and click Merge Pallet."),
  step(1, "Click Merge Pallet on the line"),
  shot("04-01_merge_button.png"),
  caption("Figure 4.1 - The Merge Pallet button on a receipt line."),
  step(2, "Or start it from the Magic Wizard"),
  body("You can also open the Magic Wizard and click Merge on the line - it opens the same dialog."),
  shot("04-03_magic_merge.png"),
  caption("Figure 4.2 - Starting a merge from the Magic Wizard."),

  h2("4.2  Merge Type 1 - Fixed Merge Pallet"),
  body("For a Fixed client, the dialog already has the client's one dedicated pallet set to Merge Here - you just confirm."),
  step(3, "Review and Confirm"),
  body("Check that Merge Here is on for the fixed pallet, then click Confirm. If the pallet is still empty, this first line counts as one received pallet; later lines merging onto it (once it holds stock) do not."),
  shot("04A-01_fixed_dialog.png"),
  caption("Figure 4.3 - Fixed mode: the dedicated pallet is pre-selected."),
  step(4, "The line is now merged"),
  body("The line adopts the fixed pallet's series and now shows Un-merge."),
  shot("04A-03_fixed_result.png"),
  caption("Figure 4.4 - The merged line on the fixed pallet (WM-32423 / 00001 B)."),

  h2("4.3  Merge Type 2 - Multiple Special Pallets"),
  body("For a Multiple client, click Merge Pallet on the line the same way - but the dialog now offers two choices: merge onto a pallet already stocked, or start a new special pallet."),
  shot("04B-01_multiple_lines.png", 500),
  caption("Figure 4.5 - A Multiple client's receipt; start the same way with Merge Pallet."),

  P([T("Option A - Merge onto a pallet already stocked", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 120, after: 60 } }),
  step(5, "Pick the pallet to merge onto"),
  body("Choose Merge onto a pallet already stocked. The client's special pallets currently in storage are listed. Turn on Merge Here for the one you want - its current contents appear under On the selected pallet - then click Confirm."),
  shot("04B-02_merge_existing.png"),
  caption("Figure 4.6 - Choosing an existing special pallet to merge onto."),

  P([T("Option B - Start a NEW special pallet", { size: 22, bold: true, color: NAVY })],
    { spacing: { before: 160, after: 60 } }),
  step(6, "Fill the three details"),
  body("Choose Start a NEW special pallet, then fill all three: PSI Type, New Empty Pallet, and New Location. Click Confirm - the pallet is created and assigned to the line. A new special pallet counts as one received pallet (+1)."),
  shot("04B-04_new_special.png", 520),
  caption("Figure 4.7 - Starting a new special pallet."),
  step(7, "Confirmation"),
  body("A notification confirms the new pallet, and the line now shows Un-merge on it."),
  shot("04B-05_result.png"),
  caption("Figure 4.8 - The new special pallet created and assigned to the line."),

  h2("4.4  Un-merge"),
  body("Any merged line can be reversed. Click Un-merge on the line - its original Pallet Series comes back, and the pallet count self-corrects."),
  step(8, "Click Un-merge"),
  shot("04C_unmerge.png", 360),
  caption("Figure 4.9 - Un-merge returns the line's original pallet."),

  spacer(60),
  callout("What's next", [
    "Chapter 5 - Withdrawal & Pallet Counting.",
  ]),
];

// ---------------- CHAPTER 5 ----------------
const ch5 = [
  P([new PageBreak()]),
  h1("Chapter 5 · Withdrawal & Pallet Counting"),
  body("Withdrawing merged stock is done exactly like any other withdrawal - the merge feature adds no extra steps here. What is worth knowing is how a merge pallet is counted on your printouts, and that the Lot No., Batch #, and Prodcode stay visible when you withdraw."),
  callout("Who does this", [
    "Responsible role: Documentation Staff encode withdrawals (WR) - the same as any withdrawal.",
  ]),

  h2("5.1  How pallets are counted"),
  body("One physical pallet is always counted once. This table shows how each scenario is counted on the receiving and withdrawal printouts."),
  spacer(40),
  tbl([6760, 2600], [
    [{ t: "Scenario" }, { t: "Counts as", align: AlignmentType.CENTER }],
    [{ t: "Receiving - merge onto a pallet that already holds stock" },
     { t: "+0  (no new pallet)", align: AlignmentType.CENTER, bold: true, color: NAVY }],
    [{ t: "Receiving - first stock on an empty pallet, or a new special pallet" },
     { t: "+1", align: AlignmentType.CENTER, bold: true }],
    [{ t: "Withdrawal - partial (stock still left on the pallet)" },
     { t: "−0  (pallet stays)", align: AlignmentType.CENTER, bold: true, color: NAVY }],
    [{ t: "Withdrawal - full (pallet emptied)" },
     { t: "−1", align: AlignmentType.CENTER, bold: true }],
  ]),
  spacer(80),
  body("If a shared pallet is split across several trucks, it is counted on the withdrawal that empties it - not on the first truck that draws from it."),

  h2("5.2  Lot No., Batch # & Prodcode on the withdrawal"),
  body("When you withdraw, the Lot No. and the stored Prodcode (which already includes the Batch #) are shown, read-only, on the withdrawal's Pallet Breakdown, so the same identifiers follow the stock all the way out."),
  shot("05_wr_readonly.png"),
  caption("Figure 5.1 - Lot No. and Prodcode shown (read-only) on a withdrawal."),

  spacer(60),
  callout("That's the whole flow", [
    "Client Configuration → Lot / Batch encoding → Merge on receiving → Withdrawal & counting.",
    "One physical pallet, counted once - from receiving all the way to withdrawal.",
  ]),
];

const header = new Header({ children: [new Paragraph({
  tabStops: [{ type: TabStopType.RIGHT, position: CW }],
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 4 } },
  spacing: { after: 60 },
  children: [T("Merge Pallet - User Manual", { size: 16, color: NAVY, bold: true }),
             T("\tElyon Solutions × Vifel", { size: 16, color: GREY })] })] });
const footer = new Footer({ children: [new Paragraph({
  tabStops: [{ type: TabStopType.RIGHT, position: CW }],
  border: { top: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 4 } },
  spacing: { before: 40 },
  children: [T("© 2026 Elyon Solutions International Inc.", { size: 15, color: GREY }),
             T("\tPage ", { size: 15, color: GREY }),
             new TextRun({ children: [PageNumber.CURRENT], size: 15, color: GREY, font: "Arial" })] })] });

const doc = new Document({
  creator: "Elyon Solutions International Inc.",
  title: "Pallet Merge Enhancement - User Manual",
  styles: {
    default: { document: { run: { font: "Arial", size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 300, after: 160 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: RULE, space: 6 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: NAVY_D, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "cbul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "▪",
      alignment: AlignmentType.LEFT,
      style: { run: { color: NAVY }, paragraph: { indent: { left: 400, hanging: 220 } } } }] },
  ] },
  sections: [
    { properties: { page: { size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1440, bottom: 1080, left: 1440 } } }, children: cover },
    { properties: { page: { size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1260, left: 1440 }, pageNumbers: { start: 1 } } },
      headers: { default: header }, footers: { default: footer },
      children: [...toc, ...howto, ...ch2, ...ch3, ...ch4, ...ch5] },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(DIR, "VIFEL_Merge_Pallet_User_Manual.docx");
  fs.writeFileSync(out, buf);
  console.log("WROTE", out, buf.length, "bytes");
});
