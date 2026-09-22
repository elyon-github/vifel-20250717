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
from odoo import fields, models


class StockQuantCorrectionWizardLotBatch(models.TransientModel):
    _inherit = 'stock.quant.correction.wizard'

    def _vifel_correction_line_extra_vals(self, quant):
        """Fill the base hook with this feature's stamped values."""
        vals = super()._vifel_correction_line_extra_vals(quant)
        vals.update(quant._vifel_quant_audit_vals())
        return vals



def _clean_lot_no(value):
    """Typed Lot No. compared and stored trimmed, so a stray space is neither
    a phantom change nor a second spelling of the same lot."""
    return value.strip()


# --- Lot No. correctable in Adjust Pallet Details ----------------------------
# The Lot No. is typed on the receiving line and stamped onto the quant at
# validation. When it was never typed (or a return re-received the pallet
# without it) nothing afterwards let anyone fill it in: the RR column locks at
# done and the quant lists are read-only. These overrides fill the neutral
# correction hooks in multiple_relocation, so the Lot No. goes through the same
# request -> approval -> apply path as every other pallet detail, is written
# back onto the RR's Pallet Breakdown, and lands in the adjustment history.
#
# It is a label only: not part of the quant's identity (that is Odoo's lot_id,
# which stays locked), not counted by the Pallet Kilos Record, not billed.


class StockQuantCorrectionWizardLotNo(models.TransientModel):
    _inherit = 'stock.quant.correction.wizard'

    def _vifel_correction_line_prefill(self, quant):
        vals = super()._vifel_correction_line_prefill(quant)
        vals['client_lot_no'] = quant.client_lot_no or False
        return vals

    def _vifel_adjustment_line_extra_vals(self, quant, wizard_line):
        vals = super()._vifel_adjustment_line_extra_vals(quant, wizard_line)
        vals.update({
            'old_client_lot_no': quant.client_lot_no or False,
            'new_client_lot_no': (wizard_line.client_lot_no or '').strip() or False,
        })
        return vals


class StockQuantCorrectionLineLotNo(models.TransientModel):
    _inherit = 'stock.quant.correction.line'

    client_lot_no = fields.Char(string='Lot No.')

    def _vifel_extra_correction_fields(self):
        res = super()._vifel_extra_correction_fields()
        res['client_lot_no'] = ('client_lot_no', _clean_lot_no)
        return res

    def _vifel_extra_breakdown_sync_fields(self):
        res = super()._vifel_extra_breakdown_sync_fields()
        res['client_lot_no'] = 'client_lot_no'
        return res


class StockQuantAdjustmentLineLotNo(models.Model):
    _inherit = 'stock.quant.adjustment.line'

    old_client_lot_no = fields.Char(string='Old Lot No.', readonly=True)
    new_client_lot_no = fields.Char(string='New Lot No.')

    def _vifel_extra_adjustment_fields(self):
        res = super()._vifel_extra_adjustment_fields()
        res['client_lot_no'] = ('client_lot_no', _clean_lot_no)
        return res

    def _vifel_extra_change_labels(self):
        res = super()._vifel_extra_change_labels()
        res['client_lot_no'] = 'Lot No.'
        return res
