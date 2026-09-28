# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Team request 2026-09-28: the noting account picks which Inventory
    # Analysts the documentation staff may choose as NOTED BY. Set from the
    # transfer's Configuration tab (stock.picking.vifel_noted_by_option_ids).
    vifel_noted_by_option = fields.Boolean(
        string="Noted By Option", copy=False,
        help="Offered in Noted By on transfers (Deviation Report).")
