# CR2 v2 Suite F - the feature is plug-and-play.
#
# REPLACES the old suite_f_uninstall_safety.py, which asserted the OPPOSITE
# architecture. Until 2026-07-23 the feature's fields lived in
# multiple_relocation so that uninstalling could not drop them and inflate
# pallet counts. The user has since ruled the module is installed once and
# NEVER uninstalled, so that risk cannot occur - and keeping the feature's own
# fields in someone else's module bought nothing but merge-conflict surface.
#
# The architecture is now: everything the feature owns lives in
# vifel_client_requirements. Core keeps only five GENERIC extension hooks,
# because the behaviour they gate sits inside methods of ~300 and ~990 lines
# that an add-on cannot re-implement without duplicating them and drifting.
#
# What this suite guards:
#   * core source contains ZERO references to the feature's data model;
#   * core neither imports nor XML-refs the module, nor depends on it;
#   * the five hooks exist in core and are neutral no-ops there;
#   * the optional module overrides every one of them.
#
# If that "never uninstall" ruling is ever reversed, move the fields back to
# core FIRST - dropping is_pallet_merge silently inflates pallet counts, and a
# wrong pallet count is a wrong invoice.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \\
#       < ai_context/cr2_shell_tests/suite_f_plug_and_play.py
#
# Rollback-only: nothing is committed.
import os
import traceback

env = env(user=env.ref('base.user_admin').id)
PASS, FAIL = [], []
OPT = 'vifel_client_requirements'
CORE_MODULES = ('multiple_relocation', 'pallet_kilos_record_model')


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> %s' % (detail,)))


def owners_of(model, field):
    rec = env['ir.model.fields'].search(
        [('model', '=', model), ('name', '=', field)], limit=1)
    return set((rec.modules or '').split(', ')) if rec else set()


def core_sources():
    """Every .py/.xml file of the core modules (never bytecode)."""
    from odoo.modules.module import get_module_path
    for mod in CORE_MODULES:
        for root, dirs, files in os.walk(get_module_path(mod)):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.endswith(('.py', '.xml')):
                    p = os.path.join(root, f)
                    with open(p, encoding='utf-8', errors='ignore') as fh:
                        yield mod, f, fh.read()


try:
    # ---- 1. the feature owns its own fields ---------------------------
    for model, field, label in [
            ('stock.move.line', 'is_pallet_merge', 'F1'),
            ('stock.move.line', 'client_lot_no', 'F2'),
            ('stock.quant', 'client_lot_no', 'F3'),
            ('stock.move.line', 'vifel_premerge_captured', 'F4'),
            ('res.partner', 'vifel_can_merge_pallets', 'F5'),
            ('res.partner', 'vifel_psi_type_ids', 'F6'),
            ('stock.move.line', 'vifel_show_merge_button', 'F7'),
            ('stock.picking', 'show_client_lot_no', 'F8'),
            ('stock.move.line.fast_encode_rr.line', 'is_pallet_merge', 'F9')]:
        mods = owners_of(model, field)
        check('%s %s.%s is owned by the feature module' % (label, model, field),
              OPT in mods and not (mods & set(CORE_MODULES)), mods)

    # ---- 2. models that belong to the feature -------------------------
    for model, label in [('vifel.psi.type', 'F10'),
                         ('pallet.merge.wizard', 'F11'),
                         ('pallet.merge.candidate', 'F12')]:
        rec = env['ir.model'].search([('model', '=', model)], limit=1)
        mods = set((rec.modules or '').split(', ')) if rec else set()
        check('%s model %s belongs to the feature module' % (label, model),
              OPT in mods, mods)

    # ---- 3. core knows NOTHING about the feature's data model ---------
    # The real plug-and-play test. Comments naming the module are fine (they
    # document who overrides the hooks); references to its FIELDS are not.
    for token, label in [('is_pallet_merge', 'F13'),
                         ('client_lot_no', 'F14'),
                         ('vifel_premerge', 'F15'),
                         ('pallet.merge.wizard', 'F16')]:
        hits = ['%s/%s' % (m, f) for m, f, text in core_sources()
                if token in text]
        check('%s core source never mentions %s' % (label, token),
              not hits, hits[:4])

    # ---- 4. no hard coupling, and the dependency points one way -------
    hard = ('from odoo.addons.%s' % OPT, 'import %s' % OPT,
            'ref="%s.' % OPT, "ref='%s." % OPT)
    bad = ['%s/%s' % (m, f) for m, f, text in core_sources()
           if any(h in text for h in hard)]
    check('F17 core never imports or XML-refs the feature module', not bad, bad)

    for mod, label in [('multiple_relocation', 'F18'),
                       ('pallet_kilos_record_model', 'F19')]:
        rec = env['ir.module.module'].search([('name', '=', mod)], limit=1)
        deps = rec.dependencies_id.mapped('name')
        check('%s %s does not depend on the feature module' % (label, mod),
              OPT not in deps, deps)

    # ---- 5. the five hooks exist in core and are neutral there --------
    HOOKS = {
        'stock.move.line.fast_encode_rr': [
            ('_vifel_line_is_merge_locked', False),
            ('_vifel_apply_merge_locked_line', False),
            ('_vifel_line_write_vals', {}),
        ],
        'pallet_kilos_record_model.pallet_kilos_record_model': [
            ('_vifel_line_originates_pallet', True),
            ('_vifel_merge_free_domain', []),
        ],
    }
    n = 20
    for model, hooks in HOOKS.items():
        for hook, neutral in hooks:
            cls = None
            for klass in type(env[model]).__mro__:
                if hook in klass.__dict__:
                    cls = klass
                    break
            in_core = cls is not None and any(
                m in cls.__module__ for m in CORE_MODULES)
            # the OUTERMOST definition must be the feature's override
            outer = type(env[model]).__mro__[0]
            overridden = any(
                OPT in k.__module__
                for k in type(env[model]).__mro__ if hook in k.__dict__)
            check('F%d %s.%s is overridden by the feature module'
                  % (n, model.split('.')[-1], hook), overridden,
                  cls.__module__ if cls else 'not found')
            n += 1

    # core's own implementation must still be the neutral default
    from odoo.modules.module import get_module_path
    fe = open(os.path.join(get_module_path('multiple_relocation'),
                           'wizard', 'FastEncodeRR.py'),
              encoding='utf-8').read()
    pkr = open(os.path.join(get_module_path('pallet_kilos_record_model'),
                            'models', 'models.py'), encoding='utf-8').read()
    check('F%d core hooks are neutral no-ops' % n,
          'def _vifel_line_is_merge_locked' in fe and 'return False' in fe
          and 'def _vifel_merge_free_domain' in pkr and 'return []' in pkr)
    n += 1

    # ---- 6. blast radius today ---------------------------------------
    ML = env['stock.move.line']
    print('   evidence in this DB: %d merged lines, %d with a Lot No.'
          % (ML.search_count([('is_pallet_merge', '=', True)]),
             ML.search_count([('client_lot_no', '!=', False)])))

except Exception:
    print('UNEXPECTED ERROR:')
    traceback.print_exc()
    FAIL.append('unexpected exception')

env.cr.rollback()
print('ROLLED BACK')
print('RESULT: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED:', FAIL)
