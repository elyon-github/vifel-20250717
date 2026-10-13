# -*- coding: utf-8 -*-
"""Receipt-local recycle of voided special pallet series (see
vifel_voided_special_pallet.py for the rationale)."""
from odoo import fields, models


class StockPickingVoidedSpecial(models.Model):
    _inherit = 'stock.picking'

    vifel_voided_special_psi_ids = fields.One2many(
        'vifel.voided.special.pallet', 'picking_id',
        string='Voided Special Pallet Series')

    def _vifel_pull_voided_special(self, psi_type):
        """Recycle the LOWEST voided series of ``psi_type`` on this receipt:
        delete the record (consumed) and return its series. None if none voided
        for that type."""
        self.ensure_one()
        if not psi_type:
            return None
        row = self.env['vifel.voided.special.pallet'].search([
            ('picking_id', '=', self.id),
            ('psi_type_id', '=', psi_type.id),
        ], order='number asc, id asc', limit=1)
        if not row:
            return None
        series = row.series
        row.unlink()
        return series

    def _vifel_void_special_series(self, series):
        """Save ``series`` to this receipt's voided list, but only when it belongs
        to one of the client's special pallet TYPES. A no-op for any other series
        (a Fixed PSI, or the client-code normal series), so callers can pass any
        vacated series without extra checks. Idempotent per (picking, series)."""
        self.ensure_one()
        series = (series or '').strip()
        if not series:
            return
        ptype = self.env['vifel.psi.type']._type_for_series(
            self.partner_id, series)
        if not ptype:
            return
        number = ptype._parse(series)
        if number is None:
            return
        Voided = self.env['vifel.voided.special.pallet']
        if Voided.search_count([('picking_id', '=', self.id),
                                ('series', '=', series)]):
            return
        Voided.create({
            'picking_id': self.id, 'psi_type_id': ptype.id,
            'series': series, 'number': number,
        })
