# -*- coding: utf-8 -*-
"""Pallet Merge wizard (Client-Specific Requirement Enhancement).

Merges one incoming Pallet Breakdown line onto a pallet that is already
stocked: the line adopts the target's PSI and location and is flagged
is_pallet_merge so the ledger does not count a new pallet.

Two client modes (profile-driven):
  Fixed    — the profile pins ONE pallet + PSI, offered forever
             (Wonder Meats: R 5666 / WMF-00230).
  Multiple — stocked pallets whose PSI prefix belongs to the client's
             PSI types; regular stocked pallets widen the list when
             Include Regular Pallets is on, or stand in entirely when
             the client has no types. This mode can also CREATE a new
             special pallet: draw a series from a type and place it on
             an empty pallet — a plain line, counted +1.

"Is the target full" is the Documentation Staff's judgment — the window
shows the target's PSI / location / KG / quantity, no capacity rule.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class PalletMergeWizard(models.TransientModel):
    _name = 'pallet.merge.wizard'
    _description = 'Merge an incoming line onto a stocked pallet'

    move_line_id = fields.Many2one(
        'stock.move.line', required=True, ondelete='cascade',
        string='Pallet Line')
    picking_id = fields.Many2one(
        related='move_line_id.picking_id')
    partner_id = fields.Many2one(
        related='move_line_id.picking_id.partner_id', string='Client')
    is_multiple_mode = fields.Boolean(
        related='partner_id.vifel_multiple_pallet_support')
    line_psi = fields.Char(
        related='move_line_id.x_studio_pallet_series_id',
        string='Line PSI (current)')

    allowed_package_ids = fields.Many2many(
        'stock.quant.package', compute='_compute_allowed_package_ids')
    target_package_id = fields.Many2one(
        'stock.quant.package', string='Merge Onto Pallet',
        domain="[('id', 'in', allowed_package_ids)]")

    # what the Documentation Staff judges "full" by
    target_psi = fields.Char(compute='_compute_target_info', string='Target PSI')
    target_location_id = fields.Many2one(
        'stock.location', compute='_compute_target_info', string='Target Location')
    target_kg = fields.Float(
        compute='_compute_target_info', string='Target Weight (KG)',
        digits=(12, 3))
    target_qty = fields.Float(
        compute='_compute_target_info', string='Target Quantity')
    target_psi_count = fields.Integer(compute='_compute_target_info')

    # create-new-special path (Multiple mode)
    psi_type_id = fields.Many2one(
        'vifel.psi.type', string='PSI Type',
        domain="[('partner_id', '=', partner_id)]")
    new_package_id = fields.Many2one(
        'stock.quant.package', string='New Empty Pallet',
        domain="[('location_id', '=', False), "
               "('package_type_id.name', '=', 'Pallet'), "
               "('x_studio_active', '=', True), "
               "'|', ('x_studio_receiving_report_id', '=', False), "
               "('x_studio_receiving_report_id', '=', picking_id)]")
    new_location_id = fields.Many2one(
        'stock.location', string='New Location',
        domain="[('usage', '=', 'internal'), "
               "('x_studio_is_a_blast_freezer', '!=', True), "
               "'|', ('x_studio_is_an_aisle', '=', True), "
               "'&', ('child_ids', '=', False), "
               "('x_studio_occupied_by_1', '=', False), "
               "'|', ('x_studio_receiving_report_id', '=', False), "
               "('x_studio_receiving_report_id', '=', picking_id)]")

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        # Fixed mode: the pinned pallet IS the target — pre-select it
        for wizard in wizards:
            partner = wizard.partner_id
            if (not wizard.target_package_id
                    and partner.vifel_can_merge_pallets
                    and not partner.vifel_multiple_pallet_support):
                wizard.target_package_id = partner.vifel_fixed_package_id
        return wizards

    # ------------------------------------------------------------------
    # candidates
    # ------------------------------------------------------------------
    def _stocked_quants(self, package):
        return package.quant_ids.filtered(
            lambda q: q.quantity > 0 and q.location_id.usage == 'internal')

    @api.depends('move_line_id')
    def _compute_allowed_package_ids(self):
        Quant = self.env['stock.quant']
        for wizard in self:
            partner = wizard.partner_id
            if not partner.vifel_can_merge_pallets:
                wizard.allowed_package_ids = False
                continue
            if not partner.vifel_multiple_pallet_support:
                wizard.allowed_package_ids = partner.vifel_fixed_package_id
                continue
            warehouse = wizard.picking_id.picking_type_id.warehouse_id
            quants = Quant.search([
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
            # Regular pallets join the list when asked to — or stand in
            # entirely when the client has no special types at all. The
            # quants are already owner-scoped, so "regular" is simply any
            # stocked pallet of the client: NOT matched against the client
            # code, because a code change leaves legacy-prefix stock (e.g.
            # BGZ-... pallets of a client whose code is now BG) that is
            # every bit as mergeable.
            include_regular = partner.vifel_include_regular_pallets or not prefixes
            packages = self.env['stock.quant.package']
            for quant in quants:
                prefix = (quant.x_studio_pallet_series_id or '').rpartition('-')[0]
                if include_regular or prefix in prefixes:
                    packages |= quant.package_id
            wizard.allowed_package_ids = packages

    @api.depends('target_package_id')
    def _compute_target_info(self):
        for wizard in self:
            quants = wizard._stocked_quants(wizard.target_package_id) \
                if wizard.target_package_id else self.env['stock.quant']
            psis = sorted({q.x_studio_pallet_series_id
                           for q in quants if q.x_studio_pallet_series_id})
            partner = wizard.partner_id
            if not psis and wizard.target_package_id \
                    and wizard.target_package_id == partner.vifel_fixed_package_id:
                # pinned pallet with no stock yet: profile PSI stands in
                wizard.target_psi = '%s (empty pallet)' % (
                    partner.vifel_fixed_psi or '')
            else:
                wizard.target_psi = ', '.join(psis)
            wizard.target_psi_count = len(psis)
            wizard.target_location_id = quants[:1].location_id
            wizard.target_kg = sum(quants.mapped('quantity'))
            wizard.target_qty = sum(quants.mapped('x_studio_2nd_uom'))

    # ------------------------------------------------------------------
    # merge
    # ------------------------------------------------------------------
    def action_confirm(self):
        self.ensure_one()
        line = self.move_line_id
        picking = line.picking_id
        partner = self.partner_id
        target = self.target_package_id
        if not target:
            raise UserError('Pick the pallet to merge onto first.')
        if target == line.result_package_id:
            raise UserError('The line is already on that pallet.')

        quants = self._stocked_quants(target)
        psis = sorted({q.x_studio_pallet_series_id
                       for q in quants if q.x_studio_pallet_series_id})
        if len(psis) > 1:
            raise UserError(
                'Pallet %s carries %d different Pallet Series (%s) — it '
                'must be consolidated to one PSI before it can be a merge '
                'target.' % (target.name, len(psis), ', '.join(psis)))
        if psis:
            adopted = psis[0]
            target_location = quants[:1].location_id
        else:
            # an empty target is only meaningful for the pinned fixed
            # pallet, whose profile PSI stands in
            if target != partner.vifel_fixed_package_id \
                    or not (partner.vifel_fixed_psi or '').strip():
                raise UserError(
                    'Pallet %s has no stock, so there is no PSI to adopt. '
                    'Merging needs a stocked pallet.' % target.name)
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
        # skip_pallet_series_sync: the sync machinery would treat this as
        # a plain repallet and re-sync/recycle on its own terms;
        # vifel_pallet_merge marks the write as intentional for un-merge
        # detection. The stocked target is deliberately NOT stamped with
        # reservation fields — it is occupied, not reserved.
        line.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)

        # the series drawn earlier for this line goes back to its pool —
        # unless another line of this RR still uses it
        if old_series and old_series != adopted:
            still_used = self.env['stock.move.line'].search([
                ('picking_id', '=', picking.id),
                ('x_studio_pallet_series_id', '=', old_series),
                ('id', '!=', line.id),
            ], limit=1)
            if not still_used:
                partner.push_unused_pallet(old_series)

        # the empty pallet / location reserved earlier are free again
        if old_package_id and old_package_id != target.id:
            line._free_pallet_if_unused(picking.id, old_package_id)
        if old_location_id and old_location_id != line.location_dest_id.id:
            line._free_location_if_unused(picking.id, old_location_id)

        picking.message_post(body=(
            'Line #%s (%s) merged onto pallet <b>%s</b> — adopted PSI '
            '<b>%s</b>%s. The pallet count is not incremented for this '
            'line.' % (
                line.x_studio_ or '', line.product_id.display_name,
                target.name, adopted,
                ' at %s' % target_location.complete_name
                if target_location else '')))
        return {'type': 'ir.actions.act_window_close'}

    # ------------------------------------------------------------------
    # create a new special pallet (Multiple mode; first-of-type or
    # current one judged full)
    # ------------------------------------------------------------------
    def action_create_special(self):
        self.ensure_one()
        line = self.move_line_id
        picking = line.picking_id
        partner = self.partner_id
        if not partner.vifel_multiple_pallet_support:
            raise UserError('This client does not use PSI types.')
        if not (self.psi_type_id and self.new_package_id
                and self.new_location_id):
            raise UserError(
                'Pick the PSI type, an empty pallet and a location first.')

        series = self.psi_type_id.draw_number()
        old_series = line.x_studio_pallet_series_id or ''
        old_package_id = line.result_package_id.id
        old_location_id = line.location_dest_id.id

        # a plain line: new pallet on the floor, counted +1
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
                partner.push_unused_pallet(old_series)
        if old_package_id and old_package_id != self.new_package_id.id:
            line._free_pallet_if_unused(picking.id, old_package_id)
        if old_location_id and old_location_id != self.new_location_id.id:
            line._free_location_if_unused(picking.id, old_location_id)

        picking.message_post(body=(
            'Line #%s (%s): new special pallet <b>%s</b> started with PSI '
            '<b>%s</b> at %s.' % (
                line.x_studio_ or '', line.product_id.display_name,
                self.new_package_id.name, series,
                self.new_location_id.complete_name)))
        return {'type': 'ir.actions.act_window_close'}
