"""Print Count on the RR / WR / BFRR / BFWR reports.

Every time one of the 8 Summary / Per Pallet reports is rendered as a PDF
(print button, Print menu, download), the Transfer's Print Count goes up by
one before the PDF is built, so the page shows the count including this
print. The reports print it next to Last Print Date (migration 19.0.0.4.35).
The counter is written with SQL so printing a validated Transfer does not
trigger write() overrides, tracking or the post-validation adjustment log.
"""
from odoo import fields, models

P = 'studio_customization.studio_report_docume_603fbdfc-3014-4b3d-a461-45261cb3aeba'
COUNTED_REPORTS = {
    P,                              # BFWR (Final)
    P + '_copy_1',                  # BFRR (Final)
    P + '_copy_2',                  # Receiving Report (Final)
    P + '_copy_3',                  # Withdrawal Report - Consolidated (Final)
    P + '_copy_2_copy_1',           # Receiving Report (Final) (Per Pallet)
    P + '_copy_3_copy_1',           # Withdrawal Report - Per Pallet (Final)
    P + '_copy_2_copy_1_copy_1',    # BFRR (Final) (Per Pallet)
    P + '_copy_3_copy_1_copy_1',    # BFWR - Per Pallet (Final)
}


class StockPickingPrintCount(models.Model):
    _inherit = 'stock.picking'

    vifel_print_count = fields.Integer(
        string='Print Count', default=0, copy=False, readonly=True,
        help='How many times the RR / WR / BFRR / BFWR report of this '
             'Transfer was printed as PDF.')


class IrActionsReportPrintCount(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        report = self._get_report(report_ref)
        if (res_ids and report.model == 'stock.picking'
                and report.report_name in COUNTED_REPORTS):
            ids = tuple(res_ids) if isinstance(res_ids, (list, tuple)) else (res_ids,)
            self.env.cr.execute(
                "UPDATE stock_picking SET vifel_print_count = "
                "COALESCE(vifel_print_count, 0) + 1 WHERE id IN %s", (ids,))
            self.env['stock.picking'].browse(ids).invalidate_recordset(['vifel_print_count'])
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
