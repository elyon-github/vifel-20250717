# -*- coding: utf-8 -*-
"""Client smart buttons on the Contact form.

Adds counts + actions for the operational data a client owns:
transfers (normal / blast freeze), stocks (normal / blast freeze) and the
storage locations they currently occupy. The quant actions reuse the exact
domains of the Normal / Blast Freeze Inventory Overview actions so the
buttons show the same data, scoped to the contact being viewed.
"""
from ast import literal_eval

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

CLIENT_TAG = 'Client'
CLIENT_CODE_FIELD = 'x_studio_client_unique_code_1'

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
    vifel_latest_psi = fields.Char(
        string='Latest Pallet Series', compute='_compute_vifel_latest_psi',
        help='Most recently issued Pallet Series ID — the client code plus '
             'the last number the series counter handed out.')

    # ------------------------------------------------------------------
    # Client Unique Code — the PSI prefix, so it must identify ONE client
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_client_code(code):
        return (code or '').strip()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if CLIENT_CODE_FIELD in vals:
                vals[CLIENT_CODE_FIELD] = self._normalize_client_code(
                    vals[CLIENT_CODE_FIELD])
        return super().create(vals_list)

    def write(self, vals):
        if CLIENT_CODE_FIELD in vals:
            vals[CLIENT_CODE_FIELD] = self._normalize_client_code(
                vals[CLIENT_CODE_FIELD])
        return super().write(vals)

    @api.constrains(CLIENT_CODE_FIELD)
    def _check_client_unique_code(self):
        """No two contacts may share a Client Unique Code.

        The code prefixes every Pallet Series ID of the client, so a
        duplicate makes two clients mint the same series (AP-000001 for
        both) — the identity the whole warehouse relies on.

        Comparison ignores case and surrounding spaces, and archived
        contacts count too: unarchiving one would revive the clash.
        """
        for partner in self:
            code = self._normalize_client_code(partner[CLIENT_CODE_FIELD])
            if not code:
                continue
            # ilike narrows to a superset in SQL (it also catches 'hex'
            # and legacy ' HEX '); the exact call is made in Python below.
            others = self.with_context(active_test=False).search([
                ('id', '!=', partner.id),
                (CLIENT_CODE_FIELD, 'ilike', code),
            ])
            clash = others.filtered(
                lambda o: self._normalize_client_code(
                    o[CLIENT_CODE_FIELD]).lower() == code.lower())
            if clash:
                raise ValidationError(_(
                    "Client Unique Code \"%(code)s\" is already used by "
                    "%(client)s%(more)s.\n\n"
                    "The code prefixes this client's Pallet Series IDs, so it "
                    "must belong to one client only — otherwise two clients "
                    "would issue the same series."
                ) % {
                    'code': code,
                    'client': clash[0].display_name,
                    'more': (_(" and %s more") % (len(clash) - 1)
                             if len(clash) > 1 else ''),
                })

    @api.depends('category_id')
    def _compute_is_vifel_client(self):
        for partner in self:
            partner.is_vifel_client = CLIENT_TAG in partner.category_id.mapped('name')

    def _compute_vifel_latest_psi(self):
        """Client code + series counter, zfilled: e.g. BGZ-000042.

        getattr keeps a bare DB without the Studio fields from crashing.
        """
        for partner in self:
            code = self._normalize_client_code(
                getattr(partner, CLIENT_CODE_FIELD, ''))
            counter = int(getattr(partner, 'x_studio_pallet_series_id', 0) or 0)
            partner.vifel_latest_psi = (
                '%s-%s' % (code, str(counter).zfill(6)) if code else False)

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

    def _vifel_transfer_type_wizard(self, blast_freeze=False):
        """Ask Receiving or Withdrawal before opening the transfers."""
        self.ensure_one()
        wizard = self.env['multiple_relocation.client.transfer.type.wizard'].create({
            'partner_id': self.id,
            'is_blast_freeze': blast_freeze,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': '%s Transfer Transactions — %s' % (
                'Blast Freeze' if blast_freeze else 'Normal', self.name),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': dict(self.env.context, dialog_size='medium'),
        }

    def action_vifel_normal_transfers(self):
        """Pick Receiving or Withdrawal, then open the client's transfers."""
        return self._vifel_transfer_type_wizard()

    def action_vifel_bf_transfers(self):
        """Pick BF IN or BF OUT, then open the client's transfers."""
        return self._vifel_transfer_type_wizard(blast_freeze=True)

    def action_vifel_normal_stocks(self):
        """Normal Inventory Overview, scoped to this client."""
        return self._vifel_action(
            'Normal Stock Inquiry — %s' % self.name,
            'stock.quant', self._vifel_quant_domain(),
            'tree,form,kanban,pivot,graph',
            {'show_pkr_report': True, 'vifel_client_id': self.id,
             'search_default_productgroup': 1,
             'default_partner_ids': [(6, 0, [self.id])]})

    def action_vifel_bf_stocks(self):
        """Blast Freeze Inventory Overview, scoped to this client."""
        return self._vifel_action(
            'Blast Freeze Stock Inquiry — %s' % self.name,
            'stock.quant', self._vifel_quant_domain(blast_freeze=True),
            'tree,form,kanban,pivot,graph',
            {'show_pkr_report': True, 'vifel_client_id': self.id,
             'search_default_productgroup': 1,
             'default_partner_ids': [(6, 0, [self.id])]})

    def action_vifel_locations(self):
        """Internal storage locations this client currently occupies."""
        action = self._vifel_action(
            'Occupied Locations — %s' % self.name,
            'stock.location',
            [('x_studio_occupied_by_1', 'in', self.id),
             ('usage', '=', 'internal')],
            'tree,form,kanban',
            {'vifel_client_id': self.id})
        # Pin the VIFEL location search view (standard filters + Building
        # search/group-by) so filters, group-bys and Favorites are there.
        search_view = self.env.ref(
            'multiple_relocation.view_location_search_vifel_building',
            raise_if_not_found=False)
        if not search_view:
            search_view = self.env.ref('stock.view_location_search',
                                       raise_if_not_found=False)
        if search_view:
            action['search_view_id'] = (search_view.id, search_view.name)
        return action


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

    @api.model
    def vifel_set_client_tag_default(self):
        """Default the Client tag on contacts created from the Clients hub.

        The tag is a plain res.partner.category row without an XML id, so
        its id is resolved by name on every module update (idempotent, and
        a no-op when the tag or the action is missing).
        """
        action = self.env.ref('multiple_relocation.action_vifel_clients',
                              raise_if_not_found=False)
        tag = self.env['res.partner.category'].search(
            [('name', '=', CLIENT_TAG)], limit=1)
        if not action or not tag:
            return True
        try:
            context = literal_eval(action.context or '{}')
        except (ValueError, SyntaxError):
            context = {}
        if not isinstance(context, dict):
            context = {}
        if context.get('default_category_id') == [(6, 0, [tag.id])]:
            return True
        context['default_category_id'] = [(6, 0, [tag.id])]
        action.sudo().write({'context': repr(context)})
        return True
