# FIX PALLET DUPLICATES (rev 2 — PSI-first)
# Paste into Server Action #478 "Fix Pallet Duplicates" (model stock.quant).
# Original code backed up in sa478_fix_pallet_duplicates_BACKUP.txt.
#
# Run on selected stock.quant records after importing physical inventory.
# Rules:
#   1. Same PSI = same physical pallet -> ALL its quants must share ONE
#      package. An existing package is kept when no other PSI claims or
#      shares it; otherwise a vacant NP pallet is assigned.
#   2. A package may belong to only ONE PSI — extra claimants get their
#      own vacant NP pallet (never merge different PSIs onto one pallet).
#   3. Quants without a PSI: per (package, location) duplicate fix; the
#      first group keeps the original package, extras get vacant NPs.

Quant = env['stock.quant']
Package = env['stock.quant.package']
logs = []
sel_ids = [q.id for q in records]

np_packages = Package.search([('name', 'like', 'NP %')])

def np_key(p):
    tail = (p.name or '')[3:].strip()
    return (0, int(tail)) if tail.isdigit() else (1, 0)

np_list = sorted(np_packages, key=np_key)

used_ids = set()
for g in Quant.read_group(
        [('package_id', 'in', [p.id for p in np_list]),
         ('quantity', '>', 0),
         ('location_id.usage', '=', 'internal')],
        ['package_id'], ['package_id']):
    used_ids.add(g['package_id'][0])
for q in records:
    if q.package_id and (q.package_id.name or '').startswith('NP '):
        used_ids.add(q.package_id.id)

vacant = [p for p in np_list if p.id not in used_ids]

def take_np():
    return vacant.pop(0) if vacant else None

# ---- 1. unify by PSI -------------------------------------------------
by_psi = {}
no_psi = []
for q in records:
    if q.x_studio_pallet_series_id:
        by_psi.setdefault(q.x_studio_pallet_series_id, []).append(q)
    else:
        no_psi.append(q)

pkg_owner = {}   # package_id -> psi that owns it

for psi in sorted(by_psi):
    quants = by_psi[psi]
    target = None
    for q in quants:                      # prefer keeping a current package
        pkg = q.package_id
        if not pkg:
            continue
        if pkg_owner.get(pkg.id, psi) != psi:
            continue                      # claimed by another PSI already
        clash = Quant.search_count([
            ('package_id', '=', pkg.id),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('x_studio_pallet_series_id', '!=', psi),
            ('id', 'not in', sel_ids),
        ])
        if not clash:
            target = pkg
            break
    if target is None:
        target = take_np()
    if target is None:
        logs.append("X PSI %s: no vacant NP pallet left" % psi)
        continue
    pkg_owner[target.id] = psi
    moved = [q for q in quants
             if (q.package_id.id if q.package_id else 0) != target.id]
    if moved:
        old_names = sorted(set((q.package_id.name if q.package_id else '(none)')
                               for q in moved))
        for q in moved:
            q.write({'package_id': target.id})
        logs.append("OK PSI %s: %s -> '%s'" % (
            psi, ', '.join(old_names), target.name))

# ---- 2. no-PSI quants: per (package, location) duplicates ------------
groups = {}
for q in no_psi:
    if not q.package_id:
        continue
    groups.setdefault(q.package_id.id, {}).setdefault(
        q.location_id.id, []).append(q)

for pkg_id, loc_groups in groups.items():
    pkg = Package.browse(pkg_id)
    loc_ids = list(loc_groups)
    first = True
    for loc_id in loc_ids:
        quants = loc_groups[loc_id]
        dup_outside = Quant.search_count([
            ('package_id', '=', pkg_id),
            ('location_id', '!=', loc_id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
            ('id', 'not in', sel_ids),
        ])
        claimed = pkg_id in pkg_owner
        conflicted = claimed or dup_outside or len(loc_ids) > 1
        if conflicted and first and not claimed and not dup_outside:
            first = False
            continue                      # first group keeps the package
        first = False
        if not conflicted:
            continue
        np_pkg = take_np()
        if not np_pkg:
            logs.append("X '%s' at %s: no vacant NP pallet left" % (
                pkg.name, quants[0].location_id.display_name))
            continue
        pkg_owner[np_pkg.id] = '(no PSI)'
        for q in quants:
            q.write({'package_id': np_pkg.id})
        logs.append("OK '%s' at %s -> '%s'" % (
            pkg.name, quants[0].location_id.display_name, np_pkg.name))

if not logs:
    logs.append("OK No conflicts found. Nothing reassigned.")

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Fix Pallet Duplicates',
        'message': '\n'.join(logs),
        'type': 'warning' if any(l.startswith('X') for l in logs) else 'success',
        'sticky': True,
    },
}
