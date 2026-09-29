# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VifelNotedByName(models.Model):
    """Names the documentation staff can pick as NOTED BY on a transfer.

    Team request 2026-09-28: the noting account types these names itself in
    the transfer's Configuration tab - they are not taken from contacts.
    Read for everyone, write for 'Deviation Report: Noted By' only
    (views/noted_by_views.xml).
    """
    _name = 'vifel.noted.by.name'
    _description = 'Noted By Name'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'This name is already in the Noted By list.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # Removing a name from the tab only archives it, so typing it again
        # brings the archived row back instead of tripping name_unique.
        slots = []
        to_create = []
        for vals in vals_list:
            archived = vals.get('name') and self.with_context(active_test=False).search(
                [('name', '=', vals['name']), ('active', '=', False)], limit=1)
            if archived:
                archived.write(dict(vals, active=True))
                slots.append(archived.id)
            else:
                slots.append(None)
                to_create.append(vals)
        created = iter(super().create(to_create).ids)
        return self.browse([rid or next(created) for rid in slots])
