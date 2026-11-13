# -*- coding: utf-8 -*-
"""Assign Pallet Series (server action 347) must skip spent numbers.

The RR form's "Assign Pallet Series" button runs DB server action 347. After
using the client's unused pool it minted new numbers straight from the client
counter (f"{code}-{counter:06}", counter += 1) without skipping numbers still
on stock or already used. SAVORY MARINATED's counter was at 0 while its
opening-balance pallets used SV-00006..00022, so on 2026-11-11 the button first
collided with stocked SV-00017.. (the "still in use" error), and after the team
withdrew those pallets (M/WR/12281) it re-issued SV-000000..000020.

The counter path now calls res.partner.generate_new_pallet_series_id(), which
skips every number in use or already used and advances the counter itself.
Only the exact original lines are replaced; anything else is left untouched.
"""
import logging

_logger = logging.getLogger(__name__)

OLD_MINT = 'new_pallet_series = f"{partner_code}-{str(pallet_series_id).zfill(6)}"'
NEW_MINT = 'new_pallet_series = partner.generate_new_pallet_series_id()'
OLD_INC = '            pallet_series_id += 1\n'
OLD_SAVE = "partner.write({'x_studio_pallet_series_id': str(pallet_series_id)})"
NEW_SAVE = ("# counter is advanced by generate_new_pallet_series_id (migration "
            "0.4.10)")


def migrate(cr, version):
    cr.execute("SELECT id, code FROM ir_act_server WHERE state = 'code' "
               "AND code LIKE %s", ('%' + OLD_MINT + '%',))
    for sa_id, code in cr.fetchall():
        new = code.replace('\r\n', '\n')
        if new.count(OLD_MINT) != 1 or new.count(OLD_SAVE) != 1:
            _logger.warning("Server action %s: unexpected code, not patched",
                            sa_id)
            continue
        new = new.replace(OLD_MINT, NEW_MINT).replace(OLD_INC, '')
        new = new.replace(OLD_SAVE, NEW_SAVE)
        cr.execute("UPDATE ir_act_server SET code = %s WHERE id = %s",
                   (new, sa_id))
        _logger.info("Server action %s: Assign Pallet Series now skips used "
                     "numbers", sa_id)
