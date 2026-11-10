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
    REUPLOAD_WINDOW_DAYS = 7

    @api.model
    def _pkr_unbooked_apply_lines(self, owner_ids=None, date_from=None, date_to=None):
        """Done Inventory > Apply move lines no ledger row covers yet:
        picking-less, inventory location <-> stock, not adjustment-request
        moves (those post their own adjustment) and not relocations."""
        domain = [
            ('state', '=', 'done'), ('picking_id', '=', False),
            ('owner_id', '!=', False), ('move_id.is_inventory', '=', True),
            ('adjustment_batch_number', '=', False),
            ('pkr_stock_count_id', '=', False),
            '|', ('location_id.usage', '=', 'inventory'),
                 ('location_dest_id.usage', '=', 'inventory')]
        if owner_ids:
            domain.append(('owner_id', 'in', list(owner_ids)))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return self.env['stock.move.line'].sudo().search(domain, order='date asc, id asc')

    @api.model
    def _pkr_physical_kg_at(self, owner_id, warehouse_id, is_bf, when, inclusive):
        """Owner's kg in one partition at ``when``, rebuilt from done moves."""
        self.env.cr.execute("""
            SELECT COALESCE(SUM(
                CASE WHEN dl.usage = 'internal' AND dl.warehouse_id = %(wh)s
                          AND COALESCE(dl.x_studio_is_a_blast_freezer, FALSE) = %(bf)s
                     THEN ml.quantity ELSE 0 END
              - CASE WHEN sl.usage = 'internal' AND sl.warehouse_id = %(wh)s
                          AND COALESCE(sl.x_studio_is_a_blast_freezer, FALSE) = %(bf)s
                     THEN ml.quantity ELSE 0 END), 0)
            FROM stock_move_line ml
            JOIN stock_location sl ON sl.id = ml.location_id
            JOIN stock_location dl ON dl.id = ml.location_dest_id
            WHERE ml.state = 'done' AND ml.owner_id = %(owner)s
              AND (ml.date < %(when)s OR (%(incl)s AND ml.date = %(when)s))
        """, {'wh': warehouse_id, 'bf': bool(is_bf), 'owner': owner_id,
              'when': when, 'incl': bool(inclusive)})
        return self.env.cr.fetchone()[0] or 0.0

    @api.model
    def _pkr_find_reuploads(self, owner_ids=None, date_from=None, date_to=None):
        """Past re-uploads no ledger row covers, for every owner.

        Same rule as the live hook, replayed on history. A RE-UPLOAD is
        * a zeroing: one Apply (one transaction = one move-line date) that
          left the owner's partition with no stock, for an owner that was
          already on the ledger (a row created before it), then
        * the Apply(s) that put stock back (pure inflows) within
          REUPLOAD_WINDOW_DAYS after it.
        Apply runs that are not part of a re-upload (one-off count fixes,
        a new client's first opening balance - booked by the OB import) are
        left alone. Returns a list of sessions."""
        lines = self._pkr_unbooked_apply_lines(owner_ids, date_from, date_to)
        # one Apply = one transaction: its moves share create_date (the
        # transaction time); their done dates differ by seconds
        batches = {}
        for line in lines:
            wh, bf = self._pkr_line_partition(line)
            if not wh:
                continue
            key = (line.owner_id.id, wh, bf, line.move_id.create_date)
            batches.setdefault(key, self.env['stock.move.line'].sudo())
            batches[key] |= line
        sessions = []
        open_session = {}
        trusted = {}
        for key in sorted(batches, key=lambda k: (k[0], k[1], k[2], k[3])):
            owner_id, wh, bf, created = key
            blines = batches[key]
            pkey = (owner_id, wh, bf)
            outs = blines.filtered(lambda l: l.location_dest_id.usage == 'inventory')
            ins = blines - outs
            if outs:
                start, end = min(blines.mapped('date')), max(blines.mapped('date'))
                before = self._pkr_physical_kg_at(owner_id, wh, bf, start, False)
                after = self._pkr_physical_kg_at(owner_id, wh, bf, end, True)
                on_ledger = self.search_count(
                    self._pkr_partition_domain(owner_id, wh, bf)
                    + [('create_date', '<', start)])
                if before > 0.0005 and abs(after) < 0.0005 and on_ledger:
                    if pkey not in trusted:
                        # the zeroing test rebuilds stock from moves; only
                        # trust it when that rebuild equals today's stock
                        # (a client change without moves breaks it)
                        now_moves = self._pkr_physical_kg_at(
                            owner_id, wh, bf, fields.Datetime.now(), True)
                        now_quants = self._pkr_physical(owner_id, wh, bf)['kilos']
                        trusted[pkey] = abs(now_moves - now_quants) < 0.01
                    session = {'owner_id': owner_id, 'warehouse_id': wh,
                               'is_bf': bf, 'reset': outs, 'reset_date': start,
                               'uploads': [], 'trusted': trusted[pkey]}
                    sessions.append(session)
                    open_session[pkey] = session
                    if ins:
                        session['uploads'].append(ins)
                else:
                    open_session.pop(pkey, None)
                continue
            session = open_session.get(pkey)
            if session and min(ins.mapped('date')) - session['reset_date'] <= timedelta(
                    days=self.REUPLOAD_WINDOW_DAYS):
                session['uploads'].append(ins)
        return sessions

    @api.model
    def _pkr_backfill_stock_count(self, owner_ids=None, date_from=None,
                                  date_to=None, dry_run=False):
        """Book past re-uploads on the ledger (see _pkr_find_reuploads).

        Per re-upload: one row resetting the ledger to 0, then one row per
        upload with its pallets and kg (from the moves) and quantity / packs
        (rebuilt per pallet: still in stock + taken out by WRs - brought back
        by returns). The rows are dated at the moves, or just before the
        first ledger row that used an uploaded pallet if staff entered that
        document's start time earlier than the upload. Returns text lines."""
        report = []
        partners = self.env['res.partner'].sudo()
        for s in self._pkr_find_reuploads(owner_ids, date_from, date_to):
            owner_id, wh, bf = s['owner_id'], s['warehouse_id'], s['is_bf']
            if not s['trusted']:
                report.append('%s (wh %s%s) - zeroing %s NOT booked: its stock '
                              'history (moves) does not match the stock today, '
                              'check this client by hand'
                              % (self.env['res.partner'].browse(owner_id).name, wh,
                                 ', BF' if bf else '', s['reset_date']))
                continue
            ins_all = self.env['stock.move.line'].sudo()
            for up in s['uploads']:
                ins_all |= up
            when = s['reset_date']
            first_row = self.browse()
            pkgs = ins_all.mapped('result_package_id')
            if pkgs:
                used = self.env['stock.move.line'].sudo().search([
                    ('state', '=', 'done'), ('picking_id', '!=', False),
                    ('owner_id', '=', owner_id),
                    ('date', '>=', min(ins_all.mapped('date'))),
                    '|', ('package_id', 'in', pkgs.ids),
                         ('result_package_id', 'in', pkgs.ids)])
                first_row = self.search(
                    self._pkr_partition_domain(owner_id, wh, bf)
                    + [('record_reference', 'in', used.mapped('picking_id').ids),
                       ('start_time', '>=', when - timedelta(days=1))],
                    order='start_time asc, id asc', limit=1)
            # row times: at the moves, but never after the first row that
            # used an uploaded pallet; reset first, uploads after it, in order
            n = len(s['uploads'])
            cap = first_row.start_time if first_row else None
            t_reset = when if not cap or when < cap else cap - timedelta(seconds=n + 1)
            times = []
            for i, up in enumerate(s['uploads']):
                t = min(up.mapped('date'))
                if cap and t >= cap:
                    t = cap - timedelta(seconds=n - i)
                times.append(max(t, t_reset + timedelta(seconds=i + 1)))

            owner = partners.browse(owner_id)
            head = '%s (wh %s%s)' % (owner.name, wh, ', BF' if bf else '')
            ledger = self._pkr_ledger_before(owner_id, wh, bf, t_reset)
            delta = {m: -ledger[m] for m in _MEASURES}
            name = s['reset'][0].move_id.name
            report.append('%s - zeroing "%s" %s: %d lines, %.3f kg -> ledger reset %s'
                          % (head, name, t_reset, len(s['reset']),
                             sum(s['reset'].mapped('quantity')), delta))
            if not dry_run:
                row = self._pkr_create_stock_count_row(
                    owner_id, wh, bf, t_reset, delta, '%s (reset to 0)' % name)
                s['reset'].write({'pkr_stock_count_id': row.id})
            for up, t in zip(s['uploads'], times):
                qty, packs = self._pkr_rebuild_upload_qty_packs(owner_id, up)
                delta = {'pallets': float(len(up.mapped('result_package_id'))),
                         'kilos': sum(up.mapped('quantity')),
                         'packaging': qty, 'units': packs}
                name = up[0].move_id.name
                report.append('%s - upload "%s" %s: %d lines -> %s'
                              % (head, name, t, len(up), delta))
                if not dry_run:
                    row = self._pkr_create_stock_count_row(
                        owner_id, wh, bf, t, delta, name)
                    up.write({'pkr_stock_count_id': row.id})
        if not report:
            report.append('No unbooked re-uploads found.')
        return report

    def action_preview_past_reuploads(self):
        return self._pkr_reupload_notification(
            self._pkr_backfill_stock_count(dry_run=True), 'Past re-uploads (preview, nothing saved)')

    def action_book_past_reuploads(self):
        return self._pkr_reupload_notification(
            self._pkr_backfill_stock_count(), 'Past re-uploads booked')

    def _pkr_reupload_notification(self, lines, title):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': title, 'message': '\n'.join(lines),
                       'sticky': True, 'type': 'info'},
        }

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
