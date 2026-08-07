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
    # Multi-warehouse Phase 1: nullable for now (a snapshot still covers all
    # warehouses). Becomes required in Phase 2 when generation is rewritten to
    # one snapshot per warehouse per day (decision: 60 days retained PER
    # warehouse). Existing snapshots are backfilled by the 17.0.1.1.0 migration.
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        index=True,
        readonly=True,
        help="Warehouse this snapshot covers. Backfilled on legacy snapshots "
             "when all their lines belong to a single warehouse; empty only "
             "if a legacy snapshot genuinely mixes warehouses.",
    )
    generated_by_cron = fields.Boolean(
        string="Scheduled (auto-generated)",
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help="True when a scheduled action (daily generation or backfill) created "
             "this snapshot, as opposed to a manual/on-demand one. The Occupancy "
             "Report prefers the scheduled snapshot when more than one exists for "
             "the same day; a manual snapshot is only used as a fallback.",
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

    @api.constrains("inventory_date")
    def _check_inventory_date_not_future(self):
        """You cannot snapshot a day that has not happened yet. Compared on the
        Manila CALENDAR date, so 'today 23:59:59' (the end-of-day timestamp used
        throughout this module) is allowed while any future day is blocked. This
        one backstop covers the manual snapshot form, the occupancy wizard's
        auto-generation and the SQL-baseline path; the crons only ever create
        yesterday/past dates, so they are unaffected."""
        today_manila = datetime.now(self.MANILA_TZ).date()
        for rec in self:
            if not rec.inventory_date:
                continue
            inv_date_manila = pytz_utc.localize(
                rec.inventory_date
            ).astimezone(self.MANILA_TZ).date()
            if inv_date_manila > today_manila:
                raise ValidationError(_(
                    "You cannot generate an inventory snapshot for a future date "
                    "(%s). Please pick today or an earlier date."
                ) % inv_date_manila.strftime("%Y-%m-%d"))

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

    # Field types that can be copied as a single scalar/id onto
    # stock.quant.history. many2many / one2many are intentionally excluded.
    _COPYABLE_TTYPES = frozenset({
        "char", "text", "integer", "float", "monetary",
        "boolean", "date", "datetime", "selection", "many2one",
    })
    # Non-x_studio fields we also mirror from stock.quant -> stock.quant.history.
    _EXTRA_COPY_FIELDS = ("owner_id", "package_id")

    def _get_quant_copy_fields(self):
        """Dynamically discover which fields to copy from stock.quant onto
        stock.quant.history.

        Returns the list of field names that exist on BOTH models, so it works
        whether an x_studio_* field was declared in code (state=base) or created
        via Odoo Studio (state=manual). Self-heals when new Studio fields are
        added on both models; safely skips (and logs once) any source field that
        has no matching column on the history model. See FIX_PLAN.md (RC-5/D2).
        """
        quant_fields = self.env["stock.quant"]._fields
        history_fields = self.env["stock.quant.history"]._fields
        fields_to_copy = []
        skipped = []
        for name, field in quant_fields.items():
            if not (name.startswith("x_studio_") or name in self._EXTRA_COPY_FIELDS):
                continue
            if field.type not in self._COPYABLE_TTYPES:
                continue
            target = history_fields.get(name)
            if target is None:
                if name.startswith("x_studio_"):
                    skipped.append(name)
                continue
            # Allow char<->text interchange; otherwise require matching type.
            if target.type != field.type and {field.type, target.type} != {"char", "text"}:
                skipped.append("%s(%s!=%s)" % (name, field.type, target.type))
                continue
            fields_to_copy.append(name)
        if skipped:
            _logger.info(
                "stock.quant.history: %d unmirrored/incompatible source field(s) "
                "skipped during copy: %s",
                len(skipped), ", ".join(sorted(skipped)),
            )
        return fields_to_copy

    @api.model
    def _copy_field_values(self, source, field_names):
        """Read field_names off `source` (a stock.quant, stock.quant.history or
        stock.move.line record) and return a write-ready vals dict, coercing
        many2one values to ids. Fields absent on the source are skipped."""
        vals = {}
        source_fields = source._fields
        for name in field_names:
            field = source_fields.get(name)
            if field is None:
                continue
            value = source[name]
            if field.type == "many2one":
                value = value.id if value else False
            vals[name] = value
        return vals

    def _generate_stock_quant_history(self):
        self.ensure_one()
        _gen_start = datetime.now(self.MANILA_TZ)
        _logger.info(
            "[stock.quant.history] ===== START generation | snapshot_id=%s | %s | "
            "inventory_date=%s UTC | started_by=%s =====",
            self.id, self.name, self.inventory_date, self.env.user.login,
        )
        self.generated_date = _gen_start.astimezone(pytz_utc).replace(tzinfo=None)

        try:
            # RC-3 fix: inventory_date is stored UTC-naive; compare against the same.
            # The previous code compared against a Manila-local naive datetime which
            # introduced an 8h skew once multiple snapshots existed.
            previous_quant_snapshot = self.search(
                [
                    ("state", "=", "generated"),
                    ("inventory_date", "<", self.inventory_date),
                    ("id", "!=", self.id),
                ],
                order="inventory_date desc",
                limit=1,
            )
            self.previous_snapshot_id = previous_quant_snapshot

            copy_fields = self._get_quant_copy_fields()

            def create_quant_history(product, lot, location):
                return self.env["stock.quant.history"].sudo().create({
                    "snapshot_id": self.id,
                    "product_id": product.id,
                    "lot_id": lot.id if lot else False,
                    "location_id": location.id,
                    "quantity": 0,
                })

            quant_history = DefaultDict(
                lambda product, lot, location: create_quant_history(product, lot, location)
            )

            # Decide reconstruction strategy. If no done move line happened after
            # inventory_date, live stock.quant IS the trusted state at that date, so
            # seed directly from it (Approach B). This eliminates the phantom stock
            # from direct quant writes that never produced a move line (RC-1/RC-4).
            latest_move = self.env["stock.move.line"].sudo().search(
                [("state", "=", "done"), ("product_id.type", "=", "product")],
                order="date desc",
                limit=1,
            )
            is_current = (not latest_move) or (self.inventory_date >= latest_move.date)

            if is_current:
                _logger.info(
                    "Seeding %s directly from live stock.quant (current-day baseline)",
                    self.name,
                )
                self._seed_history_from_stock_quant(quant_history, copy_fields)
            else:
                _logger.info(
                    "Reconstructing %s by move-line replay from %s",
                    self.name, previous_quant_snapshot.name,
                )
                self._replay_into_quant_history(
                    quant_history, previous_quant_snapshot, copy_fields
                )
                # Account for pallet-detail adjustments that the plain move-line
                # replay cannot see (RC-2).
                self._apply_adjustment_lot_remap(quant_history, previous_quant_snapshot)
                self._apply_adjustment_metadata(
                    quant_history, previous_quant_snapshot, copy_fields
                )

            # Remove zero-qty rows (save disk space) AND negative-qty rows.
            # Negative on-hand KG is physically impossible and is treated as bad
            # source data: per business rule, never store negative kilograms in the
            # history. quantity <= 0 covers both cases. Done via direct SQL to avoid
            # a per-record loop.
            _logger.info("Remove stock_quant_history rows with quantity <= 0 (zero/negative KG)")
            self.env["stock.quant.history"].flush_model()
            self.env.cr.execute(
                "DELETE FROM stock_quant_history where quantity <= 0 and snapshot_id = %s",
                (self.id,),
            )
            self.state = "generated"

            row_count = self.env["stock.quant.history"].sudo().search_count(
                [("snapshot_id", "=", self.id)]
            )
            elapsed = (datetime.now(self.MANILA_TZ) - _gen_start).total_seconds()
            _logger.info(
                "[stock.quant.history] ===== FINISHED generation | snapshot_id=%s | %s | "
                "mode=%s | rows=%s | duration=%.1fs =====",
                self.id, self.name,
                "seed-from-stock.quant" if is_current else "move-line-replay",
                row_count, elapsed,
            )

        except Exception:
            elapsed = (datetime.now(self.MANILA_TZ) - _gen_start).total_seconds()
            _logger.exception(
                "[stock.quant.history] ===== ERROR in generation | snapshot_id=%s | %s | "
                "inventory_date=%s UTC | duration=%.1fs =====",
                self.id, self.name, self.inventory_date, elapsed,
            )
            raise

    def _seed_history_from_stock_quant(self, quant_history, copy_fields):
        """Approach B: build the snapshot rows directly from live stock.quant.

        Used when inventory_date is current (no later moves), so stock.quant is
        the source of truth. Guarantees the snapshot matches the live inventory
        by construction.
        """
        ignored_location_usage = self._ignored_location_usage()
        quants = self.env["stock.quant"].sudo().search([
            ("product_id.type", "=", "product"),
            ("location_id.usage", "not in", ignored_location_usage),
            ("quantity", "!=", 0),
        ])
        _logger.info("Seeding from %s stock.quant record(s)", len(quants))
        for quant in quants:
            rec = quant_history[
                (quant.product_id, quant.lot_id, quant.location_id)
            ]
            vals = self._copy_field_values(quant, copy_fields)
            vals["quantity"] = quant.quantity
            rec.write(vals)

    def _replay_into_quant_history(self, quant_history, previous_quant_snapshot, copy_fields):
        """Backward/incremental reconstruction: start from the previous snapshot
        (or zero) and replay stock.move.line deltas up to inventory_date."""
        if previous_quant_snapshot.stock_quant_history_ids.exists():
            _logger.info(
                "Duplicate %s previous stock.quant.history...",
                len(previous_quant_snapshot.stock_quant_history_ids),
            )
            for prev in previous_quant_snapshot.stock_quant_history_ids:
                quant_copy = quant_history[
                    (prev.product_id, prev.lot_id, prev.location_id)
                ]
                vals = self._copy_field_values(prev, copy_fields)
                vals["quantity"] = prev.quantity
                quant_copy.write(vals)

        stock_move_lines = (
            self.env["stock.move.line"]
            .sudo()
            .search(self._prepare_stock_move_line_filter(previous_quant_snapshot))
        )
        _logger.info(
            "Apply %s stock.move.line since previous snapshot", len(stock_move_lines)
        )
        ignored_location_usage = self._ignored_location_usage()
        for move_line in stock_move_lines:
            qty_in_product_uom = move_line.product_uom_id._compute_quantity(
                move_line.quantity, move_line.product_id.uom_id
            )
            if move_line.location_id.usage not in ignored_location_usage:
                key = (move_line.product_id, move_line.lot_id, move_line.location_id)
                quant_history[key].quantity = tools.float_round(
                    quant_history[key].quantity - qty_in_product_uom,
                    precision_rounding=move_line.product_id.uom_id.rounding,
                )

            if move_line.location_dest_id.usage not in ignored_location_usage:
                key = (move_line.product_id, move_line.lot_id, move_line.location_dest_id)
                rec = quant_history[key]
                rec.quantity = tools.float_round(
                    rec.quantity + qty_in_product_uom,
                    precision_rounding=move_line.product_id.uom_id.rounding,
                )
                # Enrich metadata straight from the move line (owner, pallet,
                # dates, container...). The move line itself carries these
                # x_studio_* values, so we no longer need the slow/brittle
                # related-quant lookup. Only non-empty values are written so we
                # never clobber good data with blanks.
                ml_vals = self._move_line_metadata_vals(move_line, copy_fields)
                if ml_vals:
                    rec.write(ml_vals)

    def _move_line_metadata_vals(self, move_line, copy_fields):
        """Build a vals dict of non-empty metadata from a stock.move.line,
        mapping the destination package from result_package_id."""
        vals = self._copy_field_values(move_line, copy_fields)
        if "package_id" in copy_fields:
            vals["package_id"] = (
                move_line.result_package_id.id
                or (move_line.package_id.id if move_line.package_id else False)
            )
        return {k: v for k, v in vals.items() if v not in (False, "", 0, 0.0)}

    def _apply_adjustment_lot_remap(self, quant_history, previous_quant_snapshot):
        """RC-2: pallet-detail adjustments approved via multiple_relocation can
        change a quant's lot/product in place. The original receipt move line
        still references the OLD lot, so the replay parks the quantity under the
        old (product, lot, location) key. Move that quantity to the new key
        using the approved stock.quant.adjustment.line records in range."""
        AdjLine = self.env.get("stock.quant.adjustment.line")
        if AdjLine is None:
            return  # multiple_relocation not installed
        AdjLine = AdjLine.sudo()
        domain = [
            ("line_state", "=", "approved"),
            ("request_id.approved_date", "<=", self.inventory_date),
        ]
        if previous_quant_snapshot.exists():
            domain.append(
                ("request_id.approved_date", ">", previous_quant_snapshot.inventory_date)
            )
        adj_lines = AdjLine.search(domain, order="request_id")
        for adj in adj_lines:
            quant = adj.quant_id
            if not quant:
                continue
            location = quant.location_id
            old_product = adj.old_product_id or quant.product_id
            new_product = adj.new_product_id or old_product
            old_lot = adj.old_lot_id
            new_lot = adj.new_lot_id or old_lot
            lot_changed = bool(adj.old_lot_id and adj.new_lot_id and adj.old_lot_id != adj.new_lot_id)
            product_changed = old_product != new_product
            if not (lot_changed or product_changed):
                continue
            old_key = (old_product, old_lot, location)
            if old_key not in quant_history:
                continue
            qty = quant_history[old_key].quantity
            if not qty:
                continue
            new_key = (new_product, new_lot, location)
            quant_history[old_key].quantity = 0  # emptied -> dropped by cleanup
            rounding = new_product.uom_id.rounding or 0.01
            quant_history[new_key].quantity = tools.float_round(
                quant_history[new_key].quantity + qty,
                precision_rounding=rounding,
            )

    def _apply_adjustment_metadata(self, quant_history, previous_quant_snapshot, copy_fields):
        """RC-2: metadata-only pallet adjustments create a zero-quantity
        correction move line carrying the NEW x_studio_* values. The plain
        replay ignores zero-qty lines, discarding those changes. Re-apply the
        metadata onto the matching existing history row (latest move wins)."""
        domain = [
            ("is_quant_detail_adjusted", "=", True),
            ("quantity", "=", 0),
            ("state", "=", "done"),
            ("date", "<=", self.inventory_date),
        ]
        if previous_quant_snapshot.exists():
            domain.append(("date", ">", previous_quant_snapshot.inventory_date))
        adj_moves = self.env["stock.move.line"].sudo().search(domain, order="date asc")
        ignored_location_usage = self._ignored_location_usage()
        for ml in adj_moves:
            if ml.location_dest_id.usage in ignored_location_usage:
                continue
            key = (ml.product_id, ml.lot_id, ml.location_dest_id)
            if key not in quant_history:
                # Don't fabricate phantom rows from metadata-only moves.
                continue
            vals = self._move_line_metadata_vals(ml, copy_fields)
            if vals:
                quant_history[key].write(vals)

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

        # Look for the SCHEDULED snapshot specifically, not just any snapshot.
        # A user may have manually generated one for this day; the scheduled
        # action must still produce its OWN authoritative end-of-day snapshot so
        # the Occupancy Report always has an odoobot record to prefer (the manual
        # one is only a fallback). The resulting duplicate on user-snapshot days
        # is resolved by the report's per-day dedupe.
        existing_cron = self.search([
            ('inventory_date', '>=', day_start),
            ('inventory_date', '<=', day_end),
            ('generated_by_cron', '=', True),
        ], limit=1)

        if not existing_cron:
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
                'generated_by_cron': True,
            })
            _logger.info(
                "CRON: created scheduled snapshot for %s (inventory_date=%s)",
                yesterday, utc_dt,
            )
            snapshot._generate_stock_quant_history()
        elif existing_cron.state == 'draft':
            _logger.info("CRON: generating existing draft scheduled snapshot for %s", yesterday)
            existing_cron._generate_stock_quant_history()
        else:
            _logger.info("CRON: scheduled snapshot for %s already exists and is generated", yesterday)

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
    BACKFILL_BATCH = 2

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

        # Walk backwards from yesterday (today is handled by the daily cron)
        missing = []
        d = today - timedelta(days=1)
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
                'generated_by_cron': True,
            })
            _logger.info(
                "Backfill CRON: created scheduled snapshot for %s (inventory_date=%s)",
                target_date, utc_dt,
            )
            try:
                snapshot._generate_stock_quant_history()
                created += 1
            except Exception:
                _logger.exception(
                    "Backfill CRON: FAILED to generate snapshot for %s (snapshot_id=%s) "
                    "— skipping to next date",
                    target_date, snapshot.id,
                )

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
