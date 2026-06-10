# Copyright 2024 Foodles (https://www.foodles.co/).
# @author Pierre Verkest <pierreverkest84@gmail.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from pytz import timezone, utc as pytz_utc

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError, UserError
from odoo.osv.expression import AND

_logger = logging.getLogger(__name__)


class StockQuantHistorySnapshot(models.Model):
    _name = "stock.quant.history.snapshot"
    _description = "stock.quant.history generation configuration model"
    _order = "inventory_date desc"

    # All datetime operations use Manila (UTC+8)
    MANILA_TZ = timezone('Asia/Manila')

    name = fields.Char(
        compute="_compute_name",
    )
    stock_quant_history_ids = fields.One2many(
        comodel_name="stock.quant.history",
        inverse_name="snapshot_id",
        string="Stock quant history",
        help="Generated stock quant history for current snapshot settings.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("generated", "Generated"),
        ],
        string="Status",
        copy=False,
        default="draft",
        readonly=True,
        required=True,
    )

    inventory_date = fields.Datetime(
        string="Inventory date",
        required=True,
        readonly=True,
        help="The date used to create stock.quant.history as it was for the given date",
    )
    generated_date = fields.Datetime(
        string="Generated date",
        readonly=True,
        copy=False,
        help="Date when stock.quant.history line have been created.",
    )
    previous_snapshot_id = fields.Many2one(
        comodel_name="stock.quant.history.snapshot",
        string="Snapshot base",
        readonly=True,
        help="Base snapshot used to generate this snapshot",
    )

    @api.depends("inventory_date")
    def _compute_name(self):
        # Odoo enforce users to be linked to an active lang
        lang = self.env["res.lang"]._lang_get(self.env.user.lang)
        dt_format = lang.date_format + " " + lang.time_format

        for rec in self:
            if not rec.inventory_date:
                rec.name = _("Snapshot")
                continue

            local_inventory_date = pytz_utc.localize(rec.inventory_date).astimezone(self.MANILA_TZ)

            rec.name = _("Snapshot %s") % local_inventory_date.strftime(dt_format)

    def action_generate_stock_quant_history(self):
        for snapshot in self:
            snapshot._generate_stock_quant_history()

    def _base_move_line_domain(self):
        """Domain selecting every *done* stock move line of storable products
        up to (and including) the snapshot inventory date.

        Quantities are rebuilt from the full move line history; the result is
        deterministic and independent of any previous snapshot, which removes
        carry-forward drift, stale "delivered but still logged" rows and stray
        negatives.
        """
        return [
            ("state", "=", "done"),
            ("date", "<=", self.inventory_date),
            ("product_id.type", "=", "product"),
        ]

    def _prepare_stock_move_line_filter(self, previous_quant_snapshot=None):
        # Kept for backward compatibility. Quantities are now rebuilt from the
        # full move line history (see _base_move_line_domain), so the previous
        # snapshot is no longer used to window the move lines.
        return self._base_move_line_domain()

    @api.model
    def _ignored_location_usage(self):
        """If you overwrite or change this
        list you'll probably want to regenerate all your
        snapshots"""
        return [
            "supplier",
            "customer",
            "inventory",
        ]

    def _generate_stock_quant_history(self):
        """Rebuild the stock quant history lines for this snapshot.

        The rebuild is *idempotent* and *deterministic*:

          * any line previously generated for this snapshot is dropped first,
            so a re-run never appends a duplicate set;
          * quantities are recomputed from the full ``stock.move.line`` history
            (incoming on non virtual destinations minus outgoing from non
            virtual sources) instead of carrying forward a previous snapshot,
            which removes drift and stale "delivered but still logged" rows.

        The result matches ``stock.quant`` (grouped by product / lot / location)
        for non virtual locations.
        """
        self.ensure_one()
        StockQuantHistory = self.env["stock.quant.history"].sudo()
        StockMoveLine = self.env["stock.move.line"].sudo()

        # Store Manila time (UTC+8) for generated_date
        self.generated_date = datetime.now(self.MANILA_TZ).replace(tzinfo=None)

        # Audit link to the most recent previously generated snapshot. Compared
        # in UTC (consistent with the move line date filter). Purely
        # informative: it is NOT used to compute quantities anymore.
        self.previous_snapshot_id = self.search(
            [
                ("state", "=", "generated"),
                ("id", "!=", self.id),
                ("inventory_date", "<=", self.inventory_date),
            ],
            order="inventory_date desc",
            limit=1,
        )

        # Idempotency: wipe any line previously generated for this snapshot.
        self.stock_quant_history_ids.unlink()

        ignored_location_usage = self._ignored_location_usage()
        base_domain = self._base_move_line_domain()

        # Net quantity per (product, lot, location), rebuilt from move lines.
        # ``quantity_product_uom`` is the done quantity already converted to the
        # product reference unit of measure (stored field on stock.move.line),
        # so no manual UoM conversion is needed.
        quantities = defaultdict(float)

        incoming = StockMoveLine._read_group(
            AND(
                [
                    base_domain,
                    [("location_dest_id.usage", "not in", ignored_location_usage)],
                ]
            ),
            ["product_id", "lot_id", "location_dest_id"],
            ["quantity_product_uom:sum"],
        )
        for product, lot, location, qty in incoming:
            quantities[(product, lot, location)] += qty

        outgoing = StockMoveLine._read_group(
            AND(
                [
                    base_domain,
                    [("location_id.usage", "not in", ignored_location_usage)],
                ]
            ),
            ["product_id", "lot_id", "location_id"],
            ["quantity_product_uom:sum"],
        )
        for product, lot, location, qty in outgoing:
            quantities[(product, lot, location)] -= qty

        _logger.info(
            "Generating %s: %s candidate (product, lot, location) key(s)",
            self.name,
            len(quantities),
        )

        create_vals = []
        for (product, lot, location), qty in quantities.items():
            rounding = product.uom_id.rounding
            qty = tools.float_round(qty, precision_rounding=rounding)
            if tools.float_is_zero(qty, precision_rounding=rounding):
                continue
            create_vals.append(
                {
                    "snapshot_id": self.id,
                    "product_id": product.id,
                    "lot_id": lot.id if lot else False,
                    "location_id": location.id,
                    "quantity": qty,
                }
            )

        history_records = (
            StockQuantHistory.create(create_vals)
            if create_vals
            else StockQuantHistory
        )

        # Enrich the additional (Studio) fields in a single batched pass.
        history_by_key = {
            (rec.product_id, rec.lot_id, rec.location_id): rec
            for rec in history_records
        }
        self._enrich_stock_quant_history(history_by_key)

        # Backstop: remove any residual zero quantity line to save disk space.
        self.env["stock.quant.history"].flush_model()
        self.env.cr.execute(
            "DELETE FROM stock_quant_history where quantity = 0 and snapshot_id = %s",
            (self.id,),
        )
        self.state = "generated"

    @staticmethod
    def _src(record, field_name):
        """Read a field defensively.

        Returns ``False`` when the (Studio) field is not defined on the model,
        so the module keeps working in databases where the custom ``x_studio_*``
        fields do not exist (e.g. a vanilla developer build).
        """
        if field_name in record._fields:
            return record[field_name]
        return False

    def _quant_enrichment_vals(self, quant):
        """Additional field values read from the current ``stock.quant``.

        Used for the fields that only live on the quant; point in time data
        coming from move lines takes precedence (see
        :meth:`_enrich_stock_quant_history`).
        """
        get = self._src
        rec_ref = get(quant, "x_studio_record_reference")
        owner = get(quant, "owner_id")
        package = get(quant, "package_id")
        qty_uom = get(quant, "x_studio_quantity_uom")
        min_uom = get(quant, "x_studio_min_quantity_uom")
        return {
            "x_studio_record_reference": rec_ref.id if rec_ref else False,
            "x_studio_stock_code": get(quant, "x_studio_stock_code") or False,
            "x_studio_return_count": get(quant, "x_studio_return_count") or 0,
            "x_studio_pallet_series_id": get(quant, "x_studio_pallet_series_id")
            or False,
            "owner_id": owner.id if owner else False,
            "package_id": package.id if package else False,
            "x_studio_production_date": get(quant, "x_studio_production_date") or False,
            "x_studio_expiration_date": get(quant, "x_studio_expiration_date") or False,
            "x_studio_loading_dock_no": get(quant, "x_studio_loading_dock_no") or False,
            "x_studio_source": get(quant, "x_studio_source") or False,
            "x_studio_container_number": get(quant, "x_studio_container_number")
            or False,
            "x_studio_gate_pass": get(quant, "x_studio_gate_pass") or False,
            "x_studio_truck_time": get(quant, "x_studio_truck_time") or False,
            "x_studio_start_time": get(quant, "x_studio_start_time") or False,
            "x_studio_end_time": get(quant, "x_studio_end_time") or False,
            "x_studio_truck_number": get(quant, "x_studio_truck_number") or False,
            "x_studio_2nd_uom": get(quant, "x_studio_2nd_uom") or 0.0,
            "x_studio_quantity_uom": qty_uom.id if qty_uom else False,
            "x_studio_total_units": get(quant, "x_studio_total_units") or 0.0,
            "x_studio_min_quantity_uom": min_uom.id if min_uom else False,
            "x_studio_special_holding": get(quant, "x_studio_special_holding") or False,
            "x_studio_sh_reason": get(quant, "x_studio_sh_reason") or "",
        }

    def _move_line_enrichment_vals(self, move_line):
        """Point in time additional field values read from the destination
        ``stock.move.line`` that last brought the stock into the location."""
        get = self._src
        owner = get(move_line, "owner_id")
        qty_uom = get(move_line, "x_studio_quantity_uom") or get(
            move_line, "x_studio_quantity_uom_delivery"
        )
        result_package = get(move_line, "result_package_id")
        package = get(move_line, "package_id")
        return {
            "owner_id": owner.id if owner else False,
            "x_studio_container_number": get(move_line, "x_studio_container_number")
            or False,
            "x_studio_production_date": get(move_line, "x_studio_production_date")
            or False,
            "x_studio_expiration_date": get(move_line, "x_studio_expiration_date")
            or False,
            "x_studio_loading_dock_no": get(
                move_line.picking_id, "x_studio_loading_dock_no"
            )
            or False,
            "x_studio_2nd_uom": get(move_line, "x_studio_2nd_uom")
            or get(move_line, "x_studio_affected_2nd_uom")
            or 0.0,
            "x_studio_quantity_uom": qty_uom.id if qty_uom else False,
            "x_studio_pallet_series_id": get(move_line, "x_studio_pallet_series_id")
            or False,
            "package_id": result_package.id
            if result_package
            else (package.id if package else False),
        }

    def _enrich_stock_quant_history(self, history_by_key):
        """Fill the additional (Studio) fields on freshly created history rows.

        Values are taken, in priority order, from:

          1. the latest *done* destination move line at/before the inventory
             date matching the (product, lot, location) of the row (point in
             time accurate);
          2. the current ``stock.quant`` properly scoped on
             (product, lot, location) for the fields that only live on the
             quant.

        Everything is read in two batched searches to avoid per-row queries.
        """
        if not history_by_key:
            return

        products = self.env["product.product"].browse()
        locations = self.env["stock.location"].browse()
        for product, lot, location in history_by_key:
            products |= product
            locations |= location

        # Latest done destination move line per (product, lot, location).
        latest_move_line_by_key = {}
        move_lines = (
            self.env["stock.move.line"]
            .sudo()
            .search(
                [
                    ("state", "=", "done"),
                    ("date", "<=", self.inventory_date),
                    ("product_id", "in", products.ids),
                    ("location_dest_id", "in", locations.ids),
                ],
                order="date asc, id asc",
            )
        )
        for move_line in move_lines:
            key = (move_line.product_id, move_line.lot_id, move_line.location_dest_id)
            if key in history_by_key:
                # ascending order => the last write wins => latest move line
                latest_move_line_by_key[key] = move_line

        # Current quants properly scoped on (product, lot, location).
        quant_by_key = {}
        quants = (
            self.env["stock.quant"]
            .sudo()
            .search(
                [
                    ("product_id", "in", products.ids),
                    ("location_id", "in", locations.ids),
                ]
            )
        )
        for quant in quants:
            key = (quant.product_id, quant.lot_id, quant.location_id)
            if key in history_by_key and key not in quant_by_key:
                quant_by_key[key] = quant

        for key, history in history_by_key.items():
            vals = {}
            quant = quant_by_key.get(key)
            if quant:
                vals.update(self._quant_enrichment_vals(quant))
            move_line = latest_move_line_by_key.get(key)
            if move_line:
                # point in time move line data overrides the current quant data
                vals.update(self._move_line_enrichment_vals(move_line))
            if vals:
                history.write(vals)

    @api.model
    def _regenerate_all_snapshots(self):
        """Re-run the generation for every existing snapshot with the current
        (corrected) logic.

        Used by the data migration and available as a manual maintenance
        action. Only touches stock.quant.history.snapshot / stock.quant.history
        records; stock.quant and stock.move.line source data are never modified.
        """
        snapshots = self.search([], order="inventory_date asc")
        total = len(snapshots)
        _logger.info("Regenerating %s stock quant history snapshot(s)", total)
        for index, snapshot in enumerate(snapshots, start=1):
            _logger.info(
                "Regenerating snapshot %s/%s (%s)", index, total, snapshot.name
            )
            snapshot._generate_stock_quant_history()
        return True

    def action_related_stock_quant_history_tree_view(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_quant_history.action_stock_quant_history"
        )
        action["domain"] = [("snapshot_id", "in", self.ids), ("owner_id", "!=", False)]
        return action

    # ──────────────────────────────────────────────
    #  CRON: daily snapshot generation + cleanup
    # ──────────────────────────────────────────────
    MAX_SNAPSHOTS = 60

    @api.model
    def _manila_day_utc_bounds(self, day):
        """Return the (start, end) UTC naive datetimes bounding the given Manila
        calendar ``day``.

        Snapshots store ``inventory_date`` in UTC, so existence checks must
        compare against UTC bounds. Sharing this helper keeps the daily and the
        backfill crons consistent and avoids creating duplicate snapshots for
        the same Manila day.
        """
        start_local = self.MANILA_TZ.localize(
            datetime.combine(day, datetime.min.time())
        )
        end_local = self.MANILA_TZ.localize(
            datetime.combine(day, datetime.max.time())
        )
        return (
            start_local.astimezone(pytz_utc).replace(tzinfo=None),
            end_local.astimezone(pytz_utc).replace(tzinfo=None),
        )

    @api.model
    def _cron_generate_daily_snapshot(self):
        """Scheduled action: generate a snapshot for yesterday at 23:59:59
        Manila time, then delete the oldest snapshots beyond MAX_SNAPSHOTS.

        Only creates stock.quant.history.snapshot +
        stock.quant.history records (reporting copies).
        NEVER touches stock.quant or stock.move.line source data.
        """
        # Yesterday in Manila
        now_manila = datetime.now(self.MANILA_TZ)
        yesterday = (now_manila - timedelta(days=1)).date()

        # Check if snapshot already exists for yesterday (Manila day → UTC
        # bounds, consistent with the backfill cron).
        day_start, day_end = self._manila_day_utc_bounds(yesterday)

        existing = self.search([
            ('inventory_date', '>=', day_start),
            ('inventory_date', '<=', day_end),
        ], limit=1)

        if not existing:
            # Create snapshot at 23:59:59 Manila → UTC
            local_dt = self.MANILA_TZ.localize(
                datetime.combine(yesterday, datetime.min.time()).replace(
                    hour=23, minute=59, second=59,
                )
            )
            utc_dt = local_dt.astimezone(pytz_utc).replace(tzinfo=None)

            snapshot = self.create({
                'inventory_date': utc_dt,
                'state': 'draft',
            })
            _logger.info(
                "CRON: created snapshot for %s (inventory_date=%s)",
                yesterday, utc_dt,
            )
            snapshot._generate_stock_quant_history()
        elif existing.state == 'draft':
            _logger.info("CRON: generating existing draft snapshot for %s", yesterday)
            existing._generate_stock_quant_history()
        else:
            _logger.info("CRON: snapshot for %s already exists and is generated", yesterday)

        # ── Cleanup: keep only the newest MAX_SNAPSHOTS ──
        all_snapshots = self.search([], order='inventory_date desc')
        if len(all_snapshots) > self.MAX_SNAPSHOTS:
            to_delete = all_snapshots[self.MAX_SNAPSHOTS:]
            count = len(to_delete)
            _logger.info(
                "CRON: deleting %d old snapshot(s) to keep max %d. "
                "This removes stock.quant.history.snapshot + "
                "stock.quant.history records ONLY (cascade). "
                "stock.quant and stock.move.line are NEVER affected.",
                count, self.MAX_SNAPSHOTS,
            )
            # Cascade on snapshot_id deletes stock.quant.history records
            to_delete.unlink()
            _logger.info("CRON: cleanup complete, %d snapshot(s) removed", count)

    # ──────────────────────────────────────────────
    #  CRON: backfill 5 snapshots per run (every 20 min)
    #  Auto-deactivates once all 60 days are covered.
    # ──────────────────────────────────────────────
    BACKFILL_BATCH = 5

    @api.model
    def _cron_backfill_snapshots(self):
        """Scheduled action: create and generate 5 snapshots per run,
        working backwards from today until 60 days are covered.

        Runs every 20 minutes.  Once all 60 days have a snapshot the
        CRON automatically deactivates itself so it stops running.
        """
        now_manila = datetime.now(self.MANILA_TZ)
        today = now_manila.date()

        # Oldest date we'd ever backfill to
        cutoff = today - timedelta(days=self.MAX_SNAPSHOTS - 1)

        # Collect existing snapshot dates (Manila dates)
        all_snaps = self.search([], order='inventory_date desc')
        existing_dates = set()
        for snap in all_snaps:
            inv_dt = snap.inventory_date
            if inv_dt.tzinfo is None:
                inv_dt = pytz_utc.localize(inv_dt)
            existing_dates.add(inv_dt.astimezone(self.MANILA_TZ).date())

        # Walk backwards from today, collect missing dates
        missing = []
        d = today
        while d >= cutoff and len(missing) < self.BACKFILL_BATCH:
            if d not in existing_dates:
                missing.append(d)
            d -= timedelta(days=1)

        if not missing:
            _logger.info(
                "Backfill CRON: all %d days already have snapshots. "
                "Auto-deactivating backfill CRON.",
                self.MAX_SNAPSHOTS,
            )
            cron = self.env.ref(
                'stock_quant_history.ir_cron_backfill_snapshots',
                raise_if_not_found=False,
            )
            if cron:
                cron.sudo().write({'active': False})
                _logger.info("Backfill CRON deactivated.")
            return

        created = 0
        for target_date in missing:
            local_dt = self.MANILA_TZ.localize(
                datetime.combine(target_date, datetime.min.time()).replace(
                    hour=23, minute=59, second=59,
                )
            )
            utc_dt = local_dt.astimezone(pytz_utc).replace(tzinfo=None)

            snapshot = self.create({
                'inventory_date': utc_dt,
                'state': 'draft',
            })
            _logger.info(
                "Backfill CRON: created snapshot for %s (inventory_date=%s)",
                target_date, utc_dt,
            )
            snapshot._generate_stock_quant_history()
            created += 1

        # Count how many days still missing after this batch
        remaining = 0
        d = missing[-1] - timedelta(days=1)
        while d >= cutoff:
            if d not in existing_dates:
                remaining += 1
            d -= timedelta(days=1)

        _logger.info(
            "Backfill CRON: generated %d snapshot(s). %d day(s) still missing.",
            created, remaining,
        )

        # If fully backfilled after this batch, auto-deactivate
        if remaining == 0:
            _logger.info(
                "Backfill CRON: all %d days now covered! "
                "Auto-deactivating backfill CRON.",
                self.MAX_SNAPSHOTS,
            )
            cron = self.env.ref(
                'stock_quant_history.ir_cron_backfill_snapshots',
                raise_if_not_found=False,
            )
            if cron:
                cron.sudo().write({'active': False})
