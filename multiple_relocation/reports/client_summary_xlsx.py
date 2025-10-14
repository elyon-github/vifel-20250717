from odoo import models
from datetime import datetime, date, timedelta


class InventorySummary(models.AbstractModel):
    _name = "report.stock_quant.inventory_summary_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Inventory Summary XLSX Report"

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

        grouped_records = {}
        for record in records:
            customer_name = record.owner_id.name
            if customer_name not in grouped_records:
                grouped_records[customer_name] = []
            grouped_records[customer_name].append(record)

        for customer_name, moves in grouped_records.items():
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
            
            # Freeze panes for easier navigation
            sheet.freeze_panes(8, 0)  # Freeze header row

            # Company header and timestamp - FIXED: Now applying proper formatting
            sheet.merge_range('A1:G1', 'INVENTORY SUMMARY', title_format)
            sheet.merge_range('A2:G2', f'CUSTOMER: {customer_name}', title_format)
            
            # Timestamp row with better formatting
            sheet.merge_range('A3:E3', 'Inventory Status as of:', right_text_format)

            sheet.merge_range('F3:G3', (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"), datetime_format)

            
            # Add a blank row for spacing
            sheet.set_row(3, 10)
            
            # Summary row with proper titles and formatting - Adjusted to span all columns
            sheet.merge_range('A5:G5', 'SUMMARY', header_format)
            sheet.write(5, 0, 'Total Quantity:', right_text_format)
            sheet.write(5, 1, sum(m.x_studio_2nd_uom for m in sorted_moves), summary_format)
            sheet.write(5, 2, 'Total Heads:', right_text_format)
            sheet.write(5, 3, sum(m.x_studio_total_units for m in sorted_moves), summary_format)
            sheet.write(5, 4, 'Total Weight (KG):', right_text_format)
            sheet.write(5, 5, sum(m.available_quantity for m in sorted_moves), summary_format)
            sheet.write(5, 6, '', summary_format)  # Extra cell for alignment
            
            # Add a blank row for spacing
            sheet.set_row(6, 10)

            # Table header - FIXED: Now including Production Date column
            headers = ["Item Description", "Container Van No.", "Production Date", "Expiration Date", 
                      "Quantity", "HEADS", "Weight(KG)"]
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
                    grouped_data[key] = {'quantity': 0, 'pcs': 0, 'weight': 0}
                grouped_data[key]['quantity'] += move.x_studio_2nd_uom
                grouped_data[key]['pcs'] += move.x_studio_total_units
                grouped_data[key]['weight'] += move.available_quantity

            # Sort by product name alphabetically
            sorted_keys = sorted(grouped_data.keys(), key=lambda k: k[0].lower())
            
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
                row += 1
                
            # Add auto-filter for easy sorting - Adjusted to include all columns
            sheet.autofilter(7, 0, row-1, 6)