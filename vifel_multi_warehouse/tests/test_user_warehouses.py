# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestUserWarehouses(TransactionCase):
    """Allowed Warehouses assignment on res.users."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh_main = cls.env.ref('stock.warehouse0')
        cls.wh_other = cls.env['stock.warehouse'].create({
            'name': 'Test WH B', 'code': 'TWB',
        })
        cls.user = cls.env['res.users'].create({
            'name': 'MW Test User', 'login': 'mw_test_user',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_assign_warehouses(self):
        """Warehouses are assigned directly on the user."""
        self.user.write({
            'allowed_warehouse_ids': [(6, 0, [self.wh_other.id])],
        })
        self.assertEqual(self.user.allowed_warehouse_ids, self.wh_other)

    def test_default_within_allowed_ok(self):
        """default_warehouse_id inside allowed_warehouse_ids is accepted."""
        self.user.write({
            'allowed_warehouse_ids': [(6, 0, [self.wh_main.id, self.wh_other.id])],
            'default_warehouse_id': self.wh_other.id,
        })
        self.assertEqual(self.user.default_warehouse_id, self.wh_other)

    def test_default_outside_allowed_raises(self):
        """default_warehouse_id outside allowed_warehouse_ids is rejected."""
        with self.assertRaises(ValidationError):
            self.user.write({
                'allowed_warehouse_ids': [(6, 0, [self.wh_main.id])],
                'default_warehouse_id': self.wh_other.id,
            })

    def test_default_without_allowed_ok(self):
        """A default warehouse with an EMPTY allowed list is accepted."""
        self.user.write({
            'allowed_warehouse_ids': [(5, 0, 0)],
            'default_warehouse_id': self.wh_main.id,
        })
        self.assertEqual(self.user.default_warehouse_id, self.wh_main)
