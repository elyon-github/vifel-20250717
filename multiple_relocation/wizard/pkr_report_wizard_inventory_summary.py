# -*- coding: utf-8 -*-
"""Offer the Inventory Summary XLSX from the Generate Report wizard.

The report itself (report.stock_quant.inventory_summary_xlsx, one sheet
per client of their current on-hand stock) already exists as a Print
action on the stock.quant list — that stays. This only adds a second
door to it from the PKR Generate Report wizard, where only the client
filter applies: the report reads live stock.quant data, so there is no
date range to pick.

Lives here rather than in pallet_kilos_record_model because this module
owns the report (and already depends on that one — the reverse reference
would be circular).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.pallet_kilos_record_model.wizard.pkr_report_wizard import (
    SNAPSHOT_REPORTS,
)

# As-of-now snapshot: the base wizard must not demand a date range for it
# (this also flags is_snapshot_report on the wizard).
SNAPSHOT_REPORTS.add('inventory_summary')


class PkrReportWizard(models.TransientModel):
    _inherit = 'pallet_kilos_record_model.report.wizard'

    report_type = fields.Selection(
        selection_add=[('inventory_summary', 'Inventory Summary XLSX')],
        ondelete={'inventory_summary': 'set default'},
    )

    def action_generate_report(self):
        self.ensure_one()
        if self.report_type == 'inventory_summary':
            return self._generate_inventory_summary()
        return super().action_generate_report()

    def _generate_inventory_summary(self):
        """Current-stock snapshot, one sheet per selected client.

        The report re-queries each owner's complete on-hand internal
        inventory itself (see reports/client_summary_xlsx.py) — the
        records passed in only decide which owners get a sheet. So one
        quant per owner is enough, and keeps the report URL short.
        """
        self.ensure_one()
        domain = [
            ('location_id.usage', '=', 'internal'),
            ('quantity', '!=', 0),
            ('owner_id', '!=', False),
        ]
        if self.partner_ids:
            domain.append(('owner_id', 'in', self.partner_ids.ids))
        groups = self.env['stock.quant']._read_group(
            domain, groupby=['owner_id'], aggregates=['id:max'])
        quants = self.env['stock.quant'].browse([qid for _owner, qid in groups])
        if not quants:
            raise UserError(_("The selected clients have no stock on hand."))
        report = self.env.ref('multiple_relocation.xlsx_client_inventory')
        return report.report_action(quants)
