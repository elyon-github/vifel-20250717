# -*- coding: utf-8 -*-
"""19.0.0.4.11: times in 24-hour ("military") format again, as on 17.

On 17 VIFEL's language shows 02/05/2026 08:00:00 (%m/%d/%Y + %H:%M:%S).
The 17 -> 19 upgrade reset the language time to 12-hour (%I:%M:%S %p).
Put the 24-hour time back on every active language still on 12-hour; the
date part is left as it is. With static/src/js/date_numeric_default.js the
fields show 02/05/2026 08:00:00, and typing a time is read the same way.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    langs = env['res.lang'].with_context(active_test=True).search([])
    for lang in langs:
        if '%I' in (lang.time_format or '') or '%p' in (lang.time_format or ''):
            old = lang.time_format
            lang.time_format = '%H:%M:%S'
            _logger.info("19.0.0.4.11: %s time format %s -> %%H:%%M:%%S", lang.code, old)
