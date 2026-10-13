# -*- coding: utf-8 -*-
"""Carry the client Lot No. / Batch # / Prodcode into occupancy history.

The occupancy snapshot discovers which quant fields to mirror by NAME: it takes
anything starting with ``x_studio_`` plus a short list of extras, and only if a
field of the same name also exists on ``stock.quant.history``. These three
qualify on neither count, so they reached occupancy history nowhere at all, and
a point-in-time question like "what Lot No. was on that pallet on 30 June" had
no answer even though the live quant carried it.

Declaring them here (rather than in stock_quant_history) keeps the feature's
fields with the feature, the same ruling that moved them out of
multiple_relocation. Note ``prodcode`` IS carryable here: on stock.quant it is a
plain stored Char, unlike on stock.move.line where it is a non-stored compute.

Forward-only by decision: the ~1.25M existing history rows stay blank and the
values appear from the next snapshot onwards.
"""
from odoo import fields, models


class StockQuantHistoryLotBatch(models.Model):
    _inherit = "stock.quant.history"

    client_lot_no = fields.Char(string="Lot No.", readonly=True)
    batch_no = fields.Char(string="Batch #", readonly=True)
    prodcode = fields.Char(string="Prodcode", readonly=True)


class StockQuantHistorySnapshotLotBatch(models.Model):
    _inherit = "stock.quant.history.snapshot"

    def _extra_copy_fields(self):
        """Add this feature's stamped values to the snapshot's copy list."""
        return super()._extra_copy_fields() + (
            "client_lot_no", "batch_no", "prodcode")
