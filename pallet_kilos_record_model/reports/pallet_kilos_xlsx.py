from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
from odoo.exceptions import ValidationError, UserError
import pytz
import logging

_logger = logging.getLogger(__name__)

class PalletKilosXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.pallet_kilos_report_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def _get_kg_format_string(self):
        """Get the dynamic KG format string based on system decimal precision."""
        try:
            # Get the decimal precision for 'Product Unit of Measure'
            precision_model = self.env['decimal.precision']
            precision_value = precision_model.precision_get('Product Unit of Measure')
            # Build format string like '#,##0.00' or '#,##0.000'
            if precision_value:
                decimals = '0' * precision_value
                return f'#,##0.{decimals}'
            return '#,##0.00'  # Default fallback
        except Exception as e:
            _logger.warning(f"Error getting decimal precision: {e}, using default")
            return '#,##0.00'

    def _define_formats(self, workbook):
        """Define and return format objects with professional Excel-like design."""
        base_font = {'font_name': 'Calibri', 'font_size': 11}
        kg_format_string = self._get_kg_format_string()
        
        # Professional header format (company name)
        header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#305496',
            'font_color': 'white',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0',
            'text_wrap': True
        })
        
        # Table header format
        table_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10,
            'bg_color': '#305496',
            'font_color': 'white',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0',
            'text_wrap': True
        })
        
        # Summary row format (totals)
        summary_format = workbook.add_format({
            **base_font,
            'bold': True,
            'bg_color': '#FFF2CC',
            'font_color': 'black',
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0',
            'num_format': kg_format_string,
            'text_wrap': True
        })
        
        # Normal text format
        normal_format = workbook.add_format({
            **base_font,
            'align': 'left',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Bold normal text format for reference documents
        normal_format_bold = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Date format
        date_format = workbook.add_format({
            **base_font,
            'num_format': 'mm/dd/yyyy',
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Standard float format
        float_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Float format with dash for zero values
        float_format_dash = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Beginning Balance (Pallets) format - bold, centered, no decimals
        pallet_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0_-;-#,##0_-;"-"_-',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # RR columns (keep green background)
        received_format_vivid = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bg_color': '#C8E6C9',
            'font_color': '#1B5E20',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # WR/Return columns (no background, just text color)
        received_format = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'font_color': '#1B5E20',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        withdrawn_format = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'font_color': '#B71C1C',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Net columns format (dark red text with light red background)
        net_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'font_color': '#B71C1C',
            'bg_color': '#FFCDD2',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Grand totals (keep vivid backgrounds)
        received_format_vivid_bold = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bg_color': '#C8E6C9',
            'font_color': '#1B5E20',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        withdrawn_format_vivid_bold = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bg_color': '#FFCDD2',
            'font_color': '#B71C1C',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Net totals format (bold version of net format)
        net_format_bold = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'font_color': '#B71C1C',
            'bg_color': '#FFCDD2',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Special gray background format
        gray_bg_format = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        gray_bg_format_bold = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        gray_bg_format_float = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        gray_bg_format_float_bold = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        gray_bg_format_pallet = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'num_format': '#,##0_-;-#,##0_-;"-"_-',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # Special format for Remaining PALLET COUNT with italic "pp"
        gray_bg_format_pallet_with_pp = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'num_format': '#,##0 "pp";-#,##0 "pp";"-"',
            'bold': True,
            'italic': True,
            'align': 'center',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        gray_bg_format_float_bold_italic = workbook.add_format({
            **base_font,
            'bg_color': '#D9D9D9',
            'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
            'bold': True,
            'italic': True,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # KG format (dynamic decimal places)
        kg_format = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0'
        })
        
        # KG format bold (dynamic decimal places, bold, yellow background)
        kg_format_bold = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bold': True,
            'bg_color': '#FFF2CC',
            'align': 'right',
            'valign': 'vcenter',
            'top': 1,
            'bottom': 1,
            'top_color': '#00B0F0',
            'bottom_color': '#00B0F0',
            'border': 1
        })
        
        return (header_format, table_header_format, summary_format, normal_format, normal_format_bold,
                date_format, float_format_dash, pallet_format, received_format_vivid, received_format,
                withdrawn_format, received_format_vivid_bold, withdrawn_format_vivid_bold,
                gray_bg_format, gray_bg_format_bold, gray_bg_format_float, gray_bg_format_float_bold, 
                gray_bg_format_pallet, gray_bg_format_pallet_with_pp, gray_bg_format_float_bold_italic,
                net_format, net_format_bold, kg_format, kg_format_bold)

    def _convert_to_user_timezone(self, utc_datetime):
        """Convert UTC datetime to user's timezone (UTC+8 for Philippines)"""
        if not utc_datetime:
            return utc_datetime
            
        # Get user's timezone, default to Asia/Manila (UTC+8)
        user_tz = self.env.user.tz or 'Asia/Manila'
        
        try:
            # Ensure datetime is timezone-aware (UTC)
            if utc_datetime.tzinfo is None:
                utc_datetime = pytz.UTC.localize(utc_datetime)
            elif utc_datetime.tzinfo != pytz.UTC:
                utc_datetime = utc_datetime.astimezone(pytz.UTC)
            
            # Convert to user timezone
            user_timezone = pytz.timezone(user_tz)
            local_datetime = utc_datetime.astimezone(user_timezone)
            
            return local_datetime
        except Exception as e:
            _logger.warning(f"Timezone conversion failed: {e}. Using original datetime.")
            return utc_datetime

    def generate_header(self, sheet, records, formats, end_date):
        """Generate the header section of the report with professional styling."""
        header_format = formats[0]
        normal_format = formats[3]
        
        # Professional company name header - Updated to span all columns including new ones
        sheet.merge_range('A1:Y1', records[0].owner_id.name or '', header_format)
        sheet.set_row(0, 30)  # Increase row height
        
        # Date range with proper timezone conversion
        if records:
            start_date = self._convert_to_user_timezone(records[0].start_time)
            date_range = start_date.strftime('%B %d, %Y') + ' - ' + end_date.strftime('%B %d, %Y')
            sheet.write('A3', date_range, normal_format)

    def generate_summary_totals(self, sheet, all_records, formats):
        """Generate summary totals row."""
        summary_format = formats[2]
        
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

        # Calculate net totals
        net_qty_out = totals['total_packaging_withdrawn'] - totals['total_returned_qty']
        net_weight_out = totals['total_kilos_withdrawn'] - totals['total_returned_kilos']
        total_pallet_out = totals['total_pallets_withdrawn'] - totals['total_returned_pallets']

        # Write totals row
        sheet.write(4, 0, 'TOTALS', summary_format)
        for col in range(1, 4):
            sheet.write(4, col, '', summary_format)
        
        # Write summary totals in corresponding columns
        sheet.write(4, 4, totals['total_packaging_received'], summary_format)
        sheet.write(4, 5, totals['total_units_received'], summary_format)
        sheet.write(4, 6, totals['total_kilos_received'], summary_format)
        sheet.write(4, 7, totals['total_pallets_received'], summary_format)
        sheet.write(4, 8, '', summary_format)
        sheet.write(4, 9, '', summary_format)
        sheet.write(4, 10, totals['total_packaging_withdrawn'], summary_format)
        sheet.write(4, 11, totals['total_returned_qty'], summary_format)
        sheet.write(4, 12, totals['total_units_withdrawn'], summary_format)
        sheet.write(4, 13, totals['total_returned_heads'], summary_format)
        sheet.write(4, 14, totals['total_kilos_withdrawn'], summary_format)
        sheet.write(4, 15, totals['total_returned_kilos'], summary_format)
        sheet.write(4, 16, totals['total_pallets_withdrawn'], summary_format)
        sheet.write(4, 17, totals['total_returned_pallets'], summary_format)
        
        # Net columns
        sheet.write(4, 18, net_qty_out, summary_format)
        sheet.write(4, 19, net_weight_out, summary_format)
        sheet.write(4, 20, total_pallet_out, summary_format)
        
        # Empty balance columns in summary
        for col in range(21, 25):
            sheet.write(4, col, '', summary_format)
            
        sheet.set_row(4, 25)  # Set row height

    def generate_table_header(self, sheet, row_index, formats):
        """Generate the table header with proper text wrapping."""
        table_header_format = formats[1]
        
        headers = [
            'Transaction Date',
            'Beginning Balance (Pallets)',
            'Beginning Balance (Weight KG)',
            'RR#',
            'RR Total Quantity IN',
            'RR Total Packs',
            'RR Total Weight (KG)',
            'RR Total Pallet IN',
            'WR#',
            'RR RETURN',
            'WR Quantity OUT',
            'Return QUANTITY',
            'WR PACKS OUT',
            'Return PACKS',
            'WR WEIGHT (KG) OUT',
            'Return WEIGHT',
            'WR PALLET OUT',
            'Return PALLET',
            'Net Quantity Out',
            'Net Weight Out',
            'Total Pallet Out',
            'Remaining PALLET COUNT',
            'Remaining QUANTITY',
            'Remaining PACKS',
            'Remaining WEIGHT (KG)'
        ]
        
        for col, header in enumerate(headers):
            sheet.write(row_index, col, header, table_header_format)
        
        sheet.set_row(row_index, 40)  # Increase row height for better text visibility

    def calculate_beginning_balances(self, sorted_records):
        """Calculate beginning balances from the first chronological record."""
        beginning_pallets = 0
        beginning_kilos = 0
        
        if sorted_records:
            first_record = sorted_records[0]
            
            # Calculate beginning balance before first transaction
            current_balance_pallets = first_record.total_balance_in_pallets or 0
            pallets_received = first_record.pallets_received or 0
            pallets_withdrawn = first_record.pallets_withdrawn or 0
            beginning_pallets = current_balance_pallets - pallets_received + pallets_withdrawn
            
            current_balance_kilos = first_record.total_balance_in_kilos or 0
            kilos_received = first_record.kilos_received or 0
            kilos_withdrawn = first_record.kilos_withdrawn or 0
            beginning_kilos = current_balance_kilos - kilos_received + kilos_withdrawn
        
        return beginning_pallets, beginning_kilos

    def get_formats_for_row(self, workbook, is_alt_row, formats):
        """Get appropriate formats based on whether it's an alternating row."""
        kg_format_string = self._get_kg_format_string()
        
        if is_alt_row:
            # Create alt row formats dynamically
            date_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': 'mm/dd/yyyy',
                'align': 'center', 'valign': 'vcenter', 'top': 1, 'bottom': 1,
                'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            pallet_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': '#,##0_-;-#,##0_-;"-"_-',
                'bold': True, 'align': 'center', 'valign': 'vcenter', 'top': 1, 'bottom': 1,
                'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            float_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
                'align': 'right', 'valign': 'vcenter', 'top': 1, 'bottom': 1,
                'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            normal_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'align': 'left', 'valign': 'vcenter',
                'top': 1, 'bottom': 1, 'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            normal_fmt_bold = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'bold': True, 'align': 'left', 'valign': 'vcenter',
                'top': 1, 'bottom': 1, 'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            received_vivid_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': kg_format_string,
                'bg_color': '#C8E6C9', 'font_color': '#1B5E20', 'align': 'right', 'valign': 'vcenter',
                'top': 1, 'bottom': 1, 'top_color': '#00B0F0', 'bottom_color': '#00B0F0'
            })
            received_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': kg_format_string,
                'font_color': '#1B5E20', 'align': 'right', 'valign': 'vcenter', 'top': 1, 'bottom': 1,
                'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            withdrawn_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': kg_format_string,
                'font_color': '#B71C1C', 'align': 'right', 'valign': 'vcenter', 'top': 1, 'bottom': 1,
                'top_color': '#00B0F0', 'bottom_color': '#00B0F0', 'bg_color': '#F2F2F2'
            })
            net_fmt = workbook.add_format({
                'font_name': 'Calibri', 'font_size': 11, 'num_format': '#,##0.00_-;-#,##0.00_-;"-"_-',
                'font_color': '#B71C1C', 'bg_color': '#FFCDD2', 'align': 'right', 'valign': 'vcenter',
                'top': 1, 'bottom': 1, 'top_color': '#00B0F0', 'bottom_color': '#00B0F0'
            })
            
            return date_fmt, pallet_fmt, float_fmt, normal_fmt, normal_fmt_bold, received_vivid_fmt, received_fmt, withdrawn_fmt, net_fmt
        else:
            return (formats[5], formats[7], formats[6], formats[3], formats[4], 
                    formats[8], formats[9], formats[10], formats[21])

    def generate_xlsx_report(self, workbook, data, records):
        """Generate the entire XLSX report with professional formatting."""
        formats = self._define_formats(workbook)
        (header_format, table_header_format, summary_format, normal_format, normal_format_bold,
         date_format, float_format_dash, pallet_format, received_format_vivid, received_format,
         withdrawn_format, received_format_vivid_bold, withdrawn_format_vivid_bold,
         gray_bg_format, gray_bg_format_bold, gray_bg_format_float, gray_bg_format_float_bold, 
         gray_bg_format_pallet, gray_bg_format_pallet_with_pp, gray_bg_format_float_bold_italic,
         net_format, net_format_bold, kg_format, kg_format_bold) = formats
        
        # Group records by owner
        records_by_owner = {}
        for record in records:
            owner_name = record.owner_id.company_id.name or record.owner_id.name
            if owner_name not in records_by_owner:
                records_by_owner[owner_name] = []
            records_by_owner[owner_name].append(record)

        for owner_name, owner_records in sorted(records_by_owner.items()):
            sheet = workbook.add_worksheet(owner_name[:31])

            # Set optimized column widths for better text visibility - Updated for new columns
            sheet.set_column(0, 0, 15)   # Date
            sheet.set_column(1, 2, 16)   # Beginning balances
            sheet.set_column(3, 3, 12)   # RR#
            sheet.set_column(4, 7, 14)   # RR columns
            sheet.set_column(8, 9, 12)   # WR# and RR RETURN
            sheet.set_column(10, 17, 14) # Transaction columns
            sheet.set_column(18, 20, 14) # Net columns
            sheet.set_column(21, 24, 16) # Balance columns

            # Same ordering as the Billing XLSX: earliest start_time first, and on a start_time
            # tie, fall back to the PKR log's create_date (unset create_date sorts earliest).
            sorted_records = sorted(owner_records, key=lambda x: (x.start_time, x.create_date or datetime.datetime.min))
            beginning_pallets, beginning_kilos = self.calculate_beginning_balances(sorted_records)

            # Get today's date in user timezone for extended date range
            user_tz = self.env.user.tz or 'Asia/Manila'
            user_timezone = pytz.timezone(user_tz)
            today = datetime.datetime.now(user_timezone).date()
            today_datetime = datetime.datetime.combine(today, datetime.time.max)

            self.generate_header(sheet, sorted_records, formats, today_datetime)
            self.generate_summary_totals(sheet, sorted_records, formats)
            self.generate_table_header(sheet, 5, formats)

            # Freeze panes for better navigation
            sheet.freeze_panes(6, 1)

            row_index = 6

            # Extended date range to today
            oldest_date = self._convert_to_user_timezone(sorted_records[0].start_time).date()
            latest_date = today  # Extend to today instead of last transaction
            
            date_list = [oldest_date + datetime.timedelta(days=x) for x in range((latest_date - oldest_date).days + 1)]

            # Prepare records lookup by date
            records_by_date = {}
            for record in sorted_records:
                record_date = self._convert_to_user_timezone(record.start_time).date()
                if record_date not in records_by_date:
                    records_by_date[record_date] = []
                records_by_date[record_date].append(record)

            summation = {
                'total_pallets_received': 0, 
                'total_pallets_withdrawn': 0, 
                'total_kilos_received': 0, 
                'total_kilos_withdrawn': 0,
                'total_net_qty_out': 0,
                'total_net_weight_out': 0,
                'total_net_pallet_out': 0
            }

            # Track last known balances for gap filling
            last_known_balances = {
                'total_balance_in_pallets': beginning_pallets,
                'total_balance_in_packaging': 0,
                'total_balance_in_units': 0,
                'total_balance_in_kilos': beginning_kilos
            }

            for current_date in date_list:
                records_for_date = records_by_date.get(current_date, [])
                is_alt_row = (row_index % 2 == 0)

                # Get formats for this row type
                date_fmt, pallet_fmt, float_fmt, normal_fmt, normal_fmt_bold, received_vivid_fmt, received_fmt, withdrawn_fmt, net_fmt = self.get_formats_for_row(
                    workbook, is_alt_row, formats)

                if records_for_date:
                    for line in records_for_date:
                        # Convert to user timezone
                        current_datetime = self._convert_to_user_timezone(line.start_time)
                        
                        sheet.write(row_index, 0, current_datetime.replace(tzinfo=None), date_fmt)
                        sheet.write(row_index, 1, line.beginning_balance_in_pallets or 0, gray_bg_format_pallet)  # Gray BG
                        sheet.write(row_index, 2, line.beginning_balance_in_kilos or 0, gray_bg_format_float)  # Gray BG
                        
                        # Use bold format for reference documents
                        sheet.write(row_index, 3, line.record_reference.name if line.record_reference and 'RR' in line.record_reference.name else '', normal_fmt_bold)
                        
                        # Apply vivid received formatting for RR columns (keep background)
                        sheet.write(row_index, 4, line.packaging_received or 0, received_vivid_fmt)
                        sheet.write(row_index, 5, line.units_received or 0, received_vivid_fmt)
                        sheet.write(row_index, 6, line.kilos_received or 0, received_vivid_fmt)
                        sheet.write(row_index, 7, line.pallets_received or 0, received_vivid_fmt)

                        # Validate return ID
                        validated_return_id = False
                        if line.record_reference.return_ids:
                            for return_id in line.record_reference.return_ids:
                                if return_id.state == 'done':
                                    validated_return_id = return_id
                                    break

                        # Use bold format for reference documents
                        sheet.write(row_index, 8, line.record_reference.name if line.record_reference and 'WR' in line.record_reference.name else '', normal_fmt_bold)
                        sheet.write(row_index, 9, validated_return_id.name if validated_return_id else '', gray_bg_format_bold)  # Gray BG

                        # Calculate return values
                        return_weight = return_qty = return_unit = 0
                        if line.record_reference and 'WR' in line.record_reference.name and validated_return_id:
                            for move_line in validated_return_id.move_ids_without_package:
                                return_unit += move_line.x_studio_min_actual_demand or 0
                                return_qty += move_line.x_studio_actual_packaging_demand or 0
                                return_weight += move_line.quantity or 0

                        # Apply formats WITHOUT background color for WR/Return columns
                        sheet.write(row_index, 10, line.packaging_withdrawn or 0, withdrawn_fmt)
                        sheet.write(row_index, 11, return_qty or 0, received_fmt)
                        sheet.write(row_index, 12, line.units_withdrawn or 0, withdrawn_fmt)
                        sheet.write(row_index, 13, return_unit or 0, received_fmt)
                        sheet.write(row_index, 14, line.kilos_withdrawn or 0, withdrawn_fmt)
                        sheet.write(row_index, 15, return_weight or 0, received_fmt)
                        sheet.write(row_index, 16, line.pallets_withdrawn or 0, withdrawn_fmt)
                        sheet.write(row_index, 17, line.return_pallets or 0, received_fmt)

                        # Net columns with dark red text and light red background
                        net_qty_out = (line.packaging_withdrawn or 0) - return_qty
                        net_weight_out = (line.kilos_withdrawn or 0) - return_weight
                        total_pallet_out = (line.pallets_withdrawn or 0) - (line.return_pallets or 0)
                        
                        sheet.write(row_index, 18, net_qty_out, net_fmt)
                        sheet.write(row_index, 19, net_weight_out, net_fmt)
                        sheet.write(row_index, 20, total_pallet_out, net_fmt)

                        # Balance columns with gray background - ALL ITALIC
                        sheet.write(row_index, 21, line.total_balance_in_pallets or 0, gray_bg_format_pallet_with_pp)  # Gray BG with "pp" - ITALIC
                        sheet.write(row_index, 22, line.total_balance_in_packaging or 0, gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC
                        sheet.write(row_index, 23, line.total_balance_in_units or 0, gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC
                        sheet.write(row_index, 24, line.total_balance_in_kilos or 0, gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC

                        # Update last known balances
                        last_known_balances.update({
                            'total_balance_in_pallets': line.total_balance_in_pallets or 0,
                            'total_balance_in_packaging': line.total_balance_in_packaging or 0,
                            'total_balance_in_units': line.total_balance_in_units or 0,
                            'total_balance_in_kilos': line.total_balance_in_kilos or 0
                        })

                        # Update summation
                        summation['total_pallets_received'] += line.pallets_received or 0
                        summation['total_pallets_withdrawn'] += line.pallets_withdrawn or 0
                        summation['total_kilos_received'] += line.kilos_received or 0
                        summation['total_kilos_withdrawn'] += line.kilos_withdrawn or 0
                        summation['total_net_qty_out'] += net_qty_out
                        summation['total_net_weight_out'] += net_weight_out
                        summation['total_net_pallet_out'] += total_pallet_out

                        # Reduced row height for better compactness
                        sheet.set_row(row_index, 18)
                        row_index += 1

                else:
                    # Empty row with inherited balances
                    user_timezone = pytz.timezone(user_tz)
                    current_datetime = user_timezone.localize(datetime.datetime.combine(current_date, datetime.time(23, 59, 59)))
                    
                    sheet.write(row_index, 0, current_datetime.replace(tzinfo=None), date_fmt)
                    sheet.write(row_index, 1, 0, gray_bg_format_pallet)  # Gray BG
                    sheet.write(row_index, 2, 0, gray_bg_format_float)  # Gray BG
                    sheet.write(row_index, 3, '', normal_fmt)
                    sheet.write(row_index, 8, '-', normal_fmt)
                    sheet.write(row_index, 9, '-', gray_bg_format)  # Gray BG
                    
                    # Fill transaction columns with zeros
                    for col in list(range(4, 8)) + list(range(10, 21)):
                        if col in [18, 19, 20]:  # Net columns
                            sheet.write(row_index, col, 0, net_fmt)
                        else:
                            sheet.write(row_index, col, 0, float_fmt)
                    
                    # Show inherited balances with gray background - ALL ITALIC
                    sheet.write(row_index, 21, last_known_balances['total_balance_in_pallets'], gray_bg_format_pallet_with_pp)  # Gray BG with "pp" - ITALIC
                    sheet.write(row_index, 22, last_known_balances['total_balance_in_packaging'], gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC
                    sheet.write(row_index, 23, last_known_balances['total_balance_in_units'], gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC
                    sheet.write(row_index, 24, last_known_balances['total_balance_in_kilos'], gray_bg_format_float_bold_italic)  # Gray BG, Bold, ITALIC
                    
                    # Reduced row height for better compactness
                    sheet.set_row(row_index, 18)
                    row_index += 1

            # Write summary totals at bottom
            sheet.write(row_index, 7, summation['total_pallets_received'], received_format_vivid_bold)
            sheet.write(row_index, 16, summation['total_pallets_withdrawn'], withdrawn_format_vivid_bold)
            sheet.write(row_index, 6, summation['total_kilos_received'], received_format_vivid_bold)
            sheet.write(row_index, 14, summation['total_kilos_withdrawn'], withdrawn_format_vivid_bold)
            
            # Net totals with bold net format
            sheet.write(row_index, 18, summation['total_net_qty_out'], net_format_bold)
            sheet.write(row_index, 19, summation['total_net_weight_out'], net_format_bold)
            sheet.write(row_index, 20, summation['total_net_pallet_out'], net_format_bold)

            # Professional footer
            sheet.write(row_index + 3, 0, "GUARANTEED", header_format)
            
        return True
