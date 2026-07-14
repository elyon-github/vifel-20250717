# -*- coding: utf-8 -*-
"""VIFEL Health Monitor.

Every check is a `_check_<code>` method returning a list of finding dicts:
    {'dedup_key': str,          # stable identity of the problem instance
     'detail': str,             # human explanation
     'owner_id': int|False,     # client, when the finding belongs to one
     'res_model': str|False,    # linked record (Open button), optional
     'res_id': int|False,
     'reference': str,          # short display reference (pallet, doc, ...)
     'measured': str,           # the offending value(s)
     'severity': str|None}      # override; defaults to the check's severity

The runner reconciles each check's current set against stored findings by
dedup_key: unseen keys are created as 'new', re-seen findings bump
last_seen ('new' from a previous run graduates to 'open'), and findings
that stopped matching are auto-'resolved'. Ignored findings keep their
lifecycle but never count toward alerts.

All checks are read-only SQL/ORM probes validated against production-clone
data before inclusion — the monitor never modifies operational records.
"""
import ast
import logging
import time

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

CATEGORIES = [
    ('ledger', 'Ledger'),
    ('identity', 'Pallet Identity'),
    ('stock', 'Stock Records'),
    ('process', 'Process & Reservations'),
    ('system', 'System Watchdog'),
]
SEVERITIES = [
    ('critical', 'Critical'),
    ('warning', 'Warning'),
    ('info', 'Info'),
]


class VifelHealthCheck(models.Model):
    _name = 'vifel.health.check'
    _description = 'VIFEL Health Check'
    _order = 'sequence, id'

    code = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, translate=False)
    description = fields.Text(readonly=True)
    category = fields.Selection(CATEGORIES, required=True, default='stock')
    severity = fields.Selection(SEVERITIES, required=True, default='warning',
                                help='Default severity of this check\'s findings.')
    active = fields.Boolean(default=True,
                            help='Inactive checks are skipped by the runner.')
    sequence = fields.Integer(default=10)
    last_run = fields.Datetime(readonly=True)
    last_duration_ms = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)
    finding_ids = fields.One2many('vifel.health.finding', 'check_id')
    open_count = fields.Integer(compute='_compute_counts', string='Open')
    new_count = fields.Integer(compute='_compute_counts', string='New')
    ignored_count = fields.Integer(compute='_compute_counts', string='Ignored')
    resolved_last_run = fields.Integer(readonly=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Check code must be unique.'),
    ]

    def _compute_counts(self):
        groups = self.env['vifel.health.finding'].read_group(
            [('check_id', 'in', self.ids), ('state', '!=', 'resolved')],
            ['check_id', 'state', 'ignored'],
            ['check_id', 'state', 'ignored'], lazy=False)
        data = {}
        for g in groups:
            cid = g['check_id'][0]
            bucket = data.setdefault(cid, {'open': 0, 'new': 0, 'ignored': 0})
            if g['ignored']:
                bucket['ignored'] += g['__count']
            else:
                bucket['open'] += g['__count']
                if g['state'] == 'new':
                    bucket['new'] += g['__count']
        for check in self:
            bucket = data.get(check.id, {'open': 0, 'new': 0, 'ignored': 0})
            check.open_count = bucket['open']
            check.new_count = bucket['new']
            check.ignored_count = bucket['ignored']

    def action_view_findings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Findings') % self.name,
            'res_model': 'vifel.health.finding',
            'view_mode': 'tree,form',
            'domain': [('check_id', '=', self.id)],
            'context': {'search_default_unresolved': 1},
        }

    def action_run_single(self):
        self.ensure_one()
        run = self.env['vifel.health.run'].create({'trigger': 'manual'})
        run._execute(self)
        return self.action_view_findings()

    # ------------------------------------------------------------------
    # Runner entry points
    # ------------------------------------------------------------------
    @api.model
    def run_all_checks(self, trigger='cron'):
        checks = self.search([('active', '=', True)])
        run = self.env['vifel.health.run'].create({'trigger': trigger})
        run._execute(checks)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Health Checks Complete'),
                'message': run.summary or _('All checks passed.'),
                'type': 'warning' if run.new_findings else 'success',
                'sticky': bool(run.new_findings),
            },
        }

    # ------------------------------------------------------------------
    # Helpers shared by checks
    # ------------------------------------------------------------------
    def _param(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(
            'vifel_health.%s' % key, default)

    def _sql(self, query, params=None):
        # flush pending ORM writes so raw SQL sees the true current state
        # (matters when Run Now follows in-transaction changes)
        self.env.flush_all()
        self.env.cr.execute(query, params or ())
        return self.env.cr.fetchall()

    def _owner_name(self, owner_id, cache={}):
        if owner_id not in cache:
            cache[owner_id] = self.env['res.partner'].browse(owner_id).name \
                if owner_id else ''
        return cache[owner_id]

    # ==================================================================
    # LEDGER
    # ==================================================================
    def _check_pallet_drift(self):
        rows = self._sql("""
            WITH ledger AS (
                SELECT owner_id, warehouse,
                       COALESCE(is_blast_freezer, false) AS bf,
                       SUM(COALESCE(pallets_received,0)
                           - COALESCE(pallets_withdrawn,0)
                           + COALESCE(adjustment_pallets,0)) AS led
                FROM pallet_kilos_record_model_pallet_kilos_record_model
                WHERE active GROUP BY 1, 2, 3),
            phys AS (
                SELECT q.owner_id, l.warehouse_id AS wh, false AS bf,
                       count(DISTINCT q.package_id) AS n
                FROM stock_quant q
                JOIN stock_location l ON l.id = q.location_id
                WHERE q.quantity > 0 AND l.usage = 'internal'
                  AND q.package_id IS NOT NULL
                GROUP BY 1, 2
                UNION ALL
                SELECT q.owner_id, l.warehouse_id, true,
                       count(DISTINCT q.bf_pallet_char)
                FROM stock_quant q
                JOIN stock_location l ON l.id = q.location_id
                WHERE q.quantity > 0 AND l.usage = 'internal'
                  AND q.location_is_bf = true
                  AND COALESCE(q.bf_pallet_char, '') <> ''
                GROUP BY 1, 2)
            SELECT COALESCE(ledger.owner_id, phys.owner_id),
                   COALESCE(ledger.warehouse, phys.wh),
                   COALESCE(ledger.bf, phys.bf),
                   COALESCE(ledger.led, 0), COALESCE(phys.n, 0)
            FROM ledger
            FULL JOIN phys ON phys.owner_id = ledger.owner_id
                          AND phys.wh = ledger.warehouse
                          AND phys.bf = ledger.bf
            WHERE round(COALESCE(ledger.led, 0)) <> COALESCE(phys.n, 0)
        """)
        out = []
        for owner_id, wh, bf, led, actual in rows:
            out.append({
                'dedup_key': 'pallet_drift:%s:%s:%s' % (owner_id, wh, bf),
                'owner_id': owner_id,
                'reference': '%s%s' % (self._owner_name(owner_id),
                                       ' (BF)' if bf else ''),
                'detail': 'Pallet ledger %g vs actual %g distinct pallet(s) '
                          'in stock (drift %+g).' % (led, actual, led - actual),
                'measured': '%+g' % (led - actual),
                'quant_domain': repr([
                    ('owner_id', '=', owner_id),
                    ('quantity', '>', 0),
                    ('location_id.usage', '=', 'internal'),
                    ('location_id.warehouse_id', '=', wh),
                    ('location_is_bf', '=', bf)]),
            })
        return out

    def _check_kg_pack_drift(self):
        rows = self._sql("""
            WITH latest AS (
                SELECT DISTINCT ON (owner_id, warehouse,
                                    COALESCE(is_blast_freezer, false))
                       owner_id, warehouse,
                       COALESCE(is_blast_freezer, false) AS bf,
                       COALESCE(total_balance_in_kilos, 0) AS tk,
                       COALESCE(total_balance_in_packaging, 0) AS tp
                FROM pallet_kilos_record_model_pallet_kilos_record_model
                WHERE active
                ORDER BY owner_id, warehouse,
                         COALESCE(is_blast_freezer, false),
                         start_time DESC, id DESC),
            phys AS (
                SELECT q.owner_id, l.warehouse_id AS wh,
                       COALESCE(q.location_is_bf, false) AS bf,
                       SUM(q.quantity) AS kg,
                       SUM(COALESCE(q.x_studio_2nd_uom, 0)) AS packs
                FROM stock_quant q
                JOIN stock_location l ON l.id = q.location_id
                WHERE q.quantity > 0 AND l.usage = 'internal'
                GROUP BY 1, 2, 3)
            SELECT COALESCE(latest.owner_id, phys.owner_id),
                   COALESCE(latest.warehouse, phys.wh),
                   COALESCE(latest.bf, phys.bf),
                   COALESCE(latest.tk, 0), COALESCE(phys.kg, 0),
                   COALESCE(latest.tp, 0), COALESCE(phys.packs, 0)
            FROM latest
            FULL JOIN phys ON phys.owner_id = latest.owner_id
                          AND phys.wh = latest.warehouse
                          AND phys.bf = latest.bf
            WHERE abs(COALESCE(latest.tk, 0) - COALESCE(phys.kg, 0)) > 0.5
               OR abs(COALESCE(latest.tp, 0) - COALESCE(phys.packs, 0)) > 0.5
        """)
        out = []
        for owner_id, wh, bf, tk, kg, tp, packs in rows:
            bits = []
            if abs(tk - kg) > 0.5:
                bits.append('KG ledger %.1f vs stock %.1f (%+.1f)'
                            % (tk, kg, tk - kg))
            if abs(tp - packs) > 0.5:
                bits.append('Packaging ledger %.1f vs stock %.1f (%+.1f)'
                            % (tp, packs, tp - packs))
            out.append({
                'dedup_key': 'kg_drift:%s:%s:%s' % (owner_id, wh, bf),
                'owner_id': owner_id,
                'reference': '%s%s' % (self._owner_name(owner_id),
                                       ' (BF)' if bf else ''),
                'detail': '; '.join(bits),
                'measured': '%+.1f kg' % (tk - kg),
                'quant_domain': repr([
                    ('owner_id', '=', owner_id),
                    ('quantity', '>', 0),
                    ('location_id.usage', '=', 'internal'),
                    ('location_id.warehouse_id', '=', wh),
                    ('location_is_bf', '=', bf)]),
            })
        return out

    def _check_pkr_coverage(self):
        missing = self._sql("""
            SELECT sp.id, sp.name FROM stock_picking sp
            JOIN stock_picking_type pt ON pt.id = sp.picking_type_id
            WHERE sp.state = 'done'
              AND pt.code IN ('incoming', 'outgoing')
              AND COALESCE(sp.x_studio_voided, false) = false
              AND COALESCE(sp.x_studio_for_revision, false) = false
              AND NOT EXISTS (
                  SELECT 1
                  FROM pallet_kilos_record_model_pallet_kilos_record_model p
                  WHERE p.active AND (p.record_reference = sp.id
                                      OR p.readjustment_document = sp.id))
        """)
        dups = self._sql("""
            SELECT p.record_reference, count(*), min(sp.name)
            FROM pallet_kilos_record_model_pallet_kilos_record_model p
            JOIN stock_picking sp ON sp.id = p.record_reference
            WHERE p.active AND p.record_reference IS NOT NULL
            GROUP BY p.record_reference HAVING count(*) > 1
        """)
        out = []
        for pick_id, name in missing:
            out.append({
                'dedup_key': 'pkr_missing:%s' % pick_id,
                'res_model': 'stock.picking', 'res_id': pick_id,
                'reference': name,
                'detail': 'Validated, non-voided document has NO active '
                          'Pallet Kilos Record row — it is not counted in '
                          'the ledger.',
                'measured': 'missing',
            })
        for ref_id, n, name in dups:
            out.append({
                'dedup_key': 'pkr_dup:%s' % ref_id,
                'res_model': 'stock.picking', 'res_id': ref_id,
                'reference': name,
                'detail': 'Document has %d active Pallet Kilos Record rows '
                          '— it is counted more than once.' % n,
                'measured': '%d rows' % n,
            })
        return out

    def _check_balance_continuity(self):
        rows = self._sql("""
            WITH r AS (
                SELECT id, owner_id, report_no,
                       total_balance_in_pallets AS tp,
                       total_balance_in_kilos AS tk,
                       COALESCE(pallets_received,0)
                         - COALESCE(pallets_withdrawn,0)
                         + COALESCE(adjustment_pallets,0) AS fp,
                       COALESCE(kilos_received,0)
                         - COALESCE(kilos_withdrawn,0)
                         + COALESCE(adjustment_kilos,0) AS fk,
                       lag(total_balance_in_pallets) OVER w AS pp,
                       lag(total_balance_in_kilos) OVER w AS pk
                FROM pallet_kilos_record_model_pallet_kilos_record_model
                WHERE active
                WINDOW w AS (PARTITION BY owner_id, warehouse,
                                          COALESCE(is_blast_freezer, false)
                             ORDER BY start_time, id))
            SELECT id, owner_id, report_no,
                   COALESCE(tp,0), COALESCE(pp,0) + COALESCE(fp,0),
                   COALESCE(tk,0), COALESCE(pk,0) + COALESCE(fk,0)
            FROM r
            WHERE pp IS NOT NULL
              AND (abs(COALESCE(tp,0) - (COALESCE(pp,0) + COALESCE(fp,0))) > 0.01
                   OR abs(COALESCE(tk,0) - (COALESCE(pk,0) + COALESCE(fk,0))) > 0.5)
        """)
        out = []
        for rec_id, owner_id, report_no, tp, ep, tk, ek in rows:
            bits = []
            if abs(tp - ep) > 0.01:
                bits.append('pallets %g (expected %g)' % (tp, ep))
            if abs(tk - ek) > 0.5:
                bits.append('kilos %.1f (expected %.1f)' % (tk, ek))
            out.append({
                'dedup_key': 'continuity:%s' % rec_id,
                'owner_id': owner_id,
                'res_model':
                    'pallet_kilos_record_model.pallet_kilos_record_model',
                'res_id': rec_id,
                'reference': report_no or ('PKR #%s' % rec_id),
                'detail': 'Running balance breaks the previous-row identity: '
                          + '; '.join(bits)
                          + '. Recompute Balances repairs this partition.',
                'measured': '; '.join(bits),
            })
        return out

    # ==================================================================
    # PALLET IDENTITY
    # ==================================================================
    def _check_split_psi(self):
        rows = self._sql("""
            SELECT q.owner_id, q.x_studio_pallet_series_id,
                   count(DISTINCT q.package_id),
                   string_agg(DISTINCT pkg.name, ', ')
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            JOIN stock_quant_package pkg ON pkg.id = q.package_id
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND q.x_studio_pallet_series_id IS NOT NULL
              AND q.x_studio_pallet_series_id <> ''
            GROUP BY 1, 2 HAVING count(DISTINCT q.package_id) > 1
        """)
        return [{
            'dedup_key': 'split:%s:%s' % (owner_id, psi),
            'owner_id': owner_id,
            'reference': psi,
            'detail': 'Series %s is spread across %d pallets: %s. A pallet '
                      'series identifies ONE physical pallet.'
                      % (psi, n, pkgs),
            'measured': '%d pallets' % n,
            'quant_domain': repr([
                ('owner_id', '=', owner_id),
                ('x_studio_pallet_series_id', '=', psi),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal')]),
        } for owner_id, psi, n, pkgs in rows]

    def _check_package_two_locations(self):
        rows = self._sql("""
            SELECT q.package_id, pkg.name, count(DISTINCT q.location_id),
                   string_agg(DISTINCT l.complete_name, ' | ')
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            JOIN stock_quant_package pkg ON pkg.id = q.package_id
            WHERE l.usage = 'internal' AND q.quantity > 0
            GROUP BY 1, 2 HAVING count(DISTINCT q.location_id) > 1
        """)
        return [{
            'dedup_key': 'pkg2loc:%s' % pkg_id,
            'res_model': 'stock.quant.package', 'res_id': pkg_id,
            'reference': name,
            'detail': 'Pallet %s has stock in %d locations at once: %s.'
                      % (name, n, locs),
            'measured': '%d locations' % n,
            'quant_domain': repr([
                ('package_id', '=', pkg_id), ('quantity', '>', 0)]),
        } for pkg_id, name, n, locs in rows]

    def _check_blank_psi(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id, pkg.name, l.complete_name
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            JOIN stock_quant_package pkg ON pkg.id = q.package_id
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND COALESCE(q.x_studio_pallet_series_id, '') = ''
        """)
        return [{
            'dedup_key': 'blankpsi:%s' % quant_id,
            'owner_id': owner_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': pkg_name,
            'detail': 'Stocked quant on pallet %s at %s has NO pallet '
                      'series (disappearing-series signature).'
                      % (pkg_name, loc),
            'measured': 'blank PSI',
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, owner_id, pkg_name, loc in rows]

    def _check_blank_bf_text(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id, l.complete_name
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE q.location_is_bf = true AND q.quantity > 0
              AND COALESCE(q.bf_pallet_char, '') = ''
        """)
        return [{
            'dedup_key': 'blankbf:%s' % quant_id,
            'owner_id': owner_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': loc,
            'detail': 'Blast-freeze stock at %s has NO Pallet Text — BF '
                      'identity and withdrawal counting depend on it.' % loc,
            'measured': 'blank BF text',
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, owner_id, loc in rows]

    # ==================================================================
    # STOCK RECORDS
    # ==================================================================
    def _check_negative_stock(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id, q.quantity, l.complete_name,
                   COALESCE(q.x_studio_pallet_series_id,
                            q.bf_pallet_char, '')
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE l.usage = 'internal' AND q.quantity < 0
        """)
        return [{
            'dedup_key': 'negstock:%s' % quant_id,
            'owner_id': owner_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': label or loc,
            'detail': 'Negative stock (%.2f KG) at %s — a validation was '
                      'forced beyond available stock.' % (qty, loc),
            'measured': '%.2f kg' % qty,
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, owner_id, qty, loc, label in rows]

    def _check_ownerless_stock(self):
        rows = self._sql("""
            SELECT q.id, q.quantity, l.complete_name,
                   COALESCE(q.x_studio_pallet_series_id,
                            q.bf_pallet_char, '')
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND q.owner_id IS NULL
        """)
        return [{
            'dedup_key': 'noowner:%s' % quant_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': label or loc,
            'detail': 'Stocked quant (%.2f KG) at %s has NO owner — '
                      'unbilled cold storage.' % (qty, loc),
            'measured': '%.2f kg' % qty,
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, qty, loc, label in rows]

    def _check_referenceless_stock(self):
        rows = self._sql("""
            SELECT q.owner_id, count(*), SUM(q.quantity)
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND q.package_id IS NOT NULL
              AND q.x_studio_record_reference IS NULL
              AND q.original_record_reference IS NULL
              AND q.x_studio_opening_balance_record_reference IS NULL
            GROUP BY 1
        """)
        return [{
            'dedup_key': 'noref:%s' % owner_id,
            'owner_id': owner_id,
            'reference': self._owner_name(owner_id),
            'detail': '%d stocked packaged quant(s) (%.1f KG) carry no '
                      'record reference at all (and are not opening-balance '
                      'stock) — PKR attribution for corrections degrades to '
                      'the latest-row fallback. Most are relocation-created '
                      'quants; the admin "Re-sync Details From Origin" '
                      'action on the quants can repair the traceable ones.'
                      % (n, kg or 0),
            'measured': '%d quants' % n,
            'quant_domain': repr([
                ('owner_id', '=', owner_id),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
                ('package_id', '!=', False),
                ('x_studio_record_reference', '=', False),
                ('original_record_reference', '=', False),
                ('x_studio_opening_balance_record_reference', '=', False)]),
        } for owner_id, n, kg in rows]

    def _check_zero_with_packs(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id,
                   COALESCE(q.x_studio_2nd_uom, 0),
                   COALESCE(q.x_studio_total_units, 0),
                   COALESCE(q.x_studio_pallet_series_id,
                            q.bf_pallet_char, '')
            FROM stock_quant q
            WHERE round(q.quantity::numeric, 6) = 0
              AND (COALESCE(q.x_studio_2nd_uom, 0) > 0
                   OR COALESCE(q.x_studio_total_units, 0) > 0)
        """)
        return [{
            'dedup_key': 'zeropacks:%s' % quant_id,
            'owner_id': owner_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': label,
            'detail': 'Quant has 0 KG but still shows %.1f packaging / '
                      '%.1f packs — inconsistent zeros distort pack-based '
                      'reports.' % (packs, units),
            'measured': '%.1f packs' % packs,
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, owner_id, packs, units, label in rows]

    def _check_stuck_zero_quants(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id,
                   COALESCE(q.x_studio_pallet_series_id,
                            q.bf_pallet_char, ''),
                   q.reserved_quantity, COALESCE(q.inventory_quantity, 0),
                   q.user_id
            FROM stock_quant q
            WHERE round(q.quantity::numeric, 6) = 0
              AND (round(q.reserved_quantity::numeric, 6) <> 0
                   OR round(COALESCE(q.inventory_quantity, 0)::numeric, 6) <> 0
                   OR q.user_id IS NOT NULL)
        """)
        out = []
        for quant_id, owner_id, label, reserved, inv_qty, user_id in rows:
            reasons = []
            if reserved:
                reasons.append('reserved %.2f' % reserved)
            if inv_qty:
                reasons.append('stale inventory count %.2f' % inv_qty)
            if user_id:
                reasons.append('assigned counter')
            out.append({
                'dedup_key': 'stuckzero:%s' % quant_id,
                'owner_id': owner_id,
                'res_model': 'stock.quant', 'res_id': quant_id,
                'reference': label,
                'detail': 'Dead 0-KG quant the zero-quant sweeper cannot '
                          'delete (%s).' % ', '.join(reasons),
                'measured': ', '.join(reasons),
                'quant_domain': repr([('id', '=', quant_id)]),
            })
        return out

    def _check_owner_mismatch(self):
        """Stock whose owner no longer matches where it came from — the
        changed-owner-on-return pattern (M/RR/03721): three angles.

        1. Stocked quants whose owner differs from their record-reference
           document's owner (aggregated per document-owner -> quant-owner
           pair).
        2. Validated RETURN documents whose owner differs from the parent
           document they return to — the root event that creates angle 1.
        3. One lot stocked under more than one owner at once — the physical
           end state when a re-owned return merges back beside original
           stock (0 today; tripwire).
        """
        out = []
        # -- 1. quant owner vs reference-document owner (per owner pair) --
        rows = self._sql("""
            SELECT sp.owner_id, q.owner_id,
                   array_agg(q.id), count(*), SUM(q.quantity)
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            JOIN stock_picking sp ON sp.id = q.x_studio_record_reference
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND sp.owner_id IS NOT NULL AND q.owner_id IS NOT NULL
              AND q.owner_id <> sp.owner_id
            GROUP BY 1, 2
        """)
        for doc_owner, quant_owner, quant_ids, n, kg in rows:
            out.append({
                'dedup_key': 'ownermm:pair:%s:%s' % (doc_owner, quant_owner),
                'owner_id': doc_owner,
                'reference': '%s → %s' % (self._owner_name(doc_owner),
                                          self._owner_name(quant_owner)),
                'detail': '%d stocked quant(s) (%.1f KG) reference documents '
                          'of %s but are owned by %s — the stock changed '
                          'owner after receipt.'
                          % (n, kg or 0, self._owner_name(doc_owner),
                             self._owner_name(quant_owner)),
                'measured': '%d quants' % n,
                'quant_domain': repr([('id', 'in', sorted(quant_ids))]),
            })
        # -- 2. return documents whose owner differs from the parent -----
        rows = self._sql("""
            SELECT child.id, child.name, child.owner_id,
                   parent.name, parent.owner_id
            FROM stock_picking child
            JOIN stock_picking parent ON parent.id = child.return_id
            WHERE child.state = 'done'
              AND child.owner_id IS NOT NULL
              AND parent.owner_id IS NOT NULL
              AND child.owner_id <> parent.owner_id
        """)
        for pick_id, name, c_owner, p_name, p_owner in rows:
            out.append({
                'dedup_key': 'ownermm:return:%s' % pick_id,
                'owner_id': p_owner,
                'res_model': 'stock.picking', 'res_id': pick_id,
                'reference': name,
                'detail': 'Return %s is owned by %s but returns to %s '
                          'which belongs to %s — the returned stock was '
                          're-owned on the way back.'
                          % (name, self._owner_name(c_owner), p_name,
                             self._owner_name(p_owner)),
                'measured': '%s ≠ %s' % (self._owner_name(c_owner),
                                         self._owner_name(p_owner)),
            })
        # -- 3. one lot stocked under two owners --------------------------
        rows = self._sql("""
            SELECT q.lot_id, lot.name, count(DISTINCT q.owner_id)
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            JOIN stock_lot lot ON lot.id = q.lot_id
            WHERE l.usage = 'internal' AND q.quantity > 0
              AND q.lot_id IS NOT NULL AND q.owner_id IS NOT NULL
            GROUP BY 1, 2 HAVING count(DISTINCT q.owner_id) > 1
        """)
        for lot_id, lot_name, n_owners in rows:
            out.append({
                'dedup_key': 'ownermm:lot:%s' % lot_id,
                'reference': lot_name,
                'detail': 'Lot %s is stocked under %d different owners at '
                          'once — one receipt line can only belong to one '
                          'client.' % (lot_name, n_owners),
                'measured': '%d owners' % n_owners,
                'quant_domain': repr([('lot_id', '=', lot_id),
                                      ('quantity', '>', 0)]),
            })
        return out

    # ==================================================================
    # PROCESS & RESERVATIONS
    # ==================================================================
    def _check_orphan_voids(self):
        rows = self._sql("""
            SELECT child.id, child.name, child.state, parent.name
            FROM stock_picking child
            JOIN stock_picking parent ON parent.id = child.return_id
            WHERE child.is_void_return = true
              AND child.state NOT IN ('done', 'cancel')
              AND COALESCE(parent.x_studio_voided, false) = false
            UNION ALL
            SELECT child.id, child.name, child.state, parent.name
            FROM stock_picking child
            JOIN stock_picking parent
              ON parent.id = child.void_source_picking_id
            WHERE child.is_void_wr = true
              AND child.state NOT IN ('done', 'cancel')
              AND COALESCE(parent.x_studio_voided, false) = false
        """)
        return [{
            'dedup_key': 'orphanvoid:%s' % pick_id,
            'res_model': 'stock.picking', 'res_id': pick_id,
            'reference': name,
            'detail': 'Unvalidated void child %s (%s) is still bound to '
                      'UNVOIDED parent %s — it could be validated or '
                      'recycled by mistake. Open the record and use the '
                      '"Clean Orphaned Void" button (or the Actions-menu '
                      'entry) to untangle it.' % (name, state, parent_name),
            'measured': state,
        } for pick_id, name, state, parent_name in rows]

    STALE_RES_QUERIES = {
        'location': ('stock.location', """
            SELECT t.id, COALESCE(t.complete_name, t.name) AS label,
                   sp.name, sp.state, COALESCE(sp.x_studio_voided, false)
            FROM stock_location t
            LEFT JOIN stock_picking sp
              ON sp.id = t.x_studio_receiving_report_id
            WHERE t.x_studio_is_reserved = true
              AND (sp.id IS NULL OR sp.state IN ('done', 'cancel')
                   OR COALESCE(sp.x_studio_voided, false) = true)
        """),
        'pallet': ('stock.quant.package', """
            SELECT t.id, t.name AS label,
                   sp.name, sp.state, COALESCE(sp.x_studio_voided, false)
            FROM stock_quant_package t
            LEFT JOIN stock_picking sp
              ON sp.id = t.x_studio_receiving_report_id
            WHERE t.x_studio_is_reserved = true
              AND (sp.id IS NULL OR sp.state IN ('done', 'cancel')
                   OR COALESCE(sp.x_studio_voided, false) = true)
        """),
    }

    def _check_stale_reservations(self):
        out = []
        for kind, (model, query) in self.STALE_RES_QUERIES.items():
            for rec_id, label, claimant, state, voided in self._sql(query):
                why = ('no claiming document' if not claimant else
                       'claimant %s is %s' % (claimant,
                                              'voided' if voided else state))
                out.append({
                    'dedup_key': 'stale_res:%s:%s' % (kind, rec_id),
                    'res_model': model, 'res_id': rec_id,
                    'reference': label,
                    'detail': 'Reserved %s %s is stale (%s) — it blocks '
                              'putaway/returns for everyone.'
                              % (kind, label, why),
                    'measured': why,
                })
        return out

    def _check_over_reserved(self):
        rows = self._sql("""
            SELECT q.id, q.owner_id, q.quantity, q.reserved_quantity,
                   COALESCE(q.x_studio_pallet_series_id,
                            q.bf_pallet_char, ''),
                   l.complete_name
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE l.usage = 'internal' AND q.quantity >= 0
              AND q.reserved_quantity > q.quantity + 0.001
        """)
        return [{
            'dedup_key': 'overres:%s' % quant_id,
            'owner_id': owner_id,
            'res_model': 'stock.quant', 'res_id': quant_id,
            'reference': label or loc,
            'detail': 'Quant reserves %.2f KG but only holds %.2f KG at %s '
                      '— phantom reservation blocks withdrawals and '
                      'corrections.' % (reserved, qty, loc),
            'measured': '%.2f > %.2f' % (reserved, qty),
            'quant_domain': repr([('id', '=', quant_id)]),
        } for quant_id, owner_id, qty, reserved, label, loc in rows]

    def _check_missing_stamp(self):
        cutoff = self._param('stamp_cutoff', '2026-07-12')
        rows = self._sql("""
            SELECT sp.id, sp.name, count(*)
            FROM stock_move_line ml
            JOIN stock_picking sp ON sp.id = ml.picking_id
            JOIN stock_picking_type pt ON pt.id = sp.picking_type_id
            WHERE pt.code = 'outgoing' AND ml.state = 'done'
              AND ml.package_id IS NOT NULL
              AND ml.reserved_quantity_on_validation IS NULL
              AND ml.create_date > %s
            GROUP BY sp.id, sp.name
        """, (cutoff,))
        return [{
            'dedup_key': 'nostamp:%s' % pick_id,
            'res_model': 'stock.picking', 'res_id': pick_id,
            'reference': name,
            'detail': '%d validated withdrawal line(s) missing the '
                      'remaining-stock stamp — the pallet-out counting '
                      'automation (SA#297) did not run for them.' % n,
            'measured': '%d lines' % n,
        } for pick_id, name, n in rows]

    # ==================================================================
    # SYSTEM WATCHDOG
    # ==================================================================
    def _check_watchdog_automations(self):
        out = []
        ar_ids = [int(x) for x in
                  self._param('watchdog_automation_ids', '').split(',')
                  if x.strip().isdigit()]
        if ar_ids:
            rows = self._sql("""
                SELECT ba.id, ba.name->>'en_US'
                FROM base_automation ba
                WHERE ba.id = ANY(%s) AND ba.active = false
            """, (ar_ids,))
            for ar_id, name in rows:
                out.append({
                    'dedup_key': 'ar_off:%s' % ar_id,
                    'res_model': 'base.automation', 'res_id': ar_id,
                    'reference': 'AR#%s' % ar_id,
                    'detail': 'Critical automation rule #%s (%s) is '
                              'INACTIVE — counting/stamping has silently '
                              'stopped.' % (ar_id, name),
                    'measured': 'inactive',
                })
        cron_ids = [int(x) for x in
                    self._param('watchdog_cron_ids', '').split(',')
                    if x.strip().isdigit()]
        if cron_ids:
            rows = self._sql("""
                SELECT c.id, s.name->>'en_US'
                FROM ir_cron c
                JOIN ir_act_server s ON s.id = c.ir_actions_server_id
                WHERE c.id = ANY(%s) AND c.active = false
            """, (cron_ids,))
            for cron_id, name in rows:
                out.append({
                    'dedup_key': 'cron_off:%s' % cron_id,
                    'res_model': 'ir.cron', 'res_id': cron_id,
                    'reference': 'Cron#%s' % cron_id,
                    'detail': 'Critical scheduled action #%s (%s) is '
                              'INACTIVE.' % (cron_id, name),
                    'measured': 'inactive',
                })
        return out

    def _check_snapshot_freshness(self):
        max_days = int(self._param('snapshot_max_age_days', '8') or 8)
        rows = self._sql(
            "SELECT max(create_date) FROM stock_quant_history_snapshot")
        latest = rows[0][0] if rows else None
        age_days = None
        if latest:
            age_days = (fields.Datetime.now() - latest).days
        if latest is None or age_days > max_days:
            return [{
                'dedup_key': 'snapshot_stale',
                'reference': 'Inventory snapshots',
                'detail': ('No inventory snapshot exists at all.'
                           if latest is None else
                           'Newest inventory snapshot is %d day(s) old '
                           '(threshold %d) — occupancy/billing reports are '
                           'going stale.' % (age_days, max_days)),
                'measured': ('none' if latest is None
                             else '%d days' % age_days),
            }]
        return []


class VifelHealthFinding(models.Model):
    _name = 'vifel.health.finding'
    _description = 'VIFEL Health Finding'
    _order = 'ignored, state, severity, last_seen desc, id desc'

    check_id = fields.Many2one('vifel.health.check', required=True,
                               ondelete='cascade', index=True, readonly=True)
    category = fields.Selection(related='check_id.category', store=True)
    dedup_key = fields.Char(required=True, readonly=True, index=True)
    severity = fields.Selection(SEVERITIES, required=True, readonly=True)
    state = fields.Selection([
        ('new', 'New'),
        ('open', 'Still Present'),
        ('resolved', 'Resolved'),
    ], default='new', required=True, readonly=True, index=True)
    owner_id = fields.Many2one('res.partner', string='Client', readonly=True)
    reference = fields.Char(string='Reference', readonly=True)
    detail = fields.Text(readonly=True)
    measured = fields.Char(string='Measured', readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    first_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)
    resolved_date = fields.Datetime(readonly=True)
    ignored = fields.Boolean(default=False,
                             help='Known and accepted — excluded from counts '
                                  'and notifications, kept for the record.')
    ignored_by = fields.Many2one('res.users', readonly=True)
    ignored_date = fields.Datetime(readonly=True)
    quant_domain = fields.Char(
        readonly=True,
        help='Domain of the stock.quants behind this finding — drives the '
             '"View Quants" preview button.')

    _sql_constraints = [
        ('dedup_uniq', 'unique(dedup_key)',
         'A finding with this identity already exists.'),
    ]

    def action_view_quants(self):
        """Preview the actual quants behind this finding, in the VIFEL
        detail list (pallet series, references, quantities, dates)."""
        self.ensure_one()
        if not self.quant_domain:
            return False
        try:
            domain = ast.literal_eval(self.quant_domain)
        except (ValueError, SyntaxError):
            return False
        tree = self.env.ref(
            'multiple_relocation.view_stock_quant_tree_vifel_details',
            raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Quants') % (self.reference or self.check_id.name),
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'views': [(tree.id if tree else False, 'tree'), (False, 'form')],
            'domain': domain,
            'context': {'create': False},
        }

    def action_open_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_toggle_ignored(self):
        for finding in self:
            vals = {'ignored': not finding.ignored}
            if vals['ignored']:
                vals.update({'ignored_by': self.env.user.id,
                             'ignored_date': fields.Datetime.now()})
            else:
                vals.update({'ignored_by': False, 'ignored_date': False})
            finding.sudo().write(vals)


class VifelHealthRun(models.Model):
    _name = 'vifel.health.run'
    _description = 'VIFEL Health Run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'display_label'

    display_label = fields.Char(compute='_compute_display_label')
    run_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    trigger = fields.Selection([('cron', 'Scheduled'), ('manual', 'Manual')],
                               default='manual', readonly=True)
    duration_ms = fields.Integer(readonly=True)
    checks_run = fields.Integer(readonly=True)
    checks_failed = fields.Integer(readonly=True)
    new_findings = fields.Integer(readonly=True)
    resolved_findings = fields.Integer(readonly=True)
    open_findings = fields.Integer(readonly=True)
    summary = fields.Text(readonly=True)

    def _compute_display_label(self):
        for run in self:
            run.display_label = 'Health run %s' % (
                fields.Datetime.to_string(run.run_date))

    def _execute(self, checks):
        """Run the given checks, reconcile findings, notify on new ones."""
        self.ensure_one()
        Finding = self.env['vifel.health.finding'].sudo()
        started = fields.Datetime.now()
        totals = {'new': 0, 'resolved': 0, 'failed': 0}
        new_bits = []

        for check in checks:
            t0 = time.time()
            try:
                items = getattr(check, '_check_%s' % check.code)()
            except Exception as exc:
                _logger.exception('Health check %s failed', check.code)
                check.sudo().write({'last_error': str(exc)[:2000],
                                    'last_run': fields.Datetime.now()})
                totals['failed'] += 1
                continue

            existing = Finding.search([
                ('check_id', '=', check.id), ('state', '!=', 'resolved')])
            by_key = {f.dedup_key: f for f in existing}
            seen = set()
            new_here = 0
            for item in items:
                key = item['dedup_key']
                seen.add(key)
                found = by_key.get(key)
                if found:
                    vals = {'last_seen': started,
                            'detail': item.get('detail'),
                            'measured': item.get('measured'),
                            'quant_domain': item.get('quant_domain') or False}
                    if found.state == 'new' and found.first_seen < started:
                        vals['state'] = 'open'
                    found.write(vals)
                else:
                    # a previously RESOLVED finding can reappear: reopen it
                    old = Finding.search([('dedup_key', '=', key)], limit=1)
                    vals = {
                        'detail': item.get('detail'),
                        'measured': item.get('measured'),
                        'owner_id': item.get('owner_id') or False,
                        'reference': item.get('reference') or '',
                        'res_model': item.get('res_model') or False,
                        'res_id': item.get('res_id') or 0,
                        'severity': item.get('severity') or check.severity,
                        'quant_domain': item.get('quant_domain') or False,
                        'state': 'new',
                        'first_seen': started, 'last_seen': started,
                        'resolved_date': False,
                    }
                    if old:
                        old.write(vals)
                        found = old
                    else:
                        found = Finding.create(
                            dict(vals, check_id=check.id, dedup_key=key))
                    if not found.ignored:
                        new_here += 1
            gone = existing.filtered(lambda f: f.dedup_key not in seen)
            if gone:
                gone.write({'state': 'resolved',
                            'resolved_date': started})
            check.sudo().write({
                'last_run': started,
                'last_duration_ms': int((time.time() - t0) * 1000),
                'last_error': False,
                'resolved_last_run': len(gone),
            })
            totals['new'] += new_here
            totals['resolved'] += len(gone)
            if new_here:
                new_bits.append('%s: %d new' % (check.name, new_here))

        open_now = Finding.search_count([
            ('state', '!=', 'resolved'), ('ignored', '=', False)])
        self.write({
            'duration_ms': int(
                (fields.Datetime.now() - started).total_seconds() * 1000),
            'checks_run': len(checks) - totals['failed'],
            'checks_failed': totals['failed'],
            'new_findings': totals['new'],
            'resolved_findings': totals['resolved'],
            'open_findings': open_now,
            'summary': ('; '.join(new_bits) if new_bits
                        else 'No new findings.')
                       + (' [%d check(s) FAILED]' % totals['failed']
                          if totals['failed'] else ''),
        })
        if totals['new']:
            self._notify_new_findings(new_bits)
        return True

    def _notify_new_findings(self, new_bits):
        """One to-do per administrator (the monitor is admin-only, so the
        recipients must be users who can actually open it)."""
        self.ensure_one()
        group = self.env.ref('multiple_relocation.inventory_super_admin',
                             raise_if_not_found=False)
        recipients = group.users.filtered('active') if group \
            else self.env['res.users']
        if not recipients:
            recipients = self.env.ref('base.user_admin')
        note = _('Health monitor found NEW issue(s):\n%s\n\n'
                 'Open Inventory → Reporting → System Health for details.'
                 ) % '\n'.join('• %s' % b for b in new_bits)
        for user in recipients:
            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=_('System Health: new findings'),
                    note=note,
                )
            except Exception:
                _logger.exception(
                    'Could not schedule health activity for user %s', user.id)
