# -*- coding: utf-8 -*-
"""Per-client special PSI types (Client-Specific Requirement Enhancement).

A merge-enabled client in Multiple Pallet Support mode owns a table of
PSI types (MDGM, BOC, TDMG, SDMG, ...): each type is an independent
series with its own prefix, counter and recycling pool. Special numbers
never mix with the client's normal PSI pool — the normal pool stores
bare integers and re-issues them under the client's unique code, so a
foreign number in it would mint a duplicate series.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Standard special types, created for any client the moment Multiple
# Pallet Support is switched on (idempotent; rows are editable after).
SEED_PREFIXES = ('MDGM', 'BOC', 'TDMG', 'SDMG')


class VifelPsiType(models.Model):
    _name = 'vifel.psi.type'
    _description = 'Client PSI Type (special pallet series)'
    _order = 'partner_id, prefix, id'

    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, ondelete='cascade',
        index=True)
    name = fields.Char(
        string='Description', required=True,
        help='What this pallet is for, in plain words — e.g. "Damaged '
             'Goods". This is what staff read; the prefix is what prints '
             'on the series.')
    prefix = fields.Char(
        string='Prefix', required=True,
        help='Short code that starts the series, e.g. SDMG.')
    next_number = fields.Integer(
        string='Next Number', default=1,
        help='Number the counter will issue next when no freed number is '
             'waiting to be reused. Change it only to continue an existing '
             'paper series.')
    next_series_preview = fields.Char(
        string='Next Series', compute='_compute_next_series_preview',
        help='Exactly what the next pallet of this type will be called.')

    @api.depends('prefix', 'next_number', 'number_pool')
    def _compute_next_series_preview(self):
        """Show the real next series instead of explaining the format.

        Freed numbers are re-issued smallest-first, so the preview follows
        the pool when one is waiting — what the user sees is what they get.
        """
        for ptype in self:
            pool = sorted(ptype.number_pool or [])
            number = pool[0] if pool else int(ptype.next_number or 1)
            ptype.next_series_preview = ptype._format(number) \
                if ptype.prefix else ''
    number_pool = fields.Json(
        string='Recyclable Numbers', default=[],
        help='Freed numbers of this type, re-issued smallest-first before '
             'the counter advances.')

    _sql_constraints = [
        ('partner_prefix_uniq', 'unique(partner_id, prefix)',
         'This client already has a PSI type with that prefix.'),
    ]

    @staticmethod
    def _normalize_prefix(prefix):
        return (prefix or '').strip().upper()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('prefix'):
                vals['prefix'] = self._normalize_prefix(vals['prefix'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('prefix'):
            vals['prefix'] = self._normalize_prefix(vals['prefix'])
        return super().write(vals)

    @api.constrains('prefix', 'partner_id')
    def _check_prefix_not_client_code(self):
        # The client's own code is the normal series — a type shadowing it
        # would hijack every normal PSI into the special routing.
        for ptype in self:
            code = (ptype.partner_id.x_studio_client_unique_code_1 or '').strip()
            if code and ptype.prefix == code.upper():
                raise ValidationError(_(
                    'Prefix "%(prefix)s" is %(client)s\'s Client Unique Code, '
                    'which already names their normal pallet series — a '
                    'special type cannot reuse it.'
                ) % {'prefix': ptype.prefix,
                     'client': ptype.partner_id.display_name})

    # ------------------------------------------------------------------
    # series arithmetic
    # ------------------------------------------------------------------
    def _format(self, number):
        self.ensure_one()
        return '%s-%s' % (self.prefix, str(number).zfill(6))

    def _parse(self, series):
        """Number of a series belonging to THIS type, else None."""
        self.ensure_one()
        prefix, _sep, number = (series or '').rpartition('-')
        return int(number) if prefix == self.prefix and number.isdigit() else None

    @api.model
    def _type_for_series(self, partner, series):
        """The partner's type owning this series' prefix (empty when none)."""
        prefix = (series or '').rpartition('-')[0]
        if not partner or not prefix:
            return self.browse()
        return self.search([
            ('partner_id', '=', partner.id),
            ('prefix', '=', prefix),
        ], limit=1)

    # ------------------------------------------------------------------
    # draw / take / give back — mirrors the normal pool's contract
    # ------------------------------------------------------------------
    def draw_number(self):
        """Next series of this type: pool smallest-first, else counter++."""
        self.ensure_one()
        pool = sorted(self.number_pool or [])
        if pool:
            number = pool[0]
            self.number_pool = [n for n in (self.number_pool or []) if n != number]
        else:
            number = int(self.next_number or 1)
            self.next_number = number + 1
        return self._format(number)

    def take_number(self, series):
        """A specific series was requested: take it from the pool when it
        is there, otherwise fall back to a normal draw."""
        self.ensure_one()
        number = self._parse(series)
        if number is not None and number in (self.number_pool or []):
            self.number_pool = [n for n in self.number_pool if n != number]
            return self._format(number)
        return self.draw_number()

    def give_back(self, series):
        """Return a freed number to this type's pool.

        Refused when the series is still on stocked internal quants
        (recycling it would mint a duplicate of live stock), or when the
        number was never issued by this counter (pooling it would collide
        with the counter when it eventually reaches that number).
        """
        self.ensure_one()
        number = self._parse(series)
        if number is None or number >= int(self.next_number or 1):
            return False
        if self.env['res.partner']._vifel_series_is_stocked(series):
            return False
        pool = self.number_pool or []
        if number not in pool:
            self.number_pool = sorted(pool + [number])
        return True
