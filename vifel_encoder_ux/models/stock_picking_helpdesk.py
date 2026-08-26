# -*- coding: utf-8 -*-
"""Raise and reach helpdesk tickets from the transfer they concern.

A problem on the floor is discovered while someone is looking at the document,
so the ticket is raised there rather than by switching apps and re-describing
which transfer went wrong. The link works from both ends: raised here it fills
itself in, and raised in the Helpdesk app the transfer can be picked by hand.
"""
from odoo import _, fields, models

# Tickets raised from a transfer are IT Support work, not customer care.
#
# Resolved by NAME rather than by id. Team ids differ between databases (here
# Customer Care is 1 and IT Support is 2, which is nothing more than creation
# order), and a hard-coded id would silently file tickets under whatever team
# happened to take that number elsewhere. If no team of this name exists the
# default is simply left off and Odoo's own default applies, so a database
# without it still works.
HELPDESK_TEAM_NAME = 'IT Support'


class StockPickingHelpdesk(models.Model):
    _inherit = 'stock.picking'

    helpdesk_ticket_ids = fields.One2many(
        'helpdesk.ticket', 'picking_id', string='Tickets')
    helpdesk_ticket_count = fields.Integer(
        string='Ticket Count', compute='_compute_helpdesk_ticket_count')

    # ------------------------------------------------------------------
    def _compute_helpdesk_ticket_count(self):
        """One grouped query for the whole recordset, not one per record.

        The same rule the client kanban counts follow: anything done per record
        in a compute is multiplied by however many rows are on screen, and this
        field is read from transfer lists as well as the form.
        """
        counts = {}
        if self.ids:
            counts = {
                group['picking_id'][0]: group['__count']
                for group in self.env['helpdesk.ticket'].read_group(
                    [('picking_id', 'in', self.ids)],
                    ['picking_id'], ['picking_id'], lazy=False)
                if group.get('picking_id')
            }
        for picking in self:
            picking.helpdesk_ticket_count = counts.get(picking.id, 0)

    # ------------------------------------------------------------------
    def _vifel_helpdesk_team(self):
        """The team tickets from a transfer belong to, or an empty recordset."""
        return self.env['helpdesk.team'].search(
            [('name', '=', HELPDESK_TEAM_NAME)], limit=1)

    def _vifel_ticket_context(self):
        """Defaults carried into a ticket raised from this transfer.

        The subject is pre-filled with the document number because that is the
        thing anyone reading the ticket later needs first, and typing it again
        is how it ends up wrong.
        """
        self.ensure_one()
        context = {
            'default_picking_id': self.id,
            'default_name': _('Issue on %s') % (self.name or ''),
        }
        if self.partner_id:
            context['default_partner_id'] = self.partner_id.id
        team = self._vifel_helpdesk_team()
        if team:
            context['default_team_id'] = team.id
        return context

    # ------------------------------------------------------------------
    def action_vifel_create_ticket(self):
        """Raise a ticket about this transfer, without leaving it."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Ticket'),
            'res_model': 'helpdesk.ticket',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': dict(self.env.context, dialog_size='large',
                            **self._vifel_ticket_context()),
        }

    def action_vifel_open_tickets(self):
        """The tickets already raised against this transfer.

        Creating from this list keeps the same defaults, so a ticket started
        from here is linked just as one started from the button is.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tickets - %s') % (self.name or ''),
            'res_model': 'helpdesk.ticket',
            'view_mode': 'tree,form',
            'domain': [('picking_id', '=', self.id)],
            'target': 'current',
            'context': self._vifel_ticket_context(),
        }
