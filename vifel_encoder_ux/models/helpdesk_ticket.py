# -*- coding: utf-8 -*-
"""Link a helpdesk ticket to the transfer it is about."""
from odoo import fields, models


class HelpdeskTicketPicking(models.Model):
    _inherit = 'helpdesk.ticket'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Transfer',
        index=True,
        # A ticket outlives the document it complains about. If a transfer is
        # deleted the ticket stays, with the link cleared: cascading would
        # destroy the record of a problem at exactly the moment someone is most
        # likely to want it.
        ondelete='set null',
        help="The receiving or withdrawal this ticket is about. Filled in "
             "automatically when the ticket is raised from a transfer, and "
             "selectable by hand when raised from the Helpdesk app.")
