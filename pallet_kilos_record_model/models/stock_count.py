# -*- coding: utf-8 -*-
"""Stock counts (Inventory > Apply) on the Pallet Kilos ledger.

The ledger (Pallet Monitoring, Billing) is a running sum of document rows:
RR in, WR out, returns and approved adjustment requests. A stock count applied
from the Inventory screen - zeroing an owner, re-uploading an opening balance,
any "Apply" on counted quantities - changed the stock but wrote nothing to the
ledger, so Pallet Monitoring kept the old balance (WONDER MEATS (FG), 10-28:
zeroed 118,287.5 kg and re-uploaded 18,429 kg, ledger never moved).

Now every Apply posts ONE "stock count" row per owner partition
(owner, warehouse, blast freezer or not) with the change in pallets, kg,
quantity and packs:

* the change is measured on the owner's physical stock before and after the
  Apply, so it is exactly what the count did;
* when the Apply leaves the partition with no stock at all (a zeroing), the
  row resets the ledger to 0 instead - the ledger may have drifted from the
  physical stock, and a zeroing means "start again from 0";
* owners with no ledger rows yet are skipped - their first upload is still
  booked by "Import opening balances" (it would double otherwise).

Values sit in the received / withdrawn columns (like the opening-balance
row), not in adjustment_*: "Re-sync pallet counts" wipes and rebuilds the
adjustment_* columns, it never touches received / withdrawn of a row without
a document.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

STOCK_COUNT_PREFIX = 'stock count: '
_MEASURES = ('pallets', 'kilos', 'packaging', 'units')
_PKR = 'pallet_kilos_record_model.pallet_kilos_record_model'


class PalletKilosStockCount(models.Model):
    _inherit = _PKR

    is_stock_count = fields.Boolean(
        string="Stock Count", readonly=True, index=True,
        help="Row posted by a stock count (Inventory > Apply): zeroing, "
             "opening-balance re-upload or counted quantity change.")
    stock_count_move_line_ids = fields.One2many(
        'stock.move.line', 'pkr_stock_count_id',
        string="Stock Count Moves", readonly=True)

    # ------------------------------------------------------------ helpers --
    def _pkr_doc_labels(self):
        """(RR# text, WR# text) for the XLSX reports. Document rows: the
        document name, as before. Stock-count rows: 'STOCK COUNT' on the side
        that moved, so the jump in the balance is explained on the row."""
        self.ensure_one()
        ref = self.record_reference
        if ref:
            name = ref.name or ''
            return (name if 'RR' in name else '', name if 'WR' in name else '')
        if self.is_stock_count:
            got_in = any((self.pallets_received, self.kilos_received,
                          self.packaging_received, self.units_received))
            got_out = any((self.pallets_withdrawn, self.kilos_withdrawn,
                           self.packaging_withdrawn, self.units_withdrawn))
            return ('STOCK COUNT' if got_in else '', 'STOCK COUNT' if got_out else '')
        return ('', '')

    @api.model
    def _pkr_partition_domain(self, owner_id, warehouse_id, is_bf):
        return [('owner_id', '=', owner_id), ('warehouse', '=', warehouse_id),
                ('is_blast_freezer', '=', bool(is_bf)), ('active', '=', True)]

    @api.model
    def _pkr_physical(self, owner_id, warehouse_id, is_bf):
        """Owner's stock in one partition: pallets (distinct packages), kg,
        quantity (2nd UoM) and packs."""
        groups = self.env['stock.quant'].sudo().read_group(
            [('owner_id', '=', owner_id), ('quantity', '>', 0),
             ('location_id.usage', '=', 'internal'),
             ('location_id.warehouse_id', '=', warehouse_id),
             ('location_is_bf', '=', bool(is_bf))],
            ['quantity:sum', 'x_studio_2nd_uom:sum', 'x_studio_total_units:sum'],
            ['package_id'], lazy=False)
        res = dict.fromkeys(_MEASURES, 0.0)
        for g in groups:
            if g['package_id']:
                res['pallets'] += 1
            res['kilos'] += g['quantity'] or 0.0
            res['packaging'] += g['x_studio_2nd_uom'] or 0.0
            res['units'] += g['x_studio_total_units'] or 0.0
        return res

    @api.model
    def _pkr_ledger_before(self, owner_id, warehouse_id, is_bf, when):
        """Ledger balance of the partition just before ``when``."""
        prev = self.search(
            self._pkr_partition_domain(owner_id, warehouse_id, is_bf)
            + [('start_time', '<', when)],
            order='start_time desc, id desc', limit=1)
        return {
            'pallets': prev.total_balance_in_pallets or 0.0,
            'kilos': prev.total_balance_in_kilos or 0.0,
            'packaging': prev.total_balance_in_packaging or 0.0,
            'units': prev.total_balance_in_units or 0.0,
        }

    @api.model
    def _pkr_create_stock_count_row(self, owner_id, warehouse_id, is_bf,
                                    when, delta, name):
        """One ledger row carrying ``delta`` (signed, per measure)."""
        def _in(m):
            return delta[m] if delta[m] > 0 else 0.0

        def _out(m):
            return -delta[m] if delta[m] < 0 else 0.0

        vals = {
            'report_no': 'SC-%s-%s' % (warehouse_id, when.strftime('%Y%m%d%H%M%S')),
            'owner_id': owner_id,
            'warehouse': warehouse_id,
            'record_reference': False,
            'readjustment_document': False,
            'is_blast_freezer': bool(is_bf),
            'is_stock_count': True,
            'active': True,
            'start_time': when,
            'end_time': when,
            'truck_type': 'N/A',
            'pallets_received': _in('pallets'),
            'pallets_withdrawn': _out('pallets'),
            'kilos_received': _in('kilos'),
            'kilos_withdrawn': _out('kilos'),
            'packaging_received': _in('packaging'),
            'packaging_withdrawn': _out('packaging'),
            'units_received': _in('units'),
            'units_withdrawn': _out('units'),
            'remarks': (STOCK_COUNT_PREFIX + (name or 'Inventory adjustment'))[:250],
        }
        # create() recalculates the running balances from ``when`` onward
        return self.sudo().create(vals)

    @staticmethod
    def _pkr_is_zero(values):
        return all(abs(values[m]) < 0.0005 for m in _MEASURES)

    # ------------------------------------------------------ live posting --
    @api.model
    def _pkr_post_stock_count(self, before, name, first_line_id):
        """Called after an Apply: ``before`` = {partition: physical}."""
        now = fields.Datetime.now()
        MoveLine = self.env['stock.move.line'].sudo()
        for (owner_id, warehouse_id, is_bf), phys_before in before.items():
            if not self.search_count(
                    self._pkr_partition_domain(owner_id, warehouse_id, is_bf)):
                # no ledger yet: the opening-balance import books it
                continue
            lines = MoveLine.search([
                ('id', '>=', first_line_id), ('state', '=', 'done'),
                ('picking_id', '=', False), ('owner_id', '=', owner_id),
                ('move_id.is_inventory', '=', True),
                ('pkr_stock_count_id', '=', False),
                '|', ('location_id.usage', '=', 'inventory'),
                     ('location_dest_id.usage', '=', 'inventory')])
            lines = lines.filtered(
                lambda l: self._pkr_line_partition(l) == (warehouse_id, bool(is_bf)))
            label = name or (lines[:1].move_id.name) or 'Inventory adjustment'
            phys_after = self._pkr_physical(owner_id, warehouse_id, is_bf)
            if self._pkr_is_zero(phys_after) and not self._pkr_is_zero(phys_before):
                # zeroing: reset the ledger itself to 0
                ledger = self._pkr_ledger_before(owner_id, warehouse_id, is_bf, now)
                delta = {m: -ledger[m] for m in _MEASURES}
                label = '%s (reset to 0)' % label
            else:
                delta = {m: phys_after[m] - phys_before[m] for m in _MEASURES}
            if self._pkr_is_zero(delta):
                continue
            row = self._pkr_create_stock_count_row(
                owner_id, warehouse_id, is_bf, now, delta, label)
            lines.write({'pkr_stock_count_id': row.id})
            _logger.info("Stock count row %s for owner %s / wh %s / bf %s: %s",
                         row.id, owner_id, warehouse_id, is_bf, delta)

    @api.model
    def _pkr_line_partition(self, line):
        loc = (line.location_dest_id if line.location_id.usage == 'inventory'
               else line.location_id)
        return (loc.warehouse_id.id,
                bool(loc['x_studio_is_a_blast_freezer']
                     if 'x_studio_is_a_blast_freezer' in loc._fields else False))

    # --------------------------------------------------------- backfill --
    @api.model
    def _pkr_backfill_stock_count(self, owner_id, date_from, date_to, dry_run=False):
        """Book a stock count that happened BEFORE this hook existed.

        Looks at the owner's Apply moves (picking-less, inventory location <->
        stock, not adjustment-request moves) between ``date_from`` and
        ``date_to`` (UTC) that no ledger row covers yet, per partition:

        * moves OUT of stock (the zeroing)  -> one row resetting the ledger to 0
        * moves INTO stock (the re-upload)  -> one row adding the uploaded
          pallets and kg (from the moves) and quantity / packs (rebuilt per
          pallet: what is still in stock + what WRs took out - what returns
          brought back, i.e. the upload plus any later correction, the same
          base the reset wiped)

        Both rows are dated just before the first ledger row that used an
        uploaded pallet (staff often enter a WR start time earlier than the
        upload), else at the move dates. Returns a list of text lines.
        """
        MoveLine = self.env['stock.move.line'].sudo()
        lines = MoveLine.search([
            ('state', '=', 'done'), ('picking_id', '=', False),
            ('owner_id', '=', owner_id), ('move_id.is_inventory', '=', True),
            ('adjustment_batch_number', '=', False),
            ('pkr_stock_count_id', '=', False),
            ('date', '>=', date_from), ('date', '<=', date_to),
            '|', ('location_id.usage', '=', 'inventory'),
                 ('location_dest_id.usage', '=', 'inventory')],
            order='date asc, id asc')
        report = []
        partitions = {}
        for line in lines:
            key = self._pkr_line_partition(line)
            side = 'in' if line.location_id.usage == 'inventory' else 'out'
            partitions.setdefault(key, {'in': MoveLine, 'out': MoveLine})
            partitions[key][side] |= line

        for (warehouse_id, is_bf), sides in partitions.items():
            outs, ins = sides['out'], sides['in']
            # placement: before the first ledger row that touched an uploaded pallet
            first_date = min((outs | ins).mapped('date'))
            when = first_date
            pkgs = ins.mapped('result_package_id')
            if pkgs:
                # documents validated AFTER the upload that moved an uploaded pallet
                used = MoveLine.search([
                    ('state', '=', 'done'), ('picking_id', '!=', False),
                    ('owner_id', '=', owner_id),
                    ('date', '>=', min(ins.mapped('date'))),
                    '|', ('package_id', 'in', pkgs.ids),
                         ('result_package_id', 'in', pkgs.ids)])
                first_row = self.search(
                    self._pkr_partition_domain(owner_id, warehouse_id, is_bf)
                    + [('record_reference', 'in', used.mapped('picking_id').ids),
                       ('start_time', '>=', first_date - timedelta(days=1))],
                    order='start_time asc, id asc', limit=1)
                if first_row and first_row.start_time < when:
                    when = first_row.start_time
            t_out = when - timedelta(seconds=2)
            t_in = when - timedelta(seconds=1)

            if outs:
                ledger = self._pkr_ledger_before(owner_id, warehouse_id, is_bf, t_out)
                delta = {m: -ledger[m] for m in _MEASURES}
                name = '%s (reset to 0)' % outs[0].move_id.name
                report.append('Zeroing %s: %d lines, %.3f kg out -> ledger reset: %s'
                              % (outs[0].move_id.name, len(outs),
                                 sum(outs.mapped('quantity')), delta))
                if not dry_run:
                    row = self._pkr_create_stock_count_row(
                        owner_id, warehouse_id, is_bf, t_out, delta, name)
                    outs.write({'pkr_stock_count_id': row.id})
            if ins:
                delta = {
                    'pallets': float(len(pkgs)),
                    'kilos': sum(ins.mapped('quantity')),
                    'packaging': 0.0, 'units': 0.0,
                }
                qty, packs = self._pkr_rebuild_upload_qty_packs(owner_id, ins)
                delta['packaging'], delta['units'] = qty, packs
                name = ins[0].move_id.name
                report.append('Upload %s: %d lines -> %s' % (name, len(ins), delta))
                if not dry_run:
                    row = self._pkr_create_stock_count_row(
                        owner_id, warehouse_id, is_bf, t_in, delta, name)
                    ins.write({'pkr_stock_count_id': row.id})
            report.append('Rows dated %s / %s (UTC)' % (t_out, t_in))
        if not partitions:
            report.append('No unbooked stock-count moves found.')
        return report

    @api.model
    def _pkr_rebuild_upload_qty_packs(self, owner_id, in_lines):
        """Quantity and packs of the uploaded pallets: in stock now + taken
        out by WRs - brought back by returns, per (package, lot)."""
        MoveLine = self.env['stock.move.line'].sudo()
        Quant = self.env['stock.quant'].sudo()
        start = min(in_lines.mapped('date'))
        qty = packs = 0.0
        seen = set()
        for line in in_lines:
            key = (line.result_package_id.id, line.lot_id.id, line.product_id.id)
            if key in seen or not line.result_package_id:
                continue
            seen.add(key)
            base = [('owner_id', '=', owner_id), ('lot_id', '=', line.lot_id.id),
                    ('product_id', '=', line.product_id.id)]
            for q in Quant.search(base + [('package_id', '=', key[0]),
                                          ('quantity', '>', 0),
                                          ('location_id.usage', '=', 'internal')]):
                qty += q.x_studio_2nd_uom or 0.0
                packs += q.x_studio_total_units or 0.0
            for ml in MoveLine.search(base + [
                    ('state', '=', 'done'), ('date', '>=', start),
                    ('package_id', '=', key[0]),
                    ('picking_id.picking_type_id.code', '=', 'outgoing')]):
                qty += ml.x_studio_affected_2nd_uom or 0.0
                packs += ml.x_studio_withdraw_units or 0.0
            for ml in MoveLine.search(base + [
                    ('state', '=', 'done'), ('date', '>=', start),
                    ('result_package_id', '=', key[0]),
                    ('picking_id.picking_type_id.code', '=', 'incoming')]):
                qty -= ml.x_studio_2nd_uom or 0.0
                packs -= ml.x_studio_total_units or 0.0
        return qty, packs


class StockMoveLinePkrStockCount(models.Model):
    _inherit = 'stock.move.line'

    pkr_stock_count_id = fields.Many2one(
        _PKR, string="Stock Count Ledger Row", readonly=True, index=True,
        ondelete='set null', copy=False)


class StockQuantPkrStockCount(models.Model):
    _inherit = 'stock.quant'

    def _apply_inventory(self):
        if self.env.context.get('pkr_skip_stock_count'):
            return super()._apply_inventory()
        PKR = self.env[_PKR].sudo()
        before = {}
        for quant in self:
            loc = quant.location_id
            if not quant.owner_id or loc.usage != 'internal' or not loc.warehouse_id:
                continue
            key = (quant.owner_id.id, loc.warehouse_id.id, bool(quant.location_is_bf))
            if key not in before:
                before[key] = PKR._pkr_physical(*key)
        self.env.cr.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM stock_move_line")
        first_line_id = self.env.cr.fetchone()[0]
        name = self.env.context.get('inventory_name')
        res = super()._apply_inventory()
        if before:
            PKR._pkr_post_stock_count(before, name, first_line_id)
        return res
