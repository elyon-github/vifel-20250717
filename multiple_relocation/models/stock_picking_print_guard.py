# -*- coding: utf-8 -*-
"""RR / WR / BFRR / BFWR printing needs a Printed By name (11-18, 4.32).

The check sits on the 8 Studio print server actions themselves
(studio_customization.print_*), not only on the buttons: whatever calls them
(the module buttons below, a button Studio re-adds or garbles on a form
save, a contextual action), they refuse to run on a Transfer whose
"Printed By" is empty, so nothing prints and "First Date/Time Printed" is
not stamped. Same mechanism as 17 (multiple_relocation 0.4.16).

"Printed By" is x_studio_printed_by_name (migration 19.0.0.4.28), or any
manual char/text field labelled "Printed By" (e.g. the one added in Studio on
live 17). With no such field the actions print as before.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PRINTED_BY = 'x_studio_printed_by_name'
PRINTED_BY_NAMES = (PRINTED_BY, 'x_studio_printed_by')
PRINTED_BY_LABEL = 'Printed By'

PRINT_ACTIONS = (
    'print_receiving_r_summary',
    'print_receiving_r_per_pallet',
    'print_withdrawal_r_summary',
    'print_withdrawal_r_per_pallet',
    'print_bf_receiving_r_summary',
    'print_bf_receiving_r_per_pallet',
    'print_bf_withdrawal_r_summary',
    'print_bf_withdrawal_r_per_pallet',
)


class IrActionsServerPrintedBy(models.Model):
    _inherit = 'ir.actions.server'

    @api.model
    def _vifel_printed_by_field(self):
        Picking = self.env['stock.picking']
        for name in PRINTED_BY_NAMES:
            if name in Picking._fields:
                return name
        field = self.env['ir.model.fields'].sudo().with_context(lang='en_US').search([
            ('model', '=', 'stock.picking'),
            ('state', '=', 'manual'),
            ('ttype', 'in', ('char', 'text')),
            ('field_description', '=ilike', PRINTED_BY_LABEL),
        ], limit=1)
        if field and field.name in Picking._fields:
            return field.name
        return False

    def _vifel_is_print_action(self):
        self.ensure_one()
        xmlid = self.get_external_id().get(self.id) or ''
        module, _sep, name = xmlid.partition('.')
        return module == 'studio_customization' and name in PRINT_ACTIONS

    def run(self):
        ctx = self.env.context
        if ctx.get('active_model') == 'stock.picking':
            for action in self:
                if not action._vifel_is_print_action():
                    continue
                field = self._vifel_printed_by_field()
                if not field:
                    _logger.warning("Printed By field not found on stock.picking; %s prints unchecked",
                                    action.get_external_id().get(action.id))
                    break
                ids = ctx.get('active_ids') or ([ctx['active_id']] if ctx.get('active_id') else [])
                for picking in self.env['stock.picking'].browse(ids).exists():
                    if picking.vifel_printed_by_missing():
                        raise UserError(_(
                            "Please indicate your name under Printed By next to NCR-Remarks "
                            "before printing %s.", picking.name))
                break
        return super().run()


class StockPickingPrintGuard(models.Model):
    _inherit = 'stock.picking'

    def _vifel_print(self, action_name):
        # The Printed By check runs in ir.actions.server.run (above).
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
