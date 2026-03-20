# -*- coding: utf-8 -*-

from odoo import models
import logging

_logger = logging.getLogger(__name__)


class FastEncodeRRAudit(models.TransientModel):
    _inherit = 'stock.move.line.fast_encode_rr'

    def action_confirm(self):
        """Inject audit context so all pool ops and writes inside are logged."""
        picking_id = self.transfer_id
        return super(
            FastEncodeRRAudit,
            self.with_context(
                audit_picking_id=picking_id,
                audit_source='wizard',
            ),
        ).action_confirm()
