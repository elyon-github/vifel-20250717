# -*- coding: utf-8 -*-

from . import controllers
from . import models
from . import wizard
from . import reports


def post_init_hook(env):
    # Backfill transacted_pallet_count on already-validated pickings so the
    # graph view isn't empty for historical data. Runs once at install/upgrade.
    done_pickings = env['stock.picking'].search([('state', '=', 'done')])
    if done_pickings:
        done_pickings._compute_transacted_pallet_count()
