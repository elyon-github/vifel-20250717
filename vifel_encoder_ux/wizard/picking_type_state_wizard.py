# -*- coding: utf-8 -*-
"""State picker for an Inventory Overview operation type.

Clicking RECEIVING used to open every receiving transfer ever made. What an
encoder actually wants is one slice of that: the drafts to finish, the ready
ones to work, or the done ones to look something up. This asks which, showing
how much sits in each, then opens exactly that.

Same shape and the same card design as the client transfer-type picker, which
is the screen this was modelled on.
"""
from odoo import api, fields, models


class PickingTypeStateWizard(models.TransientModel):
    _name = 'vifel_encoder_ux.picking.type.state.wizard'
    _description = 'Operation Type State Picker'

    # Odoo calls 'confirmed' Waiting, and 'waiting' Waiting Another Operation.
    # The Overview card lumps both under its Waiting figure
    # (count_picking_waiting in stock/models/stock_picking.py), so this picker
    # does too. Splitting them here would make the dialog disagree with the card
    # that opened it, which is worse than the slight imprecision.
    WAITING_STATES = ('confirmed', 'waiting')

    picking_type_id = fields.Many2one(
        'stock.picking.type', string='Operation Type',
        required=True, readonly=True, ondelete='cascade')

    title = fields.Char(compute='_compute_counts')
    draft_count = fields.Integer(compute='_compute_counts')
    waiting_count = fields.Integer(compute='_compute_counts')
    ready_count = fields.Integer(compute='_compute_counts')
    done_count = fields.Integer(compute='_compute_counts')

    # ------------------------------------------------------------------
    def _domain(self, states=None):
        """Every transfer of this operation type, optionally in given states."""
        self.ensure_one()
        domain = [('picking_type_id', '=', self.picking_type_id.id)]
        if states:
            domain.append(('state', 'in', list(states)))
        return domain

    @api.depends('picking_type_id')
    def _compute_counts(self):
        """One search_count per state.

        There is no count_picking_done field on stock.picking.type, and the
        count_picking_* fields that do exist are non-stored computes, so they
        cannot be read in bulk anyway. Counting directly keeps all four figures
        built the same way, which matters more here than shaving a query: this
        dialog opens for one operation type at a time.
        """
        Picking = self.env['stock.picking']
        for wiz in self:
            wiz.draft_count = Picking.search_count(wiz._domain(('draft',)))
            wiz.waiting_count = Picking.search_count(
                wiz._domain(wiz.WAITING_STATES))
            wiz.ready_count = Picking.search_count(wiz._domain(('assigned',)))
            wiz.done_count = Picking.search_count(wiz._domain(('done',)))
            warehouse = wiz.picking_type_id.warehouse_id.name
            wiz.title = ('%s: %s' % (warehouse, wiz.picking_type_id.name)
                         if warehouse else wiz.picking_type_id.name)

    # ------------------------------------------------------------------
    def _open(self, label, states):
        """Open this operation type's transfers, narrowed to one state."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '%s - %s' % (self.title, label),
            'res_model': 'stock.picking',
            'view_mode': 'tree,kanban,form',
            'domain': self._domain(states),
            'target': 'current',
            'context': {
                # A document created from this list belongs to the operation
                # type the encoder was standing in.
                'default_picking_type_id': self.picking_type_id.id,
            },
        }

    def action_open_draft(self):
        return self._open('Draft', ('draft',))

    def action_open_waiting(self):
        return self._open('Waiting', self.WAITING_STATES)

    def action_open_ready(self):
        return self._open('Ready', ('assigned',))

    def action_open_done(self):
        return self._open('Done', ('done',))

    def action_new(self):
        """Start a transfer of this operation type.

        Encoding starts from paper: by the time someone reaches this dialog they
        already know the operation, so offer the document directly rather than
        making them go through a list first. Same reasoning as the New button on
        the client transfer-type picker.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.title,
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'default_picking_type_id': self.picking_type_id.id},
        }
