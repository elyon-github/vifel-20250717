# -*- coding: utf-8 -*-

from odoo import models, fields, api


class StockPickingAudit(models.Model):
    _inherit = 'stock.picking'

    pallet_audit_count = fields.Integer(
        string='Audit Events', compute='_compute_pallet_audit_count',
    )

    def _compute_pallet_audit_count(self):
        Audit = self.env['pallet.series.audit']
        for picking in self:
            audit = Audit.search(
                [('picking_id', '=', picking.id)], limit=1,
            )
            picking.pallet_audit_count = len(audit.line_ids) if audit else 0

    def action_view_pallet_audit(self):
        self.ensure_one()
        audit = self.env['pallet.series.audit'].search(
            [('picking_id', '=', self.id)], limit=1,
        )
        if audit:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Pallet Series Audit',
                'res_model': 'pallet.series.audit',
                'view_mode': 'form',
                'res_id': audit.id,
            }
        # No audit record yet — show empty list
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pallet Series Audit',
            'res_model': 'pallet.series.audit',
            'view_mode': 'list,form',
            'domain': [('picking_id', '=', self.id)],
        }
