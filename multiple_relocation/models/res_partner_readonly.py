# -*- coding: utf-8 -*-
"""Contacts are read-only for everyone except the Contact Editor group
(data.xml: Cyril's account, inventory1.bulacan) and administrators.
Documentation Staff can NOT edit (user 2026-11-10).

Users outside those two groups get the contact form, list and kanban without
New / Edit / Duplicate / Delete / Archive - in the Contacts app and when a
contact is opened from any document. Contact Editor members and Settings
administrators keep full editing.

Done per user in get_view / get_views, AFTER Odoo's view cache (that cache is
shared by all users, see ir.ui.view._get_view_cache_key). Screens only: Odoo
itself can still update a contact (a user's own preferences, a transfer
setting the partner...), so no other flow breaks.
"""
from lxml import etree

from odoo import api, models

_CONTACT_EDITORS = ('multiple_relocation.group_contact_editor', 'base.group_system')
_LOCK = {
    'form': ('create', 'edit', 'delete', 'duplicate'),
    'tree': ('create', 'edit', 'delete'),
    'list': ('create', 'edit', 'delete'),
    'kanban': ('create', 'edit', 'delete', 'quick_create'),
}


class ResPartnerReadonlyContacts(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _vifel_contacts_locked(self):
        if self.env.su:
            return False
        user = self.env.user
        return not any(user.has_group(xmlid) for xmlid in _CONTACT_EDITORS
                       if self.env.ref(xmlid, raise_if_not_found=False))

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        res = super().get_view(view_id, view_type, **options)
        attrs = _LOCK.get(view_type)
        if attrs and res.get('arch') and self._vifel_contacts_locked():
            root = etree.fromstring(res['arch'])
            for attr in attrs:
                root.set(attr, 'false')
            res['arch'] = etree.tostring(root, encoding='unicode')
        return res

    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options)
        if self._vifel_contacts_locked():
            # no Archive / Unarchive either (the web client offers them
            # whenever the 'active' field is writable)
            fields = (res.get('models') or {}).get(self._name)
            if isinstance(fields, dict):
                fields = fields.get('fields', fields)
                if isinstance(fields.get('active'), dict):
                    fields['active']['readonly'] = True
        return res
