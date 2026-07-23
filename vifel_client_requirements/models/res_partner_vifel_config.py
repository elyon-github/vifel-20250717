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

from .vifel_psi_type import SEED_TYPES


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

    @api.constrains('vifel_fixed_package_id')
    def _check_vifel_fixed_package_owner(self):
        """The pinned pallet must be free, or already hold this client's own
        stock. Pinning a pallet occupied by someone else would offer every
        merge a target full of another client's goods — the domain on the
        field says so, but a domain is UI-only."""
        for partner in self:
            package = partner.vifel_fixed_package_id
            if not package:
                continue
            foreign = package.quant_ids.filtered(
                lambda q: q.quantity > 0 and q.owner_id
                and q.owner_id != partner)
            if foreign and not package.quant_ids.filtered(
                    lambda q: q.quantity > 0 and q.owner_id == partner):
                raise ValidationError(_(
                    'Pallet %(pallet)s is holding stock owned by %(other)s, '
                    'so it cannot be pinned as %(client)s\'s merge pallet. '
                    'Pick a pallet that is empty or already holds '
                    '%(client)s\'s stock.') % {
                        'pallet': package.name,
                        'other': ', '.join(foreign.mapped('owner_id.name')[:3]),
                        'client': partner.display_name})

    @api.model
    def _vifel_fixed_merge_packages(self):
        """Every pallet pinned as some client's Fixed Merge Pallet.

        These are dedicated: the pallet belongs to that client permanently and
        is reached only through the Merge button, which sets flag, series and
        location together. It must therefore never be offered anywhere an
        EMPTY pallet is picked — not even to its own client, and not even
        while it holds no stock.
        """
        return self.sudo().search(
            [('vifel_fixed_package_id', '!=', False)]
        ).mapped('vifel_fixed_package_id')

    def _vifel_mark_fixed_package_reserved(self, packages=None):
        """Hold the pinned pallet reserved, stock or no stock.

        Without this the pallet reads as a free empty pallet the moment it is
        emptied, and the next receipt could seat unrelated goods on it. There
        is deliberately NO receiving report attached: it is not reserved FOR a
        document, it is dedicated to a client.
        """
        packages = packages if packages is not None else \
            self.mapped('vifel_fixed_package_id')
        todo = packages.filtered(lambda p: not p.x_studio_is_reserved)
        if todo:
            todo.write({'x_studio_is_reserved': True})

    def _vifel_release_fixed_package(self, packages):
        """Let a pallet go when it stops being anyone's pinned pallet."""
        still_pinned = self._vifel_fixed_merge_packages()
        orphaned = packages - still_pinned
        # only release what is genuinely idle: a pallet holding stock, or one
        # reserved for a live receipt, is not ours to free
        free = orphaned.filtered(
            lambda p: not p.x_studio_receiving_report_id
            and not p.quant_ids.filtered(lambda q: q.quantity > 0))
        if free:
            free.write({'x_studio_is_reserved': False})

    # ------------------------------------------------------------------
    # seeding — in create/write, NOT onchange, so it also covers imports
    # and server-side writes
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered('vifel_multiple_pallet_support')._vifel_seed_psi_types()
        partners._vifel_mark_fixed_package_reserved()
        return partners

    def write(self, vals):
        # snapshot the outgoing pin so a replaced pallet can be released
        previous = self.mapped('vifel_fixed_package_id') \
            if 'vifel_fixed_package_id' in vals \
            else self.env['stock.quant.package']
        res = super().write(vals)
        if vals.get('vifel_multiple_pallet_support'):
            self._vifel_seed_psi_types()
        if 'vifel_fixed_package_id' in vals:
            self._vifel_mark_fixed_package_reserved()
            self._vifel_release_fixed_package(previous)
        return res

    def _vifel_seed_psi_types(self):
        """Create the standard pallet types this client does not have yet
        (idempotent — re-flipping the switch never duplicates rows).

        Also backfills the description on rows that still carry the bare code
        as their name, which is how they were seeded before the descriptions
        were known. A row whose description has been edited to anything else
        is left alone — the configurer's wording always wins.
        """
        PsiType = self.env['vifel.psi.type']
        for partner in self:
            by_prefix = {t.prefix: t for t in partner.vifel_psi_type_ids}
            to_create = []
            for prefix, description in SEED_TYPES:
                existing = by_prefix.get(prefix)
                if not existing:
                    to_create.append({'partner_id': partner.id,
                                      'name': description, 'prefix': prefix})
                elif existing.name == prefix:
                    existing.name = description
            if to_create:
                PsiType.create(to_create)
