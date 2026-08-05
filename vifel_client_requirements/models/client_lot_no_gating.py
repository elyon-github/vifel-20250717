# -*- coding: utf-8 -*-
"""Client Lot No. — gating and stamping (Client-Specific Requirement Enh.).

Some clients track their own lot numbers next to VIFEL's internal ones. This
module decides WHEN the column is shown (per the client's profile) and copies
the encoded value onto stock at validation.

The ``client_lot_no`` FIELDS themselves live in ``multiple_relocation``, not
here — see the manifest. They are evidence of what was received; uninstalling
this module must not erase them.
"""
from odoo import api, fields, models


class StockPickingClientLotNo(models.Model):
    _inherit = 'stock.picking'

    show_client_lot_no = fields.Boolean(
        string='Show Client Lot No.',
        compute='_compute_show_client_lot_no',
        help="This client's profile has Show Lot No. enabled.")
    show_batch_no = fields.Boolean(
        string='Show Batch # / Prodcode',
        compute='_compute_show_batch_no',
        help="This client's profile has Show Batch # / Prodcode enabled.")

    @api.depends('partner_id', 'partner_id.vifel_show_lot_no')
    def _compute_show_client_lot_no(self):
        for picking in self:
            picking.show_client_lot_no = bool(
                picking.partner_id.vifel_show_lot_no)

    @api.depends('partner_id', 'partner_id.vifel_show_batch_no')
    def _compute_show_batch_no(self):
        for picking in self:
            picking.show_batch_no = bool(
                picking.partner_id.vifel_show_batch_no)

    def action_detailed_operations(self):
        """Tell the Pallet Breakdown whether to render the Lot No. / Batch # /
        Prodcode columns.

        Core builds this action; the flags are injected into the returned
        context here so core needs no knowledge of the profile switches.
        """
        res = super().action_detailed_operations()
        if isinstance(res, dict) and isinstance(res.get('context'), dict):
            res['context'] = dict(
                res['context'],
                show_client_lot_no=self.show_client_lot_no,
                show_batch_no=self.show_batch_no,
                # Blast freezer has no Merge Pallet feature (no package/PSI), so
                # the Pallet Breakdown hides the "Merged" column there.
                vifel_is_blast_freeze=bool(self.x_studio_is_a_blast_freezer),
                # A non-merge client sees no merge UI at all: the "Merged"
                # column, the Merge / Un-merge buttons AND the "Merge Selected"
                # header all key on this flag. It MUST be a context key, not a
                # field — column_invisible is evaluated without a record in
                # scope, so a field reference there crashes the list.
                vifel_can_merge=bool(self.partner_id.vifel_can_merge_pallets))
        return res

    def button_validate(self):
        res = super().button_validate()
        self._vifel_stamp_client_lot_no()
        self._vifel_stamp_batch_prodcode()
        return res

    def _vifel_stamp_client_lot_no(self):
        """Copy each line's Lot No. onto the quants it landed on.

        Matched on the quant identity (product / destination location / lot /
        package / owner). Several lines carrying different Lot Nos can land on
        one quant — last write wins, by design.
        """
        Quant = self.env['stock.quant']
        for picking in self:
            # A present Lot No. is always persisted (the profile flag governs
            # DISPLAY, not whether an entered value is kept — gating the write
            # on it could silently drop data). Only cheap, always-correct
            # guards here: done + incoming; empty lines short-circuit below.
            if picking.state != 'done':
                continue
            if picking.picking_type_id.code != 'incoming':
                continue
            for line in picking.move_line_ids:
                lot_no = (line.client_lot_no or '').strip()
                if not lot_no:
                    continue
                quants = Quant.search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.location_dest_id.id),
                    ('lot_id', '=', line.lot_id.id),
                    ('package_id', '=', line.result_package_id.id),
                    ('owner_id', '=',
                     line.owner_id.id or picking.partner_id.id),
                ])
                if quants:
                    quants.write({'client_lot_no': lot_no})

    # Fixed 3-letter uppercase month abbreviations — never locale-dependent,
    # unlike strftime('%b'), so the Prodcode is stable on any server.
    _VIFEL_MONTHS = ('', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL',
                     'AUG', 'SEP', 'OCT', 'NOV', 'DEC')

    def _vifel_format_prodcode(self, expiration_date, batch_no, building_short):
        """DDMONYYYY + Batch# + building-shortname, e.g. 18MAY202699M.

        The date segment is the EXPIRATION date. It is dropped when there is no
        expiration date (per the client ruling): the code is then just Batch# +
        building shortname.
        """
        code = ''
        if expiration_date:
            code += '%02d%s%04d' % (
                expiration_date.day,
                self._VIFEL_MONTHS[expiration_date.month],
                expiration_date.year)
        code += (batch_no or '').strip()
        code += (building_short or '').strip()
        return code

    def _vifel_building_short(self, line, quant):
        """Building segment for the Prodcode — always 'M' (client ruling).

        Per the client, the building portion of the Prodcode is fixed to 'M'
        regardless of the quant's x_studio_building_dropped or the destination
        building's short name. (line / quant are kept in the signature so the
        caller is untouched.)
        """
        return 'M'

    def _vifel_stamp_batch_prodcode(self):
        """Freeze each receiving line's Batch # into a Prodcode on its quants.

        The building segment comes from ``_vifel_building_short``, which is
        fixed to 'M' (client ruling). Quant match is the same identity used for
        Lot No.; last write wins when several lines share a quant.
        """
        Quant = self.env['stock.quant']
        for picking in self:
            # A present Batch # is always baked into a Prodcode (profile flag =
            # display only). Cheap, always-correct guards: done + incoming;
            # empty-batch lines short-circuit below.
            if picking.state != 'done':
                continue
            if picking.picking_type_id.code != 'incoming':
                continue
            for line in picking.move_line_ids:
                batch = (line.batch_no or '').strip()
                if not batch:
                    continue
                quants = Quant.search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.location_dest_id.id),
                    ('lot_id', '=', line.lot_id.id),
                    ('package_id', '=', line.result_package_id.id),
                    ('owner_id', '=',
                     line.owner_id.id or picking.partner_id.id),
                ])
                for quant in quants:
                    quant.write({
                        'batch_no': batch,
                        'prodcode': self._vifel_format_prodcode(
                            line.x_studio_expiration_date, batch,
                            self._vifel_building_short(line, quant)),
                    })
