# Pallet series numbers currently in use on MORE THAN ONE pallet at the same
# time (COMP-2026-00043, "one-to-one assignment of pallet numbers").
#
# WHY: a series number is meant to identify one physical pallet. It returns to
# the client's recycle pool only when the pallet is withdrawn and empty. When
# the same number is live on two pallets at once, the floor cannot tell them
# apart and the pallet tag, the RR/WR and the ledger all disagree.
#
# READ-ONLY. This script writes nothing and commits nothing - it only reports,
# so the team can decide what to do per pallet.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/report_duplicate_pallet_series.py
#
# Set CSV_PATH to also drop a spreadsheet-friendly copy.
CSV_PATH = r'C:\Users\lenovo\Downloads\duplicate_pallet_series.csv'

Quant = env['stock.quant']
MoveLine = env['stock.move.line']

# Live stock only: a quant with nothing on it no longer holds the number.
quants = Quant.search([
    ('x_studio_pallet_series_id', '!=', False),
    ('package_id', '!=', False),
    ('quantity', '>', 0),
])
print('Scanning %d live quants that carry a pallet series...' % len(quants))

def _norm(series):
    """Key a series by prefix + NUMBER, ignoring zero padding.

    Padding is not consistent in the data - GB-20809 and GB-020809 are the same
    physical number. Matching on the raw string finds 78 duplicates; matching on
    the number finds 100.
    """
    s = (series or '').strip()
    if not s or '-' not in s:
        return s
    prefix, _sep, tail = s.rpartition('-')
    tail = tail.strip()
    return '%s-%d' % (prefix, int(tail)) if tail.isdigit() else s


# (owner, normalised series) -> {package: [quants]}   owner-scoped: two clients
# may each hold their own number, that is not a collision.
by_key = {}
for q in quants:
    key = (q.owner_id.id, _norm(q.x_studio_pallet_series_id))
    if not key[1]:
        continue
    by_key.setdefault(key, {}).setdefault(q.package_id, []).append(q)

dups = {k: v for k, v in by_key.items() if len(v) > 1}
print('Pallet series live on more than one pallet: %d\n' % len(dups))

rows = []
for (owner_id, series), pkgs in sorted(
        dups.items(), key=lambda kv: (env['res.partner'].browse(kv[0][0]).name or '', kv[0][1])):
    owner = env['res.partner'].browse(owner_id)
    print('%s   %s   (%d pallets)' % ((owner.name or '?')[:34].ljust(34), series, len(pkgs)))
    for pkg, qs in pkgs.items():
        qty = sum(q.quantity for q in qs)
        loc = qs[0].location_id.complete_name or ''
        indate = qs[0].in_date and qs[0].in_date.date() or ''
        # the documents that put this series on this pallet
        docs = MoveLine.search([
            ('x_studio_pallet_series_id', 'in',
             MoveLine._vifel_series_spellings(series)),
            '|', ('result_package_id', '=', pkg.id), ('package_id', '=', pkg.id),
        ]).mapped('picking_id.name')
        docs = sorted(set(d for d in docs if d))
        spelling = (qs[0].x_studio_pallet_series_id or '').strip()
        print('      %-14s %-12s %-24s %10.3f kg   since %s   %s'
              % (pkg.name or '?', spelling, loc[:24], qty, indate,
                 ', '.join(docs[:3]) or '(no document)'))
        rows.append([owner.name or '', series, spelling, pkg.name or '', loc,
                     '%.3f' % qty, str(indate), ' '.join(docs)])
    print()

# per-client tally
tally = {}
for (owner_id, _s) in dups:
    nm = env['res.partner'].browse(owner_id).name or '?'
    tally[nm] = tally.get(nm, 0) + 1
print('--- summary ---')
for nm, n in sorted(tally.items(), key=lambda kv: -kv[1]):
    print('  %-34s %d duplicated series' % (nm[:34], n))
print('  %-34s %d series, %d pallets'
      % ('TOTAL', len(dups), sum(len(v) for v in dups.values())))

if CSV_PATH:
    import csv, io
    with io.open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['Client', 'Pallet Number', 'As Written', 'Pallet',
                    'Location', 'Kilos', 'In Date', 'Documents'])
        w.writerows(rows)
    print('\nCSV written to %s' % CSV_PATH)
print('\nREAD-ONLY - nothing was written to the database.')
