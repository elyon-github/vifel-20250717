

from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
import calendar

class PalletKilosXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.occupancy_report'
    _inherit = 'report.report_xlsx.abstract'

    def _define_formats(self, workbook):
        """Define and return format objects with Excel-like design."""
        base_font = {'font_name': 'Calibri', 'font_size': 11}
        
        # Main title format
        title_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 16,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#305496',
            'font_color': 'white',
            'border': 1
        })

        # Header info format
        header_info_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 12,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#B4C6E7',
            'border': 1
        })

        # Client header format (dark blue)
        client_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        # Date header format (dark blue)
        date_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        # Sub header format (PALLET COUNT/KILOGRAMS)
        sub_header_format = workbook.add_format({
            'font_name': 'Calibri', 'font_size': 9,
            # 'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        # Normal text format
        normal_format = workbook.add_format({
            **base_font,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })

        # Number format
        number_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1
        })
        number_format_with_background = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#dcecf4',
        })
        
        # Total row format (yellow background)
        total_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#FFFF99',
            'border': 1
        })

        # Total number format
        total_number_format = workbook.add_format({
            **base_font,
            'bold': True,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFFF99',
            'border': 1
        })

        # Warehouse format
        warehouse_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        return (title_format, header_info_format, client_header_format, date_header_format, 
                sub_header_format, normal_format, number_format, number_format_with_background, total_format, 
                total_number_format, warehouse_format)

    def generate_xlsx_report(self, workbook, data, records):
        formats = self._define_formats(workbook)
        (title_format, header_info_format, client_header_format, date_header_format, 
         sub_header_format, normal_format, number_format, number_format_with_background, total_format, 
         total_number_format, warehouse_format) = formats

        # Create single sheet
        sheet = workbook.add_worksheet('Inventory Occupancy Report')
        
        # Set column widths
        sheet.set_column(0, 0, 25)  # Client column
        sheet.set_column(1, 1, 15)  # Warehouse column
        sheet.set_column(2, 200, 12)  # Date columns

        # Sort records by date
        sorted_records = sorted(records, key=lambda x: x.start_time)
        
        if not sorted_records:
            return

        # Get date range (convert to UTC+8)
        oldest_date_utc8 = (sorted_records[0].start_time + datetime.timedelta(hours=8)).date()
        latest_date_utc8 = (sorted_records[-1].start_time + datetime.timedelta(hours=8)).date()
        date_list = [oldest_date_utc8 + datetime.timedelta(days=x) for x in range((latest_date_utc8 - oldest_date_utc8).days + 1)]

        # Simplified data structure - no warehouse grouping
        owner_data = {}
        for record in sorted_records:
            warehouse_name = record.warehouse.name or 'Unknown Warehouse'
            owner_name = record.owner_id.name or 'Unknown'
            
            if owner_name not in owner_data:
                owner_data[owner_name] = {}
            
            # Convert to UTC+8 for grouping
            record_date_utc8 = (record.start_time + datetime.timedelta(hours=8)).date()
            if record_date_utc8 not in owner_data[owner_name]:
                owner_data[owner_name][record_date_utc8] = []
            owner_data[owner_name][record_date_utc8].append(record)

        # Generate header info
        month_year = oldest_date_utc8.strftime('%B %Y').upper()
        
        # Calculate total pallet position
        total_pallets = 0
        for owner_name, dates in owner_data.items():
            for date, day_records in dates.items():
                if day_records:
                    # Get the last balance of the day
                    last_record = sorted(day_records, key=lambda x: x.start_time)[-1]
                    total_pallets += last_record.total_balance_in_pallets or 0

        current_row = 0

        # Main title
        title_text = 'INVENTORY OCCUPANCY REPORT 2025'
        num_date_cols = len(date_list) * 2  # Each date has 2 columns (pallet + kilos)
        total_cols = 2 + num_date_cols + 2  # Client + Warehouse + Date columns + MAX + MIN
        sheet.merge_range(current_row, 0, current_row, total_cols - 1, title_text, title_format)
        current_row += 1

        # Header info
        sheet.merge_range(current_row, 0, current_row, 1, 'Month:', header_info_format)
        sheet.write(current_row, 2, month_year, header_info_format)
        current_row += 1
        
        sheet.merge_range(current_row, 0, current_row, 1, 'Year:', header_info_format)
        sheet.write(current_row, 2, oldest_date_utc8.year, header_info_format)
        current_row += 1
        
        sheet.merge_range(current_row, 0, current_row, 1, 'Total Pallet Position:', header_info_format)
        sheet.write(current_row, 2, total_pallets, header_info_format)
        current_row += 2

        # Single table without warehouse grouping
        # Table headers row 1
        sheet.write(current_row, 0, 'CLIENT', client_header_format)
        sheet.write(current_row, 1, 'WAREHOUSE', client_header_format)
        
        col = 2
        for date in date_list:
            date_str = date.strftime('%d-%b')
            sheet.merge_range(current_row, col, current_row, col + 1, date_str, date_header_format)
            col += 2
        
        sheet.write(current_row, col, 'MAX', client_header_format)
        sheet.write(current_row, col + 1, 'MIN', client_header_format)
        current_row += 1

        # Table headers row 2 (PALLET COUNT / KILOGRAMS)
        sheet.write(current_row, 0, '', client_header_format)
        sheet.write(current_row, 1, '', client_header_format)
        
        col = 2
        for date in date_list:
            sheet.write(current_row, col, 'PALLET COUNT', sub_header_format)
            sheet.write(current_row, col + 1, 'KILOGRAMS', sub_header_format)
            col += 2
        
        sheet.write(current_row, col, '', client_header_format)
        sheet.write(current_row, col + 1, '', client_header_format)
        current_row += 1

        # Data rows for each client
        total_pallets_by_date = {}
        total_kilos_by_date = {}
        
        for owner_name in sorted(owner_data.keys()):
            owner_dates = owner_data[owner_name]
            
            sheet.write(current_row, 0, owner_name, normal_format)
            
            # Get warehouse name from the most recent record for this owner
            warehouse_name = 'Unknown Warehouse'
            for date, day_records in owner_dates.items():
                if day_records:
                    last_record = sorted(day_records, key=lambda x: x.start_time)[-1]
                    warehouse_name = last_record.warehouse.name or 'Unknown Warehouse'
                    break
            
            sheet.write(current_row, 1, warehouse_name, normal_format)
            
            col = 2
            pallet_values = []
            last_known_pallet = 0
            last_known_kilos = 0
            
            for date in date_list:
                pallet_count = 0
                kilos_count = 0
            
                if date in owner_dates:
                    day_records = owner_dates[date]
                    if day_records:
                        # Get the last balance of the day
                        last_record = sorted(day_records, key=lambda x: x.start_time)[-1]
                        pallet_count = last_record.total_balance_in_pallets or 0
                        kilos_count = last_record.total_balance_in_kilos or 0
                        last_known_pallet = pallet_count
                        last_known_kilos = kilos_count
                else:
                    # Use last known values
                    pallet_count = last_known_pallet
                    kilos_count = last_known_kilos
            
                # Write values
                sheet.write(current_row, col, pallet_count, number_format)
                sheet.write(current_row, col + 1, kilos_count, number_format_with_background)
                pallet_values.append(pallet_count)
            
                # Update totals
                if date not in total_pallets_by_date:
                    total_pallets_by_date[date] = 0
                    total_kilos_by_date[date] = 0
                total_pallets_by_date[date] += pallet_count
                total_kilos_by_date[date] += kilos_count
            
                col += 2
            
            # MAX and MIN formulas
            if pallet_values:
                start_col = 2
                end_col = start_col + (len(date_list) * 2) - 2  # Only pallet columns
                row_num = current_row + 1  # Excel is 1-indexed
                
                # Create range string for pallet columns only (every other column starting from C)
                pallet_cols = []
                for i in range(start_col, end_col + 1, 2):
                    col_letter = chr(65 + i) if i < 26 else chr(65 + i // 26 - 1) + chr(65 + i % 26)
                    pallet_cols.append(f"{col_letter}{row_num}")
                
                if pallet_cols:
                    max_formula = f"=MAX({','.join(pallet_cols)})"
                    min_formula = f"=MIN({','.join(pallet_cols)})"
                    sheet.write_formula(current_row, col, max_formula, number_format)
                    sheet.write_formula(current_row, col + 1, min_formula, number_format)
            else:
                sheet.write(current_row, col, '-', normal_format)
                sheet.write(current_row, col + 1, '-', normal_format)
            
            current_row += 1

        # Single TOTAL row
        sheet.write(current_row, 0, 'TOTAL', total_format)
        sheet.write(current_row, 1, 'ALL WAREHOUSES', total_format)
        
        col = 2
        for date in date_list:
            total_pallets = total_pallets_by_date.get(date, 0)
            total_kilos = total_kilos_by_date.get(date, 0)
            
            if total_pallets > 0 or total_kilos > 0:
                sheet.write(current_row, col, total_pallets, total_number_format)
                sheet.write(current_row, col + 1, total_kilos, total_number_format)
            else:
                sheet.write(current_row, col, '-', total_format)
                sheet.write(current_row, col + 1, '-', total_format)
            col += 2
        
        # TOTAL MAX/MIN (empty for now)
        sheet.write(current_row, col, '', total_format)
        sheet.write(current_row, col + 1, '', total_format)