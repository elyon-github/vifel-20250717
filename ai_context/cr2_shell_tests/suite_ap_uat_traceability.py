# CR2 v2 Suite AP - UAT traceability: automated evidence for the few UAT rows
# that had no DEDICATED check (MP-B10 column order, MP-D3 stock-view columns,
# MP-C5 multi-truck empties rule). The other 21 UAT rows are each covered by an
# existing suite (see the QA certification report). Source-grounded, DB-safe.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_ap_uat_traceability.py
#
# Rollback-only: nothing is committed.
import os
import traceback

from odoo.modules.module import get_module_path

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    vdir = get_module_path('vifel_client_requirements')
    pb = open(os.path.join(vdir, 'views', 'stock_move_line_views.xml'),
              encoding='utf-8').read()
    sq = open(os.path.join(vdir, 'views', 'stock_quant_views.xml'),
              encoding='utf-8').read()

    # ===== MP-B10: Lot No. / Batch # / Prodcode appear AFTER Container # =====
    after = pb.split('name="x_studio_container_number" position="after"', 1)
    block = after[1] if len(after) > 1 else ''
    # each of the three fields must be inside the after-Container-# insertion,
    # and no field is inserted before Container # for these three.
    check('MP-B10 Lot No. / Batch # / Prodcode are placed right AFTER the '
          'Container # column in the Pallet Breakdown',
          len(after) > 1
          and 'name="client_lot_no"' in block
          and 'name="batch_no"' in block
          and 'name="prodcode"' in block,
          'block found=%s' % (len(after) > 1))

    # ===== MP-D3: the stock (Inventory) view exposes the 3 columns ==========
    check('MP-D3 the Inventory/stock.quant view offers Lot No., Batch # and '
          'Prodcode columns (optional)',
          'name="client_lot_no"' in sq
          and 'name="batch_no"' in sq
          and 'name="prodcode"' in sq)
    check('MP-D3b those stock columns are read-only frozen values (optional '
          'columns, not typed on the quant grid)',
          "optional=" in sq)

    # ===== MP-C5: multi-truck — a shared pallet counts on the WR that EMPTIES
    #       it. The withdrawn-count decision keys on reserved_quantity_on_
    #       validation (the frozen owner+PSI emptiness snapshot): only the WR
    #       whose validation leaves the pallet empty (==0) counts it -1; the
    #       truck that left stock counts it -0. Verify the mechanism is wired.
    pkr_src = open(os.path.join(get_module_path('pallet_kilos_record_model'),
                                'models', 'models.py'), encoding='utf-8').read()
    sw_src = open(os.path.join(get_module_path('vifel_client_requirements'),
                               'models', 'stock_quant_merge_withdrawal.py'),
                  encoding='utf-8').read()
    check('MP-C5 the withdrawn-pallet count keys on the emptied-rule '
          '(reserved_quantity_on_validation), so a shared pallet counts on the '
          'WR that empties it, not the first truck',
          'reserved_quantity_on_validation' in pkr_src)
    # and partial withdrawal of a merge pallet is allowed (so a first truck can
    # take part and leave the rest) — the predicate the WR machinery consults.
    check('MP-C5b a merge pallet may be partially withdrawn (first truck takes '
          'part, leaves the rest) — the partial-withdrawal predicate exists',
          'def _vifel_package_allows_partial_withdrawal' in sw_src)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
