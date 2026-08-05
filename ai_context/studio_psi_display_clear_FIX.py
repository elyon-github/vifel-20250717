# Studio field FIX — stock.move.line / x_studio_pallet_series_display
#
# WHERE: Odoo Studio → stock.move.line → field "x_studio_pallet_series_display"
#        (stored, readonly, computed). Replace the compute code with the
#        version below.
#
# WHY: the current compute is
#
#     for record in self:
#         if record.x_studio_pallet_series_id:
#             record['x_studio_pallet_series_display'] = record.x_studio_pallet_series_id
#
# It only assigns when the source HAS a value. A stored computed field keeps
# its previous stored value on any path the compute does not assign, so
# clearing x_studio_pallet_series_id leaves the display column still showing
# the old series. The line then reads as blank in one column and populated in
# the next.
#
# This is NOT specific to pallet merging — it strands a stale series on every
# path that clears a PSI: un-merging a line, the Clean Picking reset, wizard
# regrouping, manual clearing. Merging simply made it easy to notice, because
# un-merge is the quickest way to go from "has a series" to "has none".
#
# FIX: assign on BOTH branches. A compute must set the field on every path.

for record in self:
    record['x_studio_pallet_series_display'] = (
        record.x_studio_pallet_series_id or False)

# ---------------------------------------------------------------------------
# AFTER PASTING
#
# Existing rows keep whatever is stored until something recomputes them.
# To repair the ones that are already stale, run this once in the shell:
#
#     lines = env['stock.move.line'].search([
#         ('x_studio_pallet_series_id', '=', False),
#         ('x_studio_pallet_series_display', '!=', False)])
#     lines.write({'x_studio_pallet_series_display': False})
#     env.cr.commit()
#
# Count them first with search_count to see the blast radius before writing.
# ---------------------------------------------------------------------------
