# -*- coding: utf-8 -*-
"""RR / WR / BFRR / BFWR print buttons need a Printed By name (11-19).

The 8 Summary / Per Pallet print buttons on Transfers run the Studio print
server actions (studio_customization.print_*). Those actions now refuse to
run while the Transfer's "Printed By" field is empty, so nothing is printed
and "First Date/Time Printed" is not stamped.

"Printed By" is a Studio field added on live, so it is found by its label
when the usual technical name is not there. If no such field exists, the
buttons print as before.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PRINTED_BY_NAMES = ('x_studio_printed_by_name', 'x_studio_printed_by')
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
                    if not (picking[field] or '').strip():
                        raise UserError(_(
                            "Please indicate your name under Printed By before printing %s.",
                            picking.name))
                break
        return super().run()
