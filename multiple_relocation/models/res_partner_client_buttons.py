# -*- coding: utf-8 -*-
"""Client smart buttons on the Contact form.

Adds counts + actions for the operational data a client owns:
transfers (normal / blast freeze), stocks (normal / blast freeze) and the
storage locations they currently occupy. The quant actions reuse the exact
domains of the Normal / Blast Freeze Inventory Overview actions so the
buttons show the same data, scoped to the contact being viewed.
"""
from ast import literal_eval

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.query import Query
from odoo.tools.sql import SQL

CLIENT_TAG = 'Client'

# Documentation Staff read the client profile but do not maintain it.
# Created in the UI, so the module is "__custom__" — has_group resolves it in
# SQL and simply returns False on a database without it.
DOCSTAFF_GROUP = '__custom__.documentation_staff'
# Escape hatch: whoever administers the system keeps editing. Without this,
# an administrator who also carries the Documentation Staff group — as the
# admin account here does — would lock themselves out of every contact form.
DOCSTAFF_EXEMPT_GROUP = 'base.group_system'
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
    # NOT stored, deliberately. Storing it would let the Clients screen sort
    # by it in SQL, but it adds a column to res_partner — and a running server
    # keeps serving the previous registry, so every read of any partner field
    # raises "column vifel_pending_transfer_count does not exist" until the
    # service is restarted. That is a live outage on a core table for a
    # sorting nicety, so the count stays computed and the sort is done in the
    # Clients action instead (see _vifel_pending_order).
    vifel_pending_transfer_count = fields.Integer(
        string='Pending Transfers', compute='_compute_vifel_pending_count',
        help='Transfers of this client that are not yet validated — the work '
             'still outstanding, across normal and blast freeze.')
    vifel_has_activity = fields.Boolean(
        string='Has Activity', compute='_compute_vifel_client_counts',
        help='Client holds stock or has ever had a transfer. Cards without it '
             'are dimmed on the Clients screen so the eye skips them, while '
             'staying present for lookup by name.')
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

    # ------------------------------------------------------------------
    # Read-only contact form for Documentation Staff
    # ------------------------------------------------------------------
    @api.model
    def _vifel_form_is_readonly(self):
        """Should this user see the contact form read-only?"""
        user = self.env.user
        return (user.has_group(DOCSTAFF_GROUP)
                and not user.has_group(DOCSTAFF_EXEMPT_GROUP))

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        """Turn off editing on the contact form for Documentation Staff.

        This belongs in get_view, NOT in _get_view: the latter's result is
        cached by _get_view_cache on a key that does not include the user
        (ir_ui_view.py), so anything user-specific done there would be handed
        to whoever warms the cache first. get_view runs after that cache, which
        is where Odoo itself applies per-user access rights.

        Only "edit" is touched. Documentation Staff already lack create and
        unlink on res.partner, so _postprocess_access_rights has switched those
        off; write is what they still hold and what this removes from the UI.

        Deliberately every contact form, not just the Clients screen: the same
        client is reachable from a transfer's Customer field, and a rule that
        only covered one screen would not be a rule. Buttons keep working —
        they run actions rather than edit fields, so the smart buttons and the
        transfer shortcuts on a client card are unaffected.
        """
        result = super().get_view(view_id, view_type, **options)
        if view_type == 'form' and self._vifel_form_is_readonly():
            root = etree.fromstring(result['arch'].encode())
            root.set('edit', '0')
            result['arch'] = etree.tostring(root, encoding='unicode')
        return result

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

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, access_rights_uid=None):
        """Allow ordering by the (non-stored) pending count.

        Odoo cannot ORDER BY a computed field, and storing this one is not an
        option (see the field's comment — it breaks a running server until
        restart). So the Clients screen asks for it by name and the ranking is
        resolved here: one grouped query gives the count per partner, and the
        ids are reordered in Python.

        Anything else falls straight through to super(), so this is inert for
        every other partner search in the database.
        """
        # Case-insensitive throughout: the web client sends "... DESC" in
        # upper case, so matching lower case here silently sorted ascending
        # and put the idle clients first.
        order_l = (order or '').lower()
        if 'vifel_pending_transfer_count' not in order_l:
            return super()._search(domain, offset=offset, limit=limit, order=order,
                                   access_rights_uid=access_rights_uid)

        descending = 'vifel_pending_transfer_count desc' in order_l
        # Rank the whole matching set first, then apply offset/limit — paging
        # has to see the global order, not a page-local one.
        ids = list(super()._search(domain, order='complete_name asc',
                                   access_rights_uid=access_rights_uid))
        if ids:
            counts = {
                g['partner_id'][0]: g['__count']
                for g in self.env['stock.picking'].read_group(
                    [('partner_id', 'in', ids),
                     ('state', 'not in', ('done', 'cancel'))],
                    ['partner_id'], ['partner_id'], lazy=False)
                if g.get('partner_id')
            }
            # sort() is stable, so clients on the same count keep the A-Z
            # order established above.
            ids.sort(key=lambda i: counts.get(i, 0), reverse=descending)
            if offset:
                ids = ids[offset:]
            if limit:
                ids = ids[:limit]
        # _search must return a Query, not a list (search_fetch calls
        # query.is_empty()). Wrap the ranked ids in one that PRESERVES their
        # order — array_position keeps that in a single expression instead of
        # a 135-term ORDER BY.
        query = Query(self.env.cr, self._table, self._table_query)
        if not ids:
            query.add_where('FALSE')
            return query
        query.add_where('"%s".id IN %%s' % self._table, [tuple(ids)])
        query.order = SQL(
            'array_position(%s::int[], "%s".id)' % ('%s', self._table), ids)
        return query

    def _compute_vifel_pending_count(self):
        """Outstanding work per client — the one actionable number on a card.

        Stored (so the Clients screen can sort by it) and batched: one grouped
        query for the whole recordset rather than a count per partner.
        """
        counts = {}
        if self.ids:
            counts = {
                g['partner_id'][0]: g['__count']
                for g in self.env['stock.picking'].read_group(
                    [('partner_id', 'in', self.ids),
                     ('state', 'not in', ('done', 'cancel'))],
                    ['partner_id'], ['partner_id'], lazy=False)
                if g.get('partner_id')
            }
        for partner in self:
            partner.vifel_pending_transfer_count = counts.get(partner.id, 0)

    def _compute_vifel_client_counts(self):
        """Counts for the client cards, gathered in BATCH.

        The Clients kanban paints 80 cards at a time, so anything done per
        record here is multiplied by 80. Written per record (a search_count
        or search_read each) this cost ~27 ms a card — 2.1 s per page, 3.6 s
        to scroll the client list. Grouping instead costs one query per
        metric for the whole page regardless of its size: measured ~13x
        faster. Keep it batched; do not reintroduce a search inside the loop.
        """
        clients = self.filtered(lambda p: p.id and p.is_vifel_client)
        for partner in self - clients:
            partner.vifel_normal_transfer_count = 0
            partner.vifel_bf_transfer_count = 0
            partner.vifel_normal_pallet_count = 0
            partner.vifel_bf_pallet_count = 0
            partner.vifel_location_count = 0
            partner.vifel_has_activity = False
        if not clients:
            return

        ids = clients.ids
        Picking = self.env['stock.picking']
        Quant = self.env['stock.quant']

        def by_partner(model, domain, key='partner_id'):
            """{partner_id: count} for one grouped query."""
            return {
                g[key][0]: g['__count']
                for g in model.read_group(
                    [(key, 'in', ids)] + domain, [key], [key], lazy=False)
                if g.get(key)
            }

        normal_tr = by_partner(Picking, [
            ('picking_type_id.is_blast_freeze_operation', '!=', True)])
        bf_tr = by_partner(Picking, [
            ('picking_type_id.is_blast_freeze_operation', '=', True)])

        # Pallets follow the house rule — unique Pallet # for normal stock,
        # unique Pallet Text (bf_pallet_char) for BF — so this is a COUNT
        # DISTINCT, which read_group cannot express: grouping by
        # (owner, package) instead returns one row per pallet (~20k) only to
        # length them in Python, and measured 534 ms of a 747 ms page. The
        # query is built through the ORM (_where_calc) so the Studio-field
        # domains above stay the single source of truth, then the distinct
        # count is pushed into SQL — 7x faster.
        def distinct_by_owner(domain, column):
            query = Quant._where_calc([('owner_id', 'in', ids)] + domain)
            Quant._apply_ir_rules(query, 'read')
            from_clause, where_clause, params = query.get_sql()
            self.env.cr.execute(
                'SELECT "stock_quant".owner_id, COUNT(DISTINCT "stock_quant".%s) '
                'FROM %s WHERE %s GROUP BY "stock_quant".owner_id'
                % (column, from_clause, where_clause or 'TRUE'), params)
            return dict(self.env.cr.fetchall())

        normal_pallets = distinct_by_owner(
            QUANT_BASE_DOMAIN + NORMAL_BF_DOMAIN + [('package_id', '!=', False)],
            'package_id')
        bf_pallets = distinct_by_owner(
            QUANT_BASE_DOMAIN + BF_DOMAIN + [('bf_pallet_char', '!=', False)],
            'bf_pallet_char')

        # Occupied locations: a many2many, so read the relation once and
        # count per client rather than a search_count each.
        locations = {}
        Location = self.env['stock.location']
        for loc in Location.search_read(
                [('x_studio_occupied_by_1', 'in', ids), ('usage', '=', 'internal')],
                ['x_studio_occupied_by_1']):
            for pid in loc.get('x_studio_occupied_by_1') or []:
                locations[pid] = locations.get(pid, 0) + 1

        for partner in clients:
            pid = partner.id
            partner.vifel_normal_transfer_count = normal_tr.get(pid, 0)
            partner.vifel_bf_transfer_count = bf_tr.get(pid, 0)
            partner.vifel_normal_pallet_count = normal_pallets.get(pid, 0)
            partner.vifel_bf_pallet_count = bf_pallets.get(pid, 0)
            partner.vifel_location_count = locations.get(pid, 0)
            partner.vifel_has_activity = bool(
                partner.vifel_normal_pallet_count
                or partner.vifel_bf_pallet_count
                or partner.vifel_normal_transfer_count
                or partner.vifel_bf_transfer_count)

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

    # ------------------------------------------------------------------
    # Kanban badge actions
    #
    # The badges on a client card are clickable and land on exactly the
    # records they count — a badge reading "241 Transfers" opens those 241.
    # They deliberately skip the Receiving/Withdrawal picker the BUTTONS use:
    # a badge states a number, so the click shows that number, while the
    # buttons below are where a directional choice belongs.
    # ------------------------------------------------------------------
    def _vifel_transfer_list(self, name, domain):
        """Open a transfer list, showing the Documentation Staff column.

        Create is off here. A badge answers "which records are these?", so it
        carries no operation type — Pending even spans normal and BF at once.
        A transfer started from this list would have no picking type to
        inherit, which is the one field it cannot be missing. Creating one is
        what the buttons below the badges are for: they ask Receiving or
        Withdrawal first, then open the list with that type in context.
        """
        self.ensure_one()
        tree_view = self.env.ref(
            'multiple_relocation.view_picking_tree_vifel_client',
            raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': '%s — %s' % (name, self.name),
            'res_model': 'stock.picking',
            'view_mode': 'tree,kanban,form',
            'views': [(tree_view.id if tree_view else False, 'tree'),
                      (False, 'kanban'), (False, 'form')],
            'domain': domain,
            'target': 'current',
            'context': {'vifel_client_id': self.id,
                        'default_partner_id': self.id,
                        'vifel_lock_partner': 1,
                        'create': False},
        }

    def action_vifel_all_normal_transfers(self):
        """Every normal transfer of this client, any state."""
        return self._vifel_transfer_list(
            'Transfers', self._vifel_picking_domain())

    def action_vifel_all_bf_transfers(self):
        """Every blast-freeze transfer of this client, any state."""
        return self._vifel_transfer_list(
            'Blast Freeze Transfers',
            self._vifel_picking_domain(blast_freeze=True))

    def action_vifel_pending_transfers(self):
        """The unvalidated work — both directions, normal and BF together.

        No type picker: the badge means "work outstanding", so the click
        shows that work rather than asking a question first.
        """
        self.ensure_one()
        return self._vifel_transfer_list(
            'Pending Transfers',
            [('partner_id', '=', self.id),
             ('state', 'not in', ('done', 'cancel'))])

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
