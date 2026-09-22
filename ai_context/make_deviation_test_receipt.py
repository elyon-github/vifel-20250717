# Build a RECEIVING report that raises the Deviation Report, with Remarks
# already typed on every pallet, so COMP-2026-00050 can be tested end to end
# on a database other than the local restore.
#
# WHY a script: the Deviation Report button only appears when the document
# carries a discrepancy, and a discrepancy only fires on a SHORTAGE beyond the
# warehouse threshold. A receipt encoded the normal way (demand left at 0)
# never raises one, so a test document has to be built deliberately.
#
#   python odoo-bin shell -c odoo.conf -d <db> --no-http --max-cron-threads=0 \
#       < ai_context/make_deviation_test_receipt.py
#
# DRY_RUN reports what it WOULD build, and what it found to build it with,
# without writing anything. Set it to False to actually create the receipt.
DRY_RUN = True

# How short to make it. Must exceed the warehouse's "Weight (KG) Variance
# Acceptable Threshold" (5 kg on the databases seen so far) or nothing flags.
SHORT_BY_KG = 20.0
PALLET_COUNT = 4
KG_PER_PALLET = 120.0

REMARKS = [
    'Carton torn on arrival',
    'Wet outer box',
    'Carton torn on arrival',        # deliberately repeated: must print ONCE
    'Short delivery vs documented',
]


def bail(msg):
    print('ABORT: %s' % msg)
    raise SystemExit


print('database: %s' % env.cr.dbname)

# --- precondition: is the code actually live on this database? -------------
# A view/field change only takes effect once the module has been UPGRADED
# here; the file being present in the branch is not enough.
field = env['ir.model.fields'].search([
    ('model', '=', 'stock.move'),
    ('name', '=', 'vifel_deviation_remarks')], limit=1)
if not field:
    bail('stock.move.vifel_deviation_remarks does not exist on this database.\n'
         '       Upgrade the module first: Apps -> clear the "Apps" filter ->\n'
         '       "VIFEL Warehouse Operations" -> Upgrade.')

tree = env.ref('multiple_relocation.view_stock_move_line_detailed_operation_tree_inherit',
               raise_if_not_found=False)
if tree and "state == 'cancel'" not in (tree.arch_base or ''):
    bail('the Pallet Breakdown view on this database is the OLD one (Remarks\n'
         '       still locked). Upgrade multiple_relocation, then re-run.')

report_view = env['ir.ui.view'].search([
    ('key', '=', 'studio_customization.studio_report_docume_'
                 'fce63407-724b-402b-bbd7-34c49f6c89e2_document')], limit=1)
if report_view and 'vifel_deviation_remarks' not in (report_view.arch_base or ''):
    print('WARNING: the Deviation Report template here has NOT been patched, so')
    print('         the Concern/Remarks column will still print blank. Run')
    print('         ai_context/patch_deviation_report_remarks.py as well.')

# --- find the fixtures on THIS database ------------------------------------
picking_type = env['stock.picking.type'].search([
    ('code', '=', 'incoming'), ('name', 'ilike', 'receiving')],
    order='id', limit=1)
if not picking_type:
    bail('no incoming picking type named like "RECEIVING" found.')

donor = env['stock.picking'].search([
    ('picking_type_id', '=', picking_type.id),
    ('state', '=', 'done'),
    ('partner_id', '!=', False),
    ('move_ids', '!=', False)], order='id desc', limit=1)
if not donor:
    bail('no completed receipt found to copy the shape from.')
donor_move = donor.move_ids[0]

pallet_type = env['stock.package.type'].search([('name', '=', 'Pallet')], limit=1)
free_pallets = env['stock.quant.package'].search([
    ('x_studio_receiving_report_id', '=', False),
    ('package_type_id', '=', pallet_type.id if pallet_type else False),
], order='id desc', limit=200)
stocked = set(env['stock.quant'].search([
    ('package_id', 'in', free_pallets.ids)]).mapped('package_id').ids)
# also skip any pallet already sitting on a document, even an unvalidated one:
# x_studio_receiving_report_id is not always stamped, so the move lines are the
# reliable record of what a pallet number is already spoken for
claimed = set(env['stock.move.line'].search([
    ('result_package_id', 'in', free_pallets.ids),
    ('state', '!=', 'cancel')]).mapped('result_package_id').ids)
free_pallets = [p for p in free_pallets
                if p.id not in stocked and p.id not in claimed][:PALLET_COUNT]
if len(free_pallets) < PALLET_COUNT:
    bail('only %d free pallets available, need %d.'
         % (len(free_pallets), PALLET_COUNT))

actual_kg = KG_PER_PALLET * PALLET_COUNT
demand_kg = actual_kg + SHORT_BY_KG

print('picking type : %s (id %s)' % (picking_type.display_name, picking_type.id))
print('client       : %s' % donor.partner_id.display_name)
print('product      : %s' % donor_move.product_id.display_name)
print('pallets      : %s' % ', '.join(p.name for p in free_pallets))
print('demand       : %.2f kg   actual: %.2f kg   variance: -%.2f kg'
      % (demand_kg, actual_kg, SHORT_BY_KG))

if DRY_RUN:
    print('\nDRY RUN - nothing written. Set DRY_RUN = False to create it.')
    raise SystemExit

# --- build it ---------------------------------------------------------------
picking = env['stock.picking'].create({
    'partner_id': donor.partner_id.id,
    'picking_type_id': picking_type.id,
    'location_id': donor.location_id.id,
    'location_dest_id': donor.location_dest_id.id,
    'x_studio_container_': 'DEVIATION TEST',
    'x_studio_source': donor.x_studio_source or 'TEST',
    'x_studio_trucks_plate_': 'TEST-001',
    'x_studio_gate_pass': 'N/A',
})

move = env['stock.move'].create({
    'picking_id': picking.id,
    'name': 'DEVIATION TEST ITEM',
    'product_id': donor_move.product_id.id,
    'product_uom': donor_move.product_uom.id,
    'product_uom_qty': demand_kg,
    'location_id': donor.location_id.id,
    'location_dest_id': donor.location_dest_id.id,
    'x_studio_client_ref': 'DEV-TEST',
    'x_studio_packaging_unit': donor_move.x_studio_packaging_unit.id or False,
    'x_studio_min_unit': donor_move.x_studio_min_unit.id or False,
    'x_studio_demand_packaging': 40,
    'x_studio_min_uom': 400,
})
picking.action_confirm()

# action_confirm auto-creates one pallet-less line for the whole demand; it
# would make the receipt look OVER-delivered and cancel the shortage
picking.move_line_ids.filtered(lambda l: not l.result_package_id).unlink()

for pallet, remark in zip(free_pallets, REMARKS):
    env['stock.move.line'].create({
        'move_id': move.id,
        'picking_id': picking.id,
        'product_id': donor_move.product_id.id,
        'product_uom_id': donor_move.product_uom.id,
        'quantity': KG_PER_PALLET,
        'location_id': donor.location_id.id,
        'location_dest_id': donor.location_dest_id.id,
        'result_package_id': pallet.id,
        'x_studio_2nd_uom': 10,
        'x_studio_total_units': 100,
        'x_studio_container_number': 'DEVIATION TEST',
        'vifel_remarks': remark,
    })

picking.invalidate_recordset()
env.cr.commit()

print('\nCREATED %s (id %s), state %s'
      % (picking.name, picking.id, picking.state))
print('  discrepancy flag : %s   <-- drives the button'
      % picking.x_studio_has_discrepancy)
print('  kg variance      : %s' % move.x_studio_kg_variance)
print('  Concern/Remarks  : %s' % move.vifel_deviation_remarks)
print('\nOpen it, then Print -> Deviation Report.')
print('To remove it afterwards:')
print("  env['stock.picking'].browse(%s).unlink(); env.cr.commit()" % picking.id)
