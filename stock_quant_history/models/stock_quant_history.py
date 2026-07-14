# Copyright 2024 Foodles (https://www.foodles.co/).
# @author Pierre Verkest <pierreverkest84@gmail.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class StockQuantHistory(models.Model):
    _name = "stock.quant.history"
    _description = "Stock quants history"
    _order = "snapshot_id, inventory_date, product_id, lot_id, location_id"

    snapshot_id = fields.Many2one(
        comodel_name="stock.quant.history.snapshot",
        ondelete="cascade",
        required=True,
        index=True,
        string="Snapshot settings",
        help="Snapshot settings used to generate this line",
    )
    inventory_date = fields.Datetime(
        related="snapshot_id.inventory_date",
        index=True,
        store=True,
    )
    # same fields as stock.quant
    product_id = fields.Many2one(
        "product.product",
        "Product",
        ondelete="restrict",
        readonly=True,
        required=True,
        index=True,
        check_company=True,
    )
    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product Template",
        related="product_id.product_tmpl_id",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        "uom.uom", "Unit of Measure", readonly=True, related="product_id.uom_id"
    )
    company_id = fields.Many2one(
        related="location_id.company_id", string="Company", store=True, readonly=True
    )
    location_id = fields.Many2one(
        "stock.location",
        "Location",
        auto_join=True,
        ondelete="restrict",
        readonly=True,
        required=True,
        index=True,
        check_company=True,
    )
    # Multi-warehouse Phase 1. Existing rows are backfilled by raw SQL in
    # migrations/17.0.1.1.0/pre-migrate.py (the table holds ~1M+ rows; the
    # pre-created column stops the ORM from recomputing them one by one).
    warehouse_id = fields.Many2one(
        related="location_id.warehouse_id", store=True, index=True,
        string="Warehouse",
    )
    lot_id = fields.Many2one(
        "stock.lot",
        "Lot/Serial Number",
        index=True,
        ondelete="restrict",
        readonly=True,
        check_company=True,
    )
    quantity = fields.Float(
        help=(
            "Quantity of products in this quant, "
            "in the default unit of measure of the product"
        ),
        readonly=True,
    )
    # Additional fields from stock.quant
    x_studio_record_reference = fields.Many2one(
        "stock.picking",
        string="Record Reference",
        readonly=True,
    )
    x_studio_stock_code = fields.Char(
        string="Stock Code",
        readonly=True,
    )
    x_studio_return_count = fields.Integer(
        string="Return Count",
        readonly=True,
    )
    x_studio_pallet_series_id = fields.Char(
        string="Pallet Series ID",
        readonly=True,
    )
    package_id = fields.Many2one(
        "stock.quant.package",
        string="Package",
        readonly=True,
        check_company=True,
    )
    x_studio_production_date = fields.Date(
        string="Production Date",
        readonly=True,
    )
    x_studio_expiration_date = fields.Date(
        string="Expiration Date",
        readonly=True,
    )
    x_studio_loading_dock_no = fields.Char(
        string="Loading Dock No",
        readonly=True,
    )
    x_studio_source = fields.Char(
        string="Source",
        readonly=True,
    )
    x_studio_gate_pass = fields.Char(
        string="Gate Pass",
        readonly=True,
    )
    x_studio_truck_time = fields.Datetime(
        string="Truck Time",
        readonly=True,
    )
    x_studio_start_time = fields.Datetime(
        string="Start Time",
        readonly=True,
    )
    x_studio_end_time = fields.Datetime(
        string="End Time",
        readonly=True,
    )
    x_studio_truck_number = fields.Char(
        string="Truck Number",
        readonly=True,
    )
    x_studio_2nd_uom = fields.Float(
        string="2nd UoM",
        readonly=True,
    )
    x_studio_quantity_uom = fields.Many2one(
        "uom.uom",
        string="Quantity UoM",
        readonly=True,
    )
    x_studio_total_units = fields.Float(
        string="Total Units",
        readonly=True,
    )
    x_studio_min_quantity_uom = fields.Many2one(
        "uom.uom",
        string="Min Quantity UoM",
        readonly=True,
    )

    x_studio_special_holding = fields.Boolean(
        string="Special Holding",
        readonly=True,
    )
    # NOTE: x_studio_sh_reason is a `text` field on stock.quant (Studio/manual).
    # Declared as Text here too so the type matches the source and dynamic copy
    # never truncates / mis-casts. See FIX_PLAN.md (D5).
    x_studio_sh_reason = fields.Text(
        string="SH Reason",
        readonly=True,
    )
    x_studio_container_number = fields.Char(
        string="Container #",
        readonly=True,
    )
    # Additional high-value fields that exist on stock.quant via Studio but were
    # previously not mirrored here, so they never reached the reports. Declared in
    # code so the dynamic field discovery picks them up on both models. See
    # FIX_PLAN.md (D2).
    x_studio_building = fields.Char(
        string="Building",
        readonly=True,
    )
    x_studio_inbound_date = fields.Date(
        string="Inbound Date",
        readonly=True,
    )
    x_studio_remarks = fields.Char(
        string="Remarks",
        readonly=True,
    )
    x_studio_tally_sheet = fields.Char(
        string="Tally Sheet",
        readonly=True,
    )
    owner_id = fields.Many2one(
        "res.partner",
        string="Owner",
        readonly=True,
    )
    
    is_a_blast_freeze = fields.Boolean(
        related="location_id.x_studio_is_a_blast_freezer",
        string="Is a Blast Freeze",
        readonly=True,
        store=True,
    )
