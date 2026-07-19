# Phase A: client profile, PSI types, prefix-aware routing, Lot No.
import traceback
from lxml import etree

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))

def rejects(label, fn):
    try:
        with env.cr.savepoint():
            fn()
            env.flush_all()   # force SQL constraints inside the savepoint
        check(label, False, 'no error raised')
    except (ValidationError, IntegrityError):
        check(label, True)
        env.invalidate_all()

try:
    P = env['res.partner']
    T = env['vifel.psi.type']
    client = P.search([('category_id.name', '=', 'Client'),
                       ('x_studio_client_unique_code_1', '!=', False)], limit=1)
    code = client.x_studio_client_unique_code_1.strip()
    print('guinea client: %s (code %s)' % (client.name, code))

    # ---- 1. defaults & cascade -----------------------------------------
    check('A1 all four switches default OFF',
          not (client.vifel_can_merge_pallets or client.vifel_multiple_pallet_support
               or client.vifel_include_regular_pallets or client.vifel_show_lot_no))

    # ---- 2. fixed pair constraint --------------------------------------
    rejects('A2 fixed PSI without fixed pallet is refused',
            lambda: client.write({'vifel_fixed_psi': 'WMF-00230'}))
    pkg = env['stock.quant.package'].search([], limit=1)
    client.write({'vifel_can_merge_pallets': True,
                  'vifel_fixed_package_id': pkg.id,
                  'vifel_fixed_psi': 'WMF-00230'})
    check('A3 both together are accepted',
          client.vifel_fixed_package_id == pkg and client.vifel_fixed_psi == 'WMF-00230')

    # ---- 3. seeding on Multiple flip -----------------------------------
    client.write({'vifel_multiple_pallet_support': True})
    prefixes = sorted(client.vifel_psi_type_ids.mapped('prefix'))
    check('A4 flipping Multiple ON seeds the 4 standard types',
          prefixes == ['BOC', 'MDGM', 'SDMG', 'TDMG'], prefixes)
    client.write({'vifel_multiple_pallet_support': False})
    client.write({'vifel_multiple_pallet_support': True})
    check('A5 re-flipping never duplicates (still 4)',
          len(client.vifel_psi_type_ids) == 4, len(client.vifel_psi_type_ids))
    check('A6 seeded name = prefix, next_number = 1',
          all(t.name == t.prefix and t.next_number == 1
              for t in client.vifel_psi_type_ids))

    # ---- 4. type constraints -------------------------------------------
    rejects('A7 duplicate prefix on one client is refused',
            lambda: T.create({'partner_id': client.id, 'name': 'X', 'prefix': 'mdgm'}))
    rejects('A8 a type shadowing the client code is refused',
            lambda: T.create({'partner_id': client.id, 'name': 'X', 'prefix': code}))

    # ---- 5. draw / take / give_back ------------------------------------
    sdmg = client.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    s1, s2 = sdmg.draw_number(), sdmg.draw_number()
    check('A9 counter draws SDMG-000001 then SDMG-000002',
          (s1, s2) == ('SDMG-000001', 'SDMG-000002'), (s1, s2))
    check('A10 give_back accepts a drawn number', sdmg.give_back(s1) is True)
    check('A11 ... and the pool re-issues it smallest-first',
          sdmg.draw_number() == 'SDMG-000001')
    check('A12 give_back refuses a number the counter never issued',
          sdmg.give_back('SDMG-000099') is False and not (sdmg.number_pool or []))
    sdmg.write({'next_number': 231})
    check('A13 editable counter continues a paper series',
          sdmg.draw_number() == 'SDMG-000231')

    # ---- 6. prefix-aware routing through the partner pool --------------
    normal_pool_before = list(client.unused_pallet_series_ids or [])
    client.push_unused_pallet('MDGM-000001')  # never issued -> refused by type
    mdgm = client.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'MDGM')
    check('A14 special series never lands in the NORMAL pool',
          list(client.unused_pallet_series_ids or []) == normal_pool_before)
    m1 = mdgm.draw_number()
    client.push_unused_pallet(m1)
    check('A15 issued special series routes to its own type pool',
          (mdgm.number_pool or []) == [1], mdgm.number_pool)
    got = client.get_pallet_series_by_id(m1)
    check('A16 get_pallet_series_by_id serves it back from the type pool',
          got == [m1] and not (mdgm.number_pool or []), got)
    check('A17 foreign prefix without a type is dropped, not pooled',
          [client.push_unused_pallet('ZZZZ-000005'),
           list(client.unused_pallet_series_ids or [])][1] == normal_pool_before)

    # normal series still round-trip through the normal pool
    client.push_unused_pallet('%s-000777' % code)
    check('A18 normal series still reach the normal pool',
          777 in (client.unused_pallet_series_ids or []))
    back = client.get_pallet_series_by_id('%s-000777' % code)
    check('A19 ... and come back out', back == ['%s-000777' % code], back)

    # ---- 7. stocked-guard ----------------------------------------------
    stocked = env['stock.quant'].search([
        ('x_studio_pallet_series_id', '!=', False),
        ('location_id.usage', '=', 'internal'),
        ('quantity', '>', 0)], limit=1)
    owner = stocked.owner_id
    psi = stocked.x_studio_pallet_series_id
    pool_before = list(owner.unused_pallet_series_ids or [])
    owner.push_unused_pallet(psi)
    check('A20 a stocked series is never recycled (%s of %s)' % (psi, owner.name),
          list(owner.unused_pallet_series_ids or []) == pool_before)

    # ---- 8. Lot No. plumbing -------------------------------------------
    check('A21 fields exist on line and quant',
          'client_lot_no' in env['stock.move.line']._fields
          and 'client_lot_no' in env['stock.quant']._fields)
    pick = env['stock.picking'].search([('partner_id', '=', client.id)], limit=1)
    client.write({'vifel_show_lot_no': True})
    env.invalidate_all()
    check('A22 picking compute follows the profile switch',
          pick.show_client_lot_no is True)
    ctx = pick.action_detailed_operations()['context']
    check('A23 Pallet Breakdown context carries show_client_lot_no',
          ctx.get('show_client_lot_no') is True, ctx.get('show_client_lot_no'))
    client.write({'vifel_show_lot_no': False})
    env.invalidate_all()
    check('A24 ... and hides again when switched off',
          pick.action_detailed_operations()['context'].get('show_client_lot_no') is False)

    # ---- 9. the views render -------------------------------------------
    arch = P.get_view(env.ref('base.view_partner_form').id, 'form')['arch']
    check('A25 VIFEL Configuration tab is in the partner form',
          'vifel_configuration' in arch and 'vifel_psi_type_ids' in arch)
    tarch = env['stock.move.line'].get_view(
        env.ref('stock.view_stock_move_line_detailed_operation_tree').id, 'tree')['arch']
    check('A26 Pallet Breakdown carries the gated Lot No. column',
          'client_lot_no' in tarch and 'show_client_lot_no' in tarch)
    qarch = env['stock.quant'].get_view(
        env.ref('multiple_relocation.view_stock_quant_tree_custom_2').id, 'tree')['arch']
    check('A27 quant tree offers the optional Lot No. column',
          'client_lot_no' in qarch)

except Exception:
    print('UNEXPECTED ERROR:'); traceback.print_exc(); FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
