# CR2 Suite AT - void identity guard at validation time.
#
# Root cause (M/WR/08389, MEATS SUPREME, 2026-08-12): button_validate
# auto-voids ANY picking carrying is_void_wr, without checking that the
# document still reverses a voided parent. The EDIT guard disagrees:
# _void_mirror_source requires the flag AND a resolvable parent, so an
# orphaned shell is simultaneously freely editable and self-voiding.
# Operators repurposed such a shell (born from voiding GRJM's M/RR/05176)
# into a real MEATS SUPREME withdrawal; validation stamped it VOIDED and
# archived its PKR row, so 2 pallets / 1,310 kg never reached the ledger.
#
# The guard: auto-void only when the void identity is intact; when the
# pointer is lost but the CONTENT still mirrors a voided RR, repair the
# pointer and auto-void; when it mirrors nothing, the flag is stale, so
# clear it and let the document validate as what it now is.
#
#   python odoo-bin shell -c odoo.conf -d vifel_08_18_2026 --no-http \
#       --max-cron-threads=0 < ai_context/cr2_shell_tests/suite_at_void_identity_guard.py
#
# Rollback-only: nothing is committed.
import traceback
env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    P = env['stock.picking']
    # Fixtures are real documents from the incident, used read-only then
    # rolled back. GOOD is the correctly generated void WR (pointer set,
    # exact 41-pallet mirror). SHELL is the repurposed one.
    good = P.search([('name', '=', 'M/WR/08439')], limit=1)
    shell = P.search([('name', '=', 'M/WR/08389')], limit=1)
    parent_rr = P.search([('name', '=', 'M/RR/05176')], limit=1)

    check('AT0 fixtures present',
          bool(good) and bool(shell) and bool(parent_rr),
          'good=%s shell=%s rr=%s' % (good, shell, parent_rr))
    check('AT0b GOOD still carries an intact void identity',
          good.is_void_wr and good.void_source_picking_id == parent_rr
          and parent_rr.x_studio_voided,
          'good.ptr=%s rr.voided=%s' % (
              good.void_source_picking_id, parent_rr.x_studio_voided))

    # SHELL has since been repaired by sa_fix_stale_void_markers, so the
    # incident is re-armed here inside the transaction. The suite must keep
    # testing the guard long after the data it was found in got cleaned.
    shell.write({'is_void_wr': True, 'void_source_picking_id': False,
                 'x_studio_voided': True})

    # --- A. identity intact: pointer resolves to a voided parent ---------
    status, parent = good._void_identity_status()
    check('AT1 intact when the pointer resolves to a voided parent',
          status == 'intact' and parent == parent_rr,
          'status=%s parent=%s' % (status, parent))

    # --- B. recoverable: same real mirror, pointer lost ------------------
    # Simulates the pointer being cleared while the document still mirrors
    # the voided RR exactly. Content must be enough to recognise it.
    good.void_source_picking_id = False
    status, parent = good._void_identity_status()
    check('AT2 recoverable when content still mirrors the voided RR',
          status == 'recoverable' and parent == parent_rr,
          'status=%s parent=%s' % (status, parent))

    # --- C. stale: repurposed shell, mirrors nothing ---------------------
    # Different client (MEATS SUPREME vs GRJM) and different pallet series
    # (UK-018312/UK-018325 vs JM-0090xx) - it reverses nothing.
    status, parent = shell._void_identity_status()
    check('AT3 stale when the document no longer mirrors any voided RR',
          status == 'stale' and not parent,
          'status=%s parent=%s' % (status, parent))

    # --- D. validation behaviour on a stale document ---------------------
    # Reset the damage inside the transaction, then apply the guard as
    # button_validate would: the flag must be dropped and the document must
    # NOT be voided, so its ledger row survives.
    shell.x_studio_voided = False
    shell.is_void_wr = True
    shell._apply_void_identity_on_validation()
    check('AT4 a stale document is NOT auto-voided',
          not shell.x_studio_voided,
          'x_studio_voided=%s' % (shell.x_studio_voided,))
    check('AT5 its stale void flag is cleared so it cannot re-fire',
          not shell.is_void_wr,
          'is_void_wr=%s' % (shell.is_void_wr,))
    # Validation-time disarming IS announced on the document: an operator
    # who finds a transfer behaving unexpectedly needs to see why. The bulk
    # repair action stays silent instead - see sa_fix_stale_void_markers.py.
    check('AT6 the disarming is recorded in the chatter',
          bool(env['mail.message'].search_count([
              ('model', '=', 'stock.picking'), ('res_id', '=', shell.id),
              ('body', 'ilike', 'stale void')])))

    # --- E. validation behaviour on a recoverable document ---------------
    # good still has its pointer cleared from step B.
    good.x_studio_voided = False
    good._apply_void_identity_on_validation()
    check('AT7 a recoverable mirror IS auto-voided',
          good.x_studio_voided,
          'x_studio_voided=%s' % (good.x_studio_voided,))
    check('AT8 ... and its lost pointer is repaired',
          good.void_source_picking_id == parent_rr,
          'ptr=%s' % (good.void_source_picking_id,))

    # --- F. void returns bind through return_id, not the WR pointer ------
    vr = P.search([('is_void_return', '=', True),
                   ('return_id', '!=', False)], limit=1)
    if vr:
        status, parent = vr._void_identity_status()
        expected = 'intact' if vr.return_id.x_studio_voided else 'stale'
        check('AT9 void returns resolve through return_id',
              status == expected,
              'status=%s parent_voided=%s' % (status, vr.return_id.x_studio_voided))
    else:
        check('AT9 void returns resolve through return_id (no fixture)', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

print('')
print('PASSED %d / FAILED %d' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILING: ' + ', '.join(FAIL))
env.cr.rollback()
print('ROLLED BACK')
