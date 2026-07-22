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
    source_label = fields.Char(string='Where', compute='_compute_source_label')

    @api.depends('on_this_receipt')
    def _compute_source_label(self):
        for cand in self:
            cand.source_label = _('On this receipt') if cand.on_this_receipt \
                else _('In storage')

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
    line_weight = fields.Float(
        related='move_line_id.quantity', string='Line Weight (KG)')
    line_quantity = fields.Float(
        related='move_line_id.x_studio_2nd_uom', string='Line Quantity')

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
    warn_different_product = fields.Boolean(compute='_compute_selection')

    # One line describing what is being merged. A computed string rather than
    # a field group on purpose: four related fields in a group rendered as
    # three rows of labels with help icons, and pushed the Weight value into a
    # column so narrow it wrapped vertically ("0." / "00" / "0"). The encoder
    # needs to read this at a glance, not fill it in.
    line_summary = fields.Char(compute='_compute_line_summary')

    @api.depends('move_line_id')
    def _compute_line_summary(self):
        for wizard in self:
            line = wizard.move_line_id
            bits = []
            if line.x_studio_:
                bits.append(_('Line %s') % line.x_studio_)
            # product deliberately omitted — the dialog title already names it
            bits.append(_('%.3f KG') % (line.quantity or 0.0))
            bits.append(_('%g Quantity') % (line.x_studio_2nd_uom or 0.0))
            if line.x_studio_pallet_series_id:
                bits.append(_('now on %s') % line.x_studio_pallet_series_id)
            wizard.line_summary = '   ·   '.join(bits)

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

    new_package_id = fields.Many2one(
        'stock.quant.package', string='New Empty Pallet',
        domain="[('location_id', '=', False), "
               "('package_type_id.name', '=', 'Pallet'), "
               "('x_studio_active', '=', True), "
               "('x_studio_warehouse', '=', warehouse_id), "
               "'|', ('x_studio_receiving_report_id', '=', False), "
               "('x_studio_receiving_report_id', '=', picking_id)]")
    new_location_id = fields.Many2one(
        'stock.location', string='New Location',
        domain="[('usage', '=', 'internal'), "
               "('warehouse_id', '=', warehouse_id), "
               "('x_studio_is_a_blast_freezer', '!=', True), "
               "'|', ('x_studio_is_an_aisle', '=', True), "
               "'&', ('child_ids', '=', False), "
               "('x_studio_occupied_by_1', '=', False), "
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
            wizard.warn_different_product = bool(
                selected and not selected.matches_line_product)

    # ------------------------------------------------------------------
    # candidate materialisation (once, at create)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._populate_candidates()
        return wizards

    def _stocked_quants(self, package):
        return package.quant_ids.filtered(
            lambda q: q.quantity > 0 and q.location_id.usage == 'internal')

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
                - wizard.move_line_id.result_package_id

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
        packages = self._candidate_packages() \
            - self.move_line_id.result_package_id
        prefixes = set(partner.vifel_psi_type_ids.mapped('prefix'))
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
            eligible, reason = True, False
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
        seen_pkgs = set(packages.ids) | {self.move_line_id.result_package_id.id}
        siblings = {}
        for sib in (self.picking_id.move_line_ids
                    if partner.vifel_multiple_pallet_support
                    else self.env['stock.move.line']):
            pkg = sib.result_package_id
            if not pkg or sib == self.move_line_id or pkg.id in seen_pkgs:
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

        for pkg_id, grp in siblings.items():
            psis = sorted(grp['psis'])
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
        fe_line = self.env['stock.move.line.fast_encode_rr.line'].browse(
            self.fast_encode_line_id)
        if not fe_line.exists():
            return {'type': 'ir.actions.act_window_close'}
        return fe_line._reopen_fast_encode_list()

    def action_confirm(self):
        self.ensure_one()
        fe_line_id = self.fast_encode_line_id \
            or self.env.context.get('fast_encode_line_id')
        if fe_line_id:
            # inside the Magic Wizard: only merge-onto-stocked is offered.
            # Apply to the REAL line now (Phase B logic, unchanged), then
            # sync the transient row so the Magic Wizard's already-verified
            # deferred confirm keeps the merge, and reload the list.
            self._apply_merge()
            return self._sync_fast_encode_and_reopen(fe_line_id)
        if self.mode == 'new':
            return self._apply_create_special()
        return self._apply_merge()

    def _sync_fast_encode_and_reopen(self, fe_line_id):
        """Push the just-applied merge onto its Magic Wizard transient row
        and reopen the list, so the two representations never diverge."""
        line = self.move_line_id
        fe_line = self.env['stock.move.line.fast_encode_rr.line'].browse(
            fe_line_id)
        if not fe_line.exists():
            return {'type': 'ir.actions.act_window_close'}
        fe_line._vifel_sync_from_move_line(line)
        return fe_line._reopen_fast_encode_list()

    # ------------------------------------------------------------------
    # merge onto a stocked pallet
    # ------------------------------------------------------------------
    def _apply_merge(self):
        line = self.move_line_id
        picking = line.picking_id
        partner = self.partner_id
        # the manual Pallet # picker (shown when the list is capped) wins over
        # a table selection; otherwise use the checked row
        candidate = self.env['pallet.merge.candidate']
        if self.manual_package_id:
            target = self.manual_package_id
        else:
            candidate = self.candidate_line_ids.filtered('is_target')[:1]
            if not candidate:
                raise UserError(_('Pick the pallet to merge onto first.'))
            if not candidate.eligible:
                raise UserError(candidate.ineligible_reason or _(
                    'That pallet cannot be a merge target.'))
            target = candidate.package_id

        # A pallet started on THIS receipt is not yet on the floor, so the
        # line is joining a pallet this document is itself creating — a mixed
        # pallet, not a merge onto stored stock. It must NOT carry the merge
        # flag: the ledger counts unique pallets per receipt, so both lines
        # together already count exactly one. Flagging it would mean that
        # deleting the line which created the pallet leaves the pallet counted
        # ZERO, undercounting a pallet that physically exists.
        if candidate and candidate.on_this_receipt:
            return self._apply_same_receipt(candidate)
        if target == line.result_package_id:
            raise UserError(_('The line is already on that pallet.'))
        quants = self._stocked_quants(target)
        psis = sorted({q.x_studio_pallet_series_id
                       for q in quants if q.x_studio_pallet_series_id})
        if len(psis) > 1:
            # defence in depth: the row was marked ineligible, but state may
            # have moved since the wizard opened
            raise UserError(_(
                'Pallet %s now carries %d different Pallet Series (%s) — it '
                'must be consolidated to one before it can be a merge target.'
            ) % (target.name, len(psis), ', '.join(psis)))
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
            target_location = self.env['stock.location']

        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        vals = {
            'result_package_id': target.id,
            'x_studio_pallet_series_id': adopted,
            'is_pallet_merge': True,
        }
        if target_location:
            vals['location_dest_id'] = target_location.id
        # skip_pallet_series_sync: keep the repallet-sync machinery out of an
        # intentional merge; vifel_pallet_merge marks the write so the
        # un-merge detector does not treat it as an un-merge. The stocked
        # target is deliberately NOT stamped with reservation fields — it is
        # occupied, not reserved.
        line.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)

        # the series drawn earlier for this line goes back to its pool,
        # unless another line of this RR still uses it
        if old_series and old_series != adopted:
            still_used = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', old_series),
                ('id', '!=', line.id),
            ], limit=1)
            if not still_used:
                partner.with_context(
                    audit_picking_id=picking.id,
                    audit_source='wizard').push_unused_pallet(old_series)

        # the empty pallet / location reserved earlier are free again
        if old_package_id and old_package_id != target.id:
            line._free_pallet_if_unused(picking.id, old_package_id)
        if old_location_id and old_location_id != line.location_dest_id.id:
            line._free_location_if_unused(picking.id, old_location_id)

        picking.message_post(body=_(
            'Line #%s (%s) merged onto pallet <b>%s</b> — adopted Pallet '
            'Series <b>%s</b>%s. The pallet count is not incremented for '
            'this line.') % (
                line.x_studio_ or '', line.product_id.display_name,
                target.name, adopted,
                _(' at %s') % target_location.complete_name
                if target_location else ''))
        return self._done_notification(_(
            'Line #%(num)s merged onto %(pallet)s (%(psi)s). '
            'Not counted as a new pallet.') % {
                'num': line.x_studio_ or '', 'pallet': target.name,
                'psi': adopted})

    def _apply_same_receipt(self, candidate):
        """Join a pallet another line of this same receipt already uses.

        The line takes that pallet's number, series and location so the house
        rule holds (same series = same pallet = same location), but it is left
        UNFLAGGED — see the note in _apply_merge for why flagging would risk
        an undercount.
        """
        line = self.move_line_id
        picking = line.picking_id
        partner = self.partner_id
        target = candidate.package_id
        adopted = (candidate.psi or '').strip()
        if not adopted:
            raise UserError(_(
                'That pallet has no Pallet Series yet on this receipt.'))

        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        vals = {'result_package_id': target.id,
                'x_studio_pallet_series_id': adopted,
                'is_pallet_merge': False}
        if candidate.location_id:
            vals['location_dest_id'] = candidate.location_id.id
        line.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)

        # the series this line had drawn is free again, unless another line
        # of this receipt still uses it
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

        picking.message_post(body=_(
            'Line #%s (%s) placed on pallet <b>%s</b> (<b>%s</b>) together '
            'with the other line(s) of this receipt — one physical pallet, '
            'counted once.') % (
                line.x_studio_ or '', line.product_id.display_name,
                target.name, adopted))
        return self._done_notification(_(
            'Line #%(num)s placed on %(pallet)s (%(psi)s), together with the '
            'other line(s) of this receipt.') % {
                'num': line.x_studio_ or '', 'pallet': target.name,
                'psi': adopted})

    # ------------------------------------------------------------------
    # create a new special pallet (Multiple mode)
    # ------------------------------------------------------------------
    def _apply_create_special(self):
        line = self.move_line_id
        picking = line.picking_id
        partner = self.partner_id
        if not partner.vifel_multiple_pallet_support:
            raise UserError(_('This client does not use PSI types.'))
        if not (self.psi_type_id and self.new_package_id
                and self.new_location_id):
            raise UserError(_(
                'Pick the PSI type, an empty pallet and a location first.'))

        # The domains above scope the pickers, but a domain is UI-only —
        # re-check server-side so a stale form or an RPC call cannot seat a
        # pallet in a different warehouse from the one receiving it.
        warehouse = self.warehouse_id
        if warehouse:
            loc_wh = self.new_location_id.warehouse_id
            if loc_wh and loc_wh != warehouse:
                raise UserError(_(
                    'Location %(loc)s belongs to %(other)s, but this receipt '
                    'is for %(here)s. Pick a location in %(here)s.') % {
                        'loc': self.new_location_id.complete_name,
                        'other': loc_wh.name, 'here': warehouse.name})
            pkg_wh = self.new_package_id.x_studio_warehouse
            if pkg_wh and pkg_wh != warehouse:
                raise UserError(_(
                    'Pallet %(pkg)s belongs to %(other)s, but this receipt is '
                    'for %(here)s. Pick a pallet in %(here)s.') % {
                        'pkg': self.new_package_id.name,
                        'other': pkg_wh.name, 'here': warehouse.name})

        series = self.psi_type_id.draw_number()
        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        # a plain line: a new pallet on the floor, counted +1
        line.with_context(skip_pallet_series_sync=True).write({
            'result_package_id': self.new_package_id.id,
            'x_studio_pallet_series_id': series,
            'location_dest_id': self.new_location_id.id,
            'is_pallet_merge': False,
        })

        # standard receiving reservations apply to a NEW pallet
        if not self.new_package_id.x_studio_is_reserved:
            self.new_package_id.write({
                'x_studio_is_reserved': True,
                'x_studio_receiving_report_id': picking.id,
            })
        if not self.new_location_id.x_studio_is_reserved:
            self.new_location_id.write({
                'x_studio_is_reserved': True,
                'x_studio_receiving_report_id': picking.id,
            })

        if old_series and old_series != series:
            still_used = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', old_series),
                ('id', '!=', line.id),
            ], limit=1)
            if not still_used:
                partner.with_context(
                    audit_picking_id=picking.id,
                    audit_source='wizard').push_unused_pallet(old_series)
        if old_package_id and old_package_id != self.new_package_id.id:
            line._free_pallet_if_unused(picking.id, old_package_id)
        if old_location_id and old_location_id != self.new_location_id.id:
            line._free_location_if_unused(picking.id, old_location_id)

        picking.message_post(body=_(
            'Line #%s (%s): new special pallet <b>%s</b> started with Pallet '
            'Series <b>%s</b> at %s.') % (
                line.x_studio_ or '', line.product_id.display_name,
                self.new_package_id.name, series,
                self.new_location_id.complete_name))
        return self._done_notification(_(
            'New special pallet %(pallet)s started (%(psi)s).') % {
                'pallet': self.new_package_id.name, 'psi': series})

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
