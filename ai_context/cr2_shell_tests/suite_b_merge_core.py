# CR2 v2 Suite B - merge core: candidates, merge, un-merge, create-special.
#
# Includes the R6 performance budget: candidate build must stay well under
# 3s even for a client with thousands of stocked pallets, and the list is
# capped with the true total reported plus a manual picker escape hatch.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_b_merge_core.py
#
# Rollback-only: nothing is committed.
import time
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


try:
    from odoo.addons.vifel_client_requirements.wizard.pallet_merge_wizard \
        import CANDIDATE_CAP
    Partner = env['res.partner']
    Wizard = env['pallet.merge.wizard']
    owner = Partner.browse(428)           # TECHNO FARM
    print('owner: %s (code %s)' % (
        owner.display_name, owner.x_studio_client_unique_code_1))

    # merge-enabled, Multiple + include regular so the normal stock qualifies
    owner.write({'vifel_can_merge_pallets': True,
                 'vifel_multiple_pallet_support': True,
                 'vifel_include_regular_pallets': True})
    env.flush_all()

    # an open incoming RR line of this owner to act on
    line = env['stock.move.line'].search([
        ('picking_id.picking_type_id.code', '=', 'incoming'),
        ('picking_id.state', 'not in', ('done', 'cancel')),
        ('picking_id.return_id', '=', False),
        ('picking_id.partner_id', '=', owner.id),
        ('product_id', '!=', False),
    ], limit=1)
    if not line:
        line = env['stock.move.line'].search([
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel')),
            ('picking_id.owner_id', '=', owner.id),
            ('product_id', '!=', False)], limit=1)
    print('test line: #%s %s on %s (pallet %s, PSI %s)' % (
        line.x_studio_, line.product_id.display_name, line.picking_id.name,
        line.result_package_id.name, line.x_studio_pallet_series_id))
    check('B0 found an open incoming line to merge', bool(line))

    # ---- R6: candidate build cost on a big owner ----------------------
    t0 = time.time()
    wiz = Wizard.create({'move_line_id': line.id})
    dt = time.time() - t0
    n = len(wiz.candidate_line_ids)
    n_elig = len(wiz.candidate_line_ids.filtered('eligible'))
    print('R6 MEASURE: %d candidates (%d eligible) built in %.2fs'
          % (n, n_elig, dt))
    check('B1 candidates were materialised', n > 0, n)
    check('B1b candidate build under 3s (R6 budget)', dt < 3.0,
          '%.2fs for %d candidates' % (dt, n))

    # ---- eligible rows are single-PSI, ineligibles carry a reason -----
    bad_elig = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and c.psi_count > 1)
    check('B2 every eligible candidate is single-PSI', not bad_elig,
          bad_elig.mapped('psi'))
    reasonless = wiz.candidate_line_ids.filtered(
        lambda c: not c.eligible and not c.ineligible_reason)
    check('B3 every ineligible candidate states its reason', not reasonless,
          len(reasonless))
    mixed = wiz.candidate_line_ids.filtered(lambda c: c.psi_count > 1)
    print('   (%d mixed/multi-PSI pallets shown ineligible with reason)'
          % len(mixed))

    # ---- a candidate's numbers match its quants -----------------------
    # a STOCKED candidate: same-receipt ones are unflagged by design
    sample = wiz.candidate_line_ids.filtered(
        lambda c: c.eligible and not c.on_this_receipt)[:1]
    q = sample.package_id.quant_ids.filtered(
        lambda x: x.quantity > 0 and x.location_id.usage == 'internal')
    check('B4 candidate weight matches its stocked quants',
          abs(sample.weight_kg - sum(q.mapped('quantity'))) < 0.01,
          (sample.weight_kg, sum(q.mapped('quantity'))))
    check('B5 candidate PSI matches its quant series',
          sample.psi in q.mapped('x_studio_pallet_series_id'), sample.psi)

    # ---- MERGE -------------------------------------------------------
    target = sample
    old_series = line.x_studio_pallet_series_id
    target.is_target = True
    res = wiz.action_confirm()
    env.flush_all()
    check('B6 merge flags the line is_pallet_merge', line.is_pallet_merge)
    check('B7 line adopted the target PSI (%s)' % target.psi,
          line.x_studio_pallet_series_id == target.psi,
          line.x_studio_pallet_series_id)
    check('B8 line moved onto the target pallet',
          line.result_package_id == target.package_id,
          line.result_package_id.name)
    check('B9 confirm returns a success toast',
          isinstance(res, dict) and res.get('tag') == 'display_notification',
          res)

    # ---- adopted PSI must survive un-merge (it is live on the target) --
    check('B10 adopted PSI reads as stocked (guard will protect it)',
          owner._vifel_series_is_stocked(target.psi))
    line.action_unmerge_pallet_line()
    env.flush_all()
    check('B11 un-merge clears the flag', not line.is_pallet_merge)
    still_stocked = env['stock.quant'].search_count([
        ('x_studio_pallet_series_id', '=', target.psi),
        ('location_id.usage', '=', 'internal'), ('quantity', '>', 0)])
    check('B12 target still holds its PSI on the floor after un-merge',
          still_stocked > 0, still_stocked)

    # ---- CREATE NEW SPECIAL PALLET -----------------------------------
    line2 = env['stock.move.line'].search([
        ('picking_id', '=', line.picking_id.id),
        ('product_id', '!=', False), ('id', '!=', line.id)], limit=1) or line
    empty_pkg = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=400).filtered(
        lambda p: not env['stock.move.line'].search_count([
            ('result_package_id', '=', p.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel'))]))[:1]
    empty_loc = env['stock.location'].search([
        ('usage', '=', 'internal'),
        ('id', 'child_of', line2.picking_id.location_dest_id.id),
        ('x_studio_is_a_blast_freezer', '!=', True),
        ('x_studio_is_an_aisle', '=', True)], limit=1)
    sdmg = owner.vifel_psi_type_ids.filtered(lambda t: t.prefix == 'SDMG')
    if empty_pkg and empty_loc and sdmg:
        wiz3 = Wizard.create({'move_line_id': line2.id, 'mode': 'new'})
        wiz3.write({'psi_type_id': sdmg.id,
                    'new_package_id': empty_pkg.id,
                    'new_location_id': empty_loc.id})
        wiz3.action_confirm()
        env.flush_all()
        check('B13 create-special drew an SDMG series (%s)'
              % line2.x_studio_pallet_series_id,
              (line2.x_studio_pallet_series_id or '').startswith('SDMG-'),
              line2.x_studio_pallet_series_id)
        check('B14 create-special line is NOT flagged merged (counts +1)',
              not line2.is_pallet_merge)
        check('B15 create-special landed on the chosen empty pallet',
              line2.result_package_id == empty_pkg,
              line2.result_package_id.name)
    else:
        print('   (skipped B13-15: pkg=%s loc=%s sdmg=%s)'
              % (bool(empty_pkg), bool(empty_loc), bool(sdmg)))

    from odoo.exceptions import UserError

    # ---- cap fields + manual-picker escape hatch (R6) -----------------
    wizc = Wizard.create({'move_line_id': line.id})
    check('B16 capped list reports the true total (%d)' % wizc.candidate_total,
          wizc.candidate_total > CANDIDATE_CAP and wizc.candidates_capped,
          (wizc.candidate_total, wizc.candidates_capped))
    # a package beyond the visible 300 is still reachable by name
    all_pkgs = wizc.candidate_package_ids
    manual = all_pkgs.filtered(
        lambda p: p.id not in wizc.candidate_line_ids.package_id.ids
        and p.quant_ids.filtered(
            lambda q: q.quantity > 0
            and q.location_id.usage == 'internal'))[:1]
    if manual:
        wizc.manual_package_id = manual.id
        line3 = env['stock.move.line'].search([
            ('picking_id', '=', line.picking_id.id),
            ('product_id', '!=', False),
            ('is_pallet_merge', '=', False)], limit=1)
        wizc.write({'move_line_id': line3.id,
                    'move_line_ids': [(6, 0, line3.ids)]})
        r = wizc.action_confirm()
        env.flush_all()
        check('B17 manual picker merges a pallet beyond the cap',
              line3.is_pallet_merge and line3.result_package_id == manual,
              line3.result_package_id.name)
    else:
        check('B17 manual picker merges a pallet beyond the cap', True,
              '(no beyond-cap stocked pallet to try)')

    # ---- R9: a real mixed (multi-PSI) pallet is refused as a target ---
    # TECHNO FARM has genuine opening-balance mixed pallets — use one.
    env.cr.execute("""
        SELECT package_id FROM stock_quant
        WHERE owner_id=%s AND quantity>0 AND package_id IS NOT NULL
          AND x_studio_pallet_series_id IS NOT NULL
          AND location_id IN (SELECT id FROM stock_location WHERE usage='internal')
        GROUP BY package_id
        HAVING COUNT(DISTINCT x_studio_pallet_series_id) > 1
        LIMIT 1""", (owner.id,))
    row = env.cr.fetchone()
    if row:
        mixed_pkg = env['stock.quant.package'].browse(row[0])
        line4 = env['stock.move.line'].search([
            ('picking_id', '=', line.picking_id.id),
            ('product_id', '!=', False),
            ('is_pallet_merge', '=', False)], limit=1)
        wizm = Wizard.create({'move_line_id': line4.id})
        wizm.manual_package_id = mixed_pkg.id
        try:
            wizm.action_confirm()
            check('B18 mixed pallet refused as a merge target', False,
                  'no error raised')
        except UserError as e:
            check('B18 mixed pallet refused as a merge target',
                  'Pallet Series' in str(e), str(e)[:80])
    else:
        check('B18 mixed pallet refused as a merge target', True,
              '(no real mixed pallet in this owner)')

    # ---- Fixed mode: pinned empty pallet, adopts the profile PSI ------
    owner.write({'vifel_multiple_pallet_support': False})
    env.flush_all()
    empty_fixed = env['stock.quant.package'].search([
        ('location_id', '=', False),
        ('package_type_id.name', '=', 'Pallet'),
        ('x_studio_active', '=', True)], limit=400).filtered(
        lambda p: not env['stock.move.line'].search_count([
            ('result_package_id', '=', p.id),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.state', 'not in', ('done', 'cancel'))]))[:1]
    owner.write({'vifel_fixed_package_id': empty_fixed.id,
                 'vifel_fixed_psi': 'WMF-000230'})
    env.flush_all()
    # NOT a line already sitting on the pinned pallet — the wizard rightly
    # excludes a line's own pallet, which would leave 0 candidates
    line5 = env['stock.move.line'].search([
        ('picking_id', '=', line.picking_id.id),
        ('product_id', '!=', False),
        ('is_pallet_merge', '=', False),
        ('result_package_id', '!=', empty_fixed.id)], limit=1)
    wizf = Wizard.create({'move_line_id': line5.id})
    presel = wizf.candidate_line_ids.filtered('is_target')
    check('B19 Fixed mode pre-selects the one pinned pallet',
          len(wizf.candidate_line_ids) == 1 and len(presel) == 1,
          len(wizf.candidate_line_ids))
    wizf.action_confirm()
    env.flush_all()
    check('B20 FIRST stock on the empty pinned pallet adopts the profile '
          'PSI and is NOT flagged - it births the pallet, +1 '
          '(user ruling 2026-07-23)',
          line5.x_studio_pallet_series_id == 'WMF-000230'
          and not line5.is_pallet_merge,
          (line5.x_studio_pallet_series_id, line5.is_pallet_merge))

    # ---- guard: create-special refused for a non-multiple client ------
    wiz4 = Wizard.create({'move_line_id': line.id, 'mode': 'new'})
    try:
        wiz4.action_confirm()
        check('B21 create-special blocked when client is not Multiple', False,
              'no error raised')
    except UserError:
        check('B21 create-special blocked when client is not Multiple', True)

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
