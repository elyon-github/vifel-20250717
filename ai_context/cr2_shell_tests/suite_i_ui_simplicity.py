# CR2 v2 Suite I - wizard simplicity, held to core Odoo conventions.
#
# Checked against Odoo core: ZERO of the 35 stock/mrp/sale wizard views use
# an "alert alert-info" banner, and Return Picking puts its guidance in a
# plain <div class="oe_grey"> shown only when it applies. This suite keeps
# the merge dialog to that standard so it cannot drift back into a wall of
# banners and label/value grids.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_i_ui_simplicity.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    W = env['pallet.merge.wizard']
    arch = W.get_view(
        env.ref('vifel_client_requirements.view_pallet_merge_wizard_form').id,
        'form')['arch']

    check('S1 no coloured alert boxes left (core Odoo convention)',
          'alert alert-' not in arch,
          [l.strip() for l in arch.split('\n') if 'alert alert-' in l][:2])
    check('S2 guidance uses oe_grey like core Return Picking',
          'oe_grey' in arch)
    check('S3 the 4-field header group is gone (it wrapped the KG value)',
          'Line being merged' not in arch)
    # The single joined summary string that replaced it was itself replaced
    # (UAT round 7) by a labelled strip - see suite P for its checks.
    check('S4 replaced by a labelled header strip, not a field grid',
          'line_number' in arch and 'd-flex flex-wrap' in arch)
    check('S5 the candidate table is still the focus',
          'candidate_line_ids' in arch)
    # The reason column was REMOVED entirely (user, UAT round 6): an
    # unavailable row is already greyed and unselectable, and the reason is
    # delivered by the onchange warning when someone tries to pick it. The
    # field must still be LOADED, or that warning has nothing to say.
    check('S6 the reason column is gone from the table',
          'Unavailable because' not in arch)
    check('S6b ... but still loaded so the onchange can explain the refusal',
          'name="ineligible_reason" column_invisible="1"' in arch)

    # S7-S9 (the joined-summary checks) retired with the field itself; the
    # header strip is covered by suite_p_partial_withdrawal_and_header.

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
