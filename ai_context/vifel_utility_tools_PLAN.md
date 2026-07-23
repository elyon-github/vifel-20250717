# `vifel_utility_tools` — Design Spec

> **STATUS: APPROVED 2026-07-21 — implementing.**
> Author: Mark Angelo S. Templanza / Elyon · Odoo 17 Enterprise
> Verified against DB `vifel_07_21_2026` in rolled-back odoo-shell transactions.

## 1. Purpose

When importing `stock.quant` for Inventory Adjustments, product names that do not exist yet
block the import ("No matching records found in field Product"). This module auto-creates
the missing products from VIFEL's `NAME (BRAND)` convention.

## 2. The naming convention (existing, unchanged)

`product.product.name` is a stored compute in `multiple_relocation/models/models.py:237`:

```python
raw_name = f"{template_name} ({', '.join(variants)})"
```

so `CHICKEN WINGS (NAT)` = template `CHICKEN WINGS` + BRAND value `NAT`.
`product.template.create/write` force `name` to UPPERCASE (`models.py:172-183`).

Catalogue facts (`vifel_07_21_2026`): 1,930 templates / 2,886 variants / 620 BRAND values.
BRAND is `product.attribute` id 6, `create_variant='always'`. **870 templates have no
attribute line** — unbranded products are normal. Defaults: `detailed_type='product'`
(1,924), `tracking='lot'` (1,924), `uom=kg` (1,928), `categ='All'` (1,796).

## 3. Core rule: never modify an existing template

Odoo `product_template.py:745` reuses the existing variant when an attribute line has
exactly one value ("adding an attribute with only one value should not recreate product").
Measured consequences on a template that already has a variant:

| Action | Result |
|---|---|
| Add BRAND with one value | Variant reused — `CHICKEN` silently **renamed** to `CHICKEN (CDO)`. Unbranded product gone. |
| Add BRAND with two values in one write | Original variant **archived**; two new variants created. Stock/history stranded. |

**Therefore this module never adds attributes to an existing template.** Every unmatched
name produces a **brand-new template**:

```
CHICKEN         -> new template "CHICKEN", no attributes      -> variant "CHICKEN"
CHICKEN (CDO)   -> new template "CHICKEN", BRAND=[CDO]        -> variant "CHICKEN (CDO)"
```

Two templates may share a base name. That is accepted and intentional: they are different
products, and Odoo has no unique constraint on template name (the duplicate guard at
`models.py:150` is an `@api.onchange`, so it only fires for a human typing in the form).

Attaching a brand to a **newly created** template is safe — its auto-created variant is
empty and has no history to lose.

## 4. Hook

Override `product.product.name_create`, **gated on `self.env.context.get('import_file')`**.
Odoo's import screen offers *"When a value cannot be matched" → "Create new values"*
(`name_create_enabled_fields`, `base_import/static/src/import_data_options/import_data_options.js:51`),
which routes unmatched names to `name_create`. Outside an import the override defers to
`super()`, so normal many2one quick-create anywhere in the UI is unchanged.

## 5. Normalization and parsing

**Normalize** before any lookup or create: collapse internal whitespace, strip, uppercase.
Applied to the full name, the base name and the brand value.

**Parse** the last trailing `(...)` group — `^(.*)\(([^()]*)\)\s*$`:

| Input | Base | Brand |
|---|---|---|
| `Chicken Wings (Nat)` | `CHICKEN WINGS` | `NAT` |
| `chicken   wings  (nat)` | `CHICKEN WINGS` | `NAT` |
| `YELLOWFIN TUNA MEAT, PANGA` | `YELLOWFIN TUNA MEAT, PANGA` | *(none)* |
| `SALMON BELLY 1-3CM, 12KG (SJOR)` | `SALMON BELLY 1-3CM, 12KG` | `SJOR` |
| `CHICKEN (A, B)` | `CHICKEN` | `A, B` *(one value, not two)* |
| `CHICKEN ()` | `CHICKEN` | *(none)* |
| `(CDO)` | `(CDO)` | *(none — no base)* |

The whole parenthetical becomes **one** BRAND value. Splitting on `, ` would create N
variants instead of one, and a single value round-trips correctly through `_compute_name`
(which joins with `', '`).

No trailing parenthesis is not an error — it creates a brandless template, matching the 870
that already exist.

## 6. Resolution order

1. Exact match on an existing `product.product.name` (case-insensitive, normalized) → return
   it, create nothing.
2. Otherwise create a new `product.template` with the base name and catalogue defaults:
   `detailed_type='product'`, `tracking='lot'`, `uom_id=uom_po_id=kg`. `tracking='lot'` is
   mandatory — VIFEL identity depends on lots throughout.
3. If a brand was parsed: find-or-create the BRAND `product.attribute.value`, then create the
   attribute line on the new template.
4. Return the resulting variant.

**Auto-create policy (user decision):** create everything — unknown brands and templates
alike. Accepted consequence: non-brand parentheticals become BRAND values (`(10kg)` is a
packaging size, `(CLEAR TAPE)` a condition note), and `ROUND SCAD ... WITH 4 DMG BXS` vs
`... WITH 42 DMG BXS` become separate templates. Every creation is `_logger.info`-logged for
after-the-fact review.

## 7. Module layout

```
vifel_utility_tools/
├── __init__.py
├── __manifest__.py            # depends: base, product, stock, multiple_relocation
└── models/
    ├── __init__.py
    └── product_product.py     # name_create override + parse/normalize/create helpers
```

Depends on `multiple_relocation` for load order — that module owns the `_compute_name`
convention and the uppercase-forcing template create/write this code relies on.

## 8. Explicitly out of scope

- No `NO BRAND` placeholder value (dropped 2026-07-21).
- No change to how Odoo handles variants or `_create_variant_ids`.
- No change to `_compute_name`.
- No modification of any existing template, ever.
- No merge/dedup tooling for duplicate templates or junk brands — logging only.

## 9. Risks

| Risk | Mitigation |
|---|---|
| `name_create` is global — could create products outside import | Gated on `import_file`; test asserts standard behaviour when absent |
| Duplicate templates sharing a base name | Accepted by design (§3); they are distinct products |
| Junk brands from non-brand parentheticals | Accepted by decision; logged |
| BRAND attribute id assumed | Resolved by name at runtime; created if absent |
| Old-style `create(self, vals)` override in `multiple_relocation` | Templates are created one dict at a time, never batched |

## 10. Testing

odoo-shell, rolled back, on `vifel_07_21_2026`:

1. `Chicken Wings (Nat)` → new template `CHICKEN WINGS`, BRAND `NAT`, variant
   `CHICKEN WINGS (NAT)`, `tracking='lot'`.
2. Messy input `  chicken   wings  (nat) ` → same result (normalization).
3. No-paren name → brandless template, no attribute line.
4. Re-running the same name → returns the existing variant, creates nothing.
5. An existing brandless template is **never** modified when its branded form is imported.
6. `name_create` without `import_file` → standard Odoo behaviour.
7. Multi-value parenthetical `(A, B)` → one variant named `... (A, B)`.
