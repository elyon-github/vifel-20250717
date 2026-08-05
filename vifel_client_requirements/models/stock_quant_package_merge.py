# -*- coding: utf-8 -*-
"""Durable merge-pallet identity, stored on the PACKAGE.

The merge feature used to INFER a pallet's "is this a merge/condition pallet?"
identity from markers on historical ``stock.move.line`` records. That evidence is
fragile: reset/clean SAs delete the lines (identity lost — bug A1), and because a
package is never deleted (only unreserved) a recycled package still matched its
old merged done-lines (false positive — bug A2).

This makes the identity DURABLE by storing it on ``stock.quant.package`` itself:

* ``vifel_is_merge_pallet`` is set True whenever a move line on the package
  carries a merge marker (``is_pallet_merge`` / ``vifel_premerge_captured``) — set
  from the line's own create/write (``stock_move_line_merge.py``), so it tracks
  EVERY path that marks a line (wizard, import, Studio SA), not just the wizard;
  and when a Fixed pallet is pinned (``res_partner_vifel_config.py``).
* It is cleared only when the package is genuinely repurposed: emptied AND not
  (any longer) a pinned Fixed pallet — see ``vifel_free_merge_identity_if_idle``,
  called from ``_free_pallet_if_unused`` (a condition pallet emptied) and the
  Fixed-pallet release path (un-pinned while idle). This is the user's rule:
  "Pallet # empty + past owner's Fixed PSI now False → free the Pallet #."

The withdrawal predicate (``stock_quant_merge_withdrawal.py``) then reads
``pinned OR package.vifel_is_merge_pallet`` — no global move-line search, so A2's
scope leak is gone and A1's deletion can no longer erase the identity.
"""
from odoo import api, fields, models


class StockQuantPackageMergeIdentity(models.Model):
    _inherit = 'stock.quant.package'

    vifel_is_merge_pallet = fields.Boolean(
        string='Merge / Condition Pallet', default=False, copy=False, index=True,
        help='Durable marker: this pallet is a merge/condition pallet (a pinned '
             'Fixed pallet, or one that goods have been merged onto). Set when a '
             'line is merged onto it or it is pinned; freed when it is emptied '
             'and no longer pinned. Drives whether it may be withdrawn from '
             'partially.')

    def vifel_holds_stock(self):
        """True when the package physically holds any stock right now."""
        self.ensure_one()
        return bool(self.quant_ids.filtered(lambda q: q.quantity > 0))

    def vifel_mark_merge_identity(self):
        """Durably mark these packages as merge/condition pallets (idempotent)."""
        todo = self.filtered(lambda p: p and not p.vifel_is_merge_pallet)
        if todo:
            todo.write({'vifel_is_merge_pallet': True})

    def vifel_free_merge_identity_if_idle(self):
        """Free the durable marker on any of these packages that is genuinely
        repurposable: it holds NO stock and is NOT pinned as a client's Fixed
        pallet. A pinned Fixed pallet keeps its identity even while momentarily
        empty (it is dedicated and will receive again); a condition pallet loses
        it once emptied, so the next receipt starts clean (the A2 fix)."""
        if not self:
            return
        pinned = self.env['res.partner']._vifel_fixed_merge_packages()
        to_free = self.filtered(
            lambda p: p.vifel_is_merge_pallet
            and p.id not in pinned.ids
            and not p.vifel_holds_stock())
        if to_free:
            to_free.write({'vifel_is_merge_pallet': False})
