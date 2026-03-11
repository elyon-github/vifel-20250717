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


class DefaultDict(defaultdict):
    def __missing__(self, key):
        self[key] = self.default_factory(*key)
        return self[key]


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

    def _prepare_stock_move_line_filter(self, previous_quant_snapshot):
        inventory_date_manila = pytz_utc.localize(self.inventory_date).astimezone(self.MANILA_TZ).replace(tzinfo=None)
        domain = [
            ("state", "=", "done"),
            ("date", "<=", self.inventory_date),
            ("product_id.type", "=", "product"),
        ]
        # raise UserError(inventory_date_manila)
        if previous_quant_snapshot.exists():
            domain = AND(
                [domain, [("date", ">", previous_quant_snapshot.inventory_date)]]
            )
        return domain

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
        self.ensure_one()
        # Store Manila time (UTC+8) for generated_date
        self.generated_date = datetime.now(self.MANILA_TZ).replace(tzinfo=None)
        inventory_date_manila = pytz_utc.localize(self.inventory_date).astimezone(self.MANILA_TZ).replace(tzinfo=None)
        previous_quant_snapshot = self.search(
            [
                ("state", "=", "generated"),
                ("inventory_date", "<=", inventory_date_manila),
            ],
            order="inventory_date desc",
            limit=1,
        )
        
        # Function to create new stock.quant.history records with all fields
        def create_quant_history(product, lot, location, quant=None):
            vals = {
                "snapshot_id": self.id,
                "product_id": product.id,
                "lot_id": lot.id if lot else False,
                "location_id": location.id,
                "quantity": 0,
            }
            
            # If a quant is provided, copy all the additional fields
            if quant:
                # Add all the additional fields from stock.quant
                vals.update({
                    "x_studio_record_reference": quant.x_studio_record_reference.id if quant.x_studio_record_reference else False,
                    "x_studio_stock_code": quant.x_studio_stock_code or False,
                    "x_studio_return_count": quant.x_studio_return_count or 0,
                    "x_studio_pallet_series_id": quant.x_studio_pallet_series_id or False,
                    "owner_id": quant.owner_id or False,
                    "package_id": quant.package_id.id if quant.package_id else False,
                    "x_studio_production_date": quant.x_studio_production_date or False,
                    "x_studio_expiration_date": quant.x_studio_expiration_date or False,
                    "x_studio_loading_dock_no": quant.x_studio_loading_dock_no or False,
                    "x_studio_source": quant.x_studio_source or False,
                    "x_studio_container_number": quant.x_studio_container_number or False,
                    "x_studio_gate_pass": quant.x_studio_gate_pass or False,
                    "x_studio_truck_time": quant.x_studio_truck_time or False,
                    "x_studio_start_time": quant.x_studio_start_time or False,
                    "x_studio_end_time": quant.x_studio_end_time or False,
                    "x_studio_truck_number": quant.x_studio_truck_number or False,
                    "x_studio_2nd_uom": quant.x_studio_2nd_uom or 0.0,
                    "x_studio_quantity_uom": quant.x_studio_quantity_uom.id if quant.x_studio_quantity_uom else False,
                    "x_studio_total_units": quant.x_studio_total_units or 0.0,
                    "x_studio_min_quantity_uom": quant.x_studio_min_quantity_uom.id if quant.x_studio_min_quantity_uom else False,
                    "x_studio_special_holding": quant.x_studio_special_holding if quant.x_studio_special_holding else False,
                    "x_studio_sh_reason": quant.x_studio_sh_reason if quant.x_studio_sh_reason else ''
                })
            
            return self.env["stock.quant.history"].sudo().create(vals)
        
        # Modified DefaultDict to use our custom creation function
        quant_history = DefaultDict(
            lambda product, lot, location: create_quant_history(product, lot, location)
        )
        
        self.previous_snapshot_id = previous_quant_snapshot
    
        _logger.info("Processing %s from %s", self.name, self.previous_snapshot_id.name)
        if previous_quant_snapshot.stock_quant_history_ids.exists():
            _logger.info(
                "Duplicate %s previous stock.quant.history...",
                len(previous_quant_snapshot.stock_quant_history_ids),
            )
            for stock_quant_history in previous_quant_snapshot.stock_quant_history_ids:
                # copy is around 3x slower than create !
                quant_copy = quant_history[
                    (
                        stock_quant_history.product_id,
                        stock_quant_history.lot_id,
                        stock_quant_history.location_id,
                    )
                ]
                
                # Copy all the fields from previous history record
                quant_copy.write({
                    "quantity": stock_quant_history.quantity,
                    "x_studio_record_reference": stock_quant_history.x_studio_record_reference.id if stock_quant_history.x_studio_record_reference else False,
                    "x_studio_stock_code": stock_quant_history.x_studio_stock_code or False,
                    "x_studio_return_count": stock_quant_history.x_studio_return_count or 0,
                    "x_studio_pallet_series_id": stock_quant_history.x_studio_pallet_series_id or False,
                    "owner_id": stock_quant_history.owner_id or False,
                    "package_id": stock_quant_history.package_id.id if stock_quant_history.package_id else False,
                    "x_studio_production_date": stock_quant_history.x_studio_production_date or False,
                    "x_studio_expiration_date": stock_quant_history.x_studio_expiration_date or False,
                    "x_studio_loading_dock_no": stock_quant_history.x_studio_loading_dock_no or False,
                    "x_studio_source": stock_quant_history.x_studio_source or False,
                    "x_studio_container_number": stock_quant_history.x_studio_container_number or False,
                    "x_studio_gate_pass": stock_quant_history.x_studio_gate_pass or False,
                    "x_studio_truck_time": stock_quant_history.x_studio_truck_time or False,
                    "x_studio_start_time": stock_quant_history.x_studio_start_time or False,
                    "x_studio_end_time": stock_quant_history.x_studio_end_time or False,
                    "x_studio_truck_number": stock_quant_history.x_studio_truck_number or False,
                    "x_studio_2nd_uom": stock_quant_history.x_studio_2nd_uom or 0.0,
                    "x_studio_quantity_uom": stock_quant_history.x_studio_quantity_uom.id if stock_quant_history.x_studio_quantity_uom else False,
                    "x_studio_total_units": stock_quant_history.x_studio_total_units or 0.0,
                    "x_studio_min_quantity_uom": stock_quant_history.x_studio_min_quantity_uom.id if stock_quant_history.x_studio_min_quantity_uom else False,
                    "x_studio_special_holding": stock_quant_history.x_studio_special_holding if stock_quant_history.x_studio_special_holding else False,
                    "x_studio_sh_reason": stock_quant_history.x_studio_sh_reason if stock_quant_history.x_studio_sh_reason else ''
                })
    
        # For new records from stock move lines, we need to attempt to get the quant information
        stock_move_lines = (
            self.env["stock.move.line"]
            .sudo()
            .search(
                self._prepare_stock_move_line_filter(previous_quant_snapshot),
            )
        )
        # raise UserError(len(stock_move_lines))
        _logger.info(
            "Apply %s stock.move.line since previous snapshot", len(stock_move_lines)
        )
        ignored_location_usage = self._ignored_location_usage()
        for move_line in stock_move_lines:
            if move_line.location_id.usage not in ignored_location_usage:
                quant_history[
                    (move_line.product_id, move_line.lot_id, move_line.location_id)
                ].quantity = tools.float_round(
                    quant_history[
                        (move_line.product_id, move_line.lot_id, move_line.location_id)
                    ].quantity
                    - move_line.product_uom_id._compute_quantity(
                        move_line.quantity, move_line.product_id.uom_id
                    ),
                    precision_rounding=move_line.product_id.uom_id.rounding,
                )
    
            if move_line.location_dest_id.usage not in ignored_location_usage:
                quant_history[
                    (move_line.product_id, move_line.lot_id, move_line.location_dest_id)
                ].quantity = tools.float_round(
                    quant_history[
                        (
                            move_line.product_id,
                            move_line.lot_id,
                            move_line.location_dest_id,
                        )
                    ].quantity
                    + move_line.product_uom_id._compute_quantity(
                        move_line.quantity, move_line.product_id.uom_id
                    ),
                    precision_rounding=move_line.product_id.uom_id.rounding,
                )
                
                # Try to get additional fields from related quant if this is a new record
                if move_line.lot_id and move_line.location_dest_id:
                    related_quant = self.env["stock.quant"].sudo().search([
                        # ("product_id", "=", move_line.product_id.id),
                        ("lot_id", "=", move_line.lot_id.id),
                        # ("location_id", "=", move_line.location_dest_id.id)
                    ], limit=1)
                    
                    if related_quant and related_quant.x_studio_pallet_series_id:
                        # Update the fields from the related quant
                        quant_history[
                            (move_line.product_id, move_line.lot_id, move_line.location_dest_id)
                        ].write({
                            "x_studio_record_reference": related_quant.x_studio_record_reference.id if related_quant.x_studio_record_reference else False,
                            "x_studio_stock_code": related_quant.x_studio_stock_code or False,
                            "x_studio_return_count": related_quant.x_studio_return_count or 0,
                            "x_studio_pallet_series_id": related_quant.x_studio_pallet_series_id or False,
                            "owner_id": related_quant.owner_id or False,
                            "package_id": related_quant.package_id.id if related_quant.package_id else False,
                            "x_studio_production_date": related_quant.x_studio_production_date or False,
                            "x_studio_expiration_date": related_quant.x_studio_expiration_date or False,
                            "x_studio_loading_dock_no": related_quant.x_studio_loading_dock_no or False,
                            "x_studio_source": related_quant.x_studio_source or False,
                            "x_studio_container_number": related_quant.x_studio_container_number or False,
                            "x_studio_gate_pass": related_quant.x_studio_gate_pass or False,
                            "x_studio_truck_time": related_quant.x_studio_truck_time or False,
                            "x_studio_start_time": related_quant.x_studio_start_time or False,
                            "x_studio_end_time": related_quant.x_studio_end_time or False,
                            "x_studio_truck_number": related_quant.x_studio_truck_number or False,
                            "x_studio_2nd_uom": related_quant.x_studio_2nd_uom or 0.0,
                            "x_studio_quantity_uom": related_quant.x_studio_quantity_uom.id if related_quant.x_studio_quantity_uom else False,
                            "x_studio_total_units": related_quant.x_studio_total_units or 0.0,
                            "x_studio_min_quantity_uom": related_quant.x_studio_min_quantity_uom.id if related_quant.x_studio_min_quantity_uom else False,
                            "x_studio_special_holding": related_quant.x_studio_special_holding if related_quant.x_studio_special_holding else False,
                            "x_studio_sh_reason": related_quant.x_studio_sh_reason if related_quant.x_studio_sh_reason else ''
                        })
                    else:
                        related_quants = self.env["stock.move.line"].search([
                            ("x_studio_pallet_series_id", "!=", False),
                            ("lot_id", "=", move_line.lot_id.id),
                        ], order="date asc")
                        
                        related_quant = False
                        for rq in related_quants:
                            if rq.date and rq.date <= self.inventory_date and rq.x_studio_pallet_series_id:
                                related_quant = rq
                            else:
                                # We've reached beyond the target date — stop before it
                                break
                        
                        # Ensure we always have at least one (fallback to first record if none matched)
                        if not related_quant and related_quants:
                            related_quant = related_quants[0]
                        
                        if related_quant:
                            quant_history[
                                (move_line.product_id, move_line.lot_id, move_line.location_dest_id)
                            ].write({
                                "owner_id": related_quant.owner_id.id if related_quant.owner_id else False,
                                "x_studio_container_number": related_quant.x_studio_container_number or False,
                                "x_studio_production_date": related_quant.x_studio_production_date or False,
                                "x_studio_expiration_date": related_quant.x_studio_expiration_date or False,
                                "x_studio_loading_dock_no": related_quant.picking_id.x_studio_loading_dock_no or False,
                                "x_studio_2nd_uom": related_quant.x_studio_2nd_uom or related_quant.x_studio_affected_2nd_uom or 0.0,
                                "x_studio_quantity_uom": related_quant.x_studio_quantity_uom.id if related_quant.x_studio_quantity_uom else (related_quant.x_studio_quantity_uom_delivery.id if related_quant.x_studio_quantity_uom_delivery else False),
                                "x_studio_pallet_series_id": related_quant.x_studio_pallet_series_id or False,
                                "package_id": related_quant.result_package_id.id if related_quant.result_package_id else (related_quant.package_id.id if related_quant.package_id else False),
                            })
        
        # remove line with zero to save same disk space
        # avoid loop with direct SQL query
        _logger.info("Remove useless stock_quant_history with quantity == 0")
        self.env["stock.quant.history"].flush_model()
        self.env.cr.execute(
            "DELETE FROM stock_quant_history where quantity = 0 and snapshot_id = %s",
            (self.id,),
        )
        self.state = "generated"

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

        # Check if snapshot already exists for yesterday
        day_start = datetime.combine(yesterday, datetime.min.time())
        day_end = datetime.combine(yesterday, datetime.max.time())

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
