# -*- coding: utf-8 -*-
"""Transfer-type picker for the Contact smart buttons.

Clicking "Normal Transfers" / "Blast Freeze Transfers" on a client asks
which side of the operation to open — Receiving or Withdrawal — showing
the count of each so the choice is informed, then opens that list scoped
to the client.
"""
from odoo import api, fields, models


class ClientTransferTypeWizard(models.TransientModel):
    _name = 'multiple_relocation.client.transfer.type.wizard'
    _description = 'Select Transfer Type'

    partner_id = fields.Many2one('res.partner', string='Client', required=True,
                                 readonly=True)
    is_blast_freeze = fields.Boolean(string='Blast Freeze', readonly=True)
    incoming_count = fields.Integer(compute='_compute_counts',
                                    string='Receiving Transfers')
    outgoing_count = fields.Integer(compute='_compute_counts',
                                    string='Withdrawal Transfers')
    incoming_label = fields.Char(compute='_compute_counts')
    outgoing_label = fields.Char(compute='_compute_counts')
    incoming_icon = fields.Char(compute='_compute_counts')
    outgoing_icon = fields.Char(compute='_compute_counts')

    # ------------------------------------------------------------------
    def _domain(self, code):
        self.ensure_one()
        return self.partner_id._vifel_picking_domain(
            blast_freeze=self.is_blast_freeze) + [
            ('picking_type_id.code', '=', code)]

    @api.depends('partner_id', 'is_blast_freeze')
    def _compute_counts(self):
        Picking = self.env['stock.picking']
        for wiz in self:
            wiz.incoming_count = Picking.search_count(wiz._domain('incoming'))
            wiz.outgoing_count = Picking.search_count(wiz._domain('outgoing'))
            if wiz.is_blast_freeze:
                wiz.incoming_label = 'Blast Freeze - IN'
                wiz.outgoing_label = 'Blast Freeze - OUT'
            else:
                wiz.incoming_label = 'Receiving'
                wiz.outgoing_label = 'Withdrawal'
            wiz.incoming_icon = 'fa-sign-in'
            wiz.outgoing_icon = 'fa-sign-out'

    # ------------------------------------------------------------------
    def _open(self, code, label):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '%s — %s' % (label, self.partner_id.name),
            'res_model': 'stock.picking',
            'view_mode': 'tree,kanban,form,calendar,activity',
            'domain': self._domain(code),
            'target': 'current',
            'context': {
                'search_default_draft': 1,
                'search_default_waiting': 1,
                'search_default_available': 1,
                'vifel_client_id': self.partner_id.id,
            },
        }

    def action_open_incoming(self):
        return self._open('incoming', self.incoming_label)

    def action_open_outgoing(self):
        return self._open('outgoing', self.outgoing_label)
