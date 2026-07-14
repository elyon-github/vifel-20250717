# -*- coding: utf-8 -*-
"""Global warehouse record rules.

A user with Allowed Warehouses = [B] must see only warehouse B's pickings,
quants, moves, locations (plus warehouse-less records). A user with an EMPTY
allowed list is unrestricted — that is the admin/rollout path.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestWarehouseRecordRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh_a = cls.env.ref('stock.warehouse0')
        cls.wh_b = cls.env['stock.warehouse'].create({
            'name': 'Rules WH B', 'code': 'RWB',
        })
        base_groups = [
            cls.env.ref('base.group_user').id,
            cls.env.ref('stock.group_stock_user').id,
        ]
        # user restricted to warehouse B only
        cls.user_b = cls.env['res.users'].create({
            'name': 'Rules User B', 'login': 'rules_user_b',
            'groups_id': [(6, 0, base_groups)],
            'allowed_warehouse_ids': [(6, 0, [cls.wh_b.id])],
        })
        # user with EMPTY allowed list -> unrestricted
        cls.user_free = cls.env['res.users'].create({
            'name': 'Rules Free User', 'login': 'rules_free_user',
            'groups_id': [(6, 0, base_groups)],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Rules Product', 'type': 'product',
        })
        cls.picking_a = cls.env['stock.picking'].create({
            'picking_type_id': cls.wh_a.in_type_id.id,
            'location_id': cls.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': cls.wh_a.lot_stock_id.id,
        })
        cls.quant_a = cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.wh_a.lot_stock_id.id,
            'quantity': 5.0,
        })

    def test_restricted_user_cannot_see_other_warehouse_picking(self):
        """A WH-B user's picking search excludes WH-A pickings."""
        found = self.env['stock.picking'].with_user(self.user_b).search(
            [('id', '=', self.picking_a.id)])
        self.assertFalse(found)

    def test_restricted_user_cannot_see_other_warehouse_quant(self):
        """A WH-B user's quant search excludes WH-A quants."""
        found = self.env['stock.quant'].with_user(self.user_b).search(
            [('id', '=', self.quant_a.id)])
        self.assertFalse(found)

    def test_restricted_user_cannot_see_other_warehouse_location(self):
        """A WH-B user cannot see WH-A's stock location."""
        found = self.env['stock.location'].with_user(self.user_b).search(
            [('id', '=', self.wh_a.lot_stock_id.id)])
        self.assertFalse(found)

    def test_restricted_user_sees_own_warehouse(self):
        """The same user DOES see their own warehouse's records."""
        picking_b = self.env['stock.picking'].create({
            'picking_type_id': self.wh_b.in_type_id.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.wh_b.lot_stock_id.id,
        })
        found = self.env['stock.picking'].with_user(self.user_b).search(
            [('id', '=', picking_b.id)])
        self.assertEqual(found, picking_b)
        self.assertIn(self.wh_b.lot_stock_id,
                      self.env['stock.location'].with_user(self.user_b).search([]))

    def test_warehouse_list_is_scoped(self):
        """The warehouse list itself only shows allowed warehouses."""
        warehouses = self.env['stock.warehouse'].with_user(self.user_b).search([])
        self.assertEqual(warehouses, self.wh_b)

    def test_warehouse_less_records_stay_visible(self):
        """Records without a warehouse (e.g. vendor location) stay visible."""
        suppliers = self.env.ref('stock.stock_location_suppliers')
        found = self.env['stock.location'].with_user(self.user_b).search(
            [('id', '=', suppliers.id)])
        self.assertEqual(found, suppliers)

    def test_empty_allowed_list_is_unrestricted(self):
        """A user with no allowed warehouses sees everything (admin/rollout path)."""
        found = self.env['stock.picking'].with_user(self.user_free).search(
            [('id', '=', self.picking_a.id)])
        self.assertEqual(found, self.picking_a)
        warehouses = self.env['stock.warehouse'].with_user(self.user_free).search([])
        self.assertIn(self.wh_a, warehouses)
        self.assertIn(self.wh_b, warehouses)
