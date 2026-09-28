# -*- coding: utf-8 -*-
from odoo import fields, models


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
