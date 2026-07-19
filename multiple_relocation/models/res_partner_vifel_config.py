# -*- coding: utf-8 -*-
"""Client profile: VIFEL Configuration (Client-Specific Requirement Enh.).

Checkbox cascade on the Contact form, everything OFF by default:

    Can Merge Pallets                (master switch)
      └─ Multiple Pallet Support     (mode switch, exclusive)
           OFF  -> Fixed Merge Pallet: one pinned pallet + PSI offered
                   forever (Wonder Meats: R 5666 / WMF-00230)
           ON   -> PSI Types table (special series per prefix)
           └─ Include Regular Pallets (widens the merge candidates)
    Show Lot No.                     (independent of merging)
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .vifel_psi_type import SEED_PREFIXES


class ResPartnerVifelConfig(models.Model):
    _inherit = 'res.partner'

    vifel_can_merge_pallets = fields.Boolean(
        string='Can Merge Pallets', default=False,
        help='Master switch: incoming pallet lines of this client may be '
             'merged onto an existing stocked pallet.')
    vifel_multiple_pallet_support = fields.Boolean(
        string='Multiple Pallet Support', default=False,
        help='ON: the client works with special PSI types (table below). '
             'OFF: a single fixed merge pallet is offered forever.')
    vifel_include_regular_pallets = fields.Boolean(
        string='Include Regular Pallets', default=False,
        help='Also offer the client\'s regular stocked pallets as merge '
             'targets, next to the special-type ones.')
    vifel_show_lot_no = fields.Boolean(
        string='Show Lot No.', default=False,
        help='Show the client Lot No. column on this client\'s transfer '
             'lines and stock.')
    vifel_fixed_package_id = fields.Many2one(
        'stock.quant.package', string='Fixed Merge Pallet',
        help='The one pallet always offered as merge target (Fixed mode).')
    vifel_fixed_psi = fields.Char(
        string='Fixed Merge PSI',
        help='PSI adopted when merging onto the fixed pallet while it '
             'carries no stock yet.')
    vifel_psi_type_ids = fields.One2many(
        'vifel.psi.type', 'partner_id', string='PSI Types')

    @api.constrains('vifel_fixed_package_id', 'vifel_fixed_psi')
    def _check_vifel_fixed_pair(self):
        """Fixed pallet and fixed PSI go together — a pinned pallet without
        a PSI dead-ends the merge of an empty target, a PSI without a
        pallet anchors nothing."""
        for partner in self:
            if bool(partner.vifel_fixed_package_id) != bool(
                    (partner.vifel_fixed_psi or '').strip()):
                raise ValidationError(_(
                    'Fixed Merge Pallet and Fixed Merge PSI must be set '
                    'together (or both left empty) — one without the other '
                    'cannot anchor a merge.'))

    # ------------------------------------------------------------------
    # seeding — in create/write, NOT onchange, so it also covers imports
    # and server-side writes
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered('vifel_multiple_pallet_support')._vifel_seed_psi_types()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if vals.get('vifel_multiple_pallet_support'):
            self._vifel_seed_psi_types()
        return res

    def _vifel_seed_psi_types(self):
        """Create the standard special types this client does not have yet
        (idempotent — re-flipping the switch never duplicates rows)."""
        PsiType = self.env['vifel.psi.type']
        for partner in self:
            existing = set(partner.vifel_psi_type_ids.mapped('prefix'))
            PsiType.create([
                {'partner_id': partner.id, 'name': prefix, 'prefix': prefix}
                for prefix in SEED_PREFIXES if prefix not in existing
            ])
