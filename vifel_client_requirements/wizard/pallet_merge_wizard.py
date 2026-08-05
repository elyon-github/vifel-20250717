# -*- coding: utf-8 -*-
"""Pallet Merge wizard, v2 (Client-Specific Requirement Enhancement).

Redesign of the v1 wizard, which stacked two unrelated jobs behind one
group heading and asked the user to judge "does this fit?" from a bare
Pallet # dropdown, while withholding the very numbers the judgment needs.

v2 principles:

* **One dialog, one primary action.** A mode radio switches the lower
  half between *Merge onto a stocked pallet* and *Start a new special
  pallet*; there is exactly one Confirm button, dispatched on the mode.
* **A candidate TABLE, not a dropdown.** Every eligible pallet is a row
  showing PSI / Product / Location / Weight (KG) / Quantity, so the fit
  judgment (which is the Documentation Staff's to make — no system
  capacity rule) has all the numbers in front of it, next to a header
  strip showing the line being merged.
* **Reasons, not silence.** A mixed (multi-PSI) pallet is shown as an
  INELIGIBLE row carrying its reason, never dropped from the list — the
  user learns why they cannot pick it.

The candidate rows are materialised once, at create, rather than as a
non-stored computed field: a computed o2m recomputes on cache
invalidation and would wipe the user's row selection the moment they
click it.

Merge business rules honoured (BUSINESS_CONTEXT_AND_LEARNINGS.md §3-5):
one physical pallet = one PSI; merged line = +0 pallets but full amounts;
same owner only; never BF; never a return.
"""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# How many candidate pallets to materialise in the table. The intended
# merge clients have a handful (Wonder Meats: 1; Consistent: its condition
# pallets), so this never bites them. It exists only so a mis-scoped client
# — Multiple + Include Regular on a large inventory — degrades to a usable
# window instead of thousands of rows: the table shows the first CAP
# (special-type pallets first), a banner says how many were hidden, and the
# manual Pallet # picker reaches any pallet beyond the cap.
CANDIDATE_CAP = 300


class PalletMergeCandidate(models.TransientModel):
    _name = 'pallet.merge.candidate'
    _description = 'A pallet offered as a merge target'
    _order = 'eligible desc, psi, id'

    wizard_id = fields.Many2one(
        'pallet.merge.wizard', required=True, ondelete='cascade', index=True)
    package_id = fields.Many2one('stock.quant.package', string='Pallet #')
    psi = fields.Char(string='Pallet Series')
    psi_count = fields.Integer(string='PSI Count')
    product_summary = fields.Char(string='Product')
    location_id = fields.Many2one('stock.location', string='Location')
    weight_kg = fields.Float(string='Weight (KG)', digits=(12, 3))
    quantity = fields.Float(string='Quantity')
    matches_line_product = fields.Boolean(string='Same Product')
    eligible = fields.Boolean(string='Selectable', default=True)
    ineligible_reason = fields.Char(string='Reason')
    is_target = fields.Boolean(string='Merge Here')
    # A pallet started earlier on THIS receipt, not yet on the floor. It has
    # no quant to read, so its figures come from the sibling lines instead.
    on_this_receipt = fields.Boolean(string='On This Receipt')
    # The empty pinned Fixed pallet: choosing it BIRTHS the pallet (+1,
    # unflagged) rather than merging onto stock (+0).
    first_stock = fields.Boolean(string='Empty — First Stock')
    source_label = fields.Char(string='Where', compute='_compute_source_label')

    @api.depends('on_this_receipt', 'first_stock')
    def _compute_source_label(self):
        for cand in self:
            if cand.first_stock:
                cand.source_label = _('Empty — starts the pallet')
            elif cand.on_this_receipt:
                cand.source_label = _('On this receipt')
            else:
                cand.source_label = _('In storage')

    @api.onchange('is_target')
    def _onchange_is_target(self):
        """Radio behaviour: checking one row clears the others. An
        ineligible row cannot be chosen at all."""
        if not self.is_target:
            return
        if not self.eligible:
            self.is_target = False
            return {'warning': {
                'title': _('Pallet not available'),
                'message': self.ineligible_reason or _(
                    'This pallet cannot be a merge target.'),
            }}
        for other in self.wizard_id.candidate_line_ids - self:
            other.is_target = False


class PalletMergeWizard(models.TransientModel):
    _name = 'pallet.merge.wizard'
    _description = 'Merge an incoming line onto a stocked pallet'

    move_line_id = fields.Many2one(
        'stock.move.line', required=True, ondelete='cascade',
        string='Pallet Line')
    # All lines being merged in this pass (1 for a per-line open, several for
    # a multi-select open). move_line_id stays the "primary" that drives the
    # single-line header and the candidate scope; every eligible line in this
    # set lands on the one chosen target.
    move_line_ids = fields.Many2many(
        'stock.move.line', 'vifel_merge_wizard_line_rel',
        string='Pallet Lines')
    is_multi = fields.Boolean(compute='_compute_multi')
    multi_count = fields.Integer(compute='_compute_multi')
    multi_weight = fields.Float(compute='_compute_multi', digits=(12, 3))
    multi_quantity = fields.Float(compute='_compute_multi')

    @api.depends('move_line_ids', 'fast_encode_line_ids')
    def _compute_multi(self):
        # When opened from the Magic Wizard, the encoder's edited-but-unconfirmed
        # weight/quantity live on the transient ROWS, not the real move lines —
        # sum those so the dialog reflects what they will actually withdraw.
        for wizard in self:
            lines = wizard.move_line_ids
            wizard.is_multi = len(lines) > 1
            wizard.multi_count = len(lines)
            rows = wizard.fast_encode_line_ids
            if rows:
                wizard.multi_weight = sum(rows.mapped('kilogram'))
                wizard.multi_quantity = sum(rows.mapped('quantity'))
            else:
                wizard.multi_weight = sum(lines.mapped('quantity'))
                wizard.multi_quantity = sum(lines.mapped('x_studio_2nd_uom'))

    picking_id = fields.Many2one(related='move_line_id.picking_id')
    partner_id = fields.Many2one(
        related='move_line_id.picking_id.partner_id', string='Client')
    is_multiple_mode = fields.Boolean(
        related='partner_id.vifel_multiple_pallet_support')

    # the line being merged — the other half of the "does it fit?" judgment
    line_product_id = fields.Many2one(
        related='move_line_id.product_id', string='Product')
    line_psi = fields.Char(
        related='move_line_id.x_studio_pallet_series_id',
        string='Current Series')
    # Computed (not related) so a merge opened from the Magic Wizard shows the
    # encoder's edited-but-unconfirmed weight / quantity from the transient ROW,
    # not the stale real-line values. Falls back to the real line otherwise.
    line_weight = fields.Float(
        compute='_compute_line_cargo', string='Line Weight (KG)')
    line_quantity = fields.Float(
        compute='_compute_line_cargo', string='Line Quantity')
    line_quantity_uom = fields.Many2one(
        related='move_line_id.x_studio_quantity_uom', string='Quantity UOM')

    @api.depends('move_line_id', 'fast_encode_line_id', 'fast_encode_line_ids')
    def _compute_line_cargo(self):
        FeLine = self.env['stock.move.line.fast_encode_rr.line']
        for wizard in self:
            row = FeLine.browse(wizard.fast_encode_line_id) \
                if wizard.fast_encode_line_id else FeLine
            if not row.exists() and wizard.fast_encode_line_ids:
                row = wizard.fast_encode_line_ids[:1]
            if row.exists():
                wizard.line_weight = row.kilogram
                wizard.line_quantity = row.quantity
            else:
                wizard.line_weight = wizard.move_line_id.quantity
                wizard.line_quantity = wizard.move_line_id.x_studio_2nd_uom

    # What is standing on the currently-selected target, shown INLINE so the
    # dialog never closes (a target='new' window would replace this wizard).
    selected_target_quant_ids = fields.Many2many(
        'stock.quant', 'vifel_merge_wizard_target_quant_rel',
        compute='_compute_selected_target_quants',
        string='On the selected pallet')

    @api.depends('candidate_line_ids.is_target')
    def _compute_selected_target_quants(self):
        for wizard in self:
            target = wizard.candidate_line_ids.filtered(
                'is_target')[:1].package_id
            wizard.selected_target_quant_ids = target.quant_ids.filtered(
                lambda q: q.quantity != 0) if target else False

    mode = fields.Selection(
        [('merge', 'Merge onto a pallet already stocked'),
         ('new', 'Start a NEW special pallet')],
        string='Action', default='merge', required=True)
    # Set when launched from inside the Magic Wizard: merge-onto-stocked only
    # (create-special stays a Pallet Breakdown action). Odoo replaces the
    # current dialog when an action opens with target='new', so the Magic
    # Wizard closes behind this one — EVERY exit path here must bring the user
    # back to it, or the encoding session is lost. Stored on the record rather
    # than read from context so Back/Confirm work regardless of how the button
    # was invoked.
    from_fast_encode = fields.Boolean(
        default=lambda self: bool(
            self.env.context.get('fast_encode_line_id')))
    fast_encode_line_id = fields.Integer(
        string='Magic Wizard Line',
        default=lambda self: self.env.context.get('fast_encode_line_id', 0))
    # every Magic Wizard transient row to sync back after a multi-merge
    fast_encode_line_ids = fields.Many2many(
        'stock.move.line.fast_encode_rr.line',
        'vifel_merge_wizard_fe_line_rel', string='Magic Wizard Rows')

    candidate_line_ids = fields.One2many(
        'pallet.merge.candidate', 'wizard_id', string='Available Pallets')
    candidate_total = fields.Integer(string='Total Eligible Pallets')
    candidates_capped = fields.Boolean(string='List Truncated')

    # escape hatch, shown only when the list is capped: reach any pallet
    # beyond the first CANDIDATE_CAP by name. Same owner-scoped domain as
    # the candidate table, so it can never pick a foreign pallet.
    manual_package_id = fields.Many2one(
        'stock.quant.package', string='Other Pallet #',
        domain="[('id', 'in', candidate_package_ids)]")
    candidate_package_ids = fields.Many2many(
        'stock.quant.package', compute='_compute_candidate_package_ids')

    # a live read-out of the current selection, for the inline warnings
    selected_candidate_id = fields.Many2one(
        'pallet.merge.candidate', compute='_compute_selection')
    selected_first_stock = fields.Boolean(compute='_compute_selection')

    # Shown as a labelled strip at the top of the dialog. Individual fields
    # rather than one joined string: a run-on line ("Line 1 · 0.000 KG · 0
    # Quantity · now on 16-042026") is hard to scan and buries the numbers
    # the fit judgment needs. Rendered as its own flex cell each, so nothing
    # can wrap mid-value the way the original four-field group did.
    # x_studio_ is an Integer (the line "#"), not a Char — see the field
    # convention note in multiple_relocation_AI_CONTEXT.md §5.
    line_number = fields.Integer(
        related='move_line_id.x_studio_', string='Line')


    # create-new-special path (Multiple mode only)
    psi_type_id = fields.Many2one(
        'vifel.psi.type', string='PSI Type',
        domain="[('partner_id', '=', partner_id)]")
    # The RR's own warehouse. Everything offered by this wizard is scoped to
    # it: merge candidates already were (see _candidate_packages), and the
    # create-new-special pallet and location must be too — with two
    # warehouses live, an unscoped picker will happily seat a pallet in the
    # wrong building. Pallets follow the Magic Wizard's existing rule
    # (x_studio_warehouse); locations use stock.location.warehouse_id, which
    # is stored and populated on every internal location.
    # Read straight off the picking: every stock.picking belongs to exactly
    # one warehouse (stock.picking.warehouse_id, stored and populated on all
    # 11,419 records here, and never disagreeing with its picking type's
    # warehouse). That record IS the reference for everything this wizard is
    # allowed to offer.
    warehouse_id = fields.Many2one(
        related='move_line_id.picking_id.warehouse_id', string='Warehouse')
    # The receipt's destination BUILDING/ZONE (e.g. M/EX). A new special pallet
    # must be seated UNDER it — the whole receipt lands in that building, so a
    # child of it is the only physically-correct home. This is tighter than the
    # warehouse (a warehouse holds several buildings).
    picking_dest_location_id = fields.Many2one(
        related='move_line_id.picking_id.location_dest_id',
        string='Receipt Destination')

    # Pallets pinned as some client's Fixed Merge Pallet: dedicated, never
    # offered as a free empty pallet even while they hold no stock.
    vifel_pinned_package_ids = fields.Many2many(
        'stock.quant.package', 'vifel_merge_wizard_pinned_pkg_rel',
        compute='_compute_vifel_pinned_package_ids')

    @api.depends('move_line_id')
    def _compute_vifel_pinned_package_ids(self):
        pinned = self.env['res.partner']._vifel_fixed_merge_packages()
        for wizard in self:
            wizard.vifel_pinned_package_ids = pinned

    # Pallets and non-aisle locations ALREADY claimed by OTHER lines of this
    # same receipt. A NEW special pallet must be a fresh one in a free spot —
    # reusing a sibling line's pallet would mix two Pallet Series on it, and
    # reusing its (non-aisle) location would stack two pallets in one bin. Both
    # are refused at validation, but the pickers should not offer them at all.
    #
    # "Claimed" spans BOTH surfaces:
    #  * the Pallet Breakdown — the REAL move lines of the receipt; and
    #  * the Magic Wizard — the sibling transient rows of the SAME Fast-Encode
    #    session whose Pallet # / Location the encoder has picked but not yet
    #    confirmed to the real lines. Without this the wizard would offer a
    #    pallet/location another Magic Wizard row already took.
    vifel_receipt_used_package_ids = fields.Many2many(
        'stock.quant.package', 'vifel_merge_wizard_used_pkg_rel',
        compute='_compute_vifel_receipt_used')
    vifel_receipt_used_location_ids = fields.Many2many(
        'stock.location', 'vifel_merge_wizard_used_loc_rel',
        compute='_compute_vifel_receipt_used')

    def _non_aisle_locs(self, records):
        """The non-aisle destination locations of the given move lines / rows."""
        return records.filtered(
            lambda r: r.location_dest_id
            and not r.location_dest_id.x_studio_is_an_aisle
        ).mapped('location_dest_id')

    @api.depends('move_line_id', 'move_line_ids',
                 'move_line_id.picking_id.move_line_ids.result_package_id',
                 'move_line_id.picking_id.move_line_ids.location_dest_id',
                 'fast_encode_line_id', 'fast_encode_line_ids')
    def _compute_vifel_receipt_used(self):
        for wizard in self:
            picking = wizard.move_line_id.picking_id
            own = wizard.move_line_ids | wizard.move_line_id
            fe_rows = wizard._fast_encode_rows()

            if fe_rows:
                # Opened from the Magic Wizard: it is a deferred-write WORKING
                # copy, so "used" must reflect the ROWS' CURRENT selections, not
                # the still-unconfirmed real move lines. A line that the encoder
                # reassigned in the Magic Wizard (e.g. moved onto a new special
                # pallet) frees its OLD pallet even though the real line still
                # carries it — using the real line here would wrongly keep that
                # pallet "used" (the "00172 B already used" false positive).
                # Each line WITH a row uses the row's state; a line with NO row
                # falls back to its real move line.
                session_rows = fe_rows[0].wizard_id.line_ids
                session_ml_ids = set(session_rows.mapped('stock_move_line'))
                sibling_rows = session_rows - fe_rows
                real_others = (picking.move_line_ids - own).filtered(
                    lambda l: l.id not in session_ml_ids)
                used_pkgs = (real_others.mapped('result_package_id')
                             | sibling_rows.mapped('result_package_id'))
                used_locs = (wizard._non_aisle_locs(real_others)
                             | wizard._non_aisle_locs(sibling_rows))
            else:
                # Opened from the Pallet Breakdown: the real move lines ARE the
                # source of truth.
                others = picking.move_line_ids - own
                used_pkgs = others.mapped('result_package_id')
                used_locs = wizard._non_aisle_locs(others)

            wizard.vifel_receipt_used_package_ids = used_pkgs
            wizard.vifel_receipt_used_location_ids = used_locs

    new_package_id = fields.Many2one(
        'stock.quant.package', string='New Empty Pallet',
        domain="[('location_id', '=', False), "
               "('package_type_id.name', '=', 'Pallet'), "
               "('x_studio_active', '=', True), "
               "('x_studio_warehouse', '=', warehouse_id), "
               "('id', 'not in', vifel_pinned_package_ids), "
               "('id', 'not in', vifel_receipt_used_package_ids), "
               "'|', ('x_studio_receiving_report_id', '=', False), "
               "('x_studio_receiving_report_id', '=', picking_id)]")
    new_location_id = fields.Many2one(
        'stock.location', string='New Location',
        domain="[('usage', '=', 'internal'), "
               "('id', 'child_of', picking_dest_location_id), "
               "('x_studio_is_a_blast_freezer', '!=', True), "
               "'|', ('x_studio_is_an_aisle', '=', True), "
               "'&', '&', ('child_ids', '=', False), "
               "('x_studio_occupied_by_1', '=', False), "
               "('id', 'not in', vifel_receipt_used_location_ids), "
               "'|', ('x_studio_receiving_report_id', '=', False), "
               "('x_studio_receiving_report_id', '=', picking_id)]")

    # ------------------------------------------------------------------
    # selection read-out
    # ------------------------------------------------------------------
    @api.depends('candidate_line_ids.is_target')
    def _compute_selection(self):
        for wizard in self:
            selected = wizard.candidate_line_ids.filtered('is_target')[:1]
            wizard.selected_candidate_id = selected
            wizard.selected_first_stock = bool(
                selected and selected.first_stock)

    @api.onchange('candidate_line_ids')
    def _onchange_candidate_lines_single_target(self):
        """Keep 'Merge Here' single-select AND make it show in the UI.

        Only ONE candidate may be the merge target. The per-row
        ``_onchange_is_target`` already clears the other rows in memory, but a
        CHILD o2m onchange that edits its siblings does not reliably re-render
        them in the web client — so a user can appear to toggle several 'Merge
        Here' at once. Declaring the exclusivity here, at the PARENT level,
        returns the whole candidate list on every toggle, so the de-selected
        rows visibly switch off. The guard below is a safety net: after the
        per-row onchange there is normally exactly one target, but if more than
        one ever slips through, keep the last-toggled and clear the rest."""
        targets = self.candidate_line_ids.filtered('is_target')
        if len(targets) > 1:
            (targets - targets[-1]).is_target = False

    # ------------------------------------------------------------------
    # candidate materialisation (once, at create)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        # vifel_skip_candidates: a throwaway wizard built only to RE-APPLY an
        # already-resolved decision (the Magic Wizard's staged-merge Confirm) —
        # it never shows the candidate table, so skip the (costly) materialise.
        skip = self.env.context.get('vifel_skip_candidates')
        for wizard in wizards:
            # a per-line open sets move_line_id only; keep move_line_ids the
            # single source of truth for "which lines are we merging"
            if not wizard.move_line_ids and wizard.move_line_id:
                wizard.move_line_ids = wizard.move_line_id
            if not skip:
                wizard._populate_candidates()
        return wizards

    def _stocked_quants(self, package):
        return package.quant_ids.filtered(
            lambda q: q.quantity > 0 and q.location_id.usage == 'internal')

    def _pinned_pallet_already_claimed(self, package):
        """Has another UNVALIDATED receipt already claimed this empty pinned
        pallet as its birth?

        The empty pinned Fixed pallet is born exactly ONCE — the first receipt
        to put stock on it counts +1 (an unflagged line); every later receipt
        merges onto it (+0), even before the first validates. Two receipts that
        both saw "no stock" would otherwise both birth it, counting the one
        physical pallet twice (and Re-sync would not self-heal, since it counts
        a unique package once per RR).

        A claim = an unflagged incoming move line on this package from a
        DIFFERENT, still-open picking. Lines of THIS wizard's own picking are
        not a foreign claim (they share the birth, deduped to +1 by the ledger).
        """
        if not package:
            return False
        return bool(self.env['stock.move.line'].search_count([
            ('result_package_id', '=', package.id),
            ('is_pallet_merge', '=', False),
            ('picking_id', '!=', self.picking_id.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel')),
        ]))

    def _lock_pinned_pallet(self, package):
        """Serialise concurrent births of the same pinned pallet.

        A row lock on the package (mirrors SA#297's FOR UPDATE pattern) so two
        confirms racing on the same empty pinned pallet cannot both pass the
        claim check: the second blocks until the first commits its unflagged
        birth line, then sees it and merges (+0) instead of birthing again.
        """
        if package:
            self.env.cr.execute(
                'SELECT id FROM stock_quant_package WHERE id = %s FOR UPDATE',
                (package.id,))

    def _candidate_packages(self):
        """The set of pallets offered to this client, owner-scoped.

        Fixed mode: the one pinned pallet. Multiple mode: the client's
        stocked pallets whose PSI prefix belongs to a client type; regular
        stocked pallets widen the list when Include Regular is on, or stand
        in entirely when the client has no types. "Regular" is any stocked
        pallet of the owner — NOT matched against the client code, because a
        code change leaves legacy-prefix stock (BGZ- under code BG) that is
        every bit as mergeable.
        """
        self.ensure_one()
        partner = self.partner_id
        if not partner.vifel_can_merge_pallets:
            return self.env['stock.quant.package']
        if not partner.vifel_multiple_pallet_support:
            return partner.vifel_fixed_package_id

        warehouse = self.warehouse_id      # the picking's own warehouse
        quants = self.env['stock.quant'].search([
            ('owner_id', '=', partner.id),
            ('package_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('location_id.x_studio_is_a_blast_freezer', '!=', True),
            ('x_studio_pallet_series_id', '!=', False),
        ])
        if warehouse:
            quants = quants.filtered(
                lambda q: q.location_id.warehouse_id == warehouse)
        prefixes = set(partner.vifel_psi_type_ids.mapped('prefix'))
        include_regular = partner.vifel_include_regular_pallets or not prefixes
        packages = self.env['stock.quant.package']
        for quant in quants:
            prefix = (quant.x_studio_pallet_series_id or '').rpartition('-')[0]
            if include_regular or prefix in prefixes:
                packages |= quant.package_id
        return packages

    @api.depends('move_line_id')
    def _compute_candidate_package_ids(self):
        for wizard in self:
            wizard.candidate_package_ids = wizard._candidate_packages() \
                - wizard._own_packages()

    def _own_packages(self):
        """Every selected line's own pallet — never a merge target of itself."""
        self.ensure_one()
        return (self.move_line_ids or self.move_line_id).mapped(
            'result_package_id')

    def _populate_candidates(self):
        """Materialise the candidate rows in ONE grouped read.

        The old per-package `.quant_ids.filtered` loop cost ~4s and 3.5k
        transient rows on a large owner. One search over the candidate
        packages' stocked quants, aggregated in Python, keeps it well under
        a second; the CANDIDATE_CAP then bounds what a mis-scoped client can
        put on screen.
        """
        self.ensure_one()
        partner = self.partner_id
        packages = self._candidate_packages() - self._own_packages()
        prefixes = set(partner.vifel_psi_type_ids.mapped('prefix'))
        # Same regular-pallet policy the stocked candidates use
        # (_candidate_packages): a client that does NOT include regular pallets
        # is offered ONLY its special-type pallets. Applied to the
        # "on this receipt" siblings below too, so a Multiple client is never
        # offered a sibling line's ORDINARY receiving pallet as a merge target.
        include_regular = partner.vifel_include_regular_pallets or not prefixes
        line_product_id = self.line_product_id.id

        # one read of every stocked internal quant on the candidate pallets
        agg = {}
        for r in self.env['stock.quant'].search_read(
                [('package_id', 'in', packages.ids), ('quantity', '>', 0),
                 ('location_id.usage', '=', 'internal')],
                ['package_id', 'x_studio_pallet_series_id', 'product_id',
                 'location_id', 'quantity', 'x_studio_2nd_uom']):
            a = agg.setdefault(r['package_id'][0], {
                'psis': set(), 'products': [], 'product_ids': set(),
                'location_id': r['location_id'] and r['location_id'][0],
                'weight': 0.0, 'quantity': 0.0})
            if r['x_studio_pallet_series_id']:
                a['psis'].add(r['x_studio_pallet_series_id'])
            if r['product_id'] and r['product_id'][0] not in a['product_ids']:
                a['product_ids'].add(r['product_id'][0])
                a['products'].append(r['product_id'][1])
            a['weight'] += r['quantity'] or 0.0
            a['quantity'] += r['x_studio_2nd_uom'] or 0.0

        scored = []
        for package in packages:
            a = agg.get(package.id)
            psis = sorted(a['psis']) if a else []
            eligible, reason, first_stock = True, False, False
            if len(psis) > 1:
                eligible = False
                reason = _('Mixed pallet — carries %d Pallet Series (%s). '
                           'Consolidate it to one series before merging onto '
                           'it.') % (len(psis), ', '.join(psis))
                psi_label = ', '.join(psis)
            elif psis:
                psi_label = psis[0]
            elif package == partner.vifel_fixed_package_id \
                    and (partner.vifel_fixed_psi or '').strip():
                psi_label = '%s (empty)' % partner.vifel_fixed_psi.strip()
                # first stock ONLY if no other open receipt already claimed
                # this empty pinned pallet — otherwise this one merges (+0)
                first_stock = not self._pinned_pallet_already_claimed(package)
            else:
                eligible = False
                reason = _('Empty pallet — no stock, so there is no Pallet '
                           'Series to adopt.')
                psi_label = ''
            prefix = psi_label.rpartition('-')[0]
            products = a['products'] if a else []
            vals = {
                'package_id': package.id,
                'psi': psi_label,
                'psi_count': len(psis),
                'product_summary': ', '.join(products[:3]),
                'location_id': a['location_id'] if a else False,
                'weight_kg': a['weight'] if a else 0.0,
                'quantity': a['quantity'] if a else 0.0,
                'matches_line_product':
                    (line_product_id in a['product_ids']) if a else True,
                'eligible': eligible,
                'ineligible_reason': reason,
                'is_target': False,
                'first_stock': first_stock,
            }
            # eligible + special-type pallets sort to the top, then by PSI
            scored.append(((0 if eligible else 1,
                            0 if prefix in prefixes else 1, psi_label), vals))

        # ---- pallets started earlier on THIS receipt ----------------------
        # They carry no quant yet (the goods arrive at validation), so the
        # stocked search above cannot see them — yet they are exactly what a
        # second line of the same receipt usually wants to join. Their figures
        # come from the sibling lines already sitting on them.
        # Multiple mode only. A Fixed client is defined by having exactly ONE
        # pallet offered forever; adding whatever other lines of the receipt
        # happen to sit on would contradict that.
        own_lines = self.move_line_ids or self.move_line_id
        seen_pkgs = set(packages.ids) | set(self._own_packages().ids)
        siblings = {}
        for sib in (self.picking_id.move_line_ids
                    if partner.vifel_multiple_pallet_support
                    else self.env['stock.move.line']):
            pkg = sib.result_package_id
            if not pkg or sib in own_lines or pkg.id in seen_pkgs:
                continue
            grp = siblings.setdefault(pkg.id, {
                'package': pkg, 'psis': set(), 'products': [],
                'product_ids': set(), 'location': sib.location_dest_id,
                'weight': 0.0, 'quantity': 0.0})
            if sib.x_studio_pallet_series_id:
                grp['psis'].add(sib.x_studio_pallet_series_id)
            if sib.product_id and sib.product_id.id not in grp['product_ids']:
                grp['product_ids'].add(sib.product_id.id)
                grp['products'].append(sib.product_id.display_name)
            grp['weight'] += sib.quantity or 0.0
            grp['quantity'] += sib.x_studio_2nd_uom or 0.0

        # ALSO: pallets started on OTHER rows of the SAME Magic Wizard session
        # that are NOT yet written to the real move lines (a STAGED create-special
        # / merge — applied only on the session's Confirm). Without this, a
        # Multi-PSI pallet just created inside the Magic Wizard would not appear
        # as a join target for the other rows until the whole session confirmed.
        # Skip any pallet already carried by a real move line (handled above) so
        # its figures are not double-counted.
        if partner.vifel_multiple_pallet_support:
            fe_rows = self._fast_encode_rows()
            if fe_rows:
                real_pkg_ids = set(
                    self.picking_id.move_line_ids.mapped('result_package_id').ids)
                for row in (fe_rows[0].wizard_id.line_ids - fe_rows):
                    pkg = row.result_package_id
                    if (not pkg or pkg.id in seen_pkgs
                            or pkg.id in real_pkg_ids):
                        continue
                    grp = siblings.setdefault(pkg.id, {
                        'package': pkg, 'psis': set(), 'products': [],
                        'product_ids': set(), 'location': row.location_dest_id,
                        'weight': 0.0, 'quantity': 0.0})
                    if row.pallet_series_id:
                        grp['psis'].add(row.pallet_series_id)
                    if row.product_id and row.product_id.id not in grp['product_ids']:
                        grp['product_ids'].add(row.product_id.id)
                        grp['products'].append(row.product_id.display_name)
                    grp['weight'] += row.kilogram or 0.0
                    grp['quantity'] += row.quantity or 0.0

        for pkg_id, grp in siblings.items():
            psis = sorted(grp['psis'])
            # Respect the client's regular-pallet policy: a Multiple client that
            # does not include regular pallets must not be offered a sibling
            # line's ORDINARY receiving pallet (its PSI prefix is the client code,
            # not a special type). Only special-type sibling pallets — the ones a
            # second line actually wants to JOIN — are kept. A pallet with no
            # series yet on this receipt (prefix '') is likewise dropped rather
            # than shown as an ineligible row.
            prefix = psis[0].rpartition('-')[0] if psis else ''
            if not (include_regular or prefix in prefixes):
                continue
            eligible, reason = True, False
            if len(psis) > 1:
                eligible = False
                reason = _('Lines on this receipt gave pallet %s more than '
                           'one Pallet Series (%s) — fix that first.') % (
                    grp['package'].name, ', '.join(psis))
            elif not psis:
                eligible = False
                reason = _('That pallet has no Pallet Series yet on this '
                           'receipt.')
            scored.append(((0 if eligible else 1, 0, psis[0] if psis else ''), {
                'package_id': pkg_id,
                'psi': ', '.join(psis),
                'psi_count': len(psis),
                'product_summary': ', '.join(grp['products'][:3]),
                'location_id': grp['location'].id,
                'weight_kg': grp['weight'],
                'quantity': grp['quantity'],
                'matches_line_product': line_product_id in grp['product_ids'],
                'eligible': eligible,
                'ineligible_reason': reason,
                'is_target': False,
                'on_this_receipt': True,
            }))

        scored.sort(key=lambda s: s[0])
        self.candidate_total = len(scored)
        self.candidates_capped = len(scored) > CANDIDATE_CAP
        rows = [(0, 0, vals) for _key, vals in scored[:CANDIDATE_CAP]]
        self.candidate_line_ids = [(5, 0, 0)] + rows
        eligibles = self.candidate_line_ids.filtered('eligible')
        # a lone eligible candidate is pre-selected (Fixed mode, or a client
        # with exactly one special pallet on the floor)
        if len(eligibles) == 1 and not self.candidates_capped:
            eligibles.is_target = True

    # ------------------------------------------------------------------
    # confirm — dispatch on mode
    # ------------------------------------------------------------------
    def action_back_to_fast_encode(self):
        """Leave without merging, but land back in the Magic Wizard.

        The plain Cancel button would close this dialog and leave nothing
        behind — the encoder's whole Fast Encode session would vanish because
        opening this dialog replaced it.
        """
        self.ensure_one()
        fe_lines = self._fast_encode_rows()
        if not fe_lines:
            return {'type': 'ir.actions.act_window_close'}
        return fe_lines[0]._reopen_fast_encode_list()

    def _fast_encode_rows(self):
        """The Magic Wizard transient rows this wizard is acting on."""
        FeLine = self.env['stock.move.line.fast_encode_rr.line']
        rows = self.fast_encode_line_ids
        if not rows and self.fast_encode_line_id:
            rows = FeLine.browse(self.fast_encode_line_id)
        return rows.exists()

    def action_confirm(self):
        self.ensure_one()
        if self._fast_encode_rows():
            # Inside the Magic Wizard the merge is DEFERRED: resolve the decision
            # here, but STAGE it onto the transient row(s) and leave the REAL
            # move line untouched. It is applied to the real line only at the
            # Magic Wizard's own Confirm (FastEncodeRR.action_confirm ->
            # _vifel_apply_staged_merge), so closing the Magic Wizard without
            # confirming never persists the merge — mirroring the staged
            # un-merge. NOTHING is written to stock.move.line here.
            return self._stage_merge_on_fast_encode()
        if self.mode == 'new':
            return self._apply_create_special()
        return self._apply_merge()

    # ------------------------------------------------------------------
    # Magic Wizard: STAGE the merge onto the transient rows (deferred write)
    # ------------------------------------------------------------------
    def _stage_merge_on_fast_encode(self):
        """Resolve the merge decision and record it on the Magic Wizard rows,
        WITHOUT touching the real move line(s)."""
        if self.mode == 'new':
            # validate the pickers exactly as the real apply will, then draw the
            # series NOW so the row can show it and Confirm reuses it (a wasted
            # number only if the wizard is cancelled — an accepted trade-off).
            self._check_create_special()
            series = self.psi_type_id.draw_number()
            decision = {'kind': 'create_special',
                        'target': self.new_package_id,
                        'adopted': series,
                        'location': self.new_location_id,
                        'psi_type': self.psi_type_id}
        else:
            resolved, eligible, skipped = self._resolve_merge()
            decision = dict(resolved, psi_type=self.env['vifel.psi.type'])
        for fe in self._fast_encode_rows():
            fe._vifel_stage_merge(decision)
        return self._fast_encode_rows()[0]._reopen_fast_encode_list()

    # ------------------------------------------------------------------
    # merge onto a stocked pallet
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # merge onto a stocked pallet — one target, one or many lines
    # ------------------------------------------------------------------
    def _resolve_merge_target(self):
        """The pallet to merge onto: the manual picker wins over the table."""
        if self.manual_package_id:
            return self.manual_package_id, self.env['pallet.merge.candidate']
        chosen = self.candidate_line_ids.filtered('is_target')
        # Only ONE 'Merge Here' may be active. The UI enforces this, but never
        # merge onto an ambiguous pick server-side — that could silently land on
        # the wrong pallet.
        if len(chosen) > 1:
            raise UserError(_(
                'More than one pallet is marked "Merge Here" (%s). Choose '
                'exactly one target pallet.') % ', '.join(
                    chosen.mapped('psi')))
        candidate = chosen[:1]
        if not candidate:
            raise UserError(_('Pick the pallet to merge onto first.'))
        if not candidate.eligible:
            raise UserError(candidate.ineligible_reason or _(
                'That pallet cannot be a merge target.'))
        return candidate.package_id, candidate

    def _partition_lines_for_merge(self, lines, target):
        """Split the selected lines into those that can merge and those to
        skip, so one stray row never blocks the rest (user ruling)."""
        eligible = self.env['stock.move.line']
        skipped = []
        # The candidate target is owner-scoped to THIS receipt's partner. A
        # line from another receipt could belong to another client, so merging
        # it here would put one owner's goods onto another owner's pallet.
        # Multi-select in either surface only ever spans one receipt; this
        # guards against a crafted selection reaching the server anyway.
        home = self.picking_id
        for line in lines:
            if line.picking_id != home:
                skipped.append((line, _('belongs to another receipt')))
            elif not line.vifel_show_merge_button:
                skipped.append((line, _('not a mergeable line')))
            elif line.is_pallet_merge:
                skipped.append((line, _('already merged')))
            elif line.result_package_id == target:
                skipped.append((line, _('already on that pallet')))
            else:
                eligible |= line
        return eligible, skipped

    def _skipped_note(self, skipped):
        if not skipped:
            return ''
        return _('\nSkipped: ') + ', '.join(
            '#%s (%s)' % (line.x_studio_ or '?', reason)
            for line, reason in skipped)

    def _resolve_merge(self):
        """Resolve the merge decision WITHOUT applying it — the single source of
        truth shared by _apply_merge (Pallet Breakdown) and the Magic Wizard's
        staged merge. Returns (decision, eligible, skipped), where decision is
        {'kind', 'target', 'adopted', 'location'} with kind one of
        'same_receipt' / 'first_stock' / 'merge'. Read-only apart from the
        pinned-pallet row lock (a concurrency guard, safe to take here)."""
        partner = self.partner_id
        target, candidate = self._resolve_merge_target()
        lines = self.move_line_ids or self.move_line_id
        eligible, skipped = self._partition_lines_for_merge(lines, target)
        if not eligible:
            raise UserError(_(
                'None of the selected line(s) can be merged onto %s.%s'
            ) % (target.name, self._skipped_note(skipped)))

        # A pallet started on THIS receipt is not yet on the floor, so a line
        # is joining a pallet this document is itself creating — a mixed
        # pallet, not a merge onto stored stock. It must NOT carry the merge
        # flag: the ledger counts unique pallets per receipt, so the lines
        # together already count exactly one.
        if candidate and candidate.on_this_receipt:
            adopted = (candidate.psi or '').strip()
            if not adopted:
                raise UserError(_(
                    'That pallet has no Pallet Series yet on this receipt.'))
            return ({'kind': 'same_receipt', 'target': target,
                     'adopted': adopted, 'location': candidate.location_id},
                    eligible, skipped)

        quants = self._stocked_quants(target)
        psis = sorted({q.x_studio_pallet_series_id
                       for q in quants if q.x_studio_pallet_series_id})
        if len(psis) > 1:
            raise UserError(_(
                'Pallet %s now carries %d different Pallet Series (%s) — it '
                'must be consolidated to one before it can be a merge target.'
            ) % (target.name, len(psis), ', '.join(psis)))

        # +0 applies ONLY while the target already holds stock (user ruling
        # 2026-07-23). The FIRST stock on the empty pinned pallet BIRTHS the
        # pallet — a plain, unflagged +1 line — because the WR that later
        # exhausts it (minus 1) would otherwise walk the balance negative.
        # But the birth happens exactly ONCE: if another open receipt already
        # claimed the empty pinned pallet, THIS one merges (+0). Lock first so
        # two concurrent confirms serialise on the claim check.
        if not psis:
            self._lock_pinned_pallet(target)
        first_stock = not psis and not self._pinned_pallet_already_claimed(
            target)
        if psis:
            adopted = psis[0]
            target_location = quants[:1].location_id
        else:
            if target != partner.vifel_fixed_package_id \
                    or not (partner.vifel_fixed_psi or '').strip():
                raise UserError(_(
                    'Pallet %s has no stock, so there is no Pallet Series to '
                    'adopt. Merging needs a stocked pallet.') % target.name)
            adopted = partner.vifel_fixed_psi.strip()
            # a claimed-but-empty pinned pallet: adopt the profile PSI (same as
            # the birth), but flagged +0 — the birthing receipt owns the +1
            target_location = self.env['stock.location']

        return ({'kind': 'first_stock' if first_stock else 'merge',
                 'target': target, 'adopted': adopted,
                 'location': target_location}, eligible, skipped)

    def _apply_merge(self):
        decision, eligible, skipped = self._resolve_merge()
        kind = decision['kind']
        target = decision['target']
        adopted = decision['adopted']
        location = decision['location']
        if kind == 'same_receipt':
            for line in eligible:
                self._apply_same_receipt_one(line, target, adopted, location)
            return self._merge_done(eligible, skipped, target, adopted,
                                    kind='same_receipt')
        for line in eligible:
            self._apply_merge_one(line, target, adopted, location,
                                  first_stock=(kind == 'first_stock'))
        return self._merge_done(eligible, skipped, target, adopted, kind=kind)

    def _free_displaced(self, line, old_series, adopted, old_package_id,
                        old_location_id, target):
        """Return the series/pallet/location this line no longer uses."""
        picking = line.picking_id
        partner = self.partner_id
        if old_series and old_series != adopted:
            still_used = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', old_series),
                ('id', '!=', line.id)], limit=1)
            if not still_used:
                partner.with_context(
                    audit_picking_id=picking.id,
                    audit_source='wizard').push_unused_pallet(old_series)
        if old_package_id and old_package_id != target.id:
            line._free_pallet_if_unused(picking.id, old_package_id)
        if old_location_id and old_location_id != line.location_dest_id.id:
            line._free_location_if_unused(picking.id, old_location_id)

    def _apply_merge_one(self, line, target, adopted, target_location,
                         first_stock):
        picking = line.picking_id
        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        vals = {
            'result_package_id': target.id,
            'x_studio_pallet_series_id': adopted,
            'is_pallet_merge': not first_stock,
            # Remember what is being displaced so un-merge restores exactly this
            # — captured for a +0 merge AND for a first-stock birth. A birth line
            # stays UNFLAGGED (is_pallet_merge False, so it still counts +1), but
            # the user placed it with the Merge button, so it must show "Merged"
            # and offer Un-merge like any other merged line. Detection still
            # needs the pallet to be SHARED, so a lone birth line (the pallet's
            # sole owner) reads as a plain line — there is nothing to peel it
            # off. This is what makes several lines birthing one Fixed pallet
            # (M/RR/05300) show as merged instead of looking like plain
            # multi-line encoding.
            'vifel_premerge_captured': True,
            'vifel_premerge_series': old_series or False,
            'vifel_premerge_location_id': old_location_id or False,
        }
        if target_location:
            vals['location_dest_id'] = target_location.id
        line.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)
        self._free_displaced(line, old_series, adopted, old_package_id,
                             old_location_id, target)

        if first_stock:
            if not target.x_studio_is_reserved:
                target.write({'x_studio_is_reserved': True,
                              'x_studio_receiving_report_id': picking.id})
            picking.message_post(body=Markup(_(
                'Line #%s (%s): first stock on pallet <b>%s</b> — Pallet '
                'Series <b>%s</b>. Counted as a received pallet (+1).')) % (
                    line.x_studio_ or '', line.product_id.display_name,
                    target.name, adopted))
        else:
            picking.message_post(body=Markup(_(
                'Line #%s (%s) merged onto pallet <b>%s</b> — adopted Pallet '
                'Series <b>%s</b>%s. The pallet count is not incremented for '
                'this line.')) % (
                    line.x_studio_ or '', line.product_id.display_name,
                    target.name, adopted,
                    _(' at %s') % target_location.complete_name
                    if target_location else ''))

    def _apply_same_receipt_one(self, line, target, adopted, target_location):
        """Join a pallet another line of this same receipt already uses —
        adopt its number/series/location, left UNFLAGGED."""
        picking = line.picking_id
        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        # Left UNFLAGGED on purpose: the pallet is born by THIS receipt, so it
        # is counted +1 once via any of its lines — never flag same-receipt
        # lines or the pallet can drop out of the received count. But capture
        # what this line gave up so it can still be PEELED BACK OFF (un-merged)
        # to its own pallet, exactly like a real merge can.
        vals = {'result_package_id': target.id,
                'x_studio_pallet_series_id': adopted,
                'is_pallet_merge': False,
                'vifel_premerge_captured': True,
                'vifel_premerge_series': old_series or False,
                'vifel_premerge_location_id': old_location_id or False}
        if target_location:
            vals['location_dest_id'] = target_location.id
        line.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)
        self._free_displaced(line, old_series, adopted, old_package_id,
                             old_location_id, target)

        picking.message_post(body=Markup(_(
            'Line #%s (%s) placed on pallet <b>%s</b> (<b>%s</b>) with the '
            'other line(s) of this receipt — one physical pallet, counted '
            'once.')) % (
                line.x_studio_ or '', line.product_id.display_name,
                target.name, adopted))

    def _merge_done(self, eligible, skipped, target, adopted, kind='merge'):
        """One summary toast for the whole pass, per-line chatter above."""
        n = len(eligible)
        if kind == 'first_stock':
            body = _('%(n)d line(s) started pallet %(pallet)s (%(psi)s) — '
                     'counted as a received pallet.')
        elif kind == 'same_receipt':
            body = _('%(n)d line(s) placed on %(pallet)s (%(psi)s), with the '
                     'other line(s) of this receipt.')
        else:
            body = _('%(n)d line(s) merged onto %(pallet)s (%(psi)s). Not '
                     'counted as a new pallet.')
        text = body % {'n': n, 'pallet': target.name, 'psi': adopted}
        return self._done_notification(text + self._skipped_note(skipped))

    def _check_create_special(self):
        """Server-side validation for 'Start a new special pallet' — shared by
        the Pallet Breakdown apply and the Magic Wizard's stage, so both refuse
        the same bad pickers up front. Read-only (raises on invalid)."""
        picking = self.move_line_id.picking_id
        partner = self.partner_id
        if not partner.vifel_multiple_pallet_support:
            raise UserError(_('This client does not use PSI types.'))
        if not (self.psi_type_id and self.new_package_id
                and self.new_location_id):
            raise UserError(_(
                'Pick the PSI type, an empty pallet and a location first.'))

        # The domains above scope the pickers, but a domain is UI-only —
        # re-check server-side so a stale form or an RPC call cannot seat a
        # pallet outside the exact place this receipt is landing.
        #
        # The location must sit UNDER the receipt's destination building/zone
        # (e.g. an M/EX receipt may only seat a new pallet somewhere under
        # M/EX), not merely anywhere in the warehouse. child_of includes the
        # destination itself, which is correct — a receipt aimed straight at a
        # leaf/aisle location may seat there too.
        dest = picking.location_dest_id
        if dest:
            loc = self.new_location_id
            under_dest = self.env['stock.location'].search_count([
                ('id', '=', loc.id), ('id', 'child_of', dest.id)])
            if not under_dest:
                raise UserError(_(
                    'Location %(loc)s is not inside %(dest)s, where this '
                    'receipt is landing. Pick a location under %(dest)s.') % {
                        'loc': loc.complete_name,
                        'dest': dest.complete_name})

        # A new special pallet cannot reuse a pallet or (non-aisle) location that
        # another line of THIS receipt already claimed — that would put two
        # Pallet Series on one pallet, or two pallets in one bin. Read the SAME
        # computed sets the pickers exclude, so a stale form / RPC cannot reuse a
        # pallet/location taken either on the Pallet Breakdown OR in a sibling
        # Magic Wizard row (domains are UI-only; this is the server backstop).
        if self.new_package_id in self.vifel_receipt_used_package_ids:
            raise UserError(_(
                'Pallet %s is already used by another line of this receipt. '
                'A new special pallet needs a fresh, empty pallet — or use '
                'Merge Pallet to place this line on it instead.')
                % self.new_package_id.name)
        if self.new_location_id in self.vifel_receipt_used_location_ids:
            raise UserError(_(
                'Location %s already holds another pallet from this receipt. '
                'Pick a free location for the new pallet.')
                % self.new_location_id.complete_name)
        warehouse = self.warehouse_id
        if warehouse:
            pkg_wh = self.new_package_id.x_studio_warehouse
            if pkg_wh and pkg_wh != warehouse:
                raise UserError(_(
                    'Pallet %(pkg)s belongs to %(other)s, but this receipt is '
                    'for %(here)s. Pick a pallet in %(here)s.') % {
                        'pkg': self.new_package_id.name,
                        'other': pkg_wh.name, 'here': warehouse.name})

    def _apply_create_special(self, preassigned_series=None):
        """Start a new special pallet. ``preassigned_series`` lets the Magic
        Wizard's staged-merge Confirm reuse the series ALREADY drawn at stage
        time (so it is not drawn twice); the Pallet Breakdown path passes None
        and draws fresh here as before."""
        line = self.move_line_id
        picking = line.picking_id
        self._check_create_special()

        series = preassigned_series or self.psi_type_id.draw_number()
        target = self.new_package_id

        # one series, one new pallet — every selected line lands on it (one
        # unique package per RR, so the ledger counts it once). Only lines
        # that can actually take a new pallet participate.
        lines = self.move_line_ids or self.move_line_id
        eligible, skipped = self._partition_lines_for_merge(lines, target)
        if not eligible:
            raise UserError(_(
                'None of the selected line(s) can start a new pallet.%s'
            ) % self._skipped_note(skipped))

        # standard receiving reservations apply to a NEW pallet
        if not target.x_studio_is_reserved:
            target.write({'x_studio_is_reserved': True,
                          'x_studio_receiving_report_id': picking.id})
        if not self.new_location_id.x_studio_is_reserved:
            self.new_location_id.write({
                'x_studio_is_reserved': True,
                'x_studio_receiving_report_id': picking.id})

        for line in eligible:
            old_series = line.x_studio_pallet_series_id or ''
            old_package_id = line.result_package_id.id
            old_location_id = line.location_dest_id.id
            # A new pallet on the floor, counted +1 (is_pallet_merge stays
            # False). But it was placed with the Merge Pallet button, so CAPTURE
            # its pre-merge state — exactly like a first-stock birth — so it
            # shows "Merged" and offers Un-merge and can be REVERTED, even as the
            # sole line on the pallet. Un-merge restores this original series
            # if still free and frees the new pallet; the drawn special series
            # is never recycled (the detach's recycle guard).
            line.with_context(skip_pallet_series_sync=True).write({
                'result_package_id': target.id,
                'x_studio_pallet_series_id': series,
                'location_dest_id': self.new_location_id.id,
                'is_pallet_merge': False,
                'vifel_premerge_captured': True,
                'vifel_premerge_series': old_series or False,
                'vifel_premerge_location_id': old_location_id or False,
            })
            self._free_displaced(line, old_series, series, old_package_id,
                                 old_location_id, target)
            picking.message_post(body=Markup(_(
                'Line #%s (%s): new special pallet <b>%s</b> started with '
                'Pallet Series <b>%s</b> at %s.')) % (
                    line.x_studio_ or '', line.product_id.display_name,
                    target.name, series,
                    self.new_location_id.complete_name))
        return self._done_notification(
            _('New special pallet %(pallet)s started (%(psi)s) with '
              '%(n)d line(s).') % {
                'pallet': target.name, 'psi': series, 'n': len(eligible)}
            + self._skipped_note(skipped))

    # ------------------------------------------------------------------
    def _done_notification(self, message):
        """Close the dialog AND tell the user it worked, then refresh the
        Pallet Breakdown behind it so the Merged flag shows at once."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pallet merge'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
