# -*- coding: utf-8 -*-
"""0.4.4: WR lines read Pallet Series ID / Container # from THEIR OWN pallet.

stock.move.line.x_studio_pallet_series_id and x_studio_container_number are
Studio computed fields. On an outgoing line they looped over every quant of
the source location with the same product / owner / lot and kept the LAST
one, ignoring the pallet. A blank quant at the same spot (e.g. the negative
no-pallet quant left by M/WR/15384 on 11-05) therefore blanked both columns
on the next withdrawal of the real pallet (M/WR/15388: R 7795, NB 10463,
NB 10688).

New rule, same loop and same conditions otherwise:
1. the quant on the line's own pallet wins;
2. else the last quant with stock (> 0) and a value;
3. else unchanged behaviour (last match), so nothing that works today moves.
'package_id' is added to the dependencies so changing a line's pallet
re-reads the values.

Only the formulas change: stored values are not recomputed by this script,
lines refresh when their quantity / pallet / quant changes. Written without
comprehensions/closures (safe_eval on py3.10 rejects them). Running it again
writes the same text, which changes nothing.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PS_COMPUTE = """for record in self:
    if record['picking_code'] == 'outgoing':
        location = self.env['stock.location'].browse(record['location_id'].id)
        own = False
        stocked = False
        last = False
        for quants in location.quant_ids:
            if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                last = quants
                if record.package_id and quants.package_id.id == record.package_id.id:
                    own = quants
                elif quants.quantity > 0 and quants.x_studio_pallet_series_id:
                    stocked = quants
        if own and own.x_studio_pallet_series_id:
            record['x_studio_pallet_series_id'] = own.x_studio_pallet_series_id
        elif stocked:
            record['x_studio_pallet_series_id'] = stocked.x_studio_pallet_series_id
        elif last:
            record['x_studio_pallet_series_id'] = last.x_studio_pallet_series_id
    # else:
    #     record['x_studio_pallet_series_id'] = ''
"""

CN_COMPUTE = """for record in self:
    if record['picking_code'] == 'outgoing' or not record['picking_code']:
        location = self.env['stock.location'].browse(record['location_id'].id)
        own = False
        stocked = False
        last = False
        for quants in location.quant_ids:
            if record.product_id.id == quants.product_id.id and record.owner_id == quants.owner_id and record.lot_id.id == quants.lot_id.id:
                last = quants
                if record.package_id and quants.package_id.id == record.package_id.id:
                    own = quants
                elif quants.quantity > 0 and quants.x_studio_container_number:
                    stocked = quants
        if own and own.x_studio_container_number:
            record['x_studio_container_number'] = own.x_studio_container_number
        elif stocked:
            record['x_studio_container_number'] = stocked.x_studio_container_number
        elif last:
            record['x_studio_container_number'] = last.x_studio_container_number
    else:
        record['x_studio_container_number'] = ''
"""

NEW = {
    'x_studio_pallet_series_id': (PS_COMPUTE, 'quant_id,quantity,package_id'),
    'x_studio_container_number': (CN_COMPUTE, 'quant_id,package_id'),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Fields = env['ir.model.fields']
    for name, (compute, depends) in NEW.items():
        field = Fields.search([('model', '=', 'stock.move.line'), ('name', '=', name)], limit=1)
        if not field:
            _logger.warning("0.4.4: stock.move.line.%s not found, skipped", name)
            continue
        if not field.compute or field.state != 'manual':
            _logger.warning("0.4.4: stock.move.line.%s is not a Studio computed field, skipped", name)
            continue
        if field.compute == compute and field.depends == depends:
            continue
        _logger.info("0.4.4: stock.move.line.%s compute was:\n%s\ndepends was: %s",
                     name, field.compute, field.depends)
        field.write({'compute': compute, 'depends': depends})
        _logger.info("0.4.4: stock.move.line.%s now reads the line's own pallet first", name)
