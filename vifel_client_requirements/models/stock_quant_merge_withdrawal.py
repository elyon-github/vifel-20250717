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

        Read the DURABLE identity stored on the package
        (``vifel_is_merge_pallet``) instead of inferring it from historical move
        lines. That flag is set whenever a line is merged onto the package or the
        package is pinned as a Fixed pallet, and freed only when the package is
        emptied and no longer pinned — so:

        * reset/clean SAs deleting the receiving lines can no longer erase the
          identity (bug A1);
        * a recycled/re-received PLAIN package no longer matches stale historical
          merged lines, because the flag was freed when it was emptied (bug A2);
        * an un-pinned Fixed pallet keeps partial withdrawal while its merged
          stock remains, losing it only once emptied (bug D2).

        The pinned clause is kept as belt-and-suspenders (config-durable) even
        though pinning also sets the flag. Requires the one-time backfill SA
        (ai_context/sa_backfill_merge_pallet_flag.py) for pre-existing packages.
        """
        if not package_id:
            return super()._vifel_package_allows_partial_withdrawal(package_id)

        pinned = self.env['res.partner']._vifel_fixed_merge_packages()
        if package_id in pinned.ids:
            return True

        # A durably-marked pallet qualifies only while it STILL HOLDS its merged
        # stock. This is what makes an emptied/recycled package correct: once its
        # merged goods are withdrawn it holds no stock, so it does NOT allow
        # partial withdrawal even though the flag is still set (bug A2) — and a
        # partial withdrawal is only ever asked of a pallet that holds stock
        # anyway. The flag itself survives line deletion (bug A1) and un-pinning
        # while full (bug D2); "holds stock" only gates the emptied case.
        package = self.env['stock.quant.package'].browse(package_id)
        if (package.exists() and package.vifel_is_merge_pallet
                and package.vifel_holds_stock()):
            return True

        return super()._vifel_package_allows_partial_withdrawal(package_id)
