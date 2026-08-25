# One-time DB script: add the special-pallet sub-rows to the CONSOLIDATED
# SUMMARY report templates (Studio QWeb, DB-side) and place them correctly.
#
# Pairs with multiple_relocation/models/stock_picking.py :: preprocess_stock_move_data
# which emits per SKU: pallet_count (FULL, unchanged), *_main (normal-only,
# main-row display) and special_rows [{description, quantity, weight, packs,
# heads}] (one per special PSI type; Multiple-Special-Pallet clients only).
#
# What this rewrites in each summary "document" template:
#   1. main row shows the *_main figures (normal only); the un-suffixed fields
#      keep the FULL totals so the grand total + pallet count are unchanged;
#   2. one centered sub-row per special type is rendered AFTER the SKU main row;
#   3. the baked "***Nothing Follows***" is stripped from the last SKU's cell and
#      re-printed AFTER its special rows (so it never sits above them).
# Template-only (no code change); idempotent (skips a template already carrying
# packaging_qty_main). Run once per DB that prints these reports:
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/apply_summary_special_rows_templates.py
#
# The full rewritten templates are also saved at ai_context/RR_Final_summary_
# template.xml and WR_Consolidated_summary_template.xml (copy-paste into Studio).
BASE = ("studio_customization.studio_report_docume_"
        "603fbdfc-3014-4b3d-a461-45261cb3aeba")

NF_STRIP = "move['product_name'].replace(' &lt;br/&gt;***Nothing Follows***', '')"
SET_NF = ("<t t-set=\"_nf\" t-value=\""
          "'***Nothing Follows***' in (move['product_name'] or '')\"/>")


def _special_block(kind):
    # description cell has NO text-align override -> inherits the row's
    # text-center, so it lines up centered under ITEM DESCRIPTION like the SKU.
    if kind == 'RR':                                  # 6 cols
        sr = ("<t t-foreach=\"move['special_rows']\" t-as=\"sr\">"
              "<tr class=\"text-center\" style=\"height: 20px; font-size: 13px;\">"
              "<td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px; white-space: nowrap;\"><t t-esc=\"sr['description']\"/></td>"
              "<td style=\"padding: 1px;\"/><td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px; text-align: right;\"><t t-esc=\"'{:,.0f}'.format(sr['packs'])\" t-if=\"sr['packs']\"/></td>"
              "<td style=\"padding: 1px; text-align: right;\">"
              "<t t-if=\"doc.partner_id.x_studio_special_3_digit_decimal_pdf_report\"><t t-esc=\"'{:,.3f}'.format(sr['weight'])\"/></t>"
              "<t t-if=\"not doc.partner_id.x_studio_special_3_digit_decimal_pdf_report\"><t t-esc=\"'{:,.2f}'.format(sr['weight'])\"/></t>"
              "</td></tr></t>")
        nf = ("<t t-if=\"_nf\"><tr class=\"text-center\" style=\"height: 20px; font-size: 13px;\">"
              "<td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px; white-space: nowrap;\">***NOTHING FOLLOWS***</td>"
              "<td style=\"padding: 1px;\"/><td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px;\"/><td style=\"padding: 1px;\"/></tr></t>")
    else:                                              # WR: 5 cols
        sr = ("<t t-foreach=\"move['special_rows']\" t-as=\"sr\">"
              "<tr class=\"text-center\" style=\"height: 25px; font-size: 13px; border: 1px solid white;\">"
              "<td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px; white-space: nowrap;\"><t t-esc=\"sr['description']\"/></td>"
              "<td style=\"padding: 1px; text-align: right;\"><t t-esc=\"'{:,.0f}'.format(sr['packs'])\" t-if=\"sr['packs']\"/></td>"
              "<td style=\"padding: 1px;\"><t t-esc=\"'{:,.0f}'.format(sr['heads'])\" t-if=\"sr['heads']\"/></td>"
              "<td style=\"padding: 1px; text-align: right;\">"
              "<t t-if=\"doc.partner_id.x_studio_special_3_digit_decimal_pdf_report\"><t t-esc=\"'{:,.3f}'.format(sr['weight'])\"/></t>"
              "<t t-if=\"not doc.partner_id.x_studio_special_3_digit_decimal_pdf_report\"><t t-esc=\"'{:,.2f}'.format(sr['weight'])\"/></t>"
              "</td></tr></t>")
        nf = ("<t t-if=\"_nf\"><tr class=\"text-center\" style=\"height: 25px; font-size: 13px; border: 1px solid white;\">"
              "<td style=\"padding: 1px;\"/>"
              "<td style=\"padding: 1px; white-space: nowrap;\">***NOTHING FOLLOWS***</td>"
              "<td style=\"padding: 1px;\"/><td style=\"padding: 1px;\"/><td style=\"padding: 1px;\"/></tr></t>")
    return sr + nf


TARGETS = [
    ("_document_copy_2", "RR Final",        "RR"),
    ("_document_copy_3", "WR Consolidated", "WR"),
    # ("_document_copy_3_copy_2", "WR-MAT", "WR"),   # if in use
]


def _apply(view, kind):
    xml = view.arch
    if "packaging_qty_main" in xml:
        return False                       # already applied
    xml = xml.replace("format(move['packaging_qty'])", "format(move['packaging_qty_main'])")
    xml = xml.replace("format(move['weight_actual'])", "format(move['weight_actual_main'])")
    # mark the last SKU (via the baked Nothing-Follows token) at loop scope
    xml = xml.replace("<t t-foreach=\"page_info['moves']\" t-as=\"move\">",
                      "<t t-foreach=\"page_info['moves']\" t-as=\"move\">" + SET_NF, 1)
    # strip the baked Nothing-Follows from the main row so it can be re-printed below
    xml = xml.replace("<t t-raw=\"move['product_name']\"/>",
                      "<t t-raw=\"" + NF_STRIP + "\"/>", 1)
    # inject special sub-rows + the moved Nothing-Follows after the SKU main <tr>
    i = xml.index("t-foreach=\"page_info['moves']\"")
    tr_end = xml.index("</tr>", i) + len("</tr>")
    xml = xml[:tr_end] + _special_block(kind) + xml[tr_end:]
    view.arch = xml
    return True


applied = []
for suffix, label, kind in TARGETS:
    v = env['ir.ui.view'].search([('key', '=', BASE + suffix)], limit=1)
    if not v:
        print('  %-16s template NOT FOUND (key %s) - skipped' % (label, suffix))
        continue
    if _apply(v, kind):
        applied.append(label)
        print('  %-16s applied (view id %s)' % (label, v.id))
    else:
        print('  %-16s already has the special rows - skipped' % label)

if applied:
    env.cr.commit()
    print('COMMITTED template edits: %s' % ', '.join(applied))
else:
    print('Nothing to apply (all targets already edited or missing).')
