# -*- coding: utf-8 -*-
"""Ledger-evidence fields for the Client-Specific Requirement Enhancement.

These two fields belong to the ``vifel_client_requirements`` feature, but they
deliberately live HERE, in the core module, and must not be moved.

``is_pallet_merge`` is why the pallet count for a line is zero. The PKR ledger
reads it every time it rebuilds. If the field lived in the optional module,
uninstalling would drop the column and every historically merged line would
silently recount as a received pallet on the next Re-sync — inflating pallet
counts, and therefore invoices, for work done months earlier. ``client_lot_no``
is likewise a record of what was received, stamped onto stock at validation.

The rule: the optional module owns the configuration, the routing and the user
interface. It never owns the record of what already happened.

copy=False on both — void mirrors and returns start clean, never inheriting a
merge flag or a lot number from the document they mirror.
"""
from odoo import fields, models


class StockMoveLineVifelClientFields(models.Model):
    _inherit = 'stock.move.line'

    is_pallet_merge = fields.Boolean(
        string='Merged Pallet', copy=False,
        help='This line was merged onto an already stocked pallet — it '
             'adopted that pallet\'s PSI and location, and does not count '
             'as a received pallet in the ledger.')
    client_lot_no = fields.Char(
        string='Lot No.', copy=False,
        help="The client's own lot number for this pallet line.")


class StockQuantVifelClientFields(models.Model):
    _inherit = 'stock.quant'

    client_lot_no = fields.Char(
        string='Lot No.', copy=False,
        help="The client's own lot number, stamped from the receiving line "
             "at validation. When several lines land on one quant, the last "
             "stamped value wins.")
