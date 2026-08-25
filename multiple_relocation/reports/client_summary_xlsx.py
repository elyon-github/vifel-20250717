from odoo import models
from datetime import datetime, date, timedelta


class InventorySummary(models.AbstractModel):
    _name = "report.stock_quant.inventory_summary_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Inventory Summary XLSX Report"

    @staticmethod
    def _pallet_id(quant):
        """Identity of the physical pallet a quant sits on, or None.

        Mirrors how pallets in stock are counted everywhere else in the system
        (vifel_health_monitor._check_pallet_drift, and the PKR Re-sync
        "actual" figure): a REGULAR pallet is its package, a BLAST-FREEZE
        pallet has no package and is identified by its free-text Pallet #
        (bf_pallet_char). The two namespaces are kept apart so a package id
        can never collide with a BF text.
        """
        if quant.package_id:
            return ('pkg', quant.package_id.id)
        bf = (quant.bf_pallet_char or '').strip()
        if bf:
            return ('bf', bf)
        return None

    def generate_xlsx_report(self, workbook, data, records):
        # Define formats with improved color scheme
        title_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 16, 'bg_color': '#1565C0', 'font_color': 'white',
            'border': 1, 'text_wrap': True
        })
        
        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12, 'bg_color': '#1565C0', 'font_color': 'white',
            'border': 1, 'text_wrap': True
        })
        
        summary_format = workbook.add_format({
            'bold': True, 'bg_color': '#FFC107', 'font_color': 'black',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'num_format': '#,##0.00', 'text_wrap': True
        })
        
        number_format = workbook.add_format({
            'num_format': '#,##0.00',
            'border': 1,
            'align': 'right'
        })

        # Pallet counts are whole pallets — never show them as 2.00
        int_format = workbook.add_format({
            'num_format': '#,##0',
            'border': 1,
            'align': 'right'
        })

        pallet_total_format = workbook.add_format({
            'bold': True, 'bg_color': '#FFC107', 'font_color': 'black',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'num_format': '#,##0', 'text_wrap': True
        })
        
        date_format = workbook.add_format({
            'num_format': 'yyyy-mm-dd', 
            'border': 1,
            'align': 'center',
        })
        
        datetime_format = workbook.add_format({
            'num_format': 'yyyy-mm-dd hh:mm', 
            'border': 1,
            'align': 'center',
            'bg_color': '#FFC107',
            'font_color': 'black',
            'bold': True, 
            
        })
        
        right_text_format = workbook.add_format({
            'align': 'right', 
            'bold': True, 
            'border': 1
        })
        
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })

        Quant = self.env['stock.quant']

        for owner in records.mapped('owner_id'):
            # Re-fetch each owner's COMPLETE on-hand internal inventory instead of trusting the
            # ticked selection. Selecting "all owners" in the list only passes a page/limit-bound
            # subset, so per-owner totals came out inaccurate; selecting one owner at a time
            # happened to pass everything. Re-querying here makes the report always match the
            # Inventory Overview for every owner present in the selection.
            moves = Quant.search([
                ('owner_id', '=', owner.id),
                ('location_id.usage', '=', 'internal'),
                # Exclude Blast-Freeze stock: this summary is for regular
                # cold-storage inventory only. x_studio_is_a_blast_freezer is the
                # canonical (stored) BF flag on the location, used system-wide.
                ('location_id.x_studio_is_a_blast_freezer', '=', False),
                ('quantity', '!=', 0),
            ])
            if not moves:
                continue
            customer_name = owner.name or 'Unknown'
            sorted_moves = sorted(moves, key=lambda move: move.x_studio_expiration_date or date.max)
            sheet = workbook.add_worksheet(customer_name[:31])
            
            # Set column widths for better readability - Adjusted for production date column
            sheet.set_column(0, 0, 40)  # Item Description
            sheet.set_column(1, 1, 35)  # Container Van No
            sheet.set_column(2, 2, 15)  # Production Date
            sheet.set_column(3, 3, 15)  # Expiration Date
            sheet.set_column(4, 4, 20)  # Quantity
            sheet.set_column(5, 5, 20)  # HEADS
            sheet.set_column(6, 6, 20)  # Weight(KG)
            sheet.set_column(7, 7, 20)  # Number of Pallets

            # Freeze panes for easier navigation
            sheet.freeze_panes(8, 0)  # Freeze header row

            # Company header and timestamp - FIXED: Now applying proper formatting
            sheet.merge_range('A1:H1', 'INVENTORY SUMMARY', title_format)
            sheet.merge_range('A2:H2', f'CUSTOMER: {customer_name}', title_format)

            # Timestamp row with better formatting
            sheet.merge_range('A3:E3', 'Inventory Status as of:', right_text_format)

            sheet.merge_range('F3:H3', (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"), datetime_format)

            
            # Add a blank row for spacing
            sheet.set_row(3, 10)
            
            # TOTAL number of pallets held by this client right now.
            # Counted over the WHOLE owner, not by summing the per-row column:
            # a pallet carrying more than one product / container / date lands
            # in several rows, so summing the column would count it twice. The
            # header figure is therefore the distinct-pallet count, matching
            # the Inventory Overview and the health monitor's pallet check.
            total_pallets = len({
                pid for pid in (self._pallet_id(m) for m in sorted_moves)
                if pid is not None
            })

            # Summary row with proper titles and formatting - Adjusted to span all columns
            sheet.merge_range('A5:H5', 'SUMMARY', header_format)
            sheet.write(5, 0, 'Total Quantity:', right_text_format)
            sheet.write(5, 1, sum(m.x_studio_2nd_uom or 0 for m in sorted_moves), summary_format)
            sheet.write(5, 2, 'Total Heads:', right_text_format)
            sheet.write(5, 3, sum(m.x_studio_total_units or 0 for m in sorted_moves), summary_format)
            sheet.write(5, 4, 'Total Weight (KG):', right_text_format)
            sheet.write(5, 5, sum(m.quantity or 0 for m in sorted_moves), summary_format)
            sheet.write(5, 6, 'Total Pallets:', right_text_format)
            sheet.write(5, 7, total_pallets, pallet_total_format)
            
            # Add a blank row for spacing
            sheet.set_row(6, 10)

            # Table header - FIXED: Now including Production Date column
            headers = ["Item Description", "Container Van No.", "Production Date", "Expiration Date",
                      "Quantity", "HEADS", "Weight(KG)", "Number of Pallets"]
            for col, h in enumerate(headers):
                sheet.write(7, col, h.upper(), header_format)
            
            # Set row height for header
            sheet.set_row(7, 30)

            # Data rows with improved grouping and formatting
            row = 8
            
            # Group by product name and sort by expiration date
            grouped_data = {}
            for move in sorted_moves:
                key = (move.product_id.name, move.x_studio_container_number,
                       move.x_studio_production_date, move.x_studio_expiration_date)
                if key not in grouped_data:
                    grouped_data[key] = {'quantity': 0, 'pcs': 0, 'weight': 0,
                                         'pallets': set()}
                grouped_data[key]['quantity'] += move.x_studio_2nd_uom or 0
                grouped_data[key]['pcs'] += move.x_studio_total_units or 0
                grouped_data[key]['weight'] += move.quantity or 0
                # distinct physical pallets holding this line's stock
                pallet_id = self._pallet_id(move)
                if pallet_id is not None:
                    grouped_data[key]['pallets'].add(pallet_id)

            # Sort by product name alphabetically
            sorted_keys = sorted(grouped_data.keys(), key=lambda k: (k[0] or '').lower())
            
            # Add data rows
            for key in sorted_keys:
                product_name, container_number, production_date, expiration_date = key
                totals = grouped_data[key]
                
                sheet.write(row, 0, product_name, cell_format)
                sheet.write(row, 1, container_number or '', cell_format)
                sheet.write(row, 2, production_date or '', date_format)  # Production Date
                sheet.write(row, 3, expiration_date or '', date_format)  # Expiration Date
                sheet.write(row, 4, totals['quantity'], number_format)
                sheet.write(row, 5, totals['pcs'], number_format)
                sheet.write(row, 6, totals['weight'], number_format)
                sheet.write(row, 7, len(totals['pallets']), int_format)
                row += 1

            # Add auto-filter for easy sorting - Adjusted to include all columns
            sheet.autofilter(7, 0, row-1, 7)
