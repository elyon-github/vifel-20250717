# -*- coding: utf-8 -*-


from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError, UserError
from odoo.osv import expression
import logging
from datetime import datetime, timedelta, date
import re
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.osv.expression import AND, OR
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
from collections import defaultdict
_logger = logging.getLogger(__name__)
from ast import literal_eval

class ResPartner(models.Model):
    _inherit = 'res.partner'

    # JSON field to store pallet series IDs
    unused_pallet_series_ids = fields.Json("Unused Pallet Series IDs", default=[])

    @api.model
    def _vifel_series_is_stocked(self, pallet_series_id):
        """The series is still on stock physically on the floor.

        Such a series must never be recycled: re-issuing it would mint a
        duplicate of live stock. Internal locations only — quants at
        customer locations are history, not stock.
        """
        if not pallet_series_id:
            return False
        return bool(self.env['stock.quant'].search_count([
            ('x_studio_pallet_series_id', '=', pallet_series_id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]))

    def push_unused_pallet(self, pallet_series_id):
        # Extract the integer part after the hyphen
        try:
            series_number = int(pallet_series_id.split('-')[-1])
        except (ValueError, IndexError):
            # raise UserError("Invalid pallet series ID format. Expected format: 'JBL-<integer>'")
            return

        # Never recycle a series that is still on stocked quants (e.g. the
        # adopted PSI of a merge target).
        if self._vifel_series_is_stocked(pallet_series_id):
            return

        # Special PSI types own their prefix: their numbers go back to the
        # type's own pool. The normal pool below stores bare integers and
        # re-issues them under the CLIENT's code, so a special number in it
        # would come back out as a duplicate normal series.
        ptype = self.env['vifel.psi.type']._type_for_series(self, pallet_series_id)
        if ptype:
            ptype.give_back(pallet_series_id)
            return
        prefix = pallet_series_id.rpartition('-')[0]
        code = (self.x_studio_client_unique_code_1 or '').strip()
        if code and prefix and prefix != code:
            # foreign prefix without a type — drop rather than pollute
            return

        # Get the current list of IDs or initialize it as an empty list if None
        pallet_series_list = self.unused_pallet_series_ids or []

        # Add the new series number if it's not already in the list
        if series_number not in pallet_series_list:
            pallet_series_list.append(series_number)
        
        # Sort the list in ascending order
        pallet_series_list.sort()

        # Update the JSON field with the sorted list
        self.unused_pallet_series_ids = pallet_series_list


    def get_smallest_pallet_series_ids(self, count):
        # Get the current list of IDs or return an empty list if None
        pallet_series_list = self.unused_pallet_series_ids or []
    
        # Sort the list in ascending order to ensure correct order
        sorted_list = sorted(pallet_series_list)
    
        # Get the first 'count' elements, but not more than the available items in the list
        smallest_ids = sorted_list[:min(count, len(sorted_list))]
        if not self.x_studio_client_unique_code_1:
            raise UserError(f"\nIt seems like Client: {self.name} does NOT have a client unique code set. \n\nPlease set it first before we can generate Pallet Series ID.")
        # Prefix each ID with 'JBL-' and return the list
        formatted_ids = [f"{self.x_studio_client_unique_code_1}-{str(id).zfill(6)}" for id in smallest_ids]

        # Remove the used pallet IDs from the original list
        self.unused_pallet_series_ids = [id for id in pallet_series_list if id not in smallest_ids]

        return formatted_ids

    def generate_new_pallet_series_id(self):
        """Generate a brand new pallet series ID from the client's counter.
        Increments the counter on res.partner after generating.
        Returns the new series ID string (e.g. 'BGZ-000042').
        """
        if not self.x_studio_client_unique_code_1:
            raise UserError(f"\nIt seems like Client: {self.name} does NOT have a client unique code set. \n\nPlease set it first before we can generate Pallet Series ID.")
        
        current_counter = int(self.x_studio_pallet_series_id or 0)
        new_series = f"{self.x_studio_client_unique_code_1}-{str(current_counter).zfill(6)}"
        self.x_studio_pallet_series_id = current_counter + 1
        return new_series

    def get_pallet_series_by_id(self, pallet_series_id):
        """
        Search for a specific pallet series ID in unused pallets.
        If found, return and remove it from unused list.
        If not found, fall back to get_smallest_pallet_series_ids(1).
        
        Args:
            pallet_series_id (str): Full pallet ID like 'AHA-000001'
        
        Returns:
            list: Single-item list with the pallet series ID
        """
        # A special-type series is served by its own type: pool first,
        # then that type's counter — never the client's normal pool.
        ptype = self.env['vifel.psi.type']._type_for_series(self, pallet_series_id)
        if ptype:
            return [ptype.take_number(pallet_series_id)]

        # Extract the integer part after the hyphen
        try:
            series_number = int(pallet_series_id.split('-')[-1])
        except (ValueError, IndexError):
            # Invalid format, fall back to smallest
            return self.get_smallest_pallet_series_ids(1)
        
        # Get the current list of IDs
        pallet_series_list = self.unused_pallet_series_ids or []
        
        # Check if the series number exists in unused pallets
        if series_number in pallet_series_list:
            # Remove it from the unused list
            pallet_series_list.remove(series_number)
            self.unused_pallet_series_ids = pallet_series_list
            
            # Format and return the found ID
            if not self.x_studio_client_unique_code_1:
                raise UserError(f"\nIt seems like Client: {self.name} does NOT have a client unique code set. \n\nPlease set it first before we can generate Pallet Series ID.")
            
            formatted_id = f"{self.x_studio_client_unique_code_1}-{str(series_number).zfill(6)}"
            return [formatted_id]
        else:
            # Not found in unused pallets, get the smallest available
            return self.get_smallest_pallet_series_ids(1)
        
        

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Many2many field for product attributes
    attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string='Attribute Values',
        compute='_compute_attribute_value_ids',
        store=True,
    )

    # Link to client expiry table
    client_expiry_table_ids = fields.One2many(
        'client.expiry.table', 'product_template_id', string="Client Expiry Tables"
    )

    uom_id = fields.Many2one(
        'uom.uom', 'Unit of Measure',
        default=lambda self: self.env.ref('uom.product_uom_kgm').id,  
        required=True,
        help="Default unit of measure used for all stock operations."
    )
    @api.depends('attribute_line_ids')
    def _compute_attribute_value_ids(self):
        for template in self:
            template.attribute_value_ids = template.attribute_line_ids.mapped('value_ids')

    @api.onchange('attribute_value_ids')
    def _compute_brand_name_domain(self):
        # Get the IDs of attribute_value_ids
        attribute_ids = self.attribute_value_ids.ids if self.attribute_value_ids else []
        return {'domain': {'x_studio_brand_name': [('id', 'in', attribute_ids)]}}

    @api.onchange('name')
    def _onchange_name(self):
        if not self.name:
            return

        # Normalize name: Remove multiple spaces and convert to lowercase
        trimmed_name = " ".join(self.name.split()).strip().lower()

        # Search for products with similar names
        domain = [('name', 'ilike', self.name)]
        if self.id:
            domain.append(('id', '!=', self.id))  # Exclude the current record

        possible_duplicates = self.env['product.product'].search(domain)
        
        for product in possible_duplicates:
            existing_cleaned_name = " ".join(product.name.split()).strip().lower()
            
            if existing_cleaned_name == trimmed_name:
                raise UserError("The Product Name you input '%s' already exists." % self.name)
            

    @api.model
    def create(self, vals):
        # Convert name to uppercase before saving
        if 'name' in vals and vals['name']:
            vals['name'] = vals['name'].upper()
        return super(ProductTemplate, self).create(vals)

    def write(self, vals):
        # Convert name to uppercase before saving
        if 'name' in vals and vals['name']:
            vals['name'] = vals['name'].upper()
        return super(ProductTemplate, self).write(vals)


class ClientExpiryTable(models.Model):
    _name = 'client.expiry.table'

    # Link to Product Template
    product_template_id = fields.Many2one('product.template', string='Product Template')

    # Many2many field for product attribute values
    line_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string='Product Attributes',
        widget='many2many_tags',  # Tags widget for easy selection
        domain=[]  # Initial empty domain, will be dynamically set
    )

    # Client (partner) field - Many2many for selecting multiple partners
    partner_ids = fields.Many2many('res.partner', string='Client', domain="[('category_id.name', '=', 'Client'), ('is_company', '!=', True)]")

    # Expiry date range for the client and product
    expiry_date_range_id = fields.Many2one('x_inventory_static_var', string='Expiry Date Range', domain="[('x_studio_use_case', '=', 'Expiry Date Range')]")

    # New field to store the available attribute values (acting as a container)
    dynamic_attribute_value_ids = fields.Many2many(
        'product.attribute.value', 
        string='Product Attribute',
        compute='_compute_dynamic_attribute_value_ids',
        store=False
    )

    @api.depends('product_template_id')
    def _compute_dynamic_attribute_value_ids(self):
        for record in self:
            if record.product_template_id:
                # Store the attribute values for the selected product template
                record.dynamic_attribute_value_ids = record.product_template_id.attribute_value_ids






class ProductProduct(models.Model):
    _inherit = 'product.product'

    name = fields.Char(compute='_compute_name', store=True, readonly=False)

    
    @api.depends(
        'product_tmpl_id.name',
        'product_template_attribute_value_ids.name',
        'product_template_attribute_value_ids.attribute_id.name'
    )
    def _compute_name(self):
        for product in self:
            template_name = (product.product_tmpl_id.name or '').strip()
            
            variants = [
                f"{v.name}".strip()
                for v in product.product_template_attribute_value_ids
                if v.attribute_id and v.name
            ]
            
            if variants:
                raw_name = f"{template_name} ({', '.join(variants)})"
            else:
                raw_name = template_name
    
            # Normalize: remove extra spaces (double, leading, trailing)
            product.name = " ".join(raw_name.split())

    def _compute_display_name(self):
        super()._compute_display_name()
        for product in self:
            name = product.display_name
            if name.count("(") > 1:
                # Split by '(' and recombine all but the last (...) as the base
                parts = name.split(" (")
                # Join all parts except the last (...) back together
                base = " (".join(parts[:-1]).strip()
                last = "(" + parts[-1]  # restore last (...) part
                product.display_name = f"{base} {last}"

                

class StockLocation(models.Model):
    _inherit = 'stock.location'

    # Override the Studio field
    x_studio_occupied_by_1 = fields.Many2many(
        'res.partner',
        'stock_location_partner_link',   # <-- NEW relation table
        'location_id',
        'partner_id',
        string="Occupied By",
        store=True,
        compute="_compute_x_studio_occupied_by_1"
    )

    vifel_location_name = fields.Char(compute="_compute_vifel_location_name", store=True)

    @api.depends('complete_name')
    def _compute_vifel_location_name(self):
        for record in self:
            record.vifel_location_name = record.convert_location_string(record.complete_name)
            
    def convert_location_string(self, s):
        parts = s.split('/')
        try:
            if len(parts) < 3:
                return s
            
            # Build the name progressively based on available parts
            result = ""
            
            # Start from part 3 (index 2)
            if len(parts) > 2:
                result += parts[2]  # e.g., "Freezer" -> "F" or full name
            
            if len(parts) > 3:
                result += parts[3]  # e.g., "Aisle 1" -> "A1"
            
            if len(parts) > 4:
                result += parts[4]  # e.g., "Row A" -> "R"
            
            if len(parts) > 5:
                result += parts[5]  # e.g., "Rack 01" -> "01"
            
            # Add the dot separator before Level and Location if they exist
            if len(parts) > 6:
                result += "."
                digit = ''.join(filter(str.isdigit, parts[6]))
                if digit:
                    result += digit
            

            
            return result if result else s
        
        except Exception:
            return s
            
            
    def name_get(self):
        """
        Override name_get to display vifel_location_name when available
        """
        res = []
        for record in self:
            # Use vifel_location_name if it exists and is different from complete_name
            if record.vifel_location_name and record.vifel_location_name != record.complete_name:
                name = f"{record.vifel_location_name}"
            else:
                name = record.complete_name or record.name
            res.append((record.id, name))
        return res
    
    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """
        Override name search to include vifel_location_name field in Many2one dropdowns.
        """
        args = args or []
        
        if name:
            # Search in both complete_name (default) and vifel_location_name
            domain = ['|', 
                      ('complete_name', operator, name),
                      ('vifel_location_name', operator, name)]
            domain += args
            
            locations = self.search(domain, limit=limit)
            return locations.name_get()
        
        # If no name provided, use default behavior
        return super(StockLocation, self).name_search(name=name, args=args, operator=operator, limit=limit)

    
    @api.depends('quant_ids.quantity', 'quant_ids')
    def _compute_x_studio_occupied_by_1(self):
        for record in self:
            
            if not record.child_ids:
                unique_owners = set()
                unique_products = set()
                unique_pallets = set()
                total_qty = 0
                
                # clear the many2many first
                record['x_studio_occupied_by_1'] = [(5, 0, 0)]
                record['x_studio_products_1'] = [(5, 0, 0)]
                record['x_studio_pallets'] = [(5, 0, 0)]
                
                # collect values
                for quant in record.quant_ids:
                    if quant.quantity > 0:
                        total_qty += quant.quantity 
                        if quant.product_id:
                            unique_products.add(quant.product_id.id)
                        if quant.owner_id:
                            unique_owners.add(quant.owner_id.id)
                        if quant.package_id:
                            unique_pallets.add(quant.package_id.id)
                
                # assign many2many
                if unique_owners:
                    record['x_studio_occupied_by_1'] = [(6, 0, list(unique_owners))]
                if unique_products:
                    record['x_studio_products_1'] = [(6, 0, list(unique_products))]
                if unique_pallets:
                    record['x_studio_pallets'] = [(6, 0, list(unique_pallets))]
                
                # assign total qty
                record['x_studio_total_quantity'] = total_qty
            else:
                # reset
                record['x_studio_occupied_by_1'] = [(5, 0, 0)]
                record['x_studio_products_1'] = [(5, 0, 0)]
                record['x_studio_pallets'] = [(5, 0, 0)]
                record['x_studio_total_quantity'] = 0

    
    def remove_reservation(self):
        for record in self:
            record.x_studio_is_reserved = False
            record.x_studio_receiving_report_id = False



class StockQuantPackages(models.Model):
    _inherit = 'stock.quant.package'

    def remove_reservation(self):
        for record in self:
            record.x_studio_is_reserved = False
            record.x_studio_receiving_report_id = False