# Copyright 2024 Foodles (https://www.foodles.co/).
# @author Pierre Verkest <pierreverkest84@gmail.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging
from collections import defaultdict

from pytz import timezone

from odoo import _, api, fields, models, tools
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

            user_tz = "Asia/Manila"
            user_timezone = timezone(user_tz)

            local_inventory_date = rec.inventory_date.astimezone(user_timezone)

            rec.name = _("Snapshot %s") % local_inventory_date.strftime(dt_format)

    def action_generate_stock_quant_history(self):
        for snapshot in self:
            snapshot._generate_stock_quant_history()

    def _prepare_stock_move_line_filter(self, previous_quant_snapshot):
        domain = [
            ("state", "=", "done"),
            ("date", "<=", self.inventory_date),
            ("product_id.type", "=", "product"),
        ]
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
        self.generated_date = fields.Datetime.now()
        previous_quant_snapshot = self.search(
            [
                ("state", "=", "generated"),
                ("inventory_date", "<=", self.inventory_date),
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
                        ("product_id", "=", move_line.product_id.id),
                        ("lot_id", "=", move_line.lot_id.id),
                        ("location_id", "=", move_line.location_dest_id.id)
                    ], limit=1)
                    
                    if related_quant:
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
        
        # remove line with zero to save same disk space
        # avoid loop with direct SQL query
        _logger.info("Remove useless stock_quant_history with quantity == 0")
        self.env["stock.quant.history"]._flush()
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
