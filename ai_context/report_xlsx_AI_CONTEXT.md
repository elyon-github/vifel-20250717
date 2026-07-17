# `report_xlsx` — AI Context Document

> **Module path**: `addons/custom_addons/vifel-20250717/report_xlsx/`
> **Origin**: OCA (Odoo Community Association) — `https://github.com/OCA/reporting-engine`
> **Authors**: ACSONE SA/NV, Creu Blanca, OCA
> **License**: AGPL-3.0
> **Odoo version**: 17 Enterprise (`version 17.0.0.0.1`)
> **Status**: Mature
> **Depends on**: `base`, `web`
> **External Python deps**: `xlsxwriter`, `xlrd`
> **Last updated**: 2026-05-16

---

## 1. Purpose (1-paragraph elevator pitch)

`report_xlsx` is the **OCA-provided base module** that adds a new `report_type='xlsx'` value to `ir.actions.report`, enabling downloadable Excel (`.xlsx`) outputs alongside Odoo's built-in PDF and HTML reports. It is **infrastructure only** — it does not ship any business reports. Every other module in `vifel-20250717/` that produces an XLSX (e.g. `pallet_kilos_record_model`, `stock_quant_history`, `multiple_relocation`) declares an `ir.actions.report` with `report_type="xlsx"` and inherits the `report.report_xlsx.abstract` abstract model defined here.

Treat this module as a **stable third-party library**: keep it pristine unless you're upstreaming a fix to OCA.

---

## 2. Where Things Live

```
report_xlsx/
├── __manifest__.py
├── README.rst                              # OCA-style README
├── readme/                                 # Multi-section README fragments
├── i18n/                                   # Translations
├── models/
│   └── ir_report.py                        # ir.actions.report extension (xlsx selection + _render_xlsx)
├── controllers/
│   └── main.py                             # /report/xlsx HTTP routes
├── report/
│   ├── report_abstract_xlsx.py             # report.report_xlsx.abstract (the base class)
│   └── report_partner_xlsx.py              # report.report_xlsx.partner_xlsx (demo)
├── demo/report.xml                         # Demo ir.actions.report (partner_xlsx)
├── static/src/js/report/
│   └── action_manager_report.esm.js        # Hooks the action manager so xlsx downloads work in the UI
└── tests/
```

There is **no Python `data` payload** in the manifest — only `demo`. The asset bundle `web.assets_backend` loads the action-manager JS shim.

---

## 3. How It Works

### Adding the `xlsx` report type
`models/ir_report.py` extends `ir.actions.report.report_type` with `('xlsx', 'XLSX')` and overrides:

- `_render_xlsx(report_ref, docids, data)` — looks up the report model via `report.<report_name>`, calls its `create_xlsx_report(docids, data)`, and (optionally) persists the bytes as an `ir.attachment` if `report.attachment` is set.
- `_get_report_from_name(report_name)` — falls back to a search by `report_type='xlsx' AND report_name=...` so the standard report dispatcher resolves XLSX reports the same way it resolves QWeb ones.
- `save_xlsx_report_attachment(docids, report_contents)` — mirrors `_render_qweb_pdf`'s attachment save path; only supports `len(docids) == 1`.

### The abstract base class
`report/report_abstract_xlsx.py` defines:

```python
class ReportXlsxAbstract(models.AbstractModel):
    _name = "report.report_xlsx.abstract"

    def _get_objs_for_report(self, docids, data): ...   # resolve recordset from docids/data/context
    def _report_xlsx_currency_format(self, currency): ...
    def create_xlsx_report(self, docids, data):
        objs = self._get_objs_for_report(docids, data)
        file_data = BytesIO()
        workbook = xlsxwriter.Workbook(file_data, self.get_workbook_options())
        self.generate_xlsx_report(workbook, data, objs)
        workbook.close()
        file_data.seek(0)
        return file_data.read(), "xlsx"

    def get_workbook_options(self): return {}
    def generate_xlsx_report(self, workbook, data, objs):
        raise NotImplementedError()
```

Concrete reports inherit this and implement `generate_xlsx_report`. Example: `report/report_partner_xlsx.py` writes each partner's `name` to row N.

### The `PatchedXlsxWorkbook` (important quirk)
The module monkey-patches `xlsxwriter.Workbook` with a `PatchedXlsxWorkbook` subclass that **auto-deduplicates sheet names** colliding under the 31-character Excel limit by appending `~01`, `~02`, … up to `~99`. This is global to the Python process once `report_xlsx` is loaded. Multi-sheet reports that would otherwise raise `DuplicateWorksheetName` silently get suffixed names instead.

### The HTTP layer
`controllers/main.py` extends the standard `ReportController`:

- `/report/<reportname>?converter=xlsx` (and variants) call `_render_xlsx` and stream back `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- `/report/download` (used by the web client's "Save" dispatcher) recognizes `xlsx` URLs, decodes querystring args (including a `context` payload), and forwards to `report_routes`.

### The frontend shim
`static/src/js/report/action_manager_report.esm.js` patches the Odoo web action manager so that when a report action's `report_type === 'xlsx'`, the client downloads the file instead of trying to render it as PDF/HTML. This is the asset bundled into `web.assets_backend`.

---

## 4. How Other Modules Use This

A consumer typically does **two things**:

1. Declare an `ir.actions.report` in XML:
   ```xml
   <record id="my_xlsx_action" model="ir.actions.report">
       <field name="name">My Report</field>
       <field name="model">my.model</field>
       <field name="report_type">xlsx</field>
       <field name="report_name">my_module.my_xlsx_template_id</field>
       <field name="report_file">my_module.my_xlsx_template_id</field>
   </record>
   ```
2. Define an abstract model named `report.<report_name>`:
   ```python
   class MyXlsxReport(models.AbstractModel):
       _name = "report.my_module.my_xlsx_template_id"
       _inherit = "report.report_xlsx.abstract"

       def generate_xlsx_report(self, workbook, data, objs):
           sheet = workbook.add_worksheet("Sheet1")
           for i, obj in enumerate(objs):
               sheet.write(i, 0, obj.display_name)
   ```

Sister modules in this repo follow this pattern: `pallet_kilos_record_model` (6 report variants), `stock_quant_history` (occupancy + summary), `multiple_relocation` (client summary, count sheet).

---

## 5. Demo Report

`demo/report.xml` registers `report.report_xlsx.partner_xlsx` against `res.partner`. Installing with demo data on gives you a clickable XLSX entry in the partner form's Print menu — useful as a smoke test.

---

## 6. Common Pitfalls

1. **`xlsxwriter` is an external Python dependency.** If it isn't installed in the venv, `report_xlsx` logs `Can not import xlsxwriter` at load time but does **not** raise. The first time a user prints an XLSX you'll get a 500. Always `pip install xlsxwriter xlrd` when bootstrapping a new env.
2. **The `PatchedXlsxWorkbook` is process-wide.** Any code in the same Python process that constructs `xlsxwriter.Workbook(...)` will use the patched class. Usually a benefit, but worth knowing when debugging unexpected sheet-name suffixes (`~01`, `~02`).
3. **`report_name` is also the model name.** The standard wiring expects an `AbstractModel` named `report.<report_name>`. Mismatches surface as "no module named `report.foo`" KeyErrors at print time.
4. **Attachments require `len(docids) == 1`.** Unlike PDFs (which can stream multiple), XLSX reports save an attachment only when called with a single record.
5. **AGPL-3.0 license.** This is an OCA module — keep modifications upstreamable. Avoid in-place patches that aren't portable; if you must customize, do it in a downstream module that overrides the relevant abstract method.
6. **Editing this module breaks every downstream report.** Treat it as a frozen base. Bugs and improvements should ideally be PR'd to https://github.com/OCA/reporting-engine.

---

## 7. Where to read next

- `pallet_kilos_record_model_AI_CONTEXT.md` — heaviest consumer (6 XLSX report variants)
- `stock_quant_history_AI_CONTEXT.md` — occupancy + inventory summary XLSX
- `multiple_relocation_AI_CONTEXT.md` — client summary + count sheet XLSX

---

## 8. AI Agent Maintenance Instructions

> **To the next AI agent reading this file:**
>
> This module is an **OCA library** — most of the time you should not touch it. Update this document only when:
>
> - **You upgrade the module** to a newer OCA version → bump the `version` in the header, re-verify sections 3 and 4 are still accurate, and note breaking changes.
> - **A downstream module starts depending on a previously-undocumented helper** (e.g. `_report_xlsx_currency_format`) → add a line in section 3.
> - **The XLSX wiring breaks** (e.g. an Odoo 17.x release changes `ir.actions.report` internals) → document the fix and any monkey-patches added.
> - **The set of consuming modules grows or shrinks** → update sections 4 and 7.
> - **The external dependency list changes** (e.g. xlsxwriter pinned to a specific version) → update the header.
>
> Do not bloat this doc with details about consumer reports — those belong in the consumers' own AI_CONTEXT.md files. Keep the focus on the library contract (`generate_xlsx_report`, `create_xlsx_report`, `report_type='xlsx'` wiring, HTTP route). Update the **Last updated** date at the top each time. Mark uncertain sections `⚠️ NEEDS VERIFICATION` rather than removing them.
