from collections import defaultdict

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, users


class TestStockQuantHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                test_queue_job_no_delay=True,  # no jobs thanks
            )
        )

        cls.stock_history_now = cls.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.now(),
            }
        )

        cls.stock_manager_user = cls.env["res.users"].create(
            {
                "name": "foo",
                "login": "stock_manager",
                "email": "foo@bar.com",
                "lang": "en_US",
                "groups_id": [
                    (
                        6,
                        0,
                        (
                            cls.env.ref("base.group_user")
                            | cls.env.ref("stock.group_stock_manager")
                        ).ids,
                    )
                ],
            }
        )
        cls.warehouse = cls.env.ref("stock.warehouse0")
        cls.location = cls.warehouse.lot_stock_id
        cls.product = cls.env["product.product"].create(
            {
                "name": "test",
                "type": "product",
                "tracking": "lot",
            }
        )
        cls.lot = cls.env["stock.lot"].create(
            {
                "name": "lot test",
                "product_id": cls.product.id,
                "company_id": cls.warehouse.company_id.id,
            }
        )
        cls.product_consu = cls.env["product.product"].create(
            {
                "name": "test",
                "type": "consu",
            }
        )

    def _update_product_stock(self, qty, uom=None):
        lot = self.lot
        location = self.location
        if not uom:
            uom = self.product.uom_id

        qty_in_base_uom = uom._compute_quantity(qty, self.product.uom_id)

        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", location.id),
                ("lot_id", "=", lot.id if lot else False),
            ],
            limit=1,
        )

        if not quant:
            quant = (
                self.env["stock.quant"]
                .with_context(inventory_mode=True)
                .create(
                    {
                        "product_id": self.product.id,
                        "location_id": location.id,
                        "lot_id": lot.id if lot else False,
                        "inventory_quantity": qty_in_base_uom,
                    }
                )
            )
            quant.action_apply_inventory()
            return

        quant.with_context(inventory_mode=True).write(
            {
                "inventory_quantity_auto_apply": qty_in_base_uom,
            }
        )

    @classmethod
    def quants_quantity_group_by(cls, recordset, key):
        """inspired from sale_product_pack PR: gh:oca/product-pack/pull/159"""
        groups = defaultdict(lambda: 0)
        for elem in recordset:
            groups[key(elem)] += elem.quantity
        return groups

    def assertQuantCompare(self, quants, expected_quants):
        """works either with stock.quant or stock.quants.history"""

        def group_key(quant):
            return quant.product_id, quant.lot_id, quant.location_id

        grouped_quants = self.quants_quantity_group_by(quants, group_key)
        grouped_expected_quants = self.quants_quantity_group_by(
            expected_quants, group_key
        )
        errors1 = []
        errors2 = []
        ok = []
        for key, quantity in grouped_quants.items():
            if grouped_expected_quants[key] != quantity:
                errors1.append(
                    f"got {quantity} != Expected {grouped_expected_quants[key]} for"
                    f"{key}: [{key[0].name}, {key[1].name}, {key[2].name}], "
                )
            else:
                ok.append(
                    f"{grouped_expected_quants[key]} for "
                    f"{key}: [{key[0].name}, {key[1].name}, {key[2].name}], "
                    f"is the same {quantity} !"
                )

        for key, quantity in grouped_expected_quants.items():
            if grouped_quants[key] != quantity:
                errors2.append(
                    f"got {grouped_quants[key]} != Expected {quantity} for "
                    f"{key}: [{key[0].name}, {key[1].name}, {key[2].name}], "
                )
        self.assertEqual(
            len(errors1) + len(errors2),
            0,
            "Following diff detected:\n\n".join(errors1)
            + "\n or/and \n "
            + "\n".join(errors2)
            + "\n\nOK records:\n"
            + "\n".join(ok),
        )

    def test_compare_quant(self):
        self.stock_history_now.action_generate_stock_quant_history()
        self.assertQuantCompare(
            self.stock_history_now.stock_quant_history_ids,
            self.env["stock.quant"].search(
                [
                    (
                        "location_id.usage",
                        "not in",
                        [
                            "customer",
                            "inventory",
                            "supplier",
                        ],
                    ),
                ]
            ),
        )

    @users("stock_manager")
    def test_unlink_snapshot_unlink_related_stock_quant_history_records(self):
        # browse with current user
        self.stock_history_now.action_generate_stock_quant_history()
        stock_history_now = self.env["stock.quant.history.snapshot"].browse(
            self.stock_history_now.id
        )
        stock_quant_history_ids = stock_history_now.stock_quant_history_ids.ids
        self.assertTrue(
            len(stock_quant_history_ids) > 0,
        )
        stock_history_now.unlink()
        self.assertEqual(
            self.env["stock.quant.history"].search_count(
                [("id", "in", stock_quant_history_ids)]
            ),
            0,
        )

    @users("stock_manager")
    def test_unlink_stock_quant_history_is_forbidden(self):
        # browse with current user
        self.stock_history_now.action_generate_stock_quant_history()
        stock_history_now = self.env["stock.quant.history.snapshot"].browse(
            self.stock_history_now.id
        )
        with self.assertRaisesRegex(
            AccessError, r"You are not allowed to delete.*stock.quant.histor.*"
        ):
            stock_history_now.stock_quant_history_ids.unlink()

    @users("stock_manager")
    def test_stock_manager_create(self):
        stock_history_now = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("1984-06-15 11:22:32"),
            }
        )
        self.assertEqual(
            stock_history_now.name,
            # en_US format
            "Snapshot 06/15/1984 11:22:32",
        )
        stock_history_now.inventory_date = fields.Datetime.now()
        stock_history_now.action_generate_stock_quant_history()

    @freeze_time("2024-01-01 10:11")
    def test_no_lines_before_oldest_move(self):
        stock_history_1970 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("1970-01-01"),
            }
        )
        stock_history_1970.action_generate_stock_quant_history()
        self.assertEqual(
            stock_history_1970.generated_date,
            fields.Datetime.from_string("2024-01-01 10:11"),
        )
        self.assertEqual(stock_history_1970.state, "generated")
        self.assertEqual(len(stock_history_1970.stock_quant_history_ids), 0)

    def test_round_decimal_using_uom_precision(self):
        with freeze_time("2023-01-01 10:00:00"):
            self._update_product_stock(10.001)

        with freeze_time("2023-01-01 20:00:00"):
            self._update_product_stock(20.002)

        snapshot_10 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 10:00:00"),
            }
        )
        snapshot_10.action_generate_stock_quant_history()
        quant_history_10 = snapshot_10.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        # force wrong rounding for testing purpose adding float in python can be tricky
        # >>> 0.1 + 0.1 + 0.1
        # 0.30000000000000004

        quant_history_10.quantity = 10.001
        snapshot_20 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 20:00:00"),
            }
        )
        snapshot_20.action_generate_stock_quant_history()
        quant_history_20 = snapshot_20.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_20.quantity, 20)

    def test_next_quant_history_generation(self):
        with freeze_time("2023-01-01 10:00:00"):
            self._update_product_stock(10)

        with freeze_time("2023-01-01 20:00:00"):
            self._update_product_stock(30)

        snapshot_10 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 10:00:00"),
            }
        )
        snapshot_10.action_generate_stock_quant_history()
        quant_history_10 = snapshot_10.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_10.quantity, 10)

        snapshot_15 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 15:00:00"),
            }
        )
        snapshot_15.action_generate_stock_quant_history()
        quant_history_15 = snapshot_15.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_15.quantity, 10)
        self.assertNotEqual(quant_history_10, quant_history_15)
        self.assertNotEqual(
            quant_history_10.inventory_date, quant_history_15.inventory_date
        )
        snapshot_20 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 20:00:00"),
            }
        )
        snapshot_20.action_generate_stock_quant_history()
        quant_history_20 = snapshot_20.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_20.quantity, 30)

        snapshot_now = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.now(),
            }
        )
        snapshot_now.action_generate_stock_quant_history()
        self.assertQuantCompare(
            snapshot_now.stock_quant_history_ids,
            self.env["stock.quant"].search(
                [
                    (
                        "location_id.usage",
                        "not in",
                        [
                            "customer",
                            "inventory",
                            "supplier",
                        ],
                    ),
                ]
            ),
        )

    def test_quant_0_not_present(self):
        with freeze_time("2023-01-01 10:00:00"):
            self._update_product_stock(10)

        with freeze_time("2023-01-01 15:00:00"):
            self._update_product_stock(0)

        with freeze_time("2023-01-01 20:00:00"):
            self._update_product_stock(30)

        snapshot_10 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 10:00:00"),
            }
        )
        snapshot_10.action_generate_stock_quant_history()
        self.assertFalse(snapshot_10.previous_snapshot_id)
        quant_history_10 = snapshot_10.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_10.quantity, 10)

        self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 12:00:00"),
            }
        )
        snapshot_15 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 15:00:00"),
            }
        )
        snapshot_15.action_generate_stock_quant_history()
        self.assertEqual(snapshot_15.previous_snapshot_id, snapshot_10)
        quant_history_15 = snapshot_15.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertFalse(
            quant_history_15.exists(),
        )

        snapshot_20 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 20:00:00"),
            }
        )
        snapshot_20.action_generate_stock_quant_history()
        self.assertEqual(snapshot_20.previous_snapshot_id, snapshot_15)
        quant_history_20 = snapshot_20.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_20.quantity, 30)

    def test_action_related_stock_quant_history_tree_view(self):
        self.assertEqual(
            self.stock_history_now.action_related_stock_quant_history_tree_view()[
                "domain"
            ],
            [("snapshot_id", "in", self.stock_history_now.ids)],
        )

    def test_consu_product_are_ignored(self):
        with freeze_time("2023-01-01 09:00:00"):
            # Create stock picking with consumable
            picking = self.env["stock.picking"].create(
                {
                    "location_id": self.env.ref("stock.stock_location_customers").id,
                    "location_dest_id": self.location.id,
                    "picking_type_id": self.env.ref("stock.picking_type_in").id,
                }
            )
            self.env["stock.move"].create(
                {
                    "name": self.product_consu.name,
                    "product_id": self.product_consu.id,
                    "product_uom_qty": 50.000,
                    "product_uom": self.product_consu.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": self.env.ref("stock.stock_location_customers").id,
                    "location_dest_id": self.location.id,
                }
            )
            picking.action_confirm()
            picking.move_ids_without_package.quantity = 50.000
            picking.button_validate()

        snapshot_10 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 10:00:00"),
            }
        )
        snapshot_10.action_generate_stock_quant_history()
        self.assertFalse(snapshot_10.stock_quant_history_ids)

    def test_different_uom(self):
        with freeze_time("2023-01-01 10:00:00"):
            self._update_product_stock(10, uom=self.env.ref("uom.product_uom_dozen"))

        snapshot_10 = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.from_string("2023-01-01 10:00:00"),
            }
        )
        snapshot_10.action_generate_stock_quant_history()
        quant_history_10 = snapshot_10.stock_quant_history_ids.filtered(
            lambda quant_history,
            pdt=self.product,
            loc=self.location: quant_history.product_id == pdt
            and quant_history.location_id == loc
        )
        self.assertEqual(quant_history_10.quantity, 120)

    def test_default_name(self):
        snapshot = self.env["stock.quant.history.snapshot"].new()
        self.assertEqual(snapshot.name, "Snapshot")

    def test_idempotent_regeneration(self):
        """Regenerating an already generated snapshot must not duplicate rows."""
        self._update_product_stock(10)
        snapshot = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.now(),
            }
        )
        snapshot.action_generate_stock_quant_history()
        first_count = len(snapshot.stock_quant_history_ids)
        self.assertTrue(first_count > 0)

        # Re-run: the previous lines must be replaced, never appended.
        snapshot.action_generate_stock_quant_history()
        second = snapshot.stock_quant_history_ids
        self.assertEqual(len(second), first_count)

        # No duplicate (product, lot, location) key inside the snapshot.
        keys = second.mapped(
            lambda h: (h.product_id.id, h.lot_id.id, h.location_id.id)
        )
        self.assertEqual(len(keys), len(set(keys)))

        # Still matches the live stock.quant.
        self.assertQuantCompare(
            second,
            self.env["stock.quant"].search(
                [
                    (
                        "location_id.usage",
                        "not in",
                        ["customer", "inventory", "supplier"],
                    ),
                ]
            ),
        )

    def test_delivered_stock_not_logged(self):
        """Stock delivered to a customer must not remain in the snapshot."""
        self._update_product_stock(10)
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.location.id,
                "location_dest_id": customers.id,
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
            }
        )
        self.env["stock.move"].create(
            {
                "name": self.product.name,
                "product_id": self.product.id,
                "product_uom_qty": 10.0,
                "product_uom": self.product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.location.id,
                "location_dest_id": customers.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.move_line_ids.write(
            {"lot_id": self.lot.id, "quantity": 10.0}
        )
        picking.button_validate()

        snapshot = self.env["stock.quant.history.snapshot"].create(
            {
                "inventory_date": fields.Datetime.now(),
            }
        )
        snapshot.action_generate_stock_quant_history()
        delivered = snapshot.stock_quant_history_ids.filtered(
            lambda h, pdt=self.product, loc=self.location: h.product_id == pdt
            and h.location_id == loc
        )
        self.assertFalse(delivered.exists())

        # The whole snapshot still matches the live stock.quant.
        self.assertQuantCompare(
            snapshot.stock_quant_history_ids,
            self.env["stock.quant"].search(
                [
                    (
                        "location_id.usage",
                        "not in",
                        ["customer", "inventory", "supplier"],
                    ),
                ]
            ),
        )

    def test_cron_daily_no_duplicate_snapshot(self):
        """Running the daily cron twice must not create a duplicate snapshot."""
        SnapshotModel = self.env["stock.quant.history.snapshot"]
        before = SnapshotModel.search_count([])
        SnapshotModel._cron_generate_daily_snapshot()
        after_first = SnapshotModel.search_count([])
        SnapshotModel._cron_generate_daily_snapshot()
        after_second = SnapshotModel.search_count([])
        self.assertEqual(after_first - before, 1)
        self.assertEqual(after_second, after_first)
