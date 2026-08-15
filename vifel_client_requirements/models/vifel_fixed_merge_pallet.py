# -*- coding: utf-8 -*-
"""Per-client Fixed Merge Pallets (Client-Specific Requirement Enhancement).

A merge-enabled client in Fixed mode (Multiple Special Pallet Support OFF) pins
one OR MORE dedicated pallets, each with its own Fixed PSI. A receipt line merged
onto one adopts THAT pallet's PSI and location; the pallet is held reserved and
carries the durable merge identity for as long as it is pinned.

This replaces the old single ``res.partner.vifel_fixed_package_id`` /
``vifel_fixed_psi`` pair (migrated into one row on upgrade). Pinning /releasing is
driven from THIS line model's create/unlink so that adding or removing a row keeps
the reserve + durable-identity state symmetric per pallet.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class VifelFixedMergePallet(models.Model):
    _name = 'vifel.fixed.merge.pallet'
    _description = 'Client Fixed Merge Pallet (dedicated pinned pallet + PSI)'
    _order = 'partner_id, id'

    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, ondelete='cascade',
        index=True)
    package_id = fields.Many2one(
        'stock.quant.package', string='Fixed Merge Pallet', required=True,
        help='A pallet dedicated to this client and always offered as a merge '
             'target in Fixed mode. Must be empty and free when first pinned.')
    psi = fields.Char(
        string='Fixed Merge PSI', required=True,
        help='The Pallet Series adopted when merging onto this pallet while it '
             'still carries no stock. Permanent identity of the pallet — never '
             'recycled, and unique across all clients.')

    _sql_constraints = [
        ('package_uniq', 'unique(package_id)',
         'That pallet is already pinned as a Fixed Merge Pallet — a pallet can '
         'belong to only one client.'),
        ('psi_uniq', 'unique(psi)',
         'That Fixed Merge PSI is already used by another fixed pallet — a '
         'Pallet Series identifies one pallet, so it must be globally unique.'),
    ]

    # ------------------------------------------------------------------
    # Legacy migration - runs on EVERY module -u.
    #
    # The old design pinned ONE Fixed pallet per client on
    # res.partner.vifel_fixed_package_id / vifel_fixed_psi. The multiple-fixed
    # feature dropped those fields (their columns linger as orphans) and moved
    # the config into this model. The manifest version stays PINNED (a bump
    # would collide on the branch/deploy workflow), so a version-gated
    # migrations/ script would NEVER fire - the conversion has to happen here,
    # in init(), which Odoo calls after the table is created on each -u.
    # ------------------------------------------------------------------
    def init(self):
        super_init = getattr(super(), 'init', None)
        if callable(super_init):
            super_init()
        cr = self.env.cr
        # No-op on a fresh install: the legacy columns never existed there.
        cr.execute("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_name = 'res_partner'
              AND column_name IN ('vifel_fixed_package_id', 'vifel_fixed_psi')
        """)
        if cr.fetchone()[0] != 2:
            return
        # Raw SQL on purpose: read the now-orphan legacy columns directly and
        # bypass the empty-&-free create guard (a migrated pallet legitimately
        # already holds stock / is reserved from its original pin). Idempotent:
        # a package that already has a row is skipped, and ON CONFLICT covers
        # the unique(package_id)/unique(psi) constraints. No commit - the module
        # loader commits the whole upgrade transaction.
        cr.execute("""
            INSERT INTO vifel_fixed_merge_pallet
                (partner_id, package_id, psi,
                 create_uid, write_uid, create_date, write_date)
            SELECT p.id, p.vifel_fixed_package_id, UPPER(TRIM(p.vifel_fixed_psi)),
                   1, 1, (now() at time zone 'UTC'), (now() at time zone 'UTC')
            FROM res_partner p
            WHERE p.vifel_fixed_package_id IS NOT NULL
              AND COALESCE(TRIM(p.vifel_fixed_psi), '') <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM vifel_fixed_merge_pallet f
                  WHERE f.package_id = p.vifel_fixed_package_id)
            ON CONFLICT DO NOTHING
        """)
        if cr.rowcount:
            _logger.info(
                "vifel.fixed.merge.pallet: migrated %s legacy single-Fixed "
                "pallet(s) into the multiple-Fixed model.", cr.rowcount)

    @staticmethod
    def _normalize_psi(psi):
        return (psi or '').strip().upper()

    # ------------------------------------------------------------------
    # create / write / unlink — keep the pin (reserve + durable identity)
    # symmetric with the rows. Uses the res.partner helpers so the reserve /
    # release / merge-identity rules stay in one place.
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('psi'):
                vals['psi'] = self._normalize_psi(vals['psi'])
        rows = super().create(vals_list)
        # Empty-&-free is checked BEFORE we pin (below), against the pallet's
        # pre-pin state — @api.constrains would see the reserved/merge state the
        # pin itself sets. Migration inserts via raw SQL and never reaches here.
        rows._assert_packages_selectable()
        self.env['res.partner']._vifel_mark_fixed_package_reserved(
            rows.mapped('package_id'))
        return rows

    def write(self, vals):
        if vals.get('psi'):
            vals['psi'] = self._normalize_psi(vals['psi'])
        previous = self.mapped('package_id') if 'package_id' in vals \
            else self.env['stock.quant.package']
        res = super().write(vals)
        if 'package_id' in vals:
            self._assert_packages_selectable()
            self.env['res.partner']._vifel_mark_fixed_package_reserved(
                self.mapped('package_id'))
            self.env['res.partner']._vifel_release_fixed_package(previous)
        return res

    def unlink(self):
        packages = self.mapped('package_id')
        res = super().unlink()
        # Release any pallet no longer pinned by anyone AND idle (emptied). A
        # pinned pallet still holding stock keeps its identity until withdrawn.
        self.env['res.partner']._vifel_release_fixed_package(packages)
        return res

    # ------------------------------------------------------------------
    # guards
    # ------------------------------------------------------------------
    def _assert_packages_selectable(self):
        """A newly pinned Fixed pallet must be EMPTY and FREE: no stock, not
        reserved, not already a merge pallet. (Pinned-by-another-client is
        blocked by the unique(package_id) SQL constraint.) Called on ORM
        create/write only — the migration bypasses the ORM, so an already-pinned
        pallet that legitimately holds stock is never re-validated here."""
        for row in self:
            package = row.package_id
            if not package:
                continue
            if package.quant_ids.filtered(lambda q: q.quantity > 0):
                raise ValidationError(_(
                    'Pallet %(pallet)s is not empty — a Fixed Merge Pallet must '
                    'be empty and free when it is pinned.'
                ) % {'pallet': package.name})
            if package.x_studio_is_reserved:
                raise ValidationError(_(
                    'Pallet %(pallet)s is reserved — pick a free pallet as the '
                    'Fixed Merge Pallet.') % {'pallet': package.name})
            if package.vifel_is_merge_pallet:
                raise ValidationError(_(
                    'Pallet %(pallet)s is already a merge / condition pallet — '
                    'it cannot also be pinned as a Fixed Merge Pallet.'
                ) % {'pallet': package.name})

    @api.constrains('psi')
    def _check_psi_not_stocked(self):
        """A Fixed PSI must not already be live on stock held by a DIFFERENT
        pallet — a Pallet Series identifies one pallet, so reusing a stocked
        series would mint a duplicate of live stock. The pallet's OWN stock is
        exempt (a pinned pallet carries its PSI once it starts receiving)."""
        for row in self:
            series = (row.psi or '').strip()
            if not series:
                continue
            stocked = self.env['stock.quant'].search([
                ('x_studio_pallet_series_id', '=', series),
                ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0),
                ('package_id', '!=', row.package_id.id),
            ], limit=1)
            if stocked:
                raise ValidationError(_(
                    'Fixed PSI "%(psi)s" is already live on stocked pallet '
                    '%(pallet)s — a Pallet Series identifies one pallet, so it '
                    'cannot be reused as a Fixed Merge PSI.'
                ) % {'psi': series,
                     'pallet': stocked.package_id.name
                     or stocked.location_id.display_name})
