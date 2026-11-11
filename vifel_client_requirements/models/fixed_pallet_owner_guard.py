# -*- coding: utf-8 -*-
"""Keep a client's pinned Fixed Merge Pallet for that client only.

A pinned pallet is reserved (x_studio_is_reserved), but an inventory
adjustment / opening-balance upload does not look at that flag. On 2026-09-14
the CMA MEAT INC. opening balance placed CMA stock (CM-86528) on R 5666, the
Fixed Merge Pallet of WONDER MEATS (FG). From then on every Wonder Meat merge
offered R 5666 under CMA's series instead of the configured Fixed Merge PSI.

This guard stops any validated move (receipt, return, upload, adjustment,
repack) from putting goods of ANOTHER client onto a pinned pallet. Moving the
whole pallet (relocation) and taking goods off it (withdrawal) stay allowed,
so stock that is already there can still be moved out.
"""
from odoo import _, models
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _vifel_line_client(self):
        self.ensure_one()
        partner = (self.owner_id or self.picking_id.partner_id
                   or self.move_id.restrict_partner_id)
        return partner.commercial_partner_id if partner else partner

    def _vifel_check_fixed_pallet_owner(self):
        pins = self.env['vifel.fixed.merge.pallet'].sudo().search(
            [('package_id', 'in', self.mapped('result_package_id').ids)])
        if not pins:
            return
        pin_by_package = {pin.package_id.id: pin for pin in pins}
        problems = []
        for line in self:
            pin = pin_by_package.get(line.result_package_id.id)
            if not pin or line.location_dest_id.usage != 'internal':
                continue
            # moving the whole pallet, not putting goods onto it
            if line.package_id == line.result_package_id:
                continue
            client = line._vifel_line_client()
            if not client:
                continue
            if client == pin.partner_id.commercial_partner_id:
                continue
            problems.append(_(
                '- %(product)s of %(client)s cannot go on pallet %(pallet)s: '
                'it is the Fixed Merge Pallet of %(owner)s.') % {
                    'product': line.product_id.display_name,
                    'client': client.display_name,
                    'pallet': line.result_package_id.name,
                    'owner': pin.partner_id.display_name})
        if problems:
            raise UserError(_(
                'A Fixed Merge Pallet can only hold its own client\'s goods.\n'
                '%s\n\nPick a different pallet for these goods.')
                % '\n'.join(problems))

    def _action_done(self):
        self._vifel_check_fixed_pallet_owner()
        return super()._action_done()
