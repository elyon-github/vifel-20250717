# -*- coding: utf-8 -*-
"""Partial withdrawal from a merge pallet is normal, not an oversight.

The Incomplete Package notice ("Detected unselected quants with the same
pallet") exists because one pallet normally holds one batch: leftovers mean
the checker missed lines. A merge pallet breaks that premise on purpose - it
holds several receipts' goods, often for different products - so withdrawing
just some of them is the expected case, and being nagged to take everything
is wrong.

The ledger already handles the consequence correctly and needs no change: a
withdrawal counts a pallet only when it leaves it EMPTY
(``reserved_quantity_on_validation == 0``). Take part of a merge pallet and
stock remains, so it counts **-0 pallets withdrawn** - exactly right, because
the pallet is still standing in the freezer holding the rest.
"""
from odoo import models


class StockQuantMergeWithdrawal(models.Model):
    _inherit = 'stock.quant'

    def _vifel_package_allows_partial_withdrawal(self, package_id):
        """A merge pallet may be withdrawn from partially.

        Two kinds qualify, and both are genuinely multi-batch:

        * a pallet pinned as some client's Fixed Merge Pallet - dedicated,
          receiving goods from many documents over its life;
        * any pallet something has actually been merged onto, which is how a
          Multiple-mode client's condition pallets accumulate.
        """
        if not package_id:
            return super()._vifel_package_allows_partial_withdrawal(package_id)

        pinned = self.env['res.partner']._vifel_fixed_merge_packages()
        if package_id in pinned.ids:
            return True

        if self.env['stock.move.line'].search_count([
                ('result_package_id', '=', package_id),
                ('is_pallet_merge', '=', True)]):
            return True

        return super()._vifel_package_allows_partial_withdrawal(package_id)
