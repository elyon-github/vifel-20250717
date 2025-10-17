from odoo import models
from itertools import groupby
from operator import itemgetter
import datetime
import re

class CountSheet(models.AbstractModel):
    _name = "report.stock_location.count_sheet_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Count Sheet"

    def generate_xlsx_report(self, workbook, data, records):
        bold = workbook.add_format({"bold": True, "border": 1})
        header_format = workbook.add_format({"bold": True, "bg_color": "#08248c", "font_color": "white", "align": "center", "valign": "vcenter", "font_size": 11, "border": 1})
        cx_name_format = workbook.add_format({"font_size": 11, "align": "center", "font_size": 11, "border": 1})
        right_text_format = workbook.add_format({"align": "right", "bold": True, "font_size": 11, "border": 1})
        number_format = workbook.add_format({"num_format": "#,##0.00", "font_size": 11, "border": 1})
        text_wrap_format = workbook.add_format({"text_wrap": True, "font_size": 11, "border": 1})
        justify_format = workbook.add_format({"align": "center", "valign": "vcenter", "text_wrap": True, "font_size": 11, "border": 1})
        justify_format_location = workbook.add_format({"align": "center", "valign": "vcenter", "text_wrap": True, "font_size": 11, 'color': 'red', 'bold': True, "border": 1})
        
        # Define the UTC+8 timezone
        utc_plus_8 = datetime.timezone(datetime.timedelta(hours=8))
        
        # Get current time in UTC+8
        date_generated = datetime.datetime.now(utc_plus_8).strftime("%Y-%m-%d %H:%M:%S")

        def get_room_number(record):
            parent_location = record.location_id
            if parent_location:
                parent_location = parent_location.location_id
                if parent_location:
                    parent_location = parent_location.location_id
                    if parent_location:
                        parent_location = parent_location.location_id
                        return parent_location.name

        def get_side(record):
            parent_location = record.location_id
            if parent_location:
                parent_location = parent_location.location_id
                if parent_location:
                    parent_location = parent_location.location_id
                    return parent_location.name

        def extract_room_number(room_str):
            """Extract numeric part from room number for proper sorting"""
            if not room_str:
                return 0
            # Extract numbers from the room string
            numbers = re.findall(r'\d+', str(room_str))
            return int(numbers[0]) if numbers else 0

        def sort_key(record):
            """Custom sort key for proper room and side ordering"""
            room = get_room_number(record)
            side = get_side(record)
            room_num = extract_room_number(room)
            return (room_num, side)

        def write_headers(sheet, current_row, room_number, side, date_generated):
            """Helper function to write headers"""
            # Set default height for date generated row
            sheet.set_row(current_row, None)
            sheet.write(current_row, 0, f"Date Generated: {date_generated}", bold)
            
            header_row = current_row + 1
            # Set default height for header row
            sheet.set_row(header_row, None)
            sheet.write(header_row, 0, f"Room {room_number} - {side}", header_format)
            sheet.write(header_row, 1, "True", header_format)
            sheet.write(header_row, 2, "Pallet # / Series", header_format)
            sheet.write(header_row, 3, "Desc.", header_format)
            sheet.write(header_row, 4, "PD", header_format)
            sheet.write(header_row, 5, "ED", header_format)
            sheet.write(header_row, 6, "QTY", header_format)
            sheet.write(header_row, 7, "Kilos", header_format)
            sheet.write(header_row, 8, "Container #", header_format)
            sheet.write(header_row, 9, f"Room {room_number} - {side}", header_format)
            sheet.write(header_row, 10, "True", header_format)
            sheet.write(header_row, 11, "Pallet #", header_format)
            sheet.write(header_row, 12, "Desc.", header_format)
            sheet.write(header_row, 13, "PD", header_format)
            sheet.write(header_row, 14, "ED", header_format)
            sheet.write(header_row, 15, "QTY", header_format)
            sheet.write(header_row, 16, "Kilos", header_format)
            sheet.write(header_row, 17, "Container #", header_format)
            
            return header_row + 1  # Return the next row after headers

        # Sort records properly by numeric room number and side
        records_sorted_by_complete_name = sorted(records, key=lambda x: x.complete_name)
        records_sorted = sorted(records_sorted_by_complete_name, key=sort_key)
        grouped_records = groupby(records_sorted, key=lambda x: (get_room_number(x), get_side(x)))

        for (room_number, side), group in grouped_records:
            sheet = workbook.add_worksheet(f"Room {room_number} - {side}")
            
            # Set the column widths
            sheet.set_column(0, 0, 15.64)  
            sheet.set_column(1, 1, 5.7109375)  
            sheet.set_column(2, 2, 19.18)  
            sheet.set_column(3, 3, 42.09)  
            sheet.set_column(4, 4, 12.36)  #PD 
            sheet.set_column(5, 5, 12.36)   #ED
            sheet.set_column(6, 6, 13.28515625)  
            sheet.set_column(7, 7, 10.28515625)  
            sheet.set_column(8, 8, 17.85546875)  
            sheet.set_column(9, 9, 15.5703125)  
            sheet.set_column(10, 10, 5)  
            sheet.set_column(11, 11, 19.140625)  
            sheet.set_column(12, 12, 42.0)  
            sheet.set_column(13, 13, 13.28515625)  
            sheet.set_column(14, 14, 12.28515625)  
            sheet.set_column(15, 15, 13.28515625)  
            sheet.set_column(16, 16, 10.28515625)  
            sheet.set_column(17, 17, 17.85546875)
            
            # Hide columns after setting widths
            sheet.set_column(1, 1, None, None, {'hidden': True})
            sheet.set_column(10, 10, None, None, {'hidden': True})

            # Write initial headers
            row = write_headers(sheet, 0, room_number, side, date_generated)
            
            # List to track page break positions
            page_breaks = []
            
            # Set row heights for content rows
            for i in range(2, 300):  # Extended range to cover all possible rows
                sheet.set_row(i, 52.5)
            
            group_list = list(group)
            content_row_counter = 0  # Track content rows written
            
            for idx, record in enumerate(group_list):
                location_name = record.complete_name
                
                pallet_names = ", ".join(record.x_studio_pallets.mapped("name")) if record.x_studio_pallets else ""
                pallet_series_names = ", ".join(
                    record.quant_ids.filtered(lambda q: q.quantity != 0).mapped("x_studio_pallet_series_id")
                ) if record.quant_ids else ""
                pallet_names = f"{pallet_names} | {pallet_series_names}"

                # Check if we need to reinitialize headers (every 21 content rows)
                if content_row_counter > 0 and content_row_counter % 21 == 0:
                    # Add page break before the new header
                    page_breaks.append(row + content_row_counter)
                    row = write_headers(sheet, row + content_row_counter, room_number, side, date_generated)
                    content_row_counter = 0  # Reset counter after headers
                
                # Calculate current row based on content rows written
                current_row = row + content_row_counter
                
                if idx % 2 == 0:  # Left side
                    sheet.write(current_row, 0, self.convert_location_string(location_name), justify_format_location)
                    sheet.write(current_row, 1, "", justify_format)
                    sheet.write(current_row, 2, pallet_names if pallet_series_names else '', justify_format)
                    sheet.write(current_row, 7, record.x_studio_total_quantity if record.x_studio_total_quantity else '', justify_format)
                else:  # Right side
                    sheet.write(current_row, 9, self.convert_location_string(location_name), justify_format_location)
                    sheet.write(current_row, 10, "", justify_format)
                    sheet.write(current_row, 11, pallet_names if pallet_series_names else '', justify_format)
                    sheet.write(current_row, 16, record.x_studio_total_quantity if record.x_studio_total_quantity else '', justify_format)
                
                # Write product details for both sides
                product_names = []
                pd = []
                ed = []
                qty = 0
                container_number_name = []
                for quant in record.quant_ids:
                    if quant.quantity > 0:
                        product_name = quant.product_id.display_name
                        product_names.append(product_name)
                        pd_name = str(quant.x_studio_production_date)
                        if pd_name != 'False':
                            pd.append(pd_name)
                        ed_name = str(quant.x_studio_expiration_date)
                        if ed_name != 'False':
                            ed.append(ed_name)
                        qty += quant.x_studio_2nd_uom
                        container_number = quant.x_studio_container_number
                        if container_number:
                            container_number_name.append(container_number)
                
                if idx % 2 == 0:  # Left side
                    sheet.write(current_row, 3, ", ".join(product_names), justify_format)
                    sheet.write(current_row, 4, ", ".join(pd), justify_format)
                    sheet.write(current_row, 5, ", ".join(ed), justify_format)
                    sheet.write(current_row, 6, qty if qty else '', justify_format)
                    sheet.write(current_row, 8, ", ".join(container_number_name), justify_format)
                else:  # Right side
                    sheet.write(current_row, 12, ", ".join(product_names), justify_format)
                    sheet.write(current_row, 13, ", ".join(pd), justify_format)
                    sheet.write(current_row, 14, ", ".join(ed), justify_format)
                    sheet.write(current_row, 15, qty if qty else '', justify_format)
                    sheet.write(current_row, 17, ", ".join(container_number_name), justify_format)
                
                # Increment content row counter only on right side completion or last item
                if idx % 2 == 1 or idx == len(group_list) - 1:
                    content_row_counter += 1
            
            # Set all page breaks at once for this worksheet
            if page_breaks:
                sheet.set_h_pagebreaks(page_breaks)

    def convert_location_string(self, s):
        parts = s.split('/')
        try:
            if len(parts) < 7:
                return s
            
            part_3 = parts[2]
            part_4 = parts[3]
            part_5 = parts[4]
            part_6 = parts[5]
            part_7 = parts[6]
            
            digit = ''.join(filter(str.isdigit, part_7))
            if not digit:
                return s
            
            return f"{part_3}{part_4}{part_5}{part_6}.{digit}"
        
        except Exception:
            return s