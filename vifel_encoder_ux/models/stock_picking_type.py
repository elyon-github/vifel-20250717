# -*- coding: utf-8 -*-
"""Inventory Overview behaviour: the state picker, and a blast-freeze repair.

Both are user-interface concerns, so they live in this module rather than in
multiple_relocation. Uninstalling takes them away and leaves the operational
engine as it was.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# An operation type whose NAME says blast freeze but whose FLAG says otherwise.
# Used only by the repair below, never as a substitute for the flag: every other
# piece of code in the system keys off is_blast_freeze_operation, and it should
# stay that way. This just makes the flag agree with reality.
BF_NAME_HINT = 'blast freeze'


class StockPickingTypeOverview(models.Model):
    _inherit = 'stock.picking.type'

    # ------------------------------------------------------------------
    # Overview card -> state picker
    # ------------------------------------------------------------------
    def _vifel_state_picker_action(self):
        """The state picker dialog for this operation type.

        Wide enough (large) that all four states sit on ONE row. At medium the
        fourth card wrapped onto a line of its own, which read as a separate
        thing rather than the last step of the same pipeline.
        """
        self.ensure_one()
        wizard = self.env['vifel_encoder_ux.picking.type.state.wizard'].create({
            'picking_type_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': wizard.title,
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': dict(self.env.context, dialog_size='large'),
        }

    def get_stock_picking_action_picking_type(self):
        """Card TITLE click: ask which state, instead of opening everything.

        Clicking an operation type used to open every transfer of that type at
        once. The states are what an encoder actually chooses between, so this
        asks first and then opens exactly that slice.

        Gated on vifel_state_picker, a context key set ONLY by the Inventory
        Overview action. Without it this method is Odoo's method unchanged, so
        anything else in the system that calls it - now or later - behaves
        exactly as it always did.
        """
        if not self.env.context.get('vifel_state_picker'):
            return super().get_stock_picking_action_picking_type()
        return self._vifel_state_picker_action()

    def get_action_picking_tree_ready(self):
        """Card BUTTON click ('N To Process'): the same picker as the title.

        The title and the button are one target as far as a user is concerned:
        both mean "open this operation type", so both now land in the same
        place. Ready is still one click away, on the READY card, and the count
        on the button still tells the truth about how many there are.

        The quieter links beside it - Waiting, Late, Back Orders - are left
        alone. Each already names one specific slice, so routing them through a
        chooser would only get in the way.

        Same context gate as above, so the method is untouched everywhere else.
        """
        if not self.env.context.get('vifel_state_picker'):
            return super().get_action_picking_tree_ready()
        return self._vifel_state_picker_action()

    # ------------------------------------------------------------------
    # Data repair
    # ------------------------------------------------------------------
    @api.model
    def vifel_repair_blast_freeze_flags(self):
        """Flag operation types that are blast freeze in name but not in data.

        Tagoloan's "Blast Freeze - IN" and "Blast Freeze - OUT" carried
        is_blast_freeze_operation = False while Meycauayan's carried True.

        That is not only cosmetic. The same flag drives operation_type_checker
        and vifel_type_of_operation (multiple_relocation/models/stock_picking.py),
        so a blast-freeze transfer raised at Tagoloan would have been classified
        RR instead of BFRR, and most of the module branches on that value. It had
        not caused harm only because that warehouse has no transfers yet.

        Matched by name rather than by id so it is portable across databases, and
        idempotent so re-running on every module update is a no-op.
        """
        candidates = self.with_context(active_test=False).search([
            ('is_blast_freeze_operation', '=', False),
        ])
        wrong = candidates.filtered(
            lambda t: BF_NAME_HINT in (t.name or '').lower())
        if not wrong:
            return True
        _logger.info(
            "VIFEL: flagging %d operation type(s) as blast freeze: %s",
            len(wrong),
            ', '.join('%s (%s)' % (t.name, t.warehouse_id.name or 'no warehouse')
                      for t in wrong))
        wrong.write({'is_blast_freeze_operation': True})
        return True
