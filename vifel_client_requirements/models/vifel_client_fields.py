# -*- coding: utf-8 -*-
"""Ledger-evidence fields for the Client-Specific Requirement Enhancement.

``is_pallet_merge`` is why the pallet count for a line is zero — the PKR ledger
reads it on every rebuild. ``client_lot_no`` is the client's own lot number,
stamped onto stock at validation. The ``vifel_premerge_*`` trio records what a
merge displaced so un-merge can restore exactly that.

THESE FIELDS LIVED IN ``multiple_relocation`` UNTIL 2026-07-23, on the argument
that uninstalling this module would drop the columns and make every
historically merged line recount as a received pallet on the next Re-sync.
The user has since ruled that the module is installed once and **never
uninstalled**, so that risk cannot occur, and keeping the feature's own fields
in someone else's module bought nothing but merge-conflict surface. They now
live with the rest of the feature.

If that ruling is ever reversed and uninstalling becomes possible, move these
back to core FIRST — dropping ``is_pallet_merge`` silently inflates pallet
counts, and a wrong pallet count is a wrong invoice.

copy=False on all — void mirrors and returns start clean, never inheriting a
merge flag, a lot number or a stale pre-merge snapshot from the document they
mirror.
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

    # What the merge displaced, so un-merge can put back exactly that instead
    # of guessing. The generic restore keys off original_pallet_series_id and
    # x_studio_initial_location, and a line that had NEITHER yet — merged
    # before any series or location was assigned — fell through it: the
    # adopted series stayed on the line and the location was reset to a
    # hardcoded fallback. Captured is a separate flag because "was empty" and
    # "never recorded" have to be told apart.
    vifel_premerge_captured = fields.Boolean(
        string='Pre-merge State Recorded', copy=False)
    vifel_premerge_series = fields.Char(
        string='Pre-merge Pallet Series', copy=False)
    vifel_premerge_location_id = fields.Many2one(
        'stock.location', string='Pre-merge Location', copy=False)


class StockQuantVifelClientFields(models.Model):
    _inherit = 'stock.quant'

    client_lot_no = fields.Char(
        string='Lot No.', copy=False,
        help="The client's own lot number, stamped from the receiving line "
             "at validation. When several lines land on one quant, the last "
             "stamped value wins.")
