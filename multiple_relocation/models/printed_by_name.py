# -*- coding: utf-8 -*-
"""Printed By: picked from a list instead of typed (19.0.0.4.38).

Same set-up as Noted By (noted_by_name.py): the names are kept in the
transfer's Configuration tab by the 'Deviation Report: Noted By' members
(Cyril's account), everyone else only picks one.

The reports, the print check, Verify Transfer and the print history all read
the text field x_studio_printed_by_name (19.0.0.4.28). That field stays and is
filled from the chosen name, so none of them change. On the form the text
field is hidden and the dropdown is shown in its place.
"""
from odoo import api, fields, models

PRINTED_BY_TEXT = 'x_studio_printed_by_name'


class VifelPrintedByName(models.Model):
    _name = 'vifel.printed.by.name'
    _description = 'Printed By Name'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'This name is already in the Printed By list.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Removing a name only archives it; adding it again brings it back.
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

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            # A corrected spelling follows onto the transfers that use it.
            Picking = self.env['stock.picking'].sudo()
            if PRINTED_BY_TEXT in Picking._fields:
                for rec in self:
                    pickings = Picking.search([('vifel_printed_by_name_id', '=', rec.id)])
                    if pickings:
                        pickings._vifel_write_printed_by_text(rec.name)
        return res


class StockPickingPrintedByName(models.Model):
    _inherit = 'stock.picking'

    vifel_printed_by_name_id = fields.Many2one(
        'vifel.printed.by.name', string='Printed By', copy=False, tracking=True,
        help='Who prints the RR / WR / BFRR / BFWR report. The choices are the '
             'names added in the Configuration tab.')
    vifel_printed_by_name_ids = fields.Many2many(
        'vifel.printed.by.name', string='Printed By Names',
        compute='_compute_vifel_printed_by_name_ids',
        inverse='_inverse_vifel_printed_by_name_ids',
        groups='multiple_relocation.group_deviation_noted_by')

    def vifel_printed_by_missing(self):
        """True when no Printed By is chosen. The dropdown is what the user
        sees, so it decides: a name typed in the old (now hidden) text field
        before 19.0.0.4.38 no longer counts. Used by Verify Transfer and the
        print buttons. Public so the Verify server action can call it."""
        self.ensure_one()
        return not self.vifel_printed_by_name_id

    def _vifel_write_printed_by_text(self, name):
        # Write the text only, without running the dropdown sync again.
        if PRINTED_BY_TEXT in self._fields:
            self.with_context(vifel_printed_by_sync=True).write(
                {PRINTED_BY_TEXT: name or False})

    def _vifel_printed_by_vals(self, vals):
        if 'vifel_printed_by_name_id' in vals and PRINTED_BY_TEXT in self._fields:
            name = self.env['vifel.printed.by.name'].browse(
                vals['vifel_printed_by_name_id']).name if vals['vifel_printed_by_name_id'] else False
            vals = dict(vals, **{PRINTED_BY_TEXT: name or False})
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        # Same guard as Noted By: a new transfer sends the Configuration list
        # as an empty command list, which must not archive every name.
        Name = self.env['vifel.printed.by.name']
        for vals in vals_list:
            for command in vals.pop('vifel_printed_by_name_ids', None) or []:
                if not isinstance(command, (list, tuple)) or len(command) < 3:
                    continue
                if command[0] == 0:
                    Name.create(command[2])
                elif command[0] == 1:
                    Name.browse(command[1]).write(command[2])
        vals_list = [self._vifel_printed_by_vals(vals) for vals in vals_list]
        records = super().create(vals_list)
        records.invalidate_recordset(['vifel_printed_by_name_ids'])
        return records

    def write(self, vals):
        if not self.env.context.get('vifel_printed_by_sync'):
            vals = self._vifel_printed_by_vals(vals)
        return super().write(vals)

    def _compute_vifel_printed_by_name_ids(self):
        names = self.env['vifel.printed.by.name'].search([])
        for record in self:
            record.vifel_printed_by_name_ids = names

    def _inverse_vifel_printed_by_name_ids(self):
        Name = self.env['vifel.printed.by.name']
        for record in self[:1]:
            kept = Name
            for line in record.vifel_printed_by_name_ids:
                if line.id:
                    line._origin.write({'name': line.name, 'sequence': line.sequence})
                    kept |= line._origin
                else:
                    kept |= Name.create({'name': line.name, 'sequence': line.sequence})
            # Removed from the tab = archived: gone from the dropdown, but
            # transfers already printed with it keep their Printed By.
            (Name.search([]) - kept).write({'active': False})
