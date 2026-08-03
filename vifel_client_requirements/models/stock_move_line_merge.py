# -*- coding: utf-8 -*-
"""Merge entry points on the Pallet Breakdown line (Client-Specific Req. Enh).

The ``is_pallet_merge`` FIELD lives in multiple_relocation (ledger evidence);
this file adds only the interaction around it — when the Merge / Un-merge
button shows, and what the two buttons do. Nothing here stores merge state, so
uninstalling drops the buttons and leaves every historical flag intact.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockMoveLineMergeEntry(models.Model):
    _inherit = 'stock.move.line'

    vifel_show_merge_button = fields.Boolean(
        compute='_compute_vifel_show_merge_button')

    # A user-facing "is this line on a merged pallet?" marker, checked for
    # EVERY line sharing the pallet — the one that started it AND the ones that
    # joined — so the column and the Un-merge button are symmetric: any line on
    # a consolidated pallet shows "Merged" and can be peeled back off. Checked
    # when the line is a +0 merge (is_pallet_merge) OR shares its pallet with
    # another line of the same receipt.
    vifel_on_merged_pallet = fields.Boolean(
        string='Merged', compute='_compute_vifel_on_merged_pallet',
        help='Checked when this line sits on a merged pallet — a +0 merge onto '
             'already-stocked pallet, or a pallet shared with other lines of '
             'this same receipt. Any such line can be un-merged; the pallet is '
             'counted once.')

    @api.depends('result_package_id', 'is_pallet_merge',
                 'vifel_premerge_captured',
                 'picking_id.move_line_ids.result_package_id',
                 'picking_id.move_line_ids.is_pallet_merge',
                 'picking_id.move_line_ids.vifel_premerge_captured')
    def _compute_vifel_on_merged_pallet(self):
        for line in self:
            # OWN marker: a +0 merge (is_pallet_merge) OR an explicit
            # merge-button placement (vifel_premerge_captured — a same-receipt
            # join OR a first-stock birth). Any line you merged with the button
            # shows "Merged" and offers Un-merge so it can be REVERTED — even as
            # the SOLE line on the pallet (e.g. line #1 the first time it merges
            # onto a Fixed pallet). Un-merge clears the marker, so a reverted
            # line goes back to plain.
            if line.is_pallet_merge or line.vifel_premerge_captured:
                line.vifel_on_merged_pallet = True
                continue
            # HOST symmetry: an UNMARKED line that shares its pallet with a
            # marked sibling also reads as merged. Merely sharing a pallet with
            # another UNMARKED line is NOT a merge — that is ordinary
            # multi-line-on-one-pallet encoding (M/RR/05299), which must stay
            # unchecked. When the marked sibling leaves, the host is alone and
            # unmarked again → plain.
            pkg = line.result_package_id
            if not pkg:
                line.vifel_on_merged_pallet = False
                continue
            line.vifel_on_merged_pallet = any(
                (sib.is_pallet_merge or sib.vifel_premerge_captured)
                for sib in (line.picking_id.move_line_ids - line)
                if sib.result_package_id == pkg)

    @api.depends('picking_id.partner_id', 'picking_id.state',
                 'picking_id.picking_type_id')
    def _compute_vifel_show_merge_button(self):
        """Merge is a receiving-time tool for merge-enabled clients:
        incoming, non blast freeze, not a return, not validated."""
        for line in self:
            picking = line.picking_id
            line.vifel_show_merge_button = bool(
                picking
                and picking.picking_type_code == 'incoming'
                and picking.state != 'done'
                and not picking.return_id
                and not getattr(picking, 'is_void_return', False)
                and not picking.x_studio_is_a_blast_freezer
                and picking.partner_id.vifel_can_merge_pallets)

    def write(self, vals):
        """Guard merged lines, and detect an un-merge.

        Both used to live inside ``multiple_relocation``'s own write override.
        They wrap it from here instead, so core carries none of this feature:
        the guard runs before core's write, and the flag is cleared after it,
        once core's restore machinery has put the line's own series back.
        """
        self._vifel_guard_merged_line_edit(vals)

        # UN-MERGE: a merged line whose pallet is changed away outside the
        # merge wizard becomes a plain line again. Conditions mirror core's
        # own early returns, so this fires exactly where core would have.
        ctx = self.env.context
        unmerged = self.browse()
        if ('result_package_id' in vals
                and not ctx.get('skip_pallet_series_sync')
                and not ctx.get('vifel_pallet_merge')):
            unmerged = self.filtered(
                lambda r: r.is_pallet_merge and r.picking_id
                and r.picking_id.picking_type_code == 'incoming'
                and r.product_id and not r.picking_id.return_id)

        res = super().write(vals)

        if unmerged:
            # bypass this override: only the flag changes, and core's write
            # returns early for a vals without result_package_id anyway. The
            # adopted PSI is NOT recycled — push_unused_pallet's stocked-guard
            # refuses a series that is live on the floor.
            super(StockMoveLineMergeEntry, unmerged).write(
                {'is_pallet_merge': False})
        return res

    def _vifel_guard_merged_line_edit(self, vals):
        """Refuse a silent edit of a merged line's location or series.

        Exempt when the merge wizard itself is writing (vifel_pallet_merge),
        when the flag is being cleared in the same write (an un-merge), and
        for validation/void machinery that carries skip_pallet_series_sync.
        """
        ctx = self.env.context
        if ctx.get('vifel_pallet_merge') or ctx.get('skip_pallet_series_sync'):
            return
        if vals.get('is_pallet_merge') is False:
            return                      # un-merging: the pin is being removed
        watched = {
            'location_dest_id': _('Location'),
            'x_studio_pallet_series_id': _('Pallet Series ID'),
        }
        touched = [label for key, label in watched.items() if key in vals]
        if not touched:
            return
        for line in self:
            if not line.is_pallet_merge:
                continue
            # Mid-un-merge: the pallet has already been cleared and the
            # restore machinery is putting the original series back (it
            # re-enters write through base_automation's wrapper). A merged
            # line with no pallet has nothing left to stay consistent with.
            if not line.result_package_id:
                continue
            raise UserError(_(
                "Line #%(num)s is merged onto pallet %(pallet)s "
                "(%(psi)s), so its %(fields)s cannot be changed here — the "
                "line has to stay where that pallet is.\n\n"
                "Press Un-merge on the line first if it should go somewhere "
                "else."
            ) % {'num': line.x_studio_ or '',
                 'pallet': line.result_package_id.name or '?',
                 'psi': line.x_studio_pallet_series_id or '?',
                 'fields': ' / '.join(touched)})

    def action_open_pallet_merge_wizard(self):
        self.ensure_one()
        return self._vifel_open_merge_wizard(self, _('Merge Pallet — %s') % (
            self.product_id.display_name or _('line #%s') % (
                self.x_studio_ or '')))

    def action_open_pallet_merge_wizard_multi(self):
        """Selection-bar 'Merge Selected': open the wizard for every mergeable
        line ticked in the Pallet Breakdown. Ineligible ones are dropped now;
        any that slip through are skipped at confirm with a note."""
        lines = self or self.browse(self.env.context.get('active_ids', []))
        mergeable = lines.filtered(
            lambda l: l.vifel_show_merge_button and not l.is_pallet_merge)
        if not mergeable:
            raise UserError(_(
                'None of the selected lines can be merged — they must be '
                'unmerged incoming lines of a merge-enabled client.'))
        return self._vifel_open_merge_wizard(
            mergeable, _('Merge %d Selected Lines') % len(mergeable))

    def _vifel_open_merge_wizard(self, lines, name):
        wizard = self.env['pallet.merge.wizard'].create({
            'move_line_id': lines[:1].id,
            'move_line_ids': [(6, 0, lines.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'pallet.merge.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _vifel_restore_premerge_state(self, captured, pre_series, pre_location):
        """Put the line back exactly as the merge found it.

        Only corrects what the generic restore cannot know:

        * a line that had NO series before merging keeps the adopted one,
          because that restore is gated on original_pallet_series_id and a
          line with no original never enters it — so the series is cleared
          here;
        * a line that had no x_studio_initial_location is sent to a hardcoded
          fallback location — so the real pre-merge location is written back
          here.

        A line that did have its own series is left to the existing, tested
        machinery (which also settles the recycling pool); this only fills the
        gaps rather than overriding it.
        """
        self.ensure_one()
        if not captured:
            return
        vals = {}
        if not pre_series and self.x_studio_pallet_series_id:
            vals['x_studio_pallet_series_id'] = False
        if pre_location and self.location_dest_id != pre_location:
            vals['location_dest_id'] = pre_location.id
        vals.update({'vifel_premerge_captured': False,
                     'vifel_premerge_series': False,
                     'vifel_premerge_location_id': False})
        self.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)

        # x_studio_pallet_series_display is a STORED Studio computed field
        # whose compute only assigns when the source has a value:
        #
        #     if record.x_studio_pallet_series_id:
        #         record['x_studio_pallet_series_display'] = ...
        #
        # so clearing the series leaves the display holding the old one. The
        # real fix is an else-branch in that Studio compute — see
        # ai_context/studio_psi_display_clear_FIX.py — but the field is
        # cleared here too, in its own write after the recompute has run, so
        # un-merge is correct even before that paste reaches a database.
        if 'x_studio_pallet_series_display' in self._fields \
                and vals.get('x_studio_pallet_series_id', True) is False:
            self.with_context(skip_pallet_series_sync=True,
                              vifel_pallet_merge=True).write(
                {'x_studio_pallet_series_display': False})

    def action_unmerge_pallet_line(self):
        """Reverse a merge: the line leaves the stocked target and becomes a
        plain line needing its own pallet again.

        Clearing the pallet routes through the stock_move write override,
        which detects the flagged line as an un-merge (clears the flag) and
        runs the standard restore-original machinery. The adopted Pallet
        Series belongs to the target's live stock, so the restore's recycle
        attempt is refused by push_unused_pallet's stocked-guard — it is
        never returned to the pool.
        """
        self.ensure_one()
        if not self.vifel_on_merged_pallet:
            raise UserError(_('This line is not a merged pallet.'))
        target_name = self.result_package_id.name
        captured = self.vifel_premerge_captured
        pre_series = self.vifel_premerge_series
        pre_location = self.vifel_premerge_location_id
        if self.is_pallet_merge:
            # +0 merge onto stock from an EARLIER receipt — the tested path:
            # clearing the pallet routes through the write override, which drops
            # the flag and runs the standard restore machinery.
            self.write({'result_package_id': False})
            self._vifel_restore_premerge_state(
                captured, pre_series, pre_location)
        else:
            # A line sharing a same-receipt pallet — either the one that STARTED
            # it or one that joined. Never flagged, so the pallet stays counted
            # +1 via whichever lines remain. Peel THIS line off explicitly (the
            # base restore machinery only runs for flagged lines).
            self._vifel_detach_same_receipt_join(pre_location)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pallet un-merged'),
                'message': _(
                    'Line #%(num)s no longer merges onto %(pallet)s — assign '
                    'it its own pallet.') % {
                        'num': self.x_studio_ or '', 'pallet': target_name},
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _vifel_restore_series_if_free(self, pre_series):
        """Draw the line's captured pre-merge Pallet Series back if it is still
        free, and return it; otherwise return False so the caller blanks the
        series and lets the pool re-assign a fresh one.

        "Free" = not physically on the floor (no stocked internal quant) AND not
        already worn by another line of this same receipt. When the join was
        made, _free_displaced pushed this series back to the owner's pool (unless
        a sibling still used it), so restoring it means DRAWING it out again with
        get_pallet_series_by_id — that keeps the pool consistent and can never
        double-book a live number (the two guards above are exactly what would
        make it live).
        """
        self.ensure_one()
        if not pre_series:
            return False
        partner = self.picking_id.partner_id
        if partner._vifel_series_is_stocked(pre_series):
            return False
        if (self.picking_id.move_line_ids - self).filtered(
                lambda l: l.x_studio_pallet_series_id == pre_series):
            return False
        # consume it from the pool / its type so it is not issued twice
        partner.get_pallet_series_by_id(pre_series)
        return pre_series

    def _vifel_detach_same_receipt_join(self, pre_location):
        """Peel a line off a pallet it SHARES with other lines of this receipt
        (the host that started it, or a line that joined).

        It drops the shared pallet so the line becomes plain and unassigned
        again; a joiner's captured pre-merge location is put back, and its
        ORIGINAL Pallet Series is restored when that number is still free (drawn
        back from the pool) — otherwise the series is blanked and the pool
        re-assigns a fresh one. Whatever it vacated — the shared pallet, the
        adopted series, the location — is freed ONLY if no sibling line still
        uses it, so peeling the LAST line off a pallet does not leave it
        reserved-but-empty. The ledger flag is never touched (it was already
        False, and the pallet stays +1 via any remaining line).
        """
        self.ensure_one()
        picking = self.picking_id
        old_pkg = self.result_package_id

        # DEFENSIVE: never blank a plain line. Only a genuinely merged line — one
        # that carries a capture marker, or is the host sharing its pallet with a
        # marked sibling — may be detached here. The detection fix already keeps
        # the Un-merge button off plain lines; this makes the method safe even if
        # it is ever reached directly.
        marked = self.vifel_premerge_captured or (old_pkg and any(
            (sib.is_pallet_merge or sib.vifel_premerge_captured)
            for sib in (picking.move_line_ids - self)
            if sib.result_package_id == old_pkg))
        if not marked:
            return

        old_series = self.x_studio_pallet_series_id or ''
        old_loc = self.location_dest_id
        restore_series = self._vifel_restore_series_if_free(
            self.vifel_premerge_series)
        vals = {'result_package_id': False,
                'x_studio_pallet_series_id': restore_series or False,
                'vifel_premerge_captured': False,
                'vifel_premerge_series': False,
                'vifel_premerge_location_id': False}
        if pre_location:
            vals['location_dest_id'] = pre_location.id
        self.with_context(skip_pallet_series_sync=True,
                          vifel_pallet_merge=True).write(vals)
        # clear the stale STORED display series only when nothing was restored
        # (its compute only assigns, never clears — same reason the +0 path
        # clears it); a restore re-populates it from the drawn series.
        if not restore_series and 'x_studio_pallet_series_display' in self._fields:
            self.with_context(skip_pallet_series_sync=True,
                              vifel_pallet_merge=True).write(
                {'x_studio_pallet_series_display': False})

        # free the vacated PALLET / LOCATION only if no sibling still uses them.
        #
        # The ADOPTED series (old_series) is DELIBERATELY never recycled here.
        # It belongs to the pallet the line merged onto — the client's dedicated
        # Fixed PSI, or a Multiple-mode special series — NOT to the peeling line,
        # which only borrowed it. Pushing it to the pool re-issues that number to
        # a brand-new pallet (the "Fixed/Multiple PSI getting recycled" bug). A
        # line can only reach this detach while the pallet is still SHARED (a
        # lone sole-owner line reads as plain and cannot un-merge), so the
        # adopted series always still has a holder — there is nothing to free.
        # The line's OWN pre-merge series is handled above by restore-if-free.
        siblings = picking.move_line_ids - self
        if old_pkg and old_pkg not in siblings.mapped('result_package_id'):
            self._free_pallet_if_unused(picking.id, old_pkg.id)
        new_loc = pre_location or old_loc
        if old_loc and old_loc != new_loc \
                and old_loc not in siblings.mapped('location_dest_id'):
            self._free_location_if_unused(picking.id, old_loc.id)
