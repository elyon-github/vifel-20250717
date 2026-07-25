# -*- coding: utf-8 -*-
"""Transfer-type picker for the Contact smart buttons.

Clicking "Normal Transfers" / "Blast Freeze Transfers" on a client asks
which side of the operation to open — Receiving or Withdrawal — showing
the count of each so the choice is informed, then opens that list scoped
to the client.
"""
from odoo import api, fields, models
from odoo.tools import html_escape


class ClientTransferTypeWizard(models.TransientModel):
    _name = 'multiple_relocation.client.transfer.type.wizard'
    _description = 'Select Transfer Type'

    # The list this picker opens is filtered to Draft / Waiting / Ready, so the
    # headline number counts exactly those states — a total including years of
    # validated documents would promise a list the user never gets. Mirrors the
    # stock.picking search filters draft / waiting / available verbatim.
    OPEN_STATES = ('draft', 'waiting', 'confirmed', 'assigned')

    partner_id = fields.Many2one('res.partner', string='Client', required=True,
                                 readonly=True)
    is_blast_freeze = fields.Boolean(string='Blast Freeze', readonly=True)
    incoming_count = fields.Integer(compute='_compute_counts',
                                    string='Receiving To Do')
    outgoing_count = fields.Integer(compute='_compute_counts',
                                    string='Withdrawal To Do')
    incoming_done_count = fields.Integer(compute='_compute_counts',
                                         string='Receiving Done')
    outgoing_done_count = fields.Integer(compute='_compute_counts',
                                         string='Withdrawal Done')
    incoming_done_label = fields.Char(compute='_compute_counts')
    outgoing_done_label = fields.Char(compute='_compute_counts')
    incoming_label = fields.Char(compute='_compute_counts')
    outgoing_label = fields.Char(compute='_compute_counts')
    incoming_icon = fields.Char(compute='_compute_counts')
    outgoing_icon = fields.Char(compute='_compute_counts')

    # ------------------------------------------------------------------
    def _domain(self, code):
        """Every transfer of this client for the direction — any state.

        Left unfiltered on purpose: it is also the domain the opened list
        uses, and the state filters there arrive as removable search defaults
        so the encoder can still reach the validated ones.
        """
        self.ensure_one()
        return self.partner_id._vifel_picking_domain(
            blast_freeze=self.is_blast_freeze) + [
            ('picking_type_id.code', '=', code)]

    @api.depends('partner_id', 'is_blast_freeze')
    def _compute_counts(self):
        Picking = self.env['stock.picking']
        for wiz in self:
            for code in ('incoming', 'outgoing'):
                base = wiz._domain(code)
                pending = Picking.search_count(
                    base + [('state', 'in', wiz.OPEN_STATES)])
                done = Picking.search_count(base + [('state', '=', 'done')])
                wiz['%s_count' % code] = pending
                wiz['%s_done_count' % code] = done
                wiz['%s_done_label' % code] = (
                    '%d done' % done if done else 'none done yet')
            if wiz.is_blast_freeze:
                wiz.incoming_label = 'Blast Freeze - IN'
                wiz.outgoing_label = 'Blast Freeze - OUT'
            else:
                wiz.incoming_label = 'Receiving'
                wiz.outgoing_label = 'Withdrawal'
            wiz.incoming_icon = 'fa-sign-in'
            wiz.outgoing_icon = 'fa-sign-out'

    # ------------------------------------------------------------------
    def _empty_help(self, label):
        """Plain-language empty state instead of Odoo's sample records."""
        self.ensure_one()
        return (
            '<p class="o_view_nocontent_smiling_face">Create a new %(label)s '
            'transaction</p><p>No %(label)s transaction of %(client)s is in '
            '<b>Draft</b>, <b>Waiting</b> or <b>Ready</b> right now.<br/>'
            'Remove the filter above to see the other %(label)s '
            'transactions of this client.</p>'
        ) % {'label': html_escape(label), 'client': html_escape(self.partner_id.name or '')}

    def _picking_type(self, code):
        """The operation type this list represents, when there is only one.

        Today each (direction x blast-freeze) pair maps to exactly one
        operation type, so a new transfer can be pre-filled with it. If a
        second warehouse ever adds a rival type the pair stops being
        unambiguous — leave the field empty then rather than guess wrong.
        """
        self.ensure_one()
        types = self.env['stock.picking.type'].search([
            ('code', '=', code),
            ('is_blast_freeze_operation',
             '=' if self.is_blast_freeze else '!=', True),
        ])
        return types if len(types) == 1 else self.env['stock.picking.type']

    def _open(self, code, label):
        self.ensure_one()
        # Client transfer list shows Documentation Staff instead of
        # Responsible; other transfer lists are untouched.
        tree_view = self.env.ref(
            'multiple_relocation.view_picking_tree_vifel_client',
            raise_if_not_found=False)
        views = [(tree_view.id if tree_view else False, 'tree'),
                 (False, 'kanban'), (False, 'form'),
                 (False, 'calendar'), (False, 'activity')]
        return {
            'type': 'ir.actions.act_window',
            'name': '%s — %s' % (label, self.partner_id.name),
            'res_model': 'stock.picking',
            'view_mode': 'tree,kanban,form,calendar,activity',
            'views': views,
            'domain': self._domain(code),
            'target': 'current',
            # Odoo's sample data (ghost REF0001... rows) reads as real
            # records to users; show a clear empty state instead.
            'useSampleModel': False,
            'help': self._empty_help(label),
            'context': {
                'search_default_draft': 1,
                'search_default_waiting': 1,
                'search_default_available': 1,
                'vifel_client_id': self.partner_id.id,
                # Creating from here means creating *for this client*: the
                # contact is pre-filled and locked, and the operation type
                # matches the list the encoder is standing in.
                'default_partner_id': self.partner_id.id,
                'default_picking_type_id': self._picking_type(code).id,
                'vifel_lock_partner': 1,
            },
        }

    def action_open_incoming(self):
        return self._open('incoming', self.incoming_label)

    def action_open_outgoing(self):
        return self._open('outgoing', self.outgoing_label)

    # ------------------------------------------------------------------
    # Create straight from the picker
    #
    # Encoding starts from paper: a Delivery Receipt arrives and the encoder
    # already knows the client and the direction before opening anything.
    # Making them walk client > picker > list > New spends three screens
    # reaching a decision they had made in advance, so the picker offers the
    # new document directly. The browse path is untouched.
    # ------------------------------------------------------------------
    def _new(self, code, label):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '%s — %s' % (label, self.partner_id.name),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                # Same pre-fill and partner lock as creating from the list, so
                # a document born here cannot drift to another client.
                'default_partner_id': self.partner_id.id,
                'default_picking_type_id': self._picking_type(code).id,
                'vifel_lock_partner': 1,
                'vifel_client_id': self.partner_id.id,
            },
        }

    def action_new_incoming(self):
        return self._new('incoming', self.incoming_label)

    def action_new_outgoing(self):
        return self._new('outgoing', self.outgoing_label)
