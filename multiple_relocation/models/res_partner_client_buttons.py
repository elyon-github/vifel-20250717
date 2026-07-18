# -*- coding: utf-8 -*-
"""Client smart buttons on the Contact form.

Adds counts + actions for the operational data a client owns:
transfers (normal / blast freeze), stocks (normal / blast freeze) and the
storage locations they currently occupy. The quant actions reuse the exact
domains of the Normal / Blast Freeze Inventory Overview actions so the
buttons show the same data, scoped to the contact being viewed.
"""
from ast import literal_eval

from odoo import api, fields, models

CLIENT_TAG = 'Client'

# Locations excluded by the Inventory Overview actions (Partners/Vendors,
# Partners/Customers) — kept verbatim so the buttons match those screens.
EXCLUDED_LOCATION_IDS = [5, 4]

# Base domain of the Inventory Overview actions, minus the owner filter.
QUANT_BASE_DOMAIN = [
    ('location_id', 'not in', EXCLUDED_LOCATION_IDS),
    ('quantity', '>', 0),
]
NORMAL_BF_DOMAIN = [
    '|',
    ('x_studio_record_reference.x_studio_is_a_blast_freezer', '!=', True),
    ('location_id.x_studio_is_a_blast_freezer', '!=', True),
]
BF_DOMAIN = [
    '|',
    ('x_studio_record_reference.x_studio_is_a_blast_freezer', '=', True),
    ('location_id.x_studio_is_a_blast_freezer', '=', True),
]


class ResPartnerClientButtons(models.Model):
    _inherit = 'res.partner'

    is_vifel_client = fields.Boolean(
        string='Is VIFEL Client', compute='_compute_is_vifel_client',
        help='Contact carries the "Client" tag — drives the VIFEL smart buttons.')
    vifel_normal_transfer_count = fields.Integer(
        string='Normal Transfers', compute='_compute_vifel_client_counts')
    vifel_bf_transfer_count = fields.Integer(
        string='Blast Freeze Transfers', compute='_compute_vifel_client_counts')
    vifel_normal_pallet_count = fields.Integer(
        string='Normal Pallets', compute='_compute_vifel_client_counts')
    vifel_bf_pallet_count = fields.Integer(
        string='Blast Freeze Pallets', compute='_compute_vifel_client_counts')
    vifel_location_count = fields.Integer(
        string='Locations Occupied', compute='_compute_vifel_client_counts')

    # ------------------------------------------------------------------
    @api.depends('category_id')
    def _compute_is_vifel_client(self):
        for partner in self:
            partner.is_vifel_client = CLIENT_TAG in partner.category_id.mapped('name')

    def _vifel_quant_domain(self, blast_freeze=False):
        """Inventory Overview domain scoped to this client."""
        self.ensure_one()
        return (QUANT_BASE_DOMAIN
                + (BF_DOMAIN if blast_freeze else NORMAL_BF_DOMAIN)
                + [('owner_id', '=', self.id)])

    def _vifel_picking_domain(self, blast_freeze=False):
        """Every transfer of this client for the category — any state."""
        self.ensure_one()
        return [
            ('partner_id', '=', self.id),
            ('picking_type_id.is_blast_freeze_operation',
             '=' if blast_freeze else '!=', True),
        ]

    def _compute_vifel_client_counts(self):
        Picking = self.env['stock.picking']
        Quant = self.env['stock.quant']
        Location = self.env['stock.location']
        for partner in self:
            if not partner.id or not partner.is_vifel_client:
                partner.vifel_normal_transfer_count = 0
                partner.vifel_bf_transfer_count = 0
                partner.vifel_normal_pallet_count = 0
                partner.vifel_bf_pallet_count = 0
                partner.vifel_location_count = 0
                continue

            partner.vifel_normal_transfer_count = Picking.search_count(
                partner._vifel_picking_domain())
            partner.vifel_bf_transfer_count = Picking.search_count(
                partner._vifel_picking_domain(blast_freeze=True))

            # Pallet counting follows the house rule: unique Pallet # for
            # normal stock, unique Pallet Text (bf_pallet_char) for BF.
            normal = Quant.search_read(
                partner._vifel_quant_domain(), ['package_id'])
            partner.vifel_normal_pallet_count = len(
                {q['package_id'][0] for q in normal if q.get('package_id')})

            bf = Quant.search_read(
                partner._vifel_quant_domain(blast_freeze=True),
                ['bf_pallet_char'])
            partner.vifel_bf_pallet_count = len(
                {q['bf_pallet_char'] for q in bf if q.get('bf_pallet_char')})

            partner.vifel_location_count = Location.search_count(
                [('x_studio_occupied_by_1', 'in', partner.id)])

    # ------------------------------------------------------------------
    # Smart button actions
    # ------------------------------------------------------------------
    def _vifel_action(self, name, res_model, domain, view_mode, context=None):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': res_model,
            'view_mode': view_mode,
            'domain': domain,
            'target': 'current',
            'context': dict(self.env.context, **(context or {})),
        }

    def action_vifel_normal_transfers(self):
        """Client's normal transfers, grouped by operation type."""
        return self._vifel_action(
            'Normal Transfer Transactions — %s' % self.name,
            'stock.picking', self._vifel_picking_domain(),
            'tree,kanban,form,calendar,activity',
            {
                'search_default_picking_type': 1,
                'search_default_draft': 1,
                'search_default_waiting': 1,
                'search_default_available': 1,
                'vifel_client_id': self.id,
            })

    def action_vifel_bf_transfers(self):
        """Client's blast-freeze transfers, grouped by operation type."""
        return self._vifel_action(
            'Blast Freeze Transfer Transactions — %s' % self.name,
            'stock.picking', self._vifel_picking_domain(blast_freeze=True),
            'tree,kanban,form,calendar,activity',
            {
                'search_default_picking_type': 1,
                'search_default_draft': 1,
                'search_default_waiting': 1,
                'search_default_available': 1,
                'vifel_client_id': self.id,
            })

    def action_vifel_normal_stocks(self):
        """Normal Inventory Overview, scoped to this client."""
        return self._vifel_action(
            'Normal Stock Inquiry — %s' % self.name,
            'stock.quant', self._vifel_quant_domain(),
            'tree,form,kanban,pivot,graph',
            {'show_pkr_report': True, 'vifel_client_id': self.id,
             'default_partner_ids': [(6, 0, [self.id])]})

    def action_vifel_bf_stocks(self):
        """Blast Freeze Inventory Overview, scoped to this client."""
        return self._vifel_action(
            'Blast Freeze Stock Inquiry — %s' % self.name,
            'stock.quant', self._vifel_quant_domain(blast_freeze=True),
            'tree,form,kanban,pivot,graph',
            {'show_pkr_report': True, 'vifel_client_id': self.id,
             'default_partner_ids': [(6, 0, [self.id])]})

    def action_vifel_locations(self):
        """Storage locations this client currently occupies."""
        return self._vifel_action(
            'Occupied Locations — %s' % self.name,
            'stock.location', [('x_studio_occupied_by_1', 'in', self.id)],
            'tree,form,kanban',
            {'vifel_client_id': self.id})


class IrActionsActWindowVifel(models.Model):
    _inherit = 'ir.actions.act_window'

    OVERVIEW_ACTION_NAMES = (
        'Normal Inventory Overview',
        'Blast Freeze Inventory Overview',
    )

    @api.model
    def vifel_enable_quant_report_button(self):
        """Add show_pkr_report to the Inventory Overview actions.

        Those actions are Studio-owned, so they cannot be referenced by XML
        id from this module. Patching by name keeps the data file idempotent
        and harmless when the actions are missing or already flagged.
        """
        actions = self.search([
            ('res_model', '=', 'stock.quant'),
            ('name', 'in', list(self.OVERVIEW_ACTION_NAMES)),
        ])
        for action in actions:
            try:
                context = literal_eval(action.context or '{}')
            except (ValueError, SyntaxError):
                continue
            if not isinstance(context, dict) or context.get('show_pkr_report'):
                continue
            context['show_pkr_report'] = True
            action.sudo().write({'context': repr(context)})
        return True
