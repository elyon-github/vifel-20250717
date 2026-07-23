# -*- coding: utf-8 -*-
"""Auto-create products from the VIFEL ``NAME (BRAND)`` convention during import.

VIFEL identifies a product as ``<base name> (<brand>)`` — the display name built by
``multiple_relocation``'s ``product.product._compute_name``: template name plus the
BRAND attribute value in parentheses.

Importing ``stock.quant`` for an Inventory Adjustment blocks whenever a name in the
client's file has no matching product. Setting the import option
*"When a value cannot be matched" -> "Create new values"* routes those names to
``name_create``, which this module implements for the convention.

Design rule that everything else follows from: **never modify an existing template.**
Odoo reuses a template's existing variant when an attribute line has exactly one value
(``product/models/product_template.py``: "adding an attribute with only one value should
not recreate product"). So adding BRAND=CDO to a template that already has stock would
silently rename ``CHICKEN`` into ``CHICKEN (CDO)`` and the unbranded product would be
gone. Creating a fresh template every time makes that impossible.

Full design + measurements: ``ai_context/vifel_utility_tools_PLAN.md``.
"""

import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

# Trailing "(...)" group at the end of a name. Non-nested by construction: the inner
# class excludes parentheses, so "A (B) (C)" yields base "A (B)" and brand "C".
_TRAILING_PAREN = re.compile(r'^(.*)\(([^()]*)\)\s*$', re.S)

_BRAND_ATTRIBUTE_NAME = 'BRAND'


def _norm(text):
    """Uppercase, collapse internal whitespace, strip. Used for every compare and write."""
    return " ".join((text or "").split()).strip().upper()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------
    @api.model
    def name_create(self, name):
        """Create a product from an imported ``NAME (BRAND)`` string.

        Only active during an import. Everywhere else (typing a new name into any
        many2one) standard Odoo behaviour is preserved.
        """
        if not self.env.context.get('import_file'):
            return super().name_create(name)

        product = self._vifel_find_or_create_by_name(name)
        if not product:
            return super().name_create(name)
        return product.id, product.display_name

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------
    @api.model
    def _vifel_find_or_create_by_name(self, raw_name):
        """Return the variant for ``raw_name``, creating template/brand if needed."""
        full_name = _norm(raw_name)
        if not full_name:
            return self.browse()

        # 1. already exists? (case-insensitive exact match on the computed name)
        existing = self.search([('name', '=ilike', full_name)], limit=1)
        if existing:
            return existing

        # 2. new template — never touch an existing one (see module docstring)
        base_name, brand_name = self._vifel_split_brand(full_name)
        template = self.env['product.template'].create(
            self._vifel_template_values(base_name))

        # 3. brand, if the name carried one
        if brand_name:
            self._vifel_attach_brand(template, brand_name)
            template.invalidate_recordset()

        variant = template.product_variant_ids[:1]
        _logger.info(
            "vifel_utility_tools: created product %r (template #%s, brand %r) "
            "from imported name %r",
            variant.display_name, template.id, brand_name or '-', raw_name)
        return variant

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    @api.model
    def _vifel_split_brand(self, full_name):
        """Split a normalized name into ``(base, brand)``.

        The whole parenthetical is ONE brand value: splitting "A, B" into two values
        would produce two variants instead of one, and a single value round-trips
        correctly through ``_compute_name`` (which joins values with ", ").
        """
        match = _TRAILING_PAREN.match(full_name)
        if not match:
            return full_name, ''

        base_name = _norm(match.group(1))
        brand_name = _norm(match.group(2))
        if not base_name:
            # e.g. "(CDO)" — nothing to hang a brand on, keep the name as-is
            return full_name, ''
        return base_name, brand_name

    # ------------------------------------------------------------------
    # creation helpers
    # ------------------------------------------------------------------
    @api.model
    def _vifel_template_values(self, base_name):
        """Defaults taken from the live catalogue (see PLAN §2).

        ``tracking='lot'`` is mandatory: VIFEL identity depends on lots throughout
        (BF pallets, void matching, snapshots).
        """
        values = {
            'name': base_name,
            'detailed_type': 'product',
            'tracking': 'lot',
        }
        uom_kg = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        if uom_kg:
            values['uom_id'] = uom_kg.id
            values['uom_po_id'] = uom_kg.id
        return values

    @api.model
    def _vifel_brand_attribute(self):
        """The BRAND attribute, resolved by name rather than a hardcoded id."""
        attribute = self.env['product.attribute'].search(
            [('name', '=ilike', _BRAND_ATTRIBUTE_NAME)], limit=1)
        if not attribute:
            attribute = self.env['product.attribute'].create({
                'name': _BRAND_ATTRIBUTE_NAME,
                'create_variant': 'always',
            })
            _logger.info("vifel_utility_tools: created missing BRAND attribute #%s",
                         attribute.id)
        return attribute

    @api.model
    def _vifel_attach_brand(self, template, brand_name):
        """Attach ``brand_name`` to a NEWLY CREATED template.

        Safe only because the template is new: its auto-created variant is empty, so
        Odoo's single-value reuse has no history to lose. Never call this on a
        template that already carries stock.
        """
        attribute = self._vifel_brand_attribute()
        value = self.env['product.attribute.value'].search([
            ('attribute_id', '=', attribute.id),
            ('name', '=ilike', brand_name),
        ], limit=1)
        if not value:
            value = self.env['product.attribute.value'].create({
                'attribute_id': attribute.id,
                'name': brand_name,
            })
            _logger.info("vifel_utility_tools: created BRAND value %r", brand_name)

        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id,
            'attribute_id': attribute.id,
            'value_ids': [(6, 0, [value.id])],
        })
        return value
