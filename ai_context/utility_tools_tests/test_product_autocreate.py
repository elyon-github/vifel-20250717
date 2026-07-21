import traceback
results = []
def check(label, cond, detail=''):
    results.append((bool(cond), label, detail))
    print("  %s %s %s" % ('PASS' if cond else 'FAIL', label, ('| ' + detail) if detail else ''), flush=True)

P = env['product.product'].with_context(import_file=True)
PLAIN = env['product.product']

env.cr.execute("SAVEPOINT t")
try:
    # ---- 1. basic brand parse + create ----
    _brand_dom = [('attribute_id', '=', 6), ('name', '=ilike', 'NAT')]
    _nat_before = env['product.attribute.value'].search_count(_brand_dom)
    pid, disp = P.name_create('Chicken Wings (Nat)')
    _nat_after = env['product.attribute.value'].search_count(_brand_dom)
    v = PLAIN.browse(pid)
    # NOTE: brand casing follows the EXISTING product.attribute.value if one matches
    # case-insensitively (e.g. existing 'Nat'), so we never create an uppercase duplicate.
    check("1 creates variant with brand", v.name.upper() == 'CHICKEN WINGS (NAT)', "name=%r" % v.name)
    check("1 template name is base", v.product_tmpl_id.name == 'CHICKEN WINGS', "tmpl=%r" % v.product_tmpl_id.name)
    check("1 tracking=lot", v.tracking == 'lot', "tracking=%r" % v.tracking)
    check("1 type=product", v.detailed_type == 'product', "type=%r" % v.detailed_type)
    check("1 uom=kg", v.uom_id.name.lower().startswith('kg'), "uom=%r" % v.uom_id.name)
    check("1 brand value attached (reuses existing casing)",
          'NAT' in [x.upper() for x in v.product_template_attribute_value_ids.mapped('name')],
          "vals=%s" % v.product_template_attribute_value_ids.mapped('name'))
    # The DB already contains case-duplicate BRAND values ('NAT' and 'Nat', MIDLAND x2,
    # ...) from before this module existed, so assert we ADD none rather than a total.
    check("1 no NEW brand value created", _nat_after == _nat_before,
          "before=%s after=%s" % (_nat_before, _nat_after))

    # ---- 2. messy input normalizes to the same product ----
    pid2, _ = P.name_create('   chicken   wings   (nat)  ')
    check("2 messy input reuses same variant", pid2 == pid, "got id=%s expected=%s" % (pid2, pid))

    # ---- 3. no parenthesis -> brandless template ----
    pid3, _ = P.name_create('Yellowfin Tuna Meat, Panga')
    v3 = PLAIN.browse(pid3)
    check("3 brandless name", v3.name == 'YELLOWFIN TUNA MEAT, PANGA', "name=%r" % v3.name)
    check("3 no attribute line", len(v3.product_tmpl_id.attribute_line_ids) == 0)

    # ---- 4. rerun returns existing, creates nothing ----
    before = env['product.template'].search_count([])
    pid4, _ = P.name_create('CHICKEN WINGS (NAT)')
    after = env['product.template'].search_count([])
    check("4 rerun reuses", pid4 == pid and before == after, "before=%s after=%s" % (before, after))

    # ---- 5. existing brandless template is NEVER modified ----
    base = env['product.template'].create({'name': 'ZZ TESTPROD', 'detailed_type': 'product', 'tracking': 'lot'})
    base_variant_id = base.product_variant_ids.id
    base_variant_name = base.product_variant_ids.name
    pid5, _ = P.name_create('ZZ TESTPROD (CDO)')
    v5 = PLAIN.browse(pid5)
    base.invalidate_recordset()
    check("5 original template untouched (no attr lines)", len(base.attribute_line_ids) == 0)
    check("5 original variant id alive & same name",
          base.product_variant_ids.id == base_variant_id and base.product_variant_ids.name == base_variant_name,
          "id=%s name=%r" % (base.product_variant_ids.id, base.product_variant_ids.name))
    check("5 new product is a DIFFERENT template",
          v5.product_tmpl_id.id != base.id, "new tmpl=%s old tmpl=%s" % (v5.product_tmpl_id.id, base.id))
    check("5 new product named with brand", v5.name == 'ZZ TESTPROD (CDO)', "name=%r" % v5.name)

    # ---- 6. outside import context -> defers to super() (pre-existing behaviour) ----
    # NOTE: standard name_create is already broken on this DB: core does
    # create({'name': ...}) but multiple_relocation makes product.product.name a
    # COMPUTED field, so product_template.name ends up NULL -> NotNullViolation.
    # The gate is proven by the fact that our code path is NOT taken here.
    env.cr.execute("SAVEPOINT s6")
    used_super = False
    try:
        PLAIN.name_create('ZZ PLAIN CREATE (BRANDX)')
    except Exception as exc:
        used_super = 'not-null' in str(exc).lower() or 'null value' in str(exc).lower()
        env.cr.execute("ROLLBACK TO SAVEPOINT s6")
    else:
        env.cr.execute("RELEASE SAVEPOINT s6")
    check("6 no-import-context defers to super (not our path)", used_super,
          "super() raised the pre-existing NotNull error, so the gate holds")

    # ---- 7. multi-value parenthetical stays ONE variant ----
    pid7, _ = P.name_create('ZZ MULTI (ALPHA, BETA)')
    v7 = PLAIN.browse(pid7)
    check("7 multi-value -> single variant", len(v7.product_tmpl_id.product_variant_ids) == 1,
          "variants=%s" % len(v7.product_tmpl_id.product_variant_ids))
    check("7 multi-value name round-trips", v7.name == 'ZZ MULTI (ALPHA, BETA)', "name=%r" % v7.name)

    # ---- 8. empty parens ----
    pid8, _ = P.name_create('ZZ EMPTY ()')
    v8 = PLAIN.browse(pid8)
    check("8 empty parens -> brandless", len(v8.product_tmpl_id.attribute_line_ids) == 0, "name=%r" % v8.name)

except Exception:
    print(traceback.format_exc(), flush=True)
    results.append((False, 'EXCEPTION', ''))
finally:
    env.cr.execute("ROLLBACK TO SAVEPOINT t")
    env.cr.rollback()

ok = sum(1 for r in results if r[0])
print("\n==== %d/%d passed ====" % (ok, len(results)), flush=True)
print("(rolled back; DB unchanged)", flush=True)
