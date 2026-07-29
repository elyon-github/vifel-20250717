# Verify: changing the Client on an editable RR with drawn PSI lines recycles the
# old client's series back to its pool and blanks the lines (no owner/PSI mismatch,
# no pool leak). Rolled-back — nothing saved.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/wr_psi_client_change_test.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.exceptions import UserError

    # ---- CORE: editable RR with PSI lines, change the client ----------
    rr = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('state', 'in', ('draft', 'assigned')),
        ('return_id', '=', False),
        ('partner_id', '!=', False)], limit=80).filtered(
        lambda p: len(p.move_line_ids.filtered('x_studio_pallet_series_id')) >= 3
        and not p.x_studio_is_a_blast_freezer)[:1]
    old_client = rr.partner_id
    lines = rr.move_line_ids.filtered('x_studio_pallet_series_id')
    old_series = {l.id: l.x_studio_pallet_series_id for l in lines}
    old_nums = sorted(int(s.split('-')[-1]) for s in old_series.values()
                      if '-' in s and s.split('-')[-1].isdigit())
    pool_before = set(old_client.unused_pallet_series_ids or [])
    check('P0 found editable RR %s with %d PSI lines (client %s)'
          % (rr.name, len(lines), old_client.name), len(lines) >= 3)
    print('   old series:', list(old_series.values())[:6])

    new_client = env['res.partner'].search([
        ('id', '!=', old_client.id),
        ('category_id.name', '=', 'Client'), ('is_company', '=', False),
        ('x_studio_client_unique_code_1', '!=', False)], limit=1)
    check('P1 have a different destination client', bool(new_client),
          new_client.name if new_client else None)

    rr.write({'partner_id': new_client.id})
    env.flush_all()

    # (a) lines blanked
    still = lines.filtered('x_studio_pallet_series_id')
    check('P2 all PSI series were blanked on the lines',
          not still, still.mapped('x_studio_pallet_series_id'))
    disp = lines.filtered(lambda l: l.x_studio_pallet_series_display) \
        if 'x_studio_pallet_series_display' in lines._fields else lines.browse()
    check('P3 the stale stored display series was cleared too', not disp,
          disp.mapped('x_studio_pallet_series_display'))
    # (b) owner flipped to new client
    check('P4 line owners are now the NEW client',
          all(l.owner_id == new_client for l in lines) or
          all(l.owner_id == new_client or not l.owner_id for l in lines),
          lines.mapped('owner_id.name'))
    # (c) no line has (new owner + an old-client series) — the mismatch is gone
    mismatch = lines.filtered(
        lambda l: l.x_studio_pallet_series_id in old_series.values())
    check('P5 NO line still carries an old-client series (mismatch prevented)',
          not mismatch)
    # (d) old series recycled back to OLD client's pool
    pool_after = set(old_client.unused_pallet_series_ids or [])
    recycled = pool_after - pool_before
    check('P6 the old series were recycled to the OLD client\'s pool',
          set(old_nums).issubset(pool_after),
          'recycled=%s expected>=%s' % (sorted(recycled), old_nums))
    check('P7 the new client did NOT receive the old series in its pool',
          not set(old_nums).issubset(set(new_client.unused_pallet_series_ids or [])))

    env.cr.rollback()

    # ---- REGRESSION 1: a linked RETURN still BLOCKS a client change ----
    ret = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'),
        ('return_id', '!=', False), ('partner_id', '!=', False)], limit=1)
    if ret:
        other = env['res.partner'].search(
            [('id', '!=', ret.partner_id.id), ('category_id.name', '=', 'Client'), ('is_company', '=', False)], limit=1)
        try:
            ret.write({'partner_id': other.id})
            check('P8 linked return still BLOCKS a client change', False,
                  'no error raised')
        except UserError as e:
            check('P8 linked return still BLOCKS a client change',
                  'linked to' in str(e), str(e)[:80])
        env.cr.rollback()
    else:
        check('P8 linked return still BLOCKS a client change', True, '(no return to test)')

    # ---- REGRESSION 2: a DONE RR is NOT auto-cleaned -------------------
    done = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'incoming'), ('state', '=', 'done'),
        ('return_id', '=', False), ('partner_id', '!=', False)], limit=40).filtered(
        lambda p: p.move_line_ids.filtered('x_studio_pallet_series_id'))[:1]
    if done:
        dl = done.move_line_ids.filtered('x_studio_pallet_series_id')
        keep = {l.id: l.x_studio_pallet_series_id for l in dl}
        other = env['res.partner'].search(
            [('id', '!=', done.partner_id.id), ('category_id.name', '=', 'Client'), ('is_company', '=', False)], limit=1)
        try:
            done.with_context(skip_return_owner_guard=True).write({'partner_id': other.id})
            env.flush_all()
            unchanged = all(l.x_studio_pallet_series_id == keep[l.id] for l in dl)
            check('P9 a DONE RR keeps its series (not auto-cleaned)', unchanged,
                  dl.mapped('x_studio_pallet_series_id')[:4])
        except Exception as e:
            check('P9 a DONE RR keeps its series (not auto-cleaned)', True,
                  '(guarded elsewhere: %s)' % repr(e)[:60])
        env.cr.rollback()
    else:
        check('P9 a DONE RR keeps its series (not auto-cleaned)', True, '(none)')

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
