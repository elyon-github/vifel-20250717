# CR2 v2 Suite F — uninstall safety (R1). Rollback-only, non-destructive.
#
# The architectural guarantee this feature is built around:
#
#   Uninstalling vifel_client_requirements removes the CONFIGURATION, the
#   ROUTING and the UI. It must never remove the LEDGER EVIDENCE.
#
# If is_pallet_merge lived in the optional module, uninstalling would drop
# the column and every historically merged line would silently recount as a
# received pallet on the next Re-sync — inflating pallet counts, and so
# invoices, for work done months earlier. These checks fail loudly if anyone
# ever "tidies" those fields into the optional module.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/cr2_shell_tests/suite_f_uninstall_safety.py
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
CORE = 'multiple_relocation'
OPT = 'vifel_client_requirements'


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def owners_of(model, field):
    """Modules that declare this field, per ir.model.fields.modules."""
    rec = env['ir.model.fields'].search(
        [('model', '=', model), ('name', '=', field)], limit=1)
    return set((rec.modules or '').split(', ')) if rec else set()


try:
    # ---- ledger evidence MUST survive uninstall ----------------------
    for model, field, label in [
            ('stock.move.line', 'is_pallet_merge', 'F1'),
            ('stock.move.line', 'client_lot_no', 'F2'),
            ('stock.quant', 'client_lot_no', 'F3')]:
        mods = owners_of(model, field)
        check('%s %s.%s is owned by CORE, survives uninstall'
              % (label, model, field),
              CORE in mods and OPT not in mods, mods)

    # ---- the optional module owns only configuration / routing / UI ---
    for model, field, label in [
            ('res.partner', 'vifel_can_merge_pallets', 'F4'),
            ('res.partner', 'vifel_multiple_pallet_support', 'F5'),
            ('res.partner', 'vifel_psi_type_ids', 'F6'),
            ('stock.move.line', 'vifel_show_merge_button', 'F7'),
            ('stock.picking', 'show_client_lot_no', 'F8')]:
        mods = owners_of(model, field)
        check('%s %s.%s is owned by the OPTIONAL module' % (label, model, field),
              OPT in mods, mods)

    # ---- models that must disappear with the module ------------------
    for model, label in [('vifel.psi.type', 'F9'),
                         ('pallet.merge.wizard', 'F10'),
                         ('pallet.merge.candidate', 'F11')]:
        rec = env['ir.model'].search([('model', '=', model)], limit=1)
        mods = set((rec.modules or '').split(', ')) if rec else set()
        check('%s model %s belongs to the optional module' % (label, model),
              OPT in mods, mods)

    # ---- PKR degrades gracefully when the flag is absent --------------
    # The counting code guards with `'is_pallet_merge' in MoveLine._fields`
    # and getattr, so a bare pallet_kilos_record_model install (no
    # multiple_relocation) never crashes. Prove the guard pattern is present.
    import os
    from odoo.modules.module import get_module_path

    pkr_src = os.path.join(get_module_path('pallet_kilos_record_model'),
                           'models', 'models.py')
    with open(pkr_src, encoding='utf-8') as fh:
        src = fh.read()
    check('F12 PKR guards the flag for a bare install',
          "'is_pallet_merge' in MoveLine._fields" in src
          and "getattr(move_line, 'is_pallet_merge'" in src)

    # ---- core never hard-couples to the optional module ---------------
    # A python import or an XML ref="vifel_client_requirements.xxx" would
    # make uninstalling the optional module break core at load time.
    # Mentions in COMMENTS are fine (and are deliberate documentation of the
    # split) — only real coupling counts.
    hard = ('from odoo.addons.%s' % OPT, 'import %s' % OPT,
            'ref="%s.' % OPT, "ref='%s." % OPT)
    bad = []
    for root, _dirs, files in os.walk(get_module_path(CORE)):
        for f in files:
            if f.endswith(('.py', '.xml')):
                with open(os.path.join(root, f), encoding='utf-8',
                          errors='ignore') as fh:
                    text = fh.read()
                if any(h in text for h in hard):
                    bad.append(f)
    check('F13 core never hard-couples to the optional module (imports/refs)',
          not bad, bad)

    # and the dependency points one way only
    core_mod = env['ir.module.module'].search([('name', '=', CORE)], limit=1)
    check('F14 core does not depend on the optional module',
          OPT not in core_mod.dependencies_id.mapped('name'),
          core_mod.dependencies_id.mapped('name'))

    # ---- blast radius today ------------------------------------------
    ML = env['stock.move.line']
    flagged = ML.search_count([('is_pallet_merge', '=', True)])
    lots = ML.search_count([('client_lot_no', '!=', False)])
    print('   evidence in this DB: %d merged lines, %d lines with a Lot No.'
          % (flagged, lots))
    check('F15 evidence fields are queryable (would survive uninstall)',
          isinstance(flagged, int) and isinstance(lots, int))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
