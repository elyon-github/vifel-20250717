# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    # THE multi-warehouse mechanism: assign warehouses here and the GLOBAL
    # record rules (security/multi_warehouse_rules.xml) filter every scoped
    # model to these warehouses. Leave EMPTY for full, unrestricted access
    # (admins, back-office). No groups involved.
    allowed_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'res_users_allowed_warehouse_rel', 'user_id', 'warehouse_id',
        string='Allowed Warehouses',
        help='Warehouses this user may see and work in. '
             'LEAVE EMPTY FOR FULL ACCESS to all warehouses.')

    default_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Default Warehouse',
        help='Pre-selected warehouse in forms and report wizards. '
             'Must be one of the Allowed Warehouses (when those are set).')

    @api.constrains('allowed_warehouse_ids', 'default_warehouse_id')
    def _check_default_in_allowed(self):
        for user in self:
            if (user.default_warehouse_id and user.allowed_warehouse_ids
                    and user.default_warehouse_id not in user.allowed_warehouse_ids):
                raise ValidationError(
                    "The default warehouse (%s) must be one of the user's "
                    "allowed warehouses." % user.default_warehouse_id.display_name)
