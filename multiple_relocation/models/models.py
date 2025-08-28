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

    def push_unused_pallet(self, pallet_series_id):
        # Extract the integer part after the hyphen
        try:
            series_number = int(pallet_series_id.split('-')[-1])
        except (ValueError, IndexError):
            # raise UserError("Invalid pallet series ID format. Expected format: 'JBL-<integer>'")
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