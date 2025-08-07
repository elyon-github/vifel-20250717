# from odoo import models
# import datetime
# from xlsxwriter.workbook import Workbook
# from odoo.exceptions import ValidationError, UserError


# import logging
# _logger = logging.getLogger(__name__)


# class PalletKilosXlsx(models.AbstractModel):
#     _name = 'report.pallet_kilos_record_model.pallet_kilos_report_xlsx'
#     _inherit = 'report.report_xlsx.abstract'

#     def _define_formats(self, workbook):
#         """Define formats for the report with enhanced visual appeal."""
#         # Enhanced company name format with bigger font, bold, and professional design
#         company_format = workbook.add_format({
#             'bold': True,
#             'align': 'center',
#             'valign': 'vcenter',
#             'font_size': 18,
#             'font_name': 'Arial Black',
#             'bg_color': '#0D47A1',  # Deep blue
#             'font_color': 'white',
#             'border': 2,
#             'border_color': '#1565C0',
#             'top': 2,
#             'bottom': 2,
#             'left': 2,
#             'right': 2
#         })
        
#         header_format = workbook.add_format({
#             'bold': True,
#             'align': 'center',
#             'valign': 'vcenter',
#             'font_size': 12,
#             'bg_color': '#E3F2FD',  # Light blue
#             'font_color': '#0D47A1',  # Dark blue text
#             'border': 1,
#             'border_color': '#1565C0'
#         })
        
#         table_header_format = workbook.add_format({
#             'bold': True,
#             'bg_color': '#1565C0',  # Dark blue
#             'font_color': 'white',  # White text
#             'align': 'center',
#             'valign': 'vcenter',
#             'border': 1,
#             'border_color': '#90CAF9'  # Light blue border
#         })
        
#         # Summary row format - different shade from headers
#         summary_format = workbook.add_format({
#             'bold': True,
#             'bg_color': '#FFC107',  # Amber/yellow
#             'font_color': '#000000',  # Black text
#             'align': 'center',
#             'valign': 'vcenter',
#             'border': 2,
#             'border_color': '#FF8F00',  # Darker amber border
#             'num_format': '#,##0.00'
#         })
        
#         normal_format = workbook.add_format({
#             'align': 'left',
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         # Standard float format
#         float_format = workbook.add_format({
#             'num_format': '#,##0.00',
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         # Float format that shows '-' for zero values
#         float_format_dash = workbook.add_format({
#             'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
#             'border': 1,
#             'border_color': '#BDBDBD',
#             'text_wrap': True
#         })
        
#         float_format_bold = workbook.add_format({
#             'num_format': '#,##0.00',
#             'bold': True,
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         date_format = workbook.add_format({
#             'num_format': 'yyyy-mm-dd',
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         # New formats for received and withdrawn data with dash for zero
#         received_format = workbook.add_format({
#             'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
#             'bg_color': '#E8F5E9',  # Light green background
#             'font_color': '#1B5E20',  # Dark green text
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         received_format_bold = workbook.add_format({
#             'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
#             'bg_color': '#E8F5E9',  # Light green background
#             'font_color': '#1B5E20',  # Dark green text
#             'bold': True,
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         withdrawn_format = workbook.add_format({
#             'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
#             'bg_color': '#FFEBEE',  # Light red background
#             'font_color': '#B71C1C',  # Dark red text
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         withdrawn_format_bold = workbook.add_format({
#             'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
#             'bg_color': '#FFEBEE',  # Light red background
#             'font_color': '#B71C1C',  # Dark red text
#             'bold': True,
#             'border': 1,
#             'border_color': '#BDBDBD'
#         })
        
#         return (company_format, header_format, table_header_format, normal_format, 
#                 float_format, float_format_bold, date_format, summary_format,
#                 received_format, received_format_bold, withdrawn_format, withdrawn_format_bold,
#                 float_format_dash)

#     def generate_header(self, sheet, records, formats):
#         """Generate the header section of the report with enhanced styling."""
#         company_format, header_format, _, normal_format, _, _, _, _, _, _, _, _, _ = formats
        
#         # Enhanced company name with merged cells for better impact
#         sheet.merge_range('A1:V2', records[0].owner_id.name or '', company_format)
        
#         # Add "BILLING DETAILS-HOLDING" with spacing
#         # sheet.write('A4', 'BILLING DETAILS-HOLDING', header_format)
        
#         # Date range
#         if records:
#             start_date = records[0].start_time + datetime.timedelta(hours=8)
#             end_date = records[-1].start_time + datetime.timedelta(hours=8)
#             date_range = start_date.strftime('%B %d, %Y') + ' - ' + end_date.strftime('%B %d, %Y')
#             sheet.write('A5', date_range, normal_format)

#     def generate_summary_totals(self, sheet, all_records, formats):
#         """Generate summary totals row at the top."""
#         _, _, _, _, _, _, _, summary_format, _, _, _, _, _ = formats
        
#         # Calculate totals from all records
#         totals = {
#             'total_packaging_received': 0,
#             'total_units_received': 0,
#             'total_kilos_received': 0,
#             'total_pallets_received': 0,
#             'total_packaging_withdrawn': 0,
#             'total_units_withdrawn': 0,
#             'total_kilos_withdrawn': 0,
#             'total_pallets_withdrawn': 0,
#             'total_returned_qty': 0,
#             'total_returned_heads': 0,
#             'total_returned_kilos': 0,
#             'total_returned_pallets': 0,
#         }
        
#         for record in all_records:
#             totals['total_packaging_received'] += record.packaging_received or 0
#             totals['total_units_received'] += record.units_received or 0
#             totals['total_kilos_received'] += record.kilos_received or 0
#             totals['total_pallets_received'] += record.pallets_received or 0
#             totals['total_packaging_withdrawn'] += record.packaging_withdrawn or 0
#             totals['total_units_withdrawn'] += record.units_withdrawn or 0
#             totals['total_kilos_withdrawn'] += record.kilos_withdrawn or 0
#             totals['total_pallets_withdrawn'] += record.pallets_withdrawn or 0
#             totals['total_returned_qty'] += record.return_packaging or 0
#             totals['total_returned_heads'] += record.return_heads or 0
#             totals['total_returned_kilos'] += record.return_kilos or 0
#             totals['total_returned_pallets'] += record.return_pallets or 0

#         # Write "TOTALS" label
#         sheet.write(6, 0, 'TOTALS', summary_format)
#         sheet.write(6, 1, '', summary_format)
#         sheet.write(6, 2, '', summary_format)
#         sheet.write(6, 3, '', summary_format)  # Empty cell under RR#
        
#         # Write summary totals in corresponding columns
#         sheet.write(6, 4, totals['total_packaging_received'], summary_format)
#         sheet.write(6, 5, totals['total_units_received'], summary_format)
#         sheet.write(6, 6, totals['total_kilos_received'], summary_format)
#         sheet.write(6, 7, totals['total_pallets_received'], summary_format)
#         sheet.write(6, 8, '', summary_format)  # Empty cell under WR#
#         sheet.write(6, 9, '', summary_format)  # Empty cell under RR RETURN
#         sheet.write(6, 10, totals['total_packaging_withdrawn'], summary_format)
#         sheet.write(6, 11, totals['total_returned_qty'], summary_format)  # Return qty (calculated differently)
#         sheet.write(6, 12, totals['total_units_withdrawn'], summary_format)
#         sheet.write(6, 13, totals['total_returned_heads'], summary_format)  # Return heads (calculated differently)
#         sheet.write(6, 14, totals['total_kilos_withdrawn'], summary_format)
#         sheet.write(6, 15, totals['total_returned_kilos'], summary_format)  # Return weight (calculated differently)
#         sheet.write(6, 16, totals['total_pallets_withdrawn'], summary_format)
#         sheet.write(6, 17, totals['total_returned_pallets'], summary_format)  # Return pallet (calculated differently)
        
#         # Balance columns - we'll leave these empty in summary as they're running balances
#         for col in range(16, 22):
#             sheet.write(6, col, '', summary_format)

#     def generate_table_header(self, sheet, row_index, formats):
#         """Generate the table header with enhanced styling."""
#         _, _, table_header_format, _, _, _, _, _, _, _, _, _, _ = formats
        
#         # Column headers with dark blue background and white text
#         headers = ['Transaction Date',
#                    'Beginning Balance (Pallets)',
#                    'Beginning Balance (Weight (KG))',
#                    'RR#.',
#                    'RR total in',
#                    'RR total heads',
#                    'RR total weight',
#                    'RR total pallet in',
#                    'WR#',
#                    "RR RETURN",
#                    "WR qty out",
#                    "Return qty",
#                    "WR heads out",
#                    "Return heads",
#                    "WR weight out",
#                    "Return weight",
#                    "WR Pallet out",
#                    "Return pallet",
#                    "Remaining pallet quantity",
#                    "Remaining quantity",
#                    "Remaining heads",
#                    "Remaining Weight"]
        
#         for col, header in enumerate(headers):
#             sheet.write(row_index, col, header, table_header_format)
    
#     def generate_xlsx_report(self, workbook, data, records):
#         """Generate the entire XLSX report with enhanced visual formatting."""
#         formats = self._define_formats(workbook)
#         # Unpack all formats
#         (company_format, header_format, table_header_format, normal_format, 
#          float_format, float_format_bold, date_format, summary_format,
#          received_format, received_format_bold, withdrawn_format, withdrawn_format_bold,
#          float_format_dash) = formats
        
#         # Group records by owner
#         records_by_owner = {}
#         for record in records:
#             owner_name = record.owner_id.company_id.name or record.owner_id.name
#             if owner_name not in records_by_owner:
#                 records_by_owner[owner_name] = []
#             records_by_owner[owner_name].append(record)
    
#         # Iterate over each owner and generate a separate sheet
#         for owner_name, owner_records in records_by_owner.items():
#             # Create a new worksheet for the owner
#             sheet = workbook.add_worksheet(owner_name)

#             sheet.set_column(0, 22, 20)      # Set all columns to width 20 first


            
#             # Sort records by date
#             sorted_records = sorted(owner_records, key=lambda x: x.start_time)

            
#             # Generate header with enhanced formatting
#             self.generate_header(sheet, sorted_records, formats)
            
#             # Generate summary totals (at row 6, 0-indexed)
#             self.generate_summary_totals(sheet, sorted_records, formats)
            
#             # Generate table header (at row 7, 0-indexed)
#             self.generate_table_header(sheet, 7, formats)
            
#             # Freeze panes at row 8 (after headers) and column A
#             sheet.freeze_panes(8, 3)
            
#             # Set starting row for data (row 8)
#             row_index = 9
    
#             # Determine the oldest and latest date
#             oldest_date = sorted_records[0].start_time.date()
#             latest_date = sorted_records[-1].start_time.date()
    
#             # Create a list of all dates between oldest_date and latest_date
#             date_list = [oldest_date + datetime.timedelta(days=x) for x in range((latest_date - oldest_date).days + 1)]
    
#             # Prepare a lookup dictionary for records by date
#             records_by_date = {}
#             for record in sorted_records:
#                 record_date = record.start_time.date()
#                 if record_date not in records_by_date:
#                     records_by_date[record_date] = []
#                 records_by_date[record_date].append(record)
    
#             # Initialize summation dictionary
#             summation = {'total_pallets_received': 0, 'total_pallets_withdrawn': 0, 'total_kilos_received': 0, 'total_kilos_withdrawn': 0}
    
#             # Iterate over the full date range
#             for current_date in date_list:
#                 # Get all records for the current date, or an empty list if none exist
#                 records_for_date = records_by_date.get(current_date, [])
        
#                 # Write a row for each record on the current date
#                 for line in records_for_date:
#                     # Ensure proper formatting and summation
#                     cstart_timetime = line.start_time + datetime.timedelta(hours=8)
#                     sheet.write(row_index, 0, cstart_timetime, date_format)
#                     sheet.write(row_index, 1, line.beginning_balance_in_pallets or 0, float_format_dash)
#                     sheet.write(row_index, 2, line.beginning_balance_in_kilos or 0, float_format_dash)
#                     # Format RR reference with consistent coloring
    
#                     sheet.write(row_index, 3, line.record_reference.name if line.record_reference and 'RR' in line.record_reference.name else '', normal_format)
                    
#                     # Apply received formatting with dash for zero values
#                     sheet.write(row_index, 4, line.packaging_received or 0, received_format)
#                     sheet.write(row_index, 5, line.units_received or 0, received_format)
#                     sheet.write(row_index, 6, line.kilos_received or 0, received_format)
#                     sheet.write(row_index, 7, line.pallets_received or 0, received_format)
                    
#                     # Format WR reference field
#                     sheet.write(row_index, 8, line.record_reference.name if line.record_reference and 'WR' in line.record_reference.name else '', normal_format)
#                     sheet.write(row_index, 9, line.record_reference.return_ids[0].name if line.record_reference and line.record_reference.return_ids else '', normal_format)
    
#                     # Calculate return values
#                     return_weight = 0
#                     return_qty = 0
#                     return_unit = 0
    
#                     if line.record_reference and 'WR' in line.record_reference.name and line.record_reference.return_ids and line.record_reference.return_ids[0]:
#                         return_id = line.record_reference.return_ids[0]
#                         return_unit = 0
#                         return_qty = 0
#                         return_weight = 0
    
#                         for lines in return_id.move_ids_without_package:
#                             return_unit += lines.x_studio_min_actual_demand
#                             return_qty += lines.x_studio_actual_packaging_demand
#                             return_weight += lines.quantity
    
#                     # Apply withdrawn formatting with dash for zero values
#                     sheet.write(row_index, 10, line.packaging_withdrawn or 0, withdrawn_format)
#                     sheet.write(row_index, 11, return_qty or 0, received_format)
#                     sheet.write(row_index, 12, line.units_withdrawn or 0, withdrawn_format)
#                     sheet.write(row_index, 13, return_unit or 0, received_format)
#                     sheet.write(row_index, 14, line.kilos_withdrawn or 0, withdrawn_format)
#                     sheet.write(row_index, 15, return_weight or 0, received_format)
                    
#                     # Use standard formats for balance fields with dash formatting
#                     sheet.write(row_index, 16, line.pallets_withdrawn or 0, withdrawn_format)
#                     sheet.write(row_index, 17, line.return_pallets or 0, received_format)
#                     sheet.write(row_index, 18, line.total_balance_in_pallets or 0, float_format_dash)
#                     sheet.write(row_index, 19, line.total_balance_in_packaging or 0, float_format_dash)
#                     sheet.write(row_index, 20, line.total_balance_in_units or 0, float_format_dash)
#                     sheet.write(row_index, 21, line.total_balance_in_kilos or 0, float_format_dash)
    
#                     # Sum up various properties
#                     summation['total_pallets_received'] += line.pallets_received or 0
#                     summation['total_pallets_withdrawn'] += line.pallets_withdrawn or 0
#                     summation['total_kilos_received'] += line.kilos_received or 0
#                     summation['total_kilos_withdrawn'] += line.kilos_withdrawn or 0
    
#                     # Increment row index
#                     row_index += 1
    
#                 # If no records for the current date, write a blank row
#                 if not records_for_date:
#                     start_time = (current_date + datetime.timedelta(hours=8))
#                     sheet.write(row_index, 0, start_time, date_format)
#                     # Write blank data for the rest of the columns
#                     sheet.write(row_index, 3, '', normal_format)
#                     # Use dash format for empty numeric cells
#                     for col in range(1, 21):
#                         sheet.write(row_index, col, 0, float_format_dash)


#                     sheet.write(row_index, 8, '-', normal_format)
#                     sheet.write(row_index, 9, '-', normal_format)
#                     # Show running balances for empty days
#                     if sorted_records:
#                         # Get last record for balance values
#                         last_record = sorted_records[-1]
#                         sheet.write(row_index, 18, last_record.total_balance_in_pallets or 0, float_format_dash)
#                         sheet.write(row_index, 19, last_record.total_balance_in_packaging or 0, float_format_dash)
#                         sheet.write(row_index, 20, last_record.total_balance_in_units or 0, float_format_dash)
#                         sheet.write(row_index, 21, last_record.total_balance_in_kilos or 0, float_format_dash)
#                     # Increment row index
#                     row_index += 1
    
#             # Write summation totals with appropriate formatting
#             sheet.write(row_index, 7, summation['total_pallets_received'] or 0, received_format_bold)
#             sheet.write(row_index, 16, summation['total_pallets_withdrawn'] or 0, withdrawn_format_bold)
#             sheet.write(row_index, 6, summation['total_kilos_received'] or 0, received_format_bold)
#             sheet.write(row_index, 14, summation['total_kilos_withdrawn'] or 0, withdrawn_format_bold)
    
#             # Add a professional looking footer
#             sheet.write(row_index + 5, 0, "GUARANTEED", header_format)
#             sheet.set_column('B:C', 30)
#             sheet.set_column(1, 3, 0)        # Then hide columns B through C
#         return True
from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
from odoo.exceptions import ValidationError, UserError


import logging
_logger = logging.getLogger(__name__)


class PalletKilosXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.pallet_kilos_report_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def _define_formats(self, workbook):
        """Define formats for the report with enhanced visual appeal."""
        # Enhanced company name format with bigger font, bold, and professional design
        company_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 18,
            'font_name': 'Arial Black',
            'bg_color': '#0D47A1',  # Deep blue
            'font_color': 'white',
            'border': 2,
            'border_color': '#1565C0',
            'top': 2,
            'bottom': 2,
            'left': 2,
            'right': 2
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 12,
            'bg_color': '#E3F2FD',  # Light blue
            'font_color': '#0D47A1',  # Dark blue text
            'border': 1,
            'border_color': '#1565C0'
        })
        
        table_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1565C0',  # Dark blue
            'font_color': 'white',  # White text
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#90CAF9'  # Light blue border
        })
        
        # Summary row format - different shade from headers
        summary_format = workbook.add_format({
            'bold': True,
            'bg_color': '#FFC107',  # Amber/yellow
            'font_color': '#000000',  # Black text
            'align': 'center',
            'valign': 'vcenter',
            'border': 2,
            'border_color': '#FF8F00',  # Darker amber border
            'num_format': '#,##0.00'
        })
        
        normal_format = workbook.add_format({
            'align': 'left',
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        # Standard float format
        float_format = workbook.add_format({
            'num_format': '#,##0.00',
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        # Float format that shows '-' for zero values
        float_format_dash = workbook.add_format({
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'border': 1,
            'border_color': '#BDBDBD',
            'text_wrap': True
        })
        
        float_format_bold = workbook.add_format({
            'num_format': '#,##0.00',
            'bold': True,
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        date_format = workbook.add_format({
            'num_format': 'yyyy-mm-dd',
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        # New formats for received and withdrawn data with dash for zero
        received_format = workbook.add_format({
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bg_color': '#E8F5E9',  # Light green background
            'font_color': '#1B5E20',  # Dark green text
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        received_format_bold = workbook.add_format({
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bg_color': '#E8F5E9',  # Light green background
            'font_color': '#1B5E20',  # Dark green text
            'bold': True,
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        withdrawn_format = workbook.add_format({
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bg_color': '#FFEBEE',  # Light red background
            'font_color': '#B71C1C',  # Dark red text
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        withdrawn_format_bold = workbook.add_format({
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bg_color': '#FFEBEE',  # Light red background
            'font_color': '#B71C1C',  # Dark red text
            'bold': True,
            'border': 1,
            'border_color': '#BDBDBD'
        })
        
        return (company_format, header_format, table_header_format, normal_format, 
                float_format, float_format_bold, date_format, summary_format,
                received_format, received_format_bold, withdrawn_format, withdrawn_format_bold,
                float_format_dash)

    def generate_header(self, sheet, records, formats):
        """Generate the header section of the report with enhanced styling."""
        company_format, header_format, _, normal_format, _, _, _, _, _, _, _, _, _ = formats
        
        # Enhanced company name with merged cells for better impact
        sheet.merge_range('A1:V2', records[0].owner_id.name or '', company_format)
        
        # Add "BILLING DETAILS-HOLDING" with spacing
        # sheet.write('A4', 'BILLING DETAILS-HOLDING', header_format)
        
        # Date range
        if records:
            start_date = records[0].start_time + datetime.timedelta(hours=8)
            end_date = records[-1].start_time + datetime.timedelta(hours=8)
            date_range = start_date.strftime('%B %d, %Y') + ' - ' + end_date.strftime('%B %d, %Y')
            sheet.write('A5', date_range, normal_format)

    def generate_summary_totals(self, sheet, all_records, formats):
        """Generate summary totals row at the top."""
        _, _, _, _, _, _, _, summary_format, _, _, _, _, _ = formats
        
        # Calculate totals from all records
        totals = {
            'total_packaging_received': 0,
            'total_units_received': 0,
            'total_kilos_received': 0,
            'total_pallets_received': 0,
            'total_packaging_withdrawn': 0,
            'total_units_withdrawn': 0,
            'total_kilos_withdrawn': 0,
            'total_pallets_withdrawn': 0,
            'total_returned_qty': 0,
            'total_returned_heads': 0,
            'total_returned_kilos': 0,
            'total_returned_pallets': 0,
        }
        
        for record in all_records:
            totals['total_packaging_received'] += record.packaging_received or 0
            totals['total_units_received'] += record.units_received or 0
            totals['total_kilos_received'] += record.kilos_received or 0
            totals['total_pallets_received'] += record.pallets_received or 0
            totals['total_packaging_withdrawn'] += record.packaging_withdrawn or 0
            totals['total_units_withdrawn'] += record.units_withdrawn or 0
            totals['total_kilos_withdrawn'] += record.kilos_withdrawn or 0
            totals['total_pallets_withdrawn'] += record.pallets_withdrawn or 0
            totals['total_returned_qty'] += record.return_packaging or 0
            totals['total_returned_heads'] += record.return_heads or 0
            totals['total_returned_kilos'] += record.return_kilos or 0
            totals['total_returned_pallets'] += record.return_pallets or 0

        # Write "TOTALS" label
        sheet.write(6, 0, 'TOTALS', summary_format)
        sheet.write(6, 1, '', summary_format)
        sheet.write(6, 2, '', summary_format)
        sheet.write(6, 3, '', summary_format)  # Empty cell under RR#
        
        # Write summary totals in corresponding columns
        sheet.write(6, 4, totals['total_packaging_received'], summary_format)
        sheet.write(6, 5, totals['total_units_received'], summary_format)
        sheet.write(6, 6, totals['total_kilos_received'], summary_format)
        sheet.write(6, 7, totals['total_pallets_received'], summary_format)
        sheet.write(6, 8, '', summary_format)  # Empty cell under WR#
        sheet.write(6, 9, '', summary_format)  # Empty cell under RR RETURN
        sheet.write(6, 10, totals['total_packaging_withdrawn'], summary_format)
        sheet.write(6, 11, totals['total_returned_qty'], summary_format)  # Return qty (calculated differently)
        sheet.write(6, 12, totals['total_units_withdrawn'], summary_format)
        sheet.write(6, 13, totals['total_returned_heads'], summary_format)  # Return heads (calculated differently)
        sheet.write(6, 14, totals['total_kilos_withdrawn'], summary_format)
        sheet.write(6, 15, totals['total_returned_kilos'], summary_format)  # Return weight (calculated differently)
        sheet.write(6, 16, totals['total_pallets_withdrawn'], summary_format)
        sheet.write(6, 17, totals['total_returned_pallets'], summary_format)  # Return pallet (calculated differently)
        
        # Balance columns - we'll leave these empty in summary as they're running balances
        for col in range(16, 22):
            sheet.write(6, col, '', summary_format)

    def generate_table_header(self, sheet, row_index, formats):
        """Generate the table header with enhanced styling."""
        _, _, table_header_format, _, _, _, _, _, _, _, _, _, _ = formats
        
        # Column headers with dark blue background and white text
        headers = ['Transaction Date',
                   'Beginning Balance (Pallets)',
                   'Beginning Balance (Weight (KG))',
                   'RR#.',
                   'RR total in',
                   'RR total heads',
                   'RR total weight',
                   'RR total pallet in',
                   'WR#',
                   "RR RETURN",
                   "WR qty out",
                   "Return qty",
                   "WR heads out",
                   "Return heads",
                   "WR weight out",
                   "Return weight",
                   "WR Pallet out",
                   "Return pallet",
                   "Remaining pallet quantity",
                   "Remaining quantity",
                   "Remaining heads",
                   "Remaining Weight"]
        
        for col, header in enumerate(headers):
            sheet.write(row_index, col, header, table_header_format)

    def calculate_beginning_balances(self, sorted_records):
        """Calculate beginning balances from the first chronological record."""
        beginning_pallets = 0
        beginning_kilos = 0
        
        if sorted_records:
            # Get the very first record chronologically
            first_record = sorted_records[0]
            
            # Debug logging
            _logger.info(f"First record values:")
            _logger.info(f"  total_balance_in_pallets: {first_record.total_balance_in_pallets}")
            _logger.info(f"  pallets_received: {first_record.pallets_received}")
            _logger.info(f"  pallets_withdrawn: {first_record.pallets_withdrawn}")
            _logger.info(f"  total_balance_in_kilos: {first_record.total_balance_in_kilos}")
            _logger.info(f"  kilos_received: {first_record.kilos_received}")
            _logger.info(f"  kilos_withdrawn: {first_record.kilos_withdrawn}")
            
            # Calculate beginning balance before first transaction
            # Formula: Beginning Balance = Current Balance - Received + Withdrawn
            
            # For pallets
            current_balance_pallets = first_record.total_balance_in_pallets or 0
            pallets_received = first_record.pallets_received or 0
            pallets_withdrawn = first_record.pallets_withdrawn or 0
            beginning_pallets = current_balance_pallets - pallets_received + pallets_withdrawn
            
            # For kilos
            current_balance_kilos = first_record.total_balance_in_kilos or 0
            kilos_received = first_record.kilos_received or 0
            kilos_withdrawn = first_record.kilos_withdrawn or 0
            beginning_kilos = current_balance_kilos - kilos_received + kilos_withdrawn
            
            _logger.info(f"Calculated beginning_pallets: {beginning_pallets}")
            _logger.info(f"Calculated beginning_kilos: {beginning_kilos}")
        
        return beginning_pallets, beginning_kilos
    
    def generate_xlsx_report(self, workbook, data, records):
        """Generate the entire XLSX report with enhanced visual formatting."""
        formats = self._define_formats(workbook)
        # Unpack all formats
        (company_format, header_format, table_header_format, normal_format, 
         float_format, float_format_bold, date_format, summary_format,
         received_format, received_format_bold, withdrawn_format, withdrawn_format_bold,
         float_format_dash) = formats
        
        # Group records by owner
        records_by_owner = {}
        for record in records:
            owner_name = record.owner_id.company_id.name or record.owner_id.name
            if owner_name not in records_by_owner:
                records_by_owner[owner_name] = []
            records_by_owner[owner_name].append(record)
    
        # Iterate over each owner and generate a separate sheet
        for owner_name, owner_records in records_by_owner.items():
            # Create a new worksheet for the owner
            sheet = workbook.add_worksheet(owner_name)

            sheet.set_column(0, 22, 20)      # Set all columns to width 20 first

            # Sort records by date
            sorted_records = sorted(owner_records, key=lambda x: x.start_time)

            # Calculate beginning balances
            beginning_pallets, beginning_kilos = self.calculate_beginning_balances(sorted_records)
            
            # Generate header with enhanced formatting
            self.generate_header(sheet, sorted_records, formats)
            
            # Generate summary totals (at row 6, 0-indexed)
            self.generate_summary_totals(sheet, sorted_records, formats)
            
            # Generate table header (at row 7, 0-indexed)
            self.generate_table_header(sheet, 7, formats)
            
            # Write beginning balances in row 9 (index 8)
            # Column S (18) for pallets, Column V (21) for kilos
            sheet.write(8, 18, beginning_pallets or 0, float_format_dash)
            sheet.write(8, 21, beginning_kilos or 0, float_format_dash)
            
            # Freeze panes at row 8 (after headers) and column A
            sheet.freeze_panes(8, 3)
            
            # Set starting row for data (row 8)
            row_index = 9
    
            # Determine the oldest and latest date
            oldest_date = sorted_records[0].start_time.date()
            latest_date = sorted_records[-1].start_time.date()
    
            # Create a list of all dates between oldest_date and latest_date
            date_list = [oldest_date + datetime.timedelta(days=x) for x in range((latest_date - oldest_date).days + 1)]
    
            # Prepare a lookup dictionary for records by date
            records_by_date = {}
            for record in sorted_records:
                record_date = record.start_time.date()
                if record_date not in records_by_date:
                    records_by_date[record_date] = []
                records_by_date[record_date].append(record)
    
            # Initialize summation dictionary
            summation = {'total_pallets_received': 0, 'total_pallets_withdrawn': 0, 'total_kilos_received': 0, 'total_kilos_withdrawn': 0}
    
            # Track the last known balances for gap filling
            last_known_balances = {
                'total_balance_in_pallets': beginning_pallets,
                'total_balance_in_packaging': 0,
                'total_balance_in_units': 0,
                'total_balance_in_kilos': beginning_kilos
            }
    
            # Iterate over the full date range
            for current_date in date_list:
                # Get all records for the current date, or an empty list if none exist
                records_for_date = records_by_date.get(current_date, [])
        
                # Write a row for each record on the current date
                for line in records_for_date:
                    # Ensure proper formatting and summation
                    cstart_timetime = line.start_time + datetime.timedelta(hours=8)
                    sheet.write(row_index, 0, cstart_timetime, date_format)
                    sheet.write(row_index, 1, line.beginning_balance_in_pallets or 0, float_format_dash)
                    sheet.write(row_index, 2, line.beginning_balance_in_kilos or 0, float_format_dash)
                    # Format RR reference with consistent coloring
    
                    sheet.write(row_index, 3, line.record_reference.name if line.record_reference and 'RR' in line.record_reference.name else '', normal_format)
                    
                    # Apply received formatting with dash for zero values
                    sheet.write(row_index, 4, line.packaging_received or 0, received_format)
                    sheet.write(row_index, 5, line.units_received or 0, received_format)
                    sheet.write(row_index, 6, line.kilos_received or 0, received_format)
                    sheet.write(row_index, 7, line.pallets_received or 0, received_format)
                    
                    # Format WR reference field
                    sheet.write(row_index, 8, line.record_reference.name if line.record_reference and 'WR' in line.record_reference.name else '', normal_format)
                    sheet.write(row_index, 9, line.record_reference.return_ids[0].name if line.record_reference and line.record_reference.return_ids else '', normal_format)
    
                    # Calculate return values
                    return_weight = 0
                    return_qty = 0
                    return_unit = 0
    
                    if line.record_reference and 'WR' in line.record_reference.name and line.record_reference.return_ids and line.record_reference.return_ids[0]:
                        return_id = line.record_reference.return_ids[0]
                        return_unit = 0
                        return_qty = 0
                        return_weight = 0
    
                        for lines in return_id.move_ids_without_package:
                            return_unit += lines.x_studio_min_actual_demand
                            return_qty += lines.x_studio_actual_packaging_demand
                            return_weight += lines.quantity
    
                    # Apply withdrawn formatting with dash for zero values
                    sheet.write(row_index, 10, line.packaging_withdrawn or 0, withdrawn_format)
                    sheet.write(row_index, 11, return_qty or 0, received_format)
                    sheet.write(row_index, 12, line.units_withdrawn or 0, withdrawn_format)
                    sheet.write(row_index, 13, return_unit or 0, received_format)
                    sheet.write(row_index, 14, line.kilos_withdrawn or 0, withdrawn_format)
                    sheet.write(row_index, 15, return_weight or 0, received_format)
                    
                    # Use standard formats for balance fields with dash formatting
                    sheet.write(row_index, 16, line.pallets_withdrawn or 0, withdrawn_format)
                    sheet.write(row_index, 17, line.return_pallets or 0, received_format)
                    sheet.write(row_index, 18, line.total_balance_in_pallets or 0, float_format_dash)
                    sheet.write(row_index, 19, line.total_balance_in_packaging or 0, float_format_dash)
                    sheet.write(row_index, 20, line.total_balance_in_units or 0, float_format_dash)
                    sheet.write(row_index, 21, line.total_balance_in_kilos or 0, float_format_dash)
    
                    # Update last known balances with current transaction values
                    last_known_balances['total_balance_in_pallets'] = line.total_balance_in_pallets or 0
                    last_known_balances['total_balance_in_packaging'] = line.total_balance_in_packaging or 0
                    last_known_balances['total_balance_in_units'] = line.total_balance_in_units or 0
                    last_known_balances['total_balance_in_kilos'] = line.total_balance_in_kilos or 0
    
                    # Sum up various properties
                    summation['total_pallets_received'] += line.pallets_received or 0
                    summation['total_pallets_withdrawn'] += line.pallets_withdrawn or 0
                    summation['total_kilos_received'] += line.kilos_received or 0
                    summation['total_kilos_withdrawn'] += line.kilos_withdrawn or 0
    
                    # Increment row index
                    row_index += 1
    
                # If no records for the current date, write a blank row with inherited balances
                if not records_for_date:
                    start_time = (current_date + datetime.timedelta(hours=8))
                    sheet.write(row_index, 0, start_time, date_format)
                    # Write blank data for the rest of the columns
                    sheet.write(row_index, 3, '', normal_format)
                    sheet.write(row_index, 8, '-', normal_format)
                    sheet.write(row_index, 9, '-', normal_format)
                    
                    # Use dash format for empty numeric cells (transaction columns)
                    for col in range(1, 18):
                        if col not in [8, 9]:  # Skip the already filled WR# and RR RETURN columns
                            sheet.write(row_index, col, 0, float_format_dash)
                    
                    # Show inherited running balances from last known transaction
                    sheet.write(row_index, 18, last_known_balances['total_balance_in_pallets'], float_format_dash)
                    sheet.write(row_index, 19, last_known_balances['total_balance_in_packaging'], float_format_dash)
                    sheet.write(row_index, 20, last_known_balances['total_balance_in_units'], float_format_dash)
                    sheet.write(row_index, 21, last_known_balances['total_balance_in_kilos'], float_format_dash)
                    
                    # Increment row index
                    row_index += 1
    
            # Write summation totals with appropriate formatting
            sheet.write(row_index, 7, summation['total_pallets_received'] or 0, received_format_bold)
            sheet.write(row_index, 16, summation['total_pallets_withdrawn'] or 0, withdrawn_format_bold)
            sheet.write(row_index, 6, summation['total_kilos_received'] or 0, received_format_bold)
            sheet.write(row_index, 14, summation['total_kilos_withdrawn'] or 0, withdrawn_format_bold)
    
            # Add a professional looking footer
            sheet.write(row_index + 5, 0, "GUARANTEED", header_format)
            sheet.set_column('B:C', 30)
            sheet.set_column(1, 2, 0)        # Then hide columns B through C
        return True