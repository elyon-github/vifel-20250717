# CR2 v2 Suite R - existing header buttons are never clobbered.
#
# REGRESSION GUARD (2026-07-24). The multi-select "Merge Selected" button
# was first added by creating a NEW <header> in an inherited list view. But
# the Pallet Breakdown tree ALREADY has a header (Verify Transfer, Assign
# Pallet Series, Assign Locations, Auto-Fill, Spawn Magic Wizard, Delete,
# from multiple_relocation). A list renders only ONE header, so the second
# one silently dropped every existing button.
#
# Rule: to add a button to a list that already has a header, APPEND to the
# existing <header> (xpath //tree/header position=inside) - never create a
# second one. This suite asserts there is exactly one header and every
# pre-existing workflow button survives alongside ours.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_r_header_not_clobbered.py
#
# Rollback-only: nothing is committed.
import traceback, re
env = env(user=env.ref('base.user_admin').id)
P,F=[],[]
def check(n,c,d=''):
    (P if c else F).append(n); print(('PASS ' if c else 'FAIL ')+n+('' if c else '  -> %s'%(d,)))
try:
    tree = env.ref('stock.view_stock_move_line_detailed_operation_tree')
    arch = env['stock.move.line'].get_view(tree.id,'tree')['arch']
    n_headers = arch.count('<header')
    check('H1 the Pallet Breakdown tree has exactly ONE header (not two)',
          n_headers == 1, '%d header elements' % n_headers)
    # every existing workflow button must still be present
    for label,tok in [('Verify Transfer','call_server_action_verify_pallet_series'),
                      ('Assign Pallet Series','name="347"'),
                      ('Assign Locations','name="300"'),
                      ('Auto-Fill Details','name="341"'),
                      ('Spawn Magic Wizard','action_open_fast_encode_wizard'),
                      ('Delete','name="unlink"')]:
        check('H2 existing button still present: %s'%label, tok in arch, tok)
    check('H3 our Merge Selected button was added to that same header',
          'action_open_pallet_merge_wizard_multi' in arch)
    # they must all be inside the SAME header block
    hdr = arch[arch.index('<header'):arch.index('</header>')]
    check('H4 all buttons live in the one header',
          'call_server_action_verify_pallet_series' in hdr
          and 'action_open_pallet_merge_wizard_multi' in hdr
          and 'action_open_fast_encode_wizard' in hdr)
    # Magic Wizard list: its (new) header is the only one
    fe = env.ref('multiple_relocation.view_fast_encode_rr_line_list')
    fearch = env['stock.move.line.fast_encode_rr.line'].get_view(fe.id,'list')['arch']
    check('H5 Magic Wizard list has exactly one header',
          fearch.count('<header') == 1, fearch.count('<header'))
    check('H6 Merge Selected present in the Magic Wizard header',
          'action_merge_selected_from_fast_encode' in fearch)
except Exception:
    traceback.print_exc(); F.append('exc')
env.cr.rollback()
print('RESULT: %d passed, %d failed'%(len(P),len(F)))
if F: print('FAILED:',F)
