# -*- coding: utf-8 -*-
"""Inventory Analysts cannot start a transfer (RR / WR / BFRR / BFWR).

User 2026-11-10: IA accounts must not create transactions; only the
Inventory Super Admin accounts can (Cyril's account; admin, IT / Tech Team
and the Warehouse Manager are in that group too). Other users - e.g.
Documentation Staff, who encode the RRs/WRs - are not affected.

For an IA user who is not an Inventory Super Admin / administrator:
* transfer form, list and kanban: no New, no Duplicate;
* Inventory Overview cards: the "New" link in the card menu is removed.

Done per user in get_view, after Odoo's view cache (shared by all users).
Screens only: transfers the system creates while an IA works (returns,
void transfers, next operations) still work.
"""
from lxml import etree

from odoo import api, models

_IA_GROUP = '__custom__.inventory_analyst'
_MAY_CREATE = ('multiple_relocation.inventory_super_admin', 'base.group_system')
_LOCK = {
    'form': ('create', 'duplicate'),
    'tree': ('create',),
    'list': ('create',),
    'kanban': ('create', 'quick_create'),
}


def _vifel_transfer_create_locked(env):
    if env.su:
        return False
    user = env.user
    if not env.ref(_IA_GROUP, raise_if_not_found=False) or not user.has_group(_IA_GROUP):
        return False
    return not any(user.has_group(x) for x in _MAY_CREATE
                   if env.ref(x, raise_if_not_found=False))


class StockPickingCreateLock(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        res = super().get_view(view_id, view_type, **options)
        attrs = _LOCK.get(view_type)
        if attrs and res.get('arch') and _vifel_transfer_create_locked(self.env):
            root = etree.fromstring(res['arch'])
            for attr in attrs:
                root.set(attr, 'false')
            res['arch'] = etree.tostring(root, encoding='unicode')
        return res


class StockPickingTypeCreateLock(models.Model):
    _inherit = 'stock.picking.type'

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        res = super().get_view(view_id, view_type, **options)
        if view_type == 'kanban' and res.get('arch') and _vifel_transfer_create_locked(self.env):
            action = self.env.ref('stock.action_picking_form', raise_if_not_found=False)
            if action:
                root = etree.fromstring(res['arch'])
                for link in root.xpath("//a[@type='action'][@name='%s' or @name='%%(stock.action_picking_form)d']" % action.id):
                    link.getparent().remove(link)
                res['arch'] = etree.tostring(root, encoding='unicode')
        return res
