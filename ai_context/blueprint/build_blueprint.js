// Pallet Merge Enhancement — To-Be Functional Blueprint (Elyon → Vifel)
// Executive-summary depth, Vifel-navy accent (#002880), Elyon-green secondary.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, Footer, AlignmentType, LevelFormat, TabStopType,
  TabStopPosition, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, PageBreak, TableOfContents,
} = require("docx");

const DIR = __dirname;
const ASSET = (f) => path.join(DIR, "assets", f);

// ---- palette ----
const NAVY = "002880";     // Vifel primary
const NAVY_D = "001B57";
const GREEN = "0A9E0A";    // Elyon secondary
const INK = "1E1E1E";
const GREY = "5A5A5A";
const RULE = "C9CFE4";     // soft navy-grey rule
const HEADFILL = "E9ECF7"; // light navy tint (table headers)
const ZEBRA = "F5F7FC";    // zebra row
const BOX = "EEF1FA";      // callout box

const CW = 9360; // content width, US Letter 1" margins

// ---- helpers ----
const T = (text, o = {}) => new TextRun({ text, font: "Arial", ...o });
const P = (children, o = {}) =>
  new Paragraph({ children: Array.isArray(children) ? children : [children], ...o });

const body = (text, o = {}) =>
  P([T(text, { size: 21, color: INK })], { spacing: { after: 120, line: 264 }, ...o });

const bullet = (runs) =>
  new Paragraph({
    numbering: { reference: "bul", level: 0 },
    spacing: { after: 70, line: 258 },
    children: Array.isArray(runs) ? runs : [T(runs, { size: 21, color: INK })],
  });

const h1 = (text) =>
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [T(text)] });
const h2 = (text) =>
  new Paragraph({ heading: HeadingLevel.HEADING_2, children: [T(text)] });

const frontTitle = (text) =>
  P([T(text, { size: 30, bold: true, color: NAVY })],
    { spacing: { before: 60, after: 200 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 10, color: NAVY, space: 6 } } });

const img = (file, w, h) =>
  new ImageRun({
    type: "png", data: fs.readFileSync(ASSET(file)),
    transformation: { width: w, height: h },
    altText: { title: "logo", description: "logo", name: "logo" },
  });

const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: RULE };
const allCell = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
const M = { top: 70, bottom: 70, left: 130, right: 130 };

// generic table: rows = array of arrays of {t, ...opts}; widths sum to CW
function table(widths, rows, { header = true } = {}) {
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((cells, ri) =>
      new TableRow({
        tableHeader: header && ri === 0,
        children: cells.map((c, ci) =>
          new TableCell({
            width: { size: widths[ci], type: WidthType.DXA },
            borders: allCell, margins: M, verticalAlign: VerticalAlign.CENTER,
            shading: {
              fill: header && ri === 0 ? HEADFILL : (ri % 2 === 0 ? ZEBRA : "FFFFFF"),
              type: ShadingType.CLEAR,
            },
            children: [P(
              (Array.isArray(c.runs) ? c.runs : [T(c.t, {
                size: 20,
                bold: (header && ri === 0) || c.bold || false,
                color: (header && ri === 0) ? NAVY : (c.color || INK),
              })]),
              { alignment: c.align || AlignmentType.LEFT,
                spacing: { after: 0, line: 250 } }
            )],
          })
        ),
      })
    ),
  });
}

// single-cell callout box (content, not a divider)
function callout(titleText, items) {
  const inner = [
    P([T(titleText, { size: 20, bold: true, color: NAVY, allCaps: true })],
      { spacing: { after: 90 } }),
    ...items.map((it) =>
      new Paragraph({
        numbering: { reference: "cbul", level: 0 },
        spacing: { after: 50, line: 252 },
        children: [T(it, { size: 20, color: INK })],
      })),
  ];
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CW, type: WidthType.DXA },
      borders: { top: { style: BorderStyle.SINGLE, size: 14, color: NAVY },
                 bottom: cellBorder, left: cellBorder, right: cellBorder },
      shading: { fill: BOX, type: ShadingType.CLEAR },
      margins: { top: 150, bottom: 150, left: 200, right: 200 },
      children: inner,
    })] })],
  });
}

const spacer = (h = 200) => P([T("", {})], { spacing: { after: h } });

// ============================ COVER ============================
const cover = [
  P([img("elyon_logo.png", 224, 63)], { spacing: { after: 40 } }),
  P([T("SOLUTIONS BLUEPRINT", { size: 18, color: GREEN, bold: true, characterSpacing: 40 })],
    { spacing: { after: 480 } }),

  // navy title band (single-cell content block)
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
        P([T("PALLET MERGE ENHANCEMENT", { size: 52, bold: true, color: "FFFFFF" })],
          { spacing: { after: 120 } }),
        P([T("To-Be Functional Blueprint", { size: 30, color: "FFFFFF" })],
          { spacing: { after: 60 } }),
        P([T("Client-Specific Requirement Enhancement", { size: 19, color: "C7D0EE", characterSpacing: 20 })]),
      ],
    })] })],
  }),

  spacer(520),
  P([T("PREPARED FOR", { size: 17, bold: true, color: GREY, characterSpacing: 60 })],
    { alignment: AlignmentType.CENTER, spacing: { after: 120 } }),
  P([img("vifel_logo.png", 232, 108)], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
  P([T("Vifel Ice Plant & Cold Storage, Inc.", { size: 24, bold: true, color: NAVY })],
    { alignment: AlignmentType.CENTER, spacing: { after: 40 } }),
  P([T("Cold-Storage Warehouse Management System", { size: 19, color: GREY })],
    { alignment: AlignmentType.CENTER, spacing: { after: 560 } }),

  // meta strip
  new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [3120, 3120, 3120],
    rows: [new TableRow({ children: [
      ["VERSION", "1.0"], ["DATE", "04 August 2026"], ["CLASSIFICATION", "Confidential"],
    ].map((c) => new TableCell({
      width: { size: 3120, type: WidthType.DXA },
      borders: { top: { style: BorderStyle.SINGLE, size: 12, color: NAVY },
                 bottom: noBorder, left: noBorder, right: noBorder },
      margins: { top: 110, bottom: 40, left: 40, right: 40 },
      children: [
        P([T(c[0], { size: 15, color: GREY, characterSpacing: 40, bold: true })],
          { alignment: AlignmentType.CENTER, spacing: { after: 30 } }),
        P([T(c[1], { size: 22, bold: true, color: NAVY })],
          { alignment: AlignmentType.CENTER }),
      ],
    })) })],
  }),
  spacer(120),
  P([T("Prepared by ", { size: 18, color: GREY }),
     T("Elyon Solutions International Inc.", { size: 18, bold: true, color: INK })],
    { alignment: AlignmentType.CENTER }),
];

// ============================ FRONT MATTER ============================
const docControl = [
  frontTitle("Document Control"),
  table([2600, 6760], [
    [{ t: "Field", bold: true }, { t: "Detail", bold: true }],
    [{ t: "Document Title" }, { t: "Pallet Merge Enhancement — To-Be Functional Blueprint" }],
    [{ t: "Document Type" }, { t: "Functional Scope / To-Be Blueprint (non-technical)" }],
    [{ t: "Prepared For" }, { t: "Vifel Ice Plant & Cold Storage, Inc." }],
    [{ t: "Prepared By" }, { t: "Elyon Solutions International Inc." }],
    [{ t: "Version" }, { t: "1.0" }],
    [{ t: "Status" }, { t: "For Review" }],
    [{ t: "Date" }, { t: "04 August 2026" }],
    [{ t: "Classification" }, { t: "Confidential — for the named client only" }],
  ]),
  spacer(180),
  P([T("Version History", { size: 24, bold: true, color: NAVY })], { spacing: { after: 120 } }),
  table([1300, 1900, 2600, 3560], [
    [{ t: "Version" }, { t: "Date" }, { t: "Author" }, { t: "Summary of Change" }],
    [{ t: "1.0" }, { t: "04 Aug 2026" }, { t: "Elyon Solutions" }, { t: "Initial scope release issued for Vifel review." }],
  ]),
];

// Manual contents (robust across Word/Google Docs/preview; no field-update prompt)
const tocMain = (num, title) =>
  new Paragraph({
    spacing: { after: 60, line: 276 },
    tabStops: [{ type: TabStopType.LEFT, position: 620 }],
    children: [T(num, { size: 22, bold: true, color: NAVY }), T("\t" + title, { size: 22, color: INK })],
  });
const tocSub = (num, title) =>
  new Paragraph({
    spacing: { after: 40, line: 264 },
    indent: { left: 620 },
    tabStops: [{ type: TabStopType.LEFT, position: 1200 }],
    children: [T(num, { size: 20, color: GREY }), T("\t" + title, { size: 20, color: GREY })],
  });
const toc = [
  P([new PageBreak()]),
  frontTitle("Contents"),
  tocMain("1", "Executive Summary"),
  tocMain("2", "Business Background & Rationale"),
  tocMain("3", "Scope of Enhancement"),
  tocSub("3.1", "Client Configuration"),
  tocSub("3.2", "Pallet Series Identifiers (PSI)"),
  tocSub("3.3", "Merge on Receiving"),
  tocSub("3.4", "Un-merge"),
  tocSub("3.5", "Lot No., Batch # & Prodcode Tracking"),
  tocSub("3.6", "Withdrawal & Pallet-Count Integrity"),
  tocSub("3.7", "Reports"),
  tocMain("4", "Out of Scope"),
  tocMain("5", "Assumptions & Dependencies"),
  tocMain("6", "Glossary"),
  tocMain("7", "Acceptance & Sign-off"),
];

// ============================ BODY ============================
const content = [
  P([new PageBreak()]),

  h1("1.  Executive Summary"),
  body("This blueprint defines the to-be scope of the Pallet Merge Enhancement, a client-specific extension to Vifel’s warehouse management system. It allows designated clients to consolidate several products or batches onto a single physical pallet — a practice their operations already follow — while keeping Vifel’s pallet count, occupancy, and billing figures accurate."),
  body("Today the system treats every received line as a separate pallet. For clients who legitimately place several items on one pallet, this over-states the number of physical pallets in storage and distorts occupancy-based billing. The enhancement introduces a controlled “merge” action, a matching “un-merge”, and the supporting configuration, identifiers, and reporting so that one physical pallet is always counted once — and only once."),
  spacer(60),
  callout("At a glance", [
    "Opt-in per client — every client is unaffected until merging is deliberately switched on.",
    "One physical pallet is counted once, no matter how many products sit on it.",
    "Fully reversible — any merge can be un-merged and the count self-corrects.",
    "Withdrawal, occupancy, and billing all read the true physical pallet count.",
    "No change whatsoever for clients who do not use merging.",
  ]),

  h1("2.  Business Background & Rationale"),
  body("As a cold-storage third-party logistics provider, Vifel measures storage and bills occupancy by the pallet. The standard system assumes one received line equals one new pallet. That assumption holds for most cargo, but not for clients who consolidate small lots — several products or production batches — onto a single pallet to use space efficiently."),
  body("Without a controlled way to record this, staff either over-count pallets (inflating occupancy and billing) or apply manual workarounds that are error-prone and leave the ledger inconsistent. The enhancement replaces those workarounds with a deliberate, auditable action that reflects what is physically on the floor."),
  bullet("Accurate occupancy and billing — charge for the pallets that physically exist."),
  bullet("A single, consistent method for staff, replacing ad-hoc manual corrections."),
  bullet("A clear, reversible audit trail of what was merged, when, and by whom."),

  h1("3.  Scope of Enhancement"),
  body("The enhancement is delivered as one installable capability covering seven grouped areas. Each area below states its intent and the key business requirements."),

  h2("3.1  Client Configuration"),
  body("Merging is governed entirely from the client record and is off by default; nothing changes for a client until it is enabled and configured."),
  bullet([T("A master switch, ", { size: 21, color: INK }), T("“Can Merge Pallets”", { size: 21, bold: true, color: INK }), T(", turns the capability on for one client at a time.", { size: 21, color: INK })]),
  bullet("Two mutually-exclusive modes: a single Fixed Merge Pallet (one dedicated pallet reused every receipt), or Multiple Pallet Support (several special pallet types)."),
  bullet("An optional “Include Regular Pallets” setting also allows merging onto ordinary stock pallets."),
  bullet("Optional per-client capture of Lot No. and Batch # (see 3.5)."),

  h2("3.2  Pallet Series Identifiers (PSI)"),
  body("Every physical pallet carries exactly one unique series number. Merge clients use dedicated series types so special pallets are recognisable and never collide with ordinary numbering."),
  bullet("One series equals one physical pallet — a system-wide integrity rule."),
  bullet("Dedicated special series types are created automatically for a Multiple-mode client."),
  bullet("Numbers are drawn and recycled automatically, never reused across the wrong pool."),

  h2("3.3  Merge on Receiving"),
  body("During receiving, a line can be merged onto a pallet that is already in stock, or onto a newly-created special pallet. Merging is available from both the Pallet Breakdown and the guided Magic Wizard, and behaves identically on each. The action is staged — nothing is committed until the user confirms."),
  spacer(40),
  table([6260, 3100], [
    [{ t: "Situation", bold: true }, { t: "Pallet count impact", bold: true, align: AlignmentType.CENTER }],
    [{ t: "Adding stock onto a pallet that already holds stock" }, { t: "+0  (no new pallet)", align: AlignmentType.CENTER, bold: true, color: NAVY }],
    [{ t: "First stock onto an empty dedicated (Fixed) pallet" }, { t: "+1", align: AlignmentType.CENTER, bold: true }],
    [{ t: "Joining another line on the same receipt" }, { t: "+1  (the shared pallet)", align: AlignmentType.CENTER, bold: true }],
    [{ t: "Starting a brand-new special pallet" }, { t: "+1", align: AlignmentType.CENTER, bold: true }],
  ]),
  spacer(90),
  bullet("The merged line adopts the target pallet’s series and location automatically."),
  bullet("A note is recorded on the receiving report whenever the pallet count is intentionally not incremented."),

  h2("3.4  Un-merge"),
  body("Any merged line can be separated again. The pallet count self-corrects and no captured data is lost."),
  bullet("Un-merge is offered wherever merge is — the Pallet Breakdown and the Magic Wizard."),
  bullet("The separated line reverts to its own pallet series and location."),
  bullet("The pallet count is restored as if the merge had not happened."),

  h2("3.5  Lot No., Batch # & Prodcode Tracking"),
  body("Optional client reference fields are captured at receiving and carried through stock, withdrawal, and reports, with a standardised product code frozen at validation."),
  bullet("Lot No. and Batch # entry are shown only for clients configured to use them."),
  bullet("A Prodcode is composed automatically (expiration date, batch, and building) and shown read-only on the withdrawal."),
  bullet("These references are available as optional columns in the stock and withdrawal views."),

  h2("3.6  Withdrawal & Pallet-Count Integrity"),
  body("A merge pallet may be withdrawn from in part, because it deliberately carries several products. The pallet is only counted as leaving storage when it is physically emptied."),
  bullet("Partial withdrawal is allowed — take one product and leave the rest — without forcing a return document."),
  bullet("The pallet counts as one leaving (−1) only on the withdrawal that empties it."),
  bullet("For multi-truck shipments, the pallet is counted against the truck that empties it, not the first truck to draw from it."),

  h2("3.7  Reports"),
  body("Every pallet-based figure reflects the merged reality — one physical pallet is counted once across all documents and reports."),
  bullet("Receiving and Withdrawal printed pallet counts, occupancy, and billing each count a merged pallet once."),
  bullet("Where enabled, the Lot No., Batch #, and Prodcode appear as tracking columns on the relevant documents."),

  h1("4.  Out of Scope"),
  body("The following are intentionally not part of this enhancement:"),
  bullet("Clients without merging enabled — no change to their receiving, withdrawal, or pallet counts."),
  bullet("Standard (non-merge) pallet handling — unchanged."),
  bullet("Blast-freeze operations — unaffected."),
  bullet("Pricing, costing, or contract terms — no change."),
  bullet("Migration of existing shared pallets — handled as a one-time deployment step, not an ongoing feature."),

  h1("5.  Assumptions & Dependencies"),
  bullet("Per-client configuration is maintained by authorised Vifel administrators."),
  bullet("Each physical pallet is represented by a single package and series."),
  bullet("The enhancement is installed once and remains installed."),
  bullet("Supporting database automations are updated during deployment."),
  bullet("Users receive brief orientation on the merge and un-merge actions."),

  h1("6.  Glossary"),
  table([2900, 6460], [
    [{ t: "Term", bold: true }, { t: "Meaning", bold: true }],
    [{ t: "PSI (Pallet Series Identifier)" }, { t: "The unique number identifying one physical pallet." }],
    [{ t: "Merge (+0)" }, { t: "Adding stock onto an existing pallet without increasing the pallet count." }],
    [{ t: "Same-receipt join" }, { t: "Two lines on one receipt sharing a pallet; counted once." }],
    [{ t: "Fixed Merge Pallet" }, { t: "A single dedicated pallet a client reuses on every receipt." }],
    [{ t: "Multiple Pallet Support" }, { t: "Mode allowing several dedicated special pallet types." }],
    [{ t: "Un-merge" }, { t: "Reversing a merge; the pallet count self-corrects." }],
    [{ t: "Pallet Breakdown" }, { t: "The receiving screen listing each pallet line." }],
    [{ t: "Magic Wizard" }, { t: "The guided receiving-encoding screen." }],
    [{ t: "RR / WR" }, { t: "Receiving Report / Withdrawal Report." }],
    [{ t: "Prodcode" }, { t: "Standardised product/batch code frozen at validation." }],
  ]),

  h1("7.  Acceptance & Sign-off"),
  body("This document represents the agreed scope of the Pallet Merge Enhancement. The following approvals are required before the build is accepted as complete."),
  spacer(40),
  table([2600, 3080, 2280, 1400], [
    [{ t: "Role", bold: true }, { t: "Name / Organisation", bold: true }, { t: "Signature", bold: true }, { t: "Date", bold: true }],
    [{ t: "Prepared by" }, { t: "Elyon Solutions International Inc." }, { t: " " }, { t: " " }],
    [{ t: "Reviewed by" }, { t: "Vifel — Operations" }, { t: " " }, { t: " " }],
    [{ t: "Approved by" }, { t: "Vifel — Management" }, { t: " " }, { t: " " }],
  ], { header: true }),
];

// ============================ HEADER / FOOTER ============================
const bodyHeader = new Header({ children: [
  new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: CW }],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 4 } },
    spacing: { after: 60 },
    children: [
      T("Pallet Merge Enhancement", { size: 16, color: NAVY, bold: true }),
      T("   |   To-Be Functional Blueprint", { size: 16, color: GREY }),
      T("\tElyon Solutions  ×  Vifel", { size: 16, color: GREY }),
    ],
  }),
] });

const bodyFooter = new Footer({ children: [
  new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: CW }],
    border: { top: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 4 } },
    spacing: { before: 40 },
    children: [
      T("Confidential  ·  © 2026 Elyon Solutions International Inc.", { size: 15, color: GREY }),
      T("\tPage ", { size: 15, color: GREY }),
      new TextRun({ children: [PageNumber.CURRENT], size: 15, color: GREY, font: "Arial" }),
    ],
  }),
] });

// ============================ DOCUMENT ============================
const doc = new Document({
  creator: "Elyon Solutions International Inc.",
  title: "Pallet Merge Enhancement — To-Be Functional Blueprint",
  description: "Client-Specific Requirement Enhancement scope for Vifel Ice Plant & Cold Storage, Inc.",
  styles: {
    default: { document: { run: { font: "Arial", size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: RULE, space: 6 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: NAVY_D, font: "Arial" },
        paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { run: { color: NAVY }, paragraph: { indent: { left: 500, hanging: 240 } } } },
    ] },
    { reference: "cbul", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "▪", alignment: AlignmentType.LEFT,
        style: { run: { color: NAVY }, paragraph: { indent: { left: 400, hanging: 220 } } } },
    ] },
  ] },
  sections: [
    { properties: { page: { size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1440, bottom: 1080, left: 1440 } } },
      children: cover },
    { properties: { page: { size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1260, left: 1440 },
        pageNumbers: { start: 1 } } },
      headers: { default: bodyHeader }, footers: { default: bodyFooter },
      children: [...docControl, ...toc, ...content] },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(DIR, "VIFEL_Pallet_Merge_To-Be_Blueprint.docx");
  fs.writeFileSync(out, buf);
  console.log("WROTE", out, buf.length, "bytes");
});
