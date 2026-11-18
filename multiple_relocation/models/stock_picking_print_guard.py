# -*- coding: utf-8 -*-
"""RR / WR / BFRR / BFWR print buttons need a Printed By name (11-18).

The 8 Summary / Per Pallet print buttons on Transfers used to call the
Studio print server actions directly. They now call these methods, which
refuse to print while the Transfer's "Printed By" field
(x_studio_printed_by_name, created by migration 19.0.0.4.28) is empty, and
otherwise run the same server action as before, so the report and the
"First Date/Time Printed" stamp are unchanged.
"""
from odoo import _, models
from odoo.exceptions import UserError

PRINTED_BY = 'x_studio_printed_by_name'


class StockPickingPrintGuard(models.Model):
    _inherit = 'stock.picking'

    def _vifel_print(self, action_name):
        if PRINTED_BY in self._fields:
            for record in self:
                if not (record[PRINTED_BY] or '').strip():
                    raise UserError(_(
                        "Please indicate your name under Printed By, next to "
                        "the NCR Remarks field, before printing."))
        action = self.env.ref('studio_customization.' + action_name)
        return action.with_context(
            active_id=self[:1].id,
            active_ids=self.ids,
            active_model='stock.picking',
        ).run()

    def action_vifel_print_rr_summary(self):
        return self._vifel_print('print_receiving_r_summary')

    def action_vifel_print_rr_per_pallet(self):
        return self._vifel_print('print_receiving_r_per_pallet')

    def action_vifel_print_wr_summary(self):
        return self._vifel_print('print_withdrawal_r_summary')

    def action_vifel_print_wr_per_pallet(self):
        return self._vifel_print('print_withdrawal_r_per_pallet')

    def action_vifel_print_bfrr_summary(self):
        return self._vifel_print('print_bf_receiving_r_summary')

    def action_vifel_print_bfrr_per_pallet(self):
        return self._vifel_print('print_bf_receiving_r_per_pallet')

    def action_vifel_print_bfwr_summary(self):
        return self._vifel_print('print_bf_withdrawal_r_summary')

    def action_vifel_print_bfwr_per_pallet(self):
        return self._vifel_print('print_bf_withdrawal_r_per_pallet')
