# -*- coding: utf-8 -*-
"""0.4.5: every WR-line Studio formula reads the line's OWN pallet.

0.4.4 fixed Pallet Series ID (Studio) and Container # / Building (Python).
Ten more Studio computed fields on stock.move.line use the same loop:

    for quants in location.quant_ids:
        if <same product / owner / lot>:
            record[...] = quants.<value>          # last match wins

Prod. Date, Exp. Date, Return Count, Special Holding, SH Reason, Unit of
Measure, Unit of Measure (Withdrawal), max_quant (Original Weight),
max_2nd_uom (Original Quantity), max_total_units. On M/WR/15388 they read
the blank negative no-pallet quant left by M/WR/15384 (blank dates,
Original Weight -40 / -289 / -249 / -20.5).

Instead of rewriting ten formulas, the one loop line is replaced by the same
loop over the same quants in a different ORDER: other quants first, then
quants with stock, then the quant on the line's own pallet LAST, so "last
match wins" lands on the own pallet. Everything else in each formula is
untouched; 'package_id' is added to the dependencies.

Replayed read-only on consultant-test (prod copy 11-09), 865 reserved WR
lines: values change only on the 4 affected pallets (R 7795, NB 10463,
NB 10688, NB 531), all from blank/negative to the pallet's own value.

Only formulas whose text has exactly one such loop line and the standard
match condition are touched; a formula already converted (marker
'vq_own') is skipped, so running this twice changes nothing. No
comprehensions / lambdas (safe_eval on py3.10 rejects closures).
"""
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

LOOP_RE = re.compile(r'^( *)for quants in location\.quant_ids:[ \t]*$', re.M)
MATCH_IF = ('if record.product_id.id == quants.product_id.id and '
            'record.owner_id == quants.owner_id and '
            'record.lot_id.id == quants.lot_id.id:')
MARKER = 'vq_own'
SKIP = {'x_studio_pallet_series_id'}  # converted by 0.4.4 with its own rule

BLOCK = """{i}vq_other = []
{i}vq_stock = []
{i}vq_own = []
{i}for vq in location.quant_ids:
{i}    if record.package_id and vq.package_id == record.package_id:
{i}        vq_own.append(vq)
{i}    elif vq.quantity > 0:
{i}        vq_stock.append(vq)
{i}    else:
{i}        vq_other.append(vq)
{i}for quants in vq_other + vq_stock + vq_own:"""


def convert(compute):
    """Return the converted formula, or None when it should not be touched."""
    if not compute or MARKER in compute or MATCH_IF not in compute:
        return None
    found = LOOP_RE.findall(compute)
    if len(found) != 1:
        return None
    return LOOP_RE.sub(lambda m: BLOCK.format(i=m.group(1)), compute, count=1)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    fields_ = env['ir.model.fields'].search([
        ('model', '=', 'stock.move.line'),
        ('state', '=', 'manual'),
        ('compute', 'ilike', 'location.quant_ids'),
    ])
    for field in fields_:
        if field.name in SKIP:
            continue
        new = convert(field.compute)
        if new is None:
            _logger.info("0.4.5: stock.move.line.%s left as is (not the standard loop or already converted)",
                         field.name)
            continue
        depends = [d.strip() for d in (field.depends or '').split(',') if d.strip()]
        if 'package_id' not in depends:
            depends.append('package_id')
        _logger.info("0.4.5: stock.move.line.%s compute was:\n%s", field.name, field.compute)
        field.write({'compute': new, 'depends': ','.join(depends)})
        _logger.info("0.4.5: stock.move.line.%s now reads the line's own pallet first", field.name)
