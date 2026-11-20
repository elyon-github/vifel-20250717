from odoo import models


class StockMoveLinePrintAdjustedContainer(models.Model):
    """Receiving reports print the Container # as corrected by an approved
    pallet adjustment, without rewriting the validated RR line.

    An approved adjustment (Adjust Pallet Details) writes the new Container #
    to the pallet's quant only; the RR's own line keeps what was typed at
    receiving (a validated RR is never rewritten). The RR Summary and
    Per Pallet reports read the line, so they kept printing the old number.

    This is print-only: follow the approved Container # corrections made on
    this RR's pallet after the RR was validated, starting from the value on
    the line (old -> new, old -> new ...). Starting from the line's own value
    and only after the RR's validation keeps a corrections made on the same
    pallet number for a different, later receipt (pallet numbers are reused)
    from leaking onto this RR.
    """
    _inherit = 'stock.move.line'

    def _vifel_print_container_number(self):
        self.ensure_one()
        container = self.x_studio_container_number or ''
        picking = self.picking_id
        pallet = self.result_package_id
        if (not picking or picking.picking_type_id.code != 'incoming'
                or picking.state != 'done' or not pallet or not container):
            return container
        domain = [
            ('line_state', '=', 'approved'),
            ('old_package_id', '=', pallet.id),
            ('old_product_id', '=', self.product_id.id),
            ('new_x_studio_container_number', '!=', False),
        ]
        if picking.date_done:
            domain.append(('approved_date', '>=', picking.date_done))
        corrections = self.env['stock.quant.adjustment.line'].sudo().search(
            domain, order='approved_date, id')
        for adj in corrections:
            old = (adj.old_x_studio_container_number or '').strip()
            new = (adj.new_x_studio_container_number or '').strip()
            if new and old != new and old == container.strip():
                container = new
        return container
