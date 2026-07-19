# -*- coding: utf-8 -*-
"""Keep a client's stock inside the building they are allowed to occupy.

A client's Preferred Locations (res.partner) say which part of the
warehouse may hold their goods — Annex only, Main only, and so on. Until
now the field was decorative: nothing read it. A Receiving Report simply
took the operation type's default destination (M/M) and the encoder was
free to steer it anywhere, so an Annex-only client's pallets could land
in Main with nothing objecting.

The placement chain on an RR runs:

    building (x_studio_building_1)          <- the encoder's control
        -> header destination               <- Studio SA #438 mirrors it
            -> line "Store To"              <- domain: child_of the header

so constraining the building constrains the whole chain. This module
does three things:

  * default    - the client's preference overrides the operation type's
                 default destination, so an Annex-only client's RR opens
                 on M/A instead of M/M
  * restrict   - the building field only offers the client's buildings
  * enforce    - a constraint refuses a header or a line that lands
                 outside the preference, whatever wrote it

Blast freeze is exempt throughout: its receipts go to the freezer
chambers (M/BF/...), which belong to no building.

Clients with no preference set are unaffected — the field is the opt-in.
"""
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BUILDING_MODEL = 'x_warehouse_building'
PREFERRED_FIELD = 'x_studio_preferred_locations'
BUILDING_FIELD = 'x_studio_building_1'
BF_FIELD = 'x_studio_is_a_blast_freezer'


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _vifel_buildings_by_preset(self):
        buildings = self.env[BUILDING_MODEL].search(
            [('x_studio_preset_location', '!=', False)])
        return {b.x_studio_preset_location.id: b for b in buildings}

    def _vifel_building(self, by_preset=None):
        """The building this location belongs to, by ancestry.

        Matched through parent_path rather than by name: the Studio
        automation guesses the building with a substring test on the
        complete name ('M/A' in ...), which happens to be right for every
        location that exists today but would quietly mislabel a location
        such as 'M/M/Aisle 1' — it contains 'M/A'.
        """
        self.ensure_one()
        if not self.id:
            return self.env[BUILDING_MODEL]
        if by_preset is None:
            by_preset = self._vifel_buildings_by_preset()
        ancestors = [int(x) for x in (self.parent_path or '').strip('/').split('/') if x]
        for loc_id in ancestors:
            if loc_id in by_preset:
                return by_preset[loc_id]
        return self.env[BUILDING_MODEL]

    def _vifel_inside(self, locations):
        """True when this location is one of `locations`, or below one.

        Preferring M/A allows M/A/1/Aisle 1.
        """
        self.ensure_one()
        if not locations:
            return True
        ancestors = {int(x) for x in (self.parent_path or '').strip('/').split('/') if x}
        return bool(set(locations.ids) & (ancestors | {self.id}))

    def _vifel_buildings(self):
        """Buildings covering this set of locations."""
        by_preset = self._vifel_buildings_by_preset()
        result = self.env[BUILDING_MODEL]
        for location in self:
            result |= location._vifel_building(by_preset=by_preset)
        return result


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    vifel_allowed_building_ids = fields.Many2many(
        BUILDING_MODEL, string='Allowed Buildings',
        compute='_compute_vifel_allowed_building_ids',
        help="Buildings this client may occupy, from their Preferred "
             "Locations. All buildings when the client has no preference.")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _vifel_preferred_locations(self):
        self.ensure_one()
        return self.partner_id[PREFERRED_FIELD] if self.partner_id \
            else self.env['stock.location']

    def _vifel_placement_restricted(self):
        """Receipts only, blast freeze excluded, client preference set."""
        self.ensure_one()
        if self.picking_type_id.code != 'incoming' or self[BF_FIELD]:
            return False
        return bool(self._vifel_preferred_locations())

    def _vifel_location_allowed(self, location):
        """A location is allowed when it sits inside a preferred one."""
        self.ensure_one()
        if not location:
            return True
        return location._vifel_inside(self._vifel_preferred_locations())

    def _vifel_default_placement(self):
        """(building, destination) this client's preference dictates.

        The operation type's default destination stands whenever it is
        already inside the preference — the point is only to override it
        when the client is not allowed there. A single preferred location
        is used as-is; several in one building fall back to that
        building's preset; several buildings pick the first
        deterministically, so creating a transfer can never dead-end on a
        destination the constraint would refuse.
        """
        self.ensure_one()
        prefs = self._vifel_preferred_locations()
        if not prefs:
            return self.env[BUILDING_MODEL], self.env['stock.location']
        if self._vifel_location_allowed(self.location_dest_id) and self.location_dest_id:
            return self.location_dest_id._vifel_building(), self.location_dest_id
        if len(prefs) == 1:
            return prefs._vifel_building(), prefs
        buildings = prefs._vifel_buildings()
        if len(buildings) == 1 and buildings.x_studio_preset_location:
            return buildings, buildings.x_studio_preset_location
        first = prefs.sorted('id')[0]
        return first._vifel_building(), first

    # ------------------------------------------------------------------
    @api.depends('partner_id', 'picking_type_id', BF_FIELD)
    def _compute_vifel_allowed_building_ids(self):
        every = self.env[BUILDING_MODEL].search([])
        for picking in self:
            if not picking._vifel_placement_restricted():
                # no preference (or blast freeze): nothing is narrowed
                picking.vifel_allowed_building_ids = every
                continue
            picking.vifel_allowed_building_ids = \
                picking._vifel_preferred_locations()._vifel_buildings()

    # ------------------------------------------------------------------
    # the picker only offers buildings this client may occupy
    # ------------------------------------------------------------------
    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """Narrow the Building picker on the combined arch, at runtime.

        Not done with an inherited view: the Building field belongs to
        Studio, and while a module is being upgraded Odoo combines only the
        views of modules already loaded — studio_customization loads after
        this one, so an xpath onto its field cannot be located at parse
        time. Patching the finished arch also survives Studio regenerating
        its customization view.
        """
        arch, view = super()._get_view(view_id, view_type, **options)
        for node in arch.xpath(".//field[@name='%s']" % BUILDING_FIELD):
            node.set('domain', "[('id', 'in', vifel_allowed_building_ids)]")
            if not arch.xpath(".//field[@name='vifel_allowed_building_ids']"):
                node.addnext(etree.Element('field', {
                    'name': 'vifel_allowed_building_ids', 'invisible': '1'}))
        return arch, view

    # ------------------------------------------------------------------
    # defaults: the preference outranks the operation type
    # ------------------------------------------------------------------
    @api.onchange('partner_id')
    def _vifel_onchange_partner_placement(self):
        for picking in self:
            if not picking._vifel_placement_restricted():
                continue
            building, dest = picking._vifel_default_placement()
            if dest:
                picking[BUILDING_FIELD] = building
                picking.location_dest_id = dest

    @api.model_create_multi
    def create(self, vals_list):
        # The placement has to be right *in the values*, not repaired
        # afterwards: constraints are validated at the end of create(), so a
        # record born on the operation type's M/M default would raise before
        # any post-create fix could run.
        vals_list = [self._vifel_apply_default_placement(vals) for vals in vals_list]
        return super().create(vals_list)

    def _vifel_apply_default_placement(self, vals):
        """Let the client's preference outrank the operation type default."""
        vals = self._add_missing_default_values(vals)
        picking = self.new(vals)
        if not picking._vifel_placement_restricted():
            return vals
        building, dest = picking._vifel_default_placement()
        if dest:
            # Written together: the Studio automations mirror building and
            # destination onto each other, and a half-applied placement
            # would trip the constraint on the next flush.
            vals = dict(vals, **{BUILDING_FIELD: building.id,
                                 'location_dest_id': dest.id})
        return vals

    # ------------------------------------------------------------------
    # enforcement
    # ------------------------------------------------------------------
    @api.constrains('partner_id', 'location_dest_id', 'picking_type_id',
                    BUILDING_FIELD, BF_FIELD)
    def _check_vifel_preferred_placement(self):
        for picking in self:
            if not picking._vifel_placement_restricted():
                continue
            prefs = picking._vifel_preferred_locations()
            allowed = picking.vifel_allowed_building_ids
            building = picking[BUILDING_FIELD]
            if building and building not in allowed:
                raise ValidationError(_(
                    "%(client)s may only be stored in %(allowed)s, so this "
                    "receipt cannot be placed in %(building)s.\n\n"
                    "Change the Building, or update the client's Preferred "
                    "Locations if they have taken space in another building."
                ) % {
                    'client': picking.partner_id.display_name,
                    'allowed': ', '.join(allowed.mapped('x_name')) or _('no building'),
                    'building': building.x_name,
                })
            if not picking._vifel_location_allowed(picking.location_dest_id):
                raise ValidationError(_(
                    "%(client)s may only be stored in %(prefs)s, so this "
                    "receipt cannot be delivered to %(dest)s."
                ) % {
                    'client': picking.partner_id.display_name,
                    'prefs': ', '.join(prefs.mapped('complete_name')),
                    'dest': picking.location_dest_id.complete_name,
                })


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _vifel_placement_client(self):
        """Whose goods this line is placing, and where they may go.

        Two ways stock reaches a shelf, and the client is named differently
        in each:

          * a receipt line, where the client is the picking's partner
          * a relocation, which moves quants through an inventory move with
            no picking at all (56k lines in this database) — there the
            client is the line's owner

        Returns an empty partner when the placement is not governed.
        """
        self.ensure_one()
        dest = self.location_dest_id
        empty = self.env['res.partner']
        if not dest or dest.usage != 'internal':
            return empty
        picking = self.picking_id
        if picking:
            return picking.partner_id if picking._vifel_placement_restricted() else empty
        # A destination outside the building structure — the blast freeze
        # chambers — is not something a building preference speaks about.
        if not dest._vifel_building():
            return empty
        return self.owner_id if self.owner_id[PREFERRED_FIELD] else empty

    @api.constrains('location_dest_id', 'picking_id', 'owner_id')
    def _check_vifel_preferred_placement(self):
        """The line is where the pallet physically lands.

        The receipt form already limits "Store To" to the header
        destination, but that is a client-side domain — this catches every
        other writer, including relocations, which never touch a picking.
        """
        for line in self:
            client = line._vifel_placement_client()
            if not client:
                continue
            prefs = client[PREFERRED_FIELD]
            if line.location_dest_id._vifel_inside(prefs):
                continue
            raise ValidationError(_(
                "%(client)s may only be stored in %(prefs)s. \"%(product)s\" "
                "is being placed in %(dest)s."
            ) % {
                'client': client.display_name,
                'prefs': ', '.join(prefs.mapped('complete_name')),
                'product': line.product_id.display_name,
                'dest': line.location_dest_id.complete_name,
            })
