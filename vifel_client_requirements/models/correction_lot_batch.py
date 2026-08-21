# -*- coding: utf-8 -*-
"""Carry the client Lot No. / Batch # onto pallet-adjustment history lines.

A correction writes IN PLACE on the quant, so the stock itself never loses
these values. But the correction also builds history move lines for the audit
trail, from two hand-maintained dicts that copied the Studio fields and
bf_pallet_char only. The adjustment history therefore showed a blank Lot No. /
Batch # for stock that plainly had them.

Plug-and-play: the base module exposes an empty
``_vifel_correction_line_extra_vals`` hook; every field name this feature owns
stays here.
"""
from odoo import models


class StockQuantCorrectionWizardLotBatch(models.TransientModel):
    _inherit = 'stock.quant.correction.wizard'

    def _vifel_correction_line_extra_vals(self, quant):
        """Fill the base hook with this feature's stamped values."""
        vals = super()._vifel_correction_line_extra_vals(quant)
        vals.update(quant._vifel_quant_audit_vals())
        return vals
