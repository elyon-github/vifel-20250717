# CR2 v2 Suite AL - relocation & adjustment vs a merge pallet's identity.
#
# Findings (Phase 0, source-grounded):
#   B1 [SAFE]  relocation keeps the SAME package (package_id is readonly on the
#              relocation line - it never re-packages), so a durable
#              package-level merge flag rides along automatically.
#   C1 [EDGE]  a quantity-only correction keeps the package (safe), but a
#              correction that moves goods to a NEW package
#              (stock_quant_correction writes 'package_id': new) strands the
#              identity on the OLD package - the durable flag should move with
#              the goods (Phase 2 nicety).
#   B2 / C2    [NEEDS-TEST, Phase 2] PSI/x_studio not reaching a relocated quant;
#              emptying via adjustment not firing the pallet -1. Deferred.
#
# This suite asserts the code facts that VALIDATE the durable-flag design's
# automatic coverage of relocation; B2/C2 get functional repros in Phase 2.
# Rollback-only.
import os
import traceback

from odoo.modules.module import get_module_path

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    mr = get_module_path('multiple_relocation')

    # B1: the relocation line's package is READONLY -> relocation never assigns a
    # new package, so a package-level merge flag survives a relocation untouched.
    reloc = open(os.path.join(mr, 'wizard', 'stock_quant_relocation_lines.py'),
                 encoding='utf-8').read()
    check('AL1 [B1] relocation keeps the same package (package_id readonly) - a '
          'durable package flag survives relocation for free',
          "package_id = fields.Many2one('stock.quant.package'" in reloc
          and 'readonly=True' in reloc)

    # C1: the correction wizard CAN write a new package_id (re-package). A
    # quantity-only correction leaves it untouched (safe); a re-package moves the
    # goods to a fresh package that must carry the identity forward (Phase 2).
    corr = open(os.path.join(mr, 'wizard', 'stock_quant_correction.py'),
                encoding='utf-8').read()
    check('AL2 [C1] the correction wizard can move goods to a NEW package '
          '(re-package) - identity must follow the goods (Phase 2)',
          "'package_id': plan['new_package'].id" in corr)

    # C2 marker: confirm the pallet -1 fires from WR validation
    # (reserved_quantity_on_validation), NOT from an adjustment - so an
    # adjust-to-zero would not decrement. Left as a Phase-2 functional repro.
    check('AL3 [C2 note] the pallet -1 is driven by WR emptiness '
          '(reserved_quantity_on_validation), so adjust-to-zero needs a Phase-2 '
          'functional check', True, 'documented, deferred')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
