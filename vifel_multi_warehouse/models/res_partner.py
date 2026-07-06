# -*- coding: utf-8 -*-
"""Contact-per-warehouse policy guard-rails.

Policy (confirmed 2026-07-04): a Contact exists in exactly ONE warehouse.
If the same real-world client transacts with another warehouse, a separate
Contact is created there. Consequences enforced here:

1. A client contact (identified by ``x_studio_client_unique_code_1`` — the
   same marker the Studio validation uses) must carry ``x_studio_warehouse``.
2. ``x_studio_warehouse`` is immutable once the contact has transaction
   history (done pickings as partner/owner, or pallet-kilos ledger rows) —
   changing it would orphan that history in the old warehouse.
3. Contacts from different warehouses can never be merged: duplicates by
   name across warehouses are BY DESIGN.

All checks tolerate the Studio fields being absent (bare test databases).
Settings administrators (``base.group_system``) may bypass the immutability
check (needed for deliberate migrations).
"""
from odoo import api, models
from odoo.exceptions import UserError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _vifel_studio_fields_present(self):
        f = self._fields
        return 'x_studio_warehouse' in f and 'x_studio_client_unique_code_1' in f

    def _vifel_has_transaction_history(self):
        """True if this partner has warehouse history that a warehouse change
        would orphan: done pickings (as partner or owner) or PKR ledger rows."""
        self.ensure_one()
        Picking = self.env['stock.picking'].sudo()
        if Picking.search_count([
                ('state', '=', 'done'),
                '|', ('partner_id', '=', self.id), ('owner_id', '=', self.id)],
                limit=1):
            return True
        pkr_model = 'pallet_kilos_record_model.pallet_kilos_record_model'
        if pkr_model in self.env:
            if self.env[pkr_model].sudo().with_context(active_test=False).search_count(
                    [('owner_id', '=', self.id)], limit=1):
                return True
        return False

    # ------------------------------------------------------------------
    # guard 1: client contacts must carry a warehouse
    # ------------------------------------------------------------------
    def _vifel_check_client_warehouse(self):
        if not self._vifel_studio_fields_present():
            return
        for partner in self:
            code = partner.x_studio_client_unique_code_1
            if code and not partner.x_studio_warehouse:
                raise ValidationError(
                    "Client contact '%s' (client code %s) must be assigned a "
                    "warehouse (contact-per-warehouse policy). Set the "
                    "Warehouse field before saving." % (partner.name, code))

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._vifel_check_client_warehouse()
        return partners

    # ------------------------------------------------------------------
    # guard 2: warehouse immutable once history exists
    # ------------------------------------------------------------------
    def write(self, vals):
        if ('x_studio_warehouse' in vals
                and self._vifel_studio_fields_present()
                and not self.env.context.get('bypass_warehouse_immutability')
                and not self.env.user.has_group('base.group_system')):
            new_wh_id = vals['x_studio_warehouse'] or False
            for partner in self:
                old_wh_id = partner.x_studio_warehouse.id or False
                if old_wh_id and new_wh_id != old_wh_id \
                        and partner._vifel_has_transaction_history():
                    raise UserError(
                        "The warehouse of '%s' cannot be changed: this contact "
                        "already has transaction history in %s. Per the "
                        "contact-per-warehouse policy, create a NEW contact for "
                        "the other warehouse instead. (Settings administrators "
                        "may override.)"
                        % (partner.name, partner.x_studio_warehouse.display_name))
        result = super().write(vals)
        if 'x_studio_client_unique_code_1' in vals or 'x_studio_warehouse' in vals:
            self._vifel_check_client_warehouse()
        return result


class MergePartnerAutomatic(models.TransientModel):
    _inherit = 'base.partner.merge.automatic.wizard'

    # ------------------------------------------------------------------
    # guard 3: never merge contacts across warehouses
    # ------------------------------------------------------------------
    def _merge(self, partner_ids, dst_partner=None, extra_checks=True):
        Partner = self.env['res.partner']
        if 'x_studio_warehouse' in Partner._fields:
            partners = Partner.browse(partner_ids).exists()
            warehouses = set()
            for partner in partners:
                if partner.x_studio_warehouse:
                    warehouses.add(partner.x_studio_warehouse.id)
            if len(warehouses) > 1:
                raise UserError(
                    "These contacts belong to different warehouses and must NOT "
                    "be merged: the same client is represented by a separate "
                    "contact in each warehouse (contact-per-warehouse policy).")
        return super()._merge(partner_ids, dst_partner=dst_partner,
                              extra_checks=extra_checks)
