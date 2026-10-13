# -*- coding: utf-8 -*-
"""Client profile: VIFEL Configuration (Client-Specific Requirement Enh.).

Checkbox cascade on the Contact form, everything OFF by default:

    Can Merge Pallets                (master switch)
      └─ Multiple Special Pallet Support   (mode switch, exclusive)
           OFF  -> Fixed Merge Pallet and PSI Support: one OR MORE dedicated
                   pinned pallets, each with its own fixed PSI
                   (vifel.fixed.merge.pallet rows)
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
        string='Multiple Special Pallet Support', default=False,
        help='ON — Multiple Special Pallet Support: the client works with '
             'special PSI-type series (the table below), each prefix with its '
             'own counter and recycling pool.\n'
             'OFF — Fixed Merge Pallet and PSI Support: the client uses one or '
             'more dedicated pinned pallets, each with its own fixed PSI.')
    vifel_include_regular_pallets = fields.Boolean(
        string='Include Regular Pallets', default=False,
        help='Also offer the client\'s regular stocked pallets as merge '
             'targets, next to the special-type ones.')
    vifel_show_lot_no = fields.Boolean(
        string='Show Lot No.', default=False,
        help='Show the client Lot No. column on this client\'s transfer '
             'lines and stock.')
    vifel_show_batch_no = fields.Boolean(
        string='Show Batch # / Prodcode', default=False,
        help='Show the Batch # input column on this client\'s receiving lines '
             'and the derived Prodcode column on its withdrawals.')
    vifel_fixed_pallet_ids = fields.One2many(
        'vifel.fixed.merge.pallet', 'partner_id',
        string='Fixed Merge Pallets',
        help='Dedicated pallets pinned for this client (Fixed mode), each with '
             'its own fixed PSI. Every merge is offered these pallets.')
    vifel_psi_type_ids = fields.One2many(
        'vifel.psi.type', 'partner_id', string='PSI Types')

    @api.model
    def _vifel_fixed_merge_packages(self):
        """Every pallet pinned as some client's Fixed Merge Pallet.

        These are dedicated: the pallet belongs to that client permanently and
        is reached only through the Merge button, which sets flag, series and
        location together. It must therefore never be offered anywhere an
        EMPTY pallet is picked — not even to its own client, and not even
        while it holds no stock. (Now a client may pin several — this returns
        the union across every vifel.fixed.merge.pallet row.)
        """
        return self.env['vifel.fixed.merge.pallet'].sudo().search(
            []).mapped('package_id')

    def _vifel_mark_fixed_package_reserved(self, packages=None):
        """Hold the pinned pallet reserved, stock or no stock.

        Without this the pallet reads as a free empty pallet the moment it is
        emptied, and the next receipt could seat unrelated goods on it. There
        is deliberately NO receiving report attached: it is not reserved FOR a
        document, it is dedicated to a client.
        """
        packages = packages if packages is not None else \
            self.mapped('vifel_fixed_pallet_ids.package_id')
        todo = packages.filtered(lambda p: not p.x_studio_is_reserved)
        if todo:
            todo.write({'x_studio_is_reserved': True})
        # A pinned Fixed pallet IS a merge pallet — stamp the durable identity so
        # it carries on the Pallet # too (and survives even while empty, since
        # the release path below only frees it once it stops being pinned).
        packages.vifel_mark_merge_identity()

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
        # Free the durable merge identity on any un-pinned pallet that is now
        # idle: emptied AND no longer pinned (user's rule). An un-pinned pallet
        # that STILL holds its merged stock keeps the identity until that stock
        # is withdrawn — vifel_free_merge_identity_if_idle enforces exactly that.
        orphaned.vifel_free_merge_identity_if_idle()

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
        # Fixed-pallet reserve / release is driven by the vifel.fixed.merge.pallet
        # line model's create/write/unlink (adding or removing a pinned pallet
        # keeps the reserve + durable-identity state symmetric per pallet), so it
        # is intentionally NOT handled here any more.
        res = super().write(vals)
        if vals.get('vifel_multiple_pallet_support'):
            self._vifel_seed_psi_types()
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
