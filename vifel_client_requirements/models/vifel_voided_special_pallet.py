# -*- coding: utf-8 -*-
"""RR-local voided special-pallet series (Client-Specific Requirement Enhancement).

When a "Start a new special pallet" line is un-merged and no other line of the
receipt still holds its drawn special series, the series is NOT lost: it is saved
here as a voided record on the receipt (stock.picking). Creating a special pallet
of the SAME type again on the SAME receipt then RECYCLES the lowest voided series
(consuming the record) instead of drawing a fresh number from the client profile.

Deliberately receipt-scoped and one-directional: a concurrent receipt never sees
this list, and a voided series that is never recycled stays bound to this receipt
forever (it is NEVER returned to the client profile pool). This is a different
rule from standard PSI recycling on purpose - the number is burned rather than
re-issued, so an accidental create+un-merge cannot lose it and cannot leak it to
another receipt.
"""
from odoo import fields, models


class VifelVoidedSpecialPallet(models.Model):
    _name = 'vifel.voided.special.pallet'
    _description = 'Voided special pallet series recyclable within one receipt'
    _order = 'number asc, id asc'

    picking_id = fields.Many2one(
        'stock.picking', string='Receipt', required=True, ondelete='cascade',
        index=True)
    psi_type_id = fields.Many2one(
        'vifel.psi.type', string='Pallet Type', required=True,
        ondelete='cascade')
    prefix = fields.Char(
        related='psi_type_id.prefix', string='Prefix', store=True)
    series = fields.Char(string='Pallet Series', required=True)
    number = fields.Integer(string='Number', index=True)
