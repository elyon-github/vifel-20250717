"""Print Count and print history on the RR / WR / BFRR / BFWR reports.

Every time one of the 8 Summary / Per Pallet reports is rendered as a PDF
(print button, Print menu, download), the Transfer's Print Count goes up by
one before the PDF is built, so the page shows the count including this
print (migration 19.0.0.4.35 puts it next to Last Print Date). Each print is
also written to vifel.print.log (who, Printed By, which report, when), shown
by the "Print Count" smart button on the Transfer (19.0.0.4.36).
The counter is written with SQL so printing a validated Transfer does not
trigger write() overrides, tracking or the post-validation adjustment log.
"""
from odoo import _, fields, models

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


class VifelPrintLog(models.Model):
    _name = 'vifel.print.log'
    _description = 'Transfer Print History'
    _order = 'print_date desc, id desc'
    _rec_name = 'picking_id'

    picking_id = fields.Many2one(
        'stock.picking', string='Transfer', required=True, index=True,
        ondelete='cascade', readonly=True)
    print_no = fields.Integer(string='Print #', readonly=True)
    report_name = fields.Char(string='Report', readonly=True)
    printed_by = fields.Char(string='Printed By', readonly=True,
                             help='The Printed By name on the Transfer at the time of printing.')
    user_id = fields.Many2one('res.users', string='Printed by User', readonly=True)
    print_date = fields.Datetime(string='Print Date', readonly=True,
                                 default=fields.Datetime.now)


class StockPickingPrintCount(models.Model):
    _inherit = 'stock.picking'

    vifel_print_count = fields.Integer(
        string='Print Count', default=0, copy=False, readonly=True,
        help='How many times the RR / WR / BFRR / BFWR report of this '
             'Transfer was printed as PDF.')

    def action_view_print_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Print History - %s', self.name),
            'res_model': 'vifel.print.log',
            'view_mode': 'list',
            'domain': [('picking_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }


class IrActionsReportPrintCount(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        report = self._get_report(report_ref)
        if (res_ids and report.model == 'stock.picking'
                and report.report_name in COUNTED_REPORTS):
            ids = tuple(res_ids) if isinstance(res_ids, (list, tuple)) else (res_ids,)
            self.env.cr.execute(
                "UPDATE stock_picking SET vifel_print_count = "
                "COALESCE(vifel_print_count, 0) + 1 WHERE id IN %s "
                "RETURNING id, vifel_print_count", (ids,))
            counts = dict(self.env.cr.fetchall())
            pickings = self.env['stock.picking'].sudo().browse(list(counts))
            pickings.invalidate_recordset(['vifel_print_count'])
            pb_field = self.env['ir.actions.server']._vifel_printed_by_field()
            self.env['vifel.print.log'].sudo().create([{
                'picking_id': picking.id,
                'print_no': counts[picking.id],
                'report_name': report.name,
                'printed_by': (picking[pb_field] or '') if pb_field else '',
                'user_id': self.env.uid,
            } for picking in pickings])
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
