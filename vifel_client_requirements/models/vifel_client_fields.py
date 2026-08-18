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
from odoo import api, fields, models


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
    # Batch # is the checker's raw input on the RECEIVING line. At validation it
    # is baked, together with the expiration date and the building it was
    # dropped in, into a Prodcode stamped onto the quant (see the gating model).
    batch_no = fields.Char(
        string='Batch #', copy=False,
        help="The client's batch number for this receiving line. At validation "
             "it becomes part of the Prodcode stamped onto stock.")
    # Prodcode is shown on the WITHDRAWAL line, read back from the quant being
    # withdrawn (the outgoing line is a fresh record and never carried it). It
    # is the frozen 'DDMONYYYY' + Batch# + building-shortname code.
    prodcode = fields.Char(
        string='Prodcode', compute='_compute_vifel_quant_readback',
        compute_sudo=True,
        help='The production code frozen onto this pallet at receiving: '
             'production date + Batch # + building short name.')
    # Lot No. is TYPED on the receiving line (client_lot_no, editable) and
    # stamped onto the quant at validation. A withdrawal line is a fresh record
    # that never carried it, so the WR Pallet Breakdown showed an empty Lot No.
    # This read-back pulls the stamped value off the source quant for display on
    # the withdrawal, exactly like Prodcode.
    vifel_lot_no_display = fields.Char(
        string='Lot No.', compute='_compute_vifel_quant_readback',
        compute_sudo=True,
        help="The client Lot No. frozen onto this pallet at receiving, shown "
             "read-only on the withdrawal line.")
    # Frozen snapshot captured at WR validation BEFORE the source quant is
    # consumed. A full withdrawal empties that quant, so the live read-back
    # below would blank the Lot No. / Prodcode after validation; once these are
    # set the display uses them instead. Stored, copy=False.
    vifel_lot_no_frozen = fields.Char(copy=False)
    vifel_prodcode_frozen = fields.Char(copy=False)

    @api.depends('package_id', 'product_id', 'lot_id', 'location_id',
                 'picking_code', 'vifel_lot_no_frozen', 'vifel_prodcode_frozen')
    def _compute_vifel_quant_readback(self):
        """Read the frozen Prodcode AND Lot No. off the quant this line
        withdraws from (one search, two display fields).

        Non-stored: the values live on the quant (stamped at the receiving
        validation); the withdrawal line only displays them, keyed on the same
        quant identity used everywhere else (product / source location / lot /
        package).

        Both display fields are shown ONLY on withdrawals, so incoming/other
        lines short-circuit to '' with no quant query, and a line without the
        minimum identity (a source package or location) is skipped too — the
        lookup only runs where it can actually resolve a quant."""
        Quant = self.env['stock.quant']
        for line in self:
            # default first, so every branch leaves the fields assigned
            line.prodcode = ''
            line.vifel_lot_no_display = ''
            # only withdrawals read back from a quant; skip the rest cheaply
            if line.picking_code != 'outgoing':
                continue
            # Once frozen at validation, keep the frozen value: the source quant
            # is gone after a full withdrawal, so the live read-back below can no
            # longer resolve it and would blank the display.
            if line.vifel_lot_no_frozen or line.vifel_prodcode_frozen:
                line.vifel_lot_no_display = line.vifel_lot_no_frozen or ''
                line.prodcode = line.vifel_prodcode_frozen or ''
                continue
            # need at least a source package or location to identify the quant
            if not line.package_id and not line.location_id:
                continue
            if not line.product_id:
                continue
            quant = Quant.search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('lot_id', '=', line.lot_id.id),
                ('package_id', '=', line.package_id.id),
            ], limit=1)
            if not quant:
                continue
            line.prodcode = quant.prodcode or ''
            line.vifel_lot_no_display = quant.client_lot_no or ''

    def _vifel_freeze_wr_readback(self):
        """Snapshot the withdrawal line's Lot No. / Prodcode off the source
        quant onto stored fields, so they still display once that quant is
        consumed at validation. Only outgoing lines with a resolvable quant;
        idempotent (never overwrites an existing frozen value)."""
        Quant = self.env['stock.quant']
        for line in self:
            if line.picking_code != 'outgoing':
                continue
            if not line.product_id or (
                    not line.package_id and not line.location_id):
                continue
            quant = Quant.sudo().search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('lot_id', '=', line.lot_id.id),
                ('package_id', '=', line.package_id.id),
            ], limit=1)
            if not quant:
                continue
            vals = {}
            if quant.client_lot_no and not line.vifel_lot_no_frozen:
                vals['vifel_lot_no_frozen'] = quant.client_lot_no
            if quant.prodcode and not line.vifel_prodcode_frozen:
                vals['vifel_prodcode_frozen'] = quant.prodcode
            if vals:
                line.write(vals)

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
    batch_no = fields.Char(
        string='Batch #', copy=False,
        help="The raw batch number stamped from the receiving line.")
    prodcode = fields.Char(
        string='Prodcode', copy=False,
        help="Production code frozen at receiving: production date "
             "(DDMONYYYY) + Batch # + building short name, e.g. 18MAY202699M.")
