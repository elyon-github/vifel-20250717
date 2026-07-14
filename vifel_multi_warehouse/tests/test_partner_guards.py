# -*- coding: utf-8 -*-
"""Contact-per-warehouse guard-rails.

The guards key on the Studio fields ``x_studio_warehouse`` and
``x_studio_client_unique_code_1`` (which exist in the production DB but not in
a bare test registry), so ``setUpClass`` creates them as manual fields — the
same way Odoo Studio does. The no-studio-fields case is covered implicitly by
every other module's partner tests (guards no-op without the fields).
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPartnerGuards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        partner_model = cls.env['ir.model']._get('res.partner')
        FieldsModel = cls.env['ir.model.fields']
        if 'x_studio_warehouse' not in Partner._fields:
            FieldsModel.create({
                'model_id': partner_model.id,
                'name': 'x_studio_warehouse',
                'field_description': 'Warehouse',
                'ttype': 'many2one',
                'relation': 'stock.warehouse',
                'state': 'manual',
            })
        if 'x_studio_client_unique_code_1' not in Partner._fields:
            FieldsModel.create({
                'model_id': partner_model.id,
                'name': 'x_studio_client_unique_code_1',
                'field_description': 'Client Unique Code',
                'ttype': 'char',
                'state': 'manual',
            })
        cls.wh_a = cls.env.ref('stock.warehouse0')
        cls.wh_b = cls.env['stock.warehouse'].create({
            'name': 'Guard WH B', 'code': 'GWB',
        })

    def _make_client(self, name, warehouse, code='TST'):
        return self.env['res.partner'].create({
            'name': name,
            'x_studio_warehouse': warehouse.id if warehouse else False,
            'x_studio_client_unique_code_1': code,
        })

    def _make_done_picking(self, partner):
        """Create and validate a 1-line internal receipt for the partner."""
        wh = self.wh_a
        product = self.env['product.product'].create({
            'name': 'Guard Product', 'type': 'product',
        })
        picking = self.env['stock.picking'].create({
            'picking_type_id': wh.in_type_id.id,
            'partner_id': partner.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': wh.lot_stock_id.id,
            'move_ids': [(0, 0, {
                'name': 'Guard move',
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': 1.0,
                'location_id': self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': wh.lot_stock_id.id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.quantity = 1.0
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        return picking

    # ── guard 1: client code requires a warehouse ────────────────────────
    def test_client_without_warehouse_rejected(self):
        """A contact with a client code but no warehouse raises."""
        with self.assertRaises(ValidationError):
            self._make_client('No WH Client', None)

    def test_client_with_warehouse_ok(self):
        """A contact with client code + warehouse is accepted."""
        partner = self._make_client('OK Client', self.wh_a)
        self.assertEqual(partner.x_studio_warehouse, self.wh_a)

    def test_clearing_warehouse_on_client_rejected(self):
        """Emptying the warehouse of a coded client raises."""
        partner = self._make_client('Clear Client', self.wh_a)
        with self.assertRaises(ValidationError):
            partner.write({'x_studio_warehouse': False})

    # ── guard 2: warehouse immutable once history exists ─────────────────
    def test_warehouse_change_without_history_ok(self):
        """No transaction history yet -> the warehouse may still be corrected."""
        partner = self._make_client('Fresh Client', self.wh_a)
        partner.write({'x_studio_warehouse': self.wh_b.id})
        self.assertEqual(partner.x_studio_warehouse, self.wh_b)

    def test_warehouse_change_with_history_rejected(self):
        """A done picking freezes the contact's warehouse."""
        partner = self._make_client('History Client', self.wh_a)
        self._make_done_picking(partner)
        with self.assertRaises(UserError):
            partner.write({'x_studio_warehouse': self.wh_b.id})

    def test_warehouse_change_with_bypass_context_ok(self):
        """The explicit migration bypass context skips the immutability guard."""
        partner = self._make_client('Bypass Client', self.wh_a)
        self._make_done_picking(partner)
        partner.with_context(bypass_warehouse_immutability=True).write(
            {'x_studio_warehouse': self.wh_b.id})
        self.assertEqual(partner.x_studio_warehouse, self.wh_b)

    def test_warehouse_change_as_settings_admin_ok(self):
        """Settings administrators may change the warehouse."""
        partner = self._make_client('Admin Client', self.wh_a)
        self._make_done_picking(partner)
        admin = self.env['res.users'].create({
            'name': 'MW Admin', 'login': 'mw_admin_guard',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_system').id,
                self.env.ref('base.group_partner_manager').id,
            ])],
        })
        partner.with_user(admin).write({'x_studio_warehouse': self.wh_b.id})
        self.assertEqual(partner.x_studio_warehouse, self.wh_b)

    # ── guard 3: no merges across warehouses ─────────────────────────────
    def test_merge_across_warehouses_rejected(self):
        """Merging contacts of two different warehouses raises."""
        p_a = self._make_client('ACME Meycauayan', self.wh_a)
        p_b = self._make_client('ACME Tagoloan', self.wh_b)
        wizard = self.env['base.partner.merge.automatic.wizard'].create({
            'partner_ids': [(6, 0, [p_a.id, p_b.id])],
            'dst_partner_id': p_a.id,
        })
        with self.assertRaises(UserError):
            wizard._merge([p_a.id, p_b.id], p_a)

    def test_merge_same_warehouse_allowed(self):
        """Merging two contacts of the SAME warehouse still works."""
        p_1 = self._make_client('Dup One', self.wh_a)
        p_2 = self._make_client('Dup Two', self.wh_a)
        wizard = self.env['base.partner.merge.automatic.wizard'].create({
            'partner_ids': [(6, 0, [p_1.id, p_2.id])],
            'dst_partner_id': p_1.id,
        })
        wizard._merge([p_1.id, p_2.id], p_1)
        self.assertFalse(p_2.exists())
