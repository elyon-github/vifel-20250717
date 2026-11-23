# -*- coding: utf-8 -*-
"""19.0.0.4.42: the Checkout Stocks button runs the checkout once.

Server action "Checkout Stocks" (Location Related Stocks > Checkout) ran
    data = model.create_transfer_stock_move(env.context.get('picking_id'), records)
    if model.create_transfer_stock_move(env.context.get('picking_id'), records):
        action = data
so every Checkout built the WR lines twice. Now it runs once:
    action = model.create_transfer_stock_move(env.context.get('picking_id'), records)
(create_transfer_stock_move always returns an action or raises.)

Same release (code): a return cannot give back more than its WR took from a
pallet (stock.picking._vifel_return_over_withdrawn, M/RR/11372), and picking
a pallet again sets the WR demand to what is picked instead of adding to the
old demand (M/WR/16855).
Old code kept as an attachment; running it again changes nothing.
"""
import base64
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TAG = '19.0.0.4.42'
DOUBLE = re.compile(
    r"data\s*=\s*model\.create_transfer_stock_move\((?P<args>[^\n]*)\)[ \t]*\n"
    r"[ \t]*if\s+model\.create_transfer_stock_move\((?P=args)\)\s*:[ \t]*\n"
    r"[ \t]*action\s*=\s*data[ \t]*")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    actions = env['ir.actions.server'].with_context(active_test=False).search([
        ('state', '=', 'code'),
        ('code', 'ilike', 'create_transfer_stock_move'),
    ])
    for sa in actions:
        code = sa.code or ''
        new = DOUBLE.sub(
            lambda m: "action = model.create_transfer_stock_move(%s)"
            % m.group('args'), code)
        if new == code:
            continue
        env['ir.attachment'].create({
            'name': '%s backup SA %s code.py' % (TAG, sa.id),
            'res_model': 'ir.actions.server', 'res_id': sa.id,
            'datas': base64.b64encode(code.encode('utf-8')),
            'mimetype': 'text/plain',
        })
        sa.code = new
        _logger.info("%s: SA %s (%s) checkout now runs once",
                     TAG, sa.id, sa.name)
