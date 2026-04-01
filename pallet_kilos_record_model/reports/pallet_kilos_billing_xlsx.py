from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
import pytz
import logging

_logger = logging.getLogger(__name__)

class PalletKilosXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.pallet_kilos_billing_report_2'
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
        """Define and return format objects with Excel-like design."""
        base_font = {'font_name': 'Calibri', 'font_size': 11}
        kg_format_string = self._get_kg_format_string()
        
        header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 14,
            'align': 'left',
            'valign': 'vcenter'
        })

        table_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        normal_format = workbook.add_format({
            **base_font,
            'align': 'left',
            'valign': 'vcenter'
        })

        float_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter'
        })

        float_format_bold = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1
        })

        # KG format with dynamic decimal places
        kg_format = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'align': 'right',
            'valign': 'vcenter'
        })

        kg_format_bold = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1
        })

        date_format = workbook.add_format({
            **base_font,
            'num_format': 'mm/dd/yyyy',
            'align': 'left',
            'valign': 'vcenter'
        })

        alt_row_format = workbook.add_format({
            **base_font,
            'bg_color': '#F2F2F2',
            'align': 'left',
            'valign': 'vcenter'
        })

        return header_format, table_header_format, normal_format, float_format, float_format_bold, date_format, alt_row_format, kg_format, kg_format_bold

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

    def generate_header(self, sheet, sorted_records, formats, end_date):
        header_format, _, normal_format, _, _, _, _ = formats
        sheet.write(0, 0, sorted_records[0].owner_id.name or '', header_format)
        sheet.write(1, 0, 'BILLING DETAILS-HOLDING', header_format)
        
        # Convert start date to user timezone
        start_date = self._convert_to_user_timezone(sorted_records[0].start_time)
        
        # Use the provided end_date (already in user timezone)
        date_range = start_date.strftime('%B %d, %Y') + ' - ' + end_date.strftime('%B %d, %Y')
        sheet.write(2, 0, date_range, normal_format)

    def generate_table_header(self, sheet, row_index, formats):
        _, table_header_format, _, _, _, _, _ = formats
        table_headers = [
            'Date', 'Receiving Report No.', 'Withdrawal Report No.', 'Pallets Received',
            'Pallets Withdrawn', 'Balance in Pallets', 'Kilos Received', 'Kilos Withdrawn',
            'Balance in Kilos'
        ]
        for col_index, header_text in enumerate(table_headers):
            sheet.write(row_index, col_index, header_text, table_header_format)

    def generate_xlsx_report(self, workbook, data, records):
        formats = self._define_formats(workbook)
        header_format, table_header_format, normal_format, float_format, float_format_bold, date_format, alt_row_format = formats

        records_by_owner = {}
        for record in records:
            owner_name = record.owner_id.name or 'Unknown'
            records_by_owner.setdefault(owner_name, []).append(record)

        for owner_name, owner_records in sorted(records_by_owner.items()):
            sheet = workbook.add_worksheet(owner_name[:31])  # Excel sheet name limit
            sheet.set_column(0, 11, 20)
            row_index = 5

            sorted_records = sorted(owner_records, key=lambda x: (x.start_time, x.create_date or datetime.datetime.min))
            
            # Convert dates to user timezone
            oldest_date_local = self._convert_to_user_timezone(sorted_records[0].start_time).date()
            
            # Get today's date in user timezone
            user_tz = self.env.user.tz or 'Asia/Manila'
            user_timezone = pytz.timezone(user_tz)
            today = datetime.datetime.now(user_timezone).date()
            
            # Use today as the end date instead of last transaction date
            latest_date_local = today
            
            # Create date list from oldest transaction to today
            date_list = [oldest_date_local + datetime.timedelta(days=x) for x in range((latest_date_local - oldest_date_local).days + 1)]

            records_by_date = {}
            for record in sorted_records:
                # Convert to user timezone then get date for grouping
                record_date_local = self._convert_to_user_timezone(record.start_time).date()
                records_by_date.setdefault(record_date_local, []).append(record)

            # Pass today's datetime for header generation
            today_datetime = datetime.datetime.combine(today, datetime.time.max)
            self.generate_header(sheet, sorted_records, formats, today_datetime)
            self.generate_table_header(sheet, row_index - 2, formats)

            summation = {
                'total_pallets_received': 0,
                'total_pallets_withdrawn': 0,
                'total_kilos_received': 0,
                'total_kilos_withdrawn': 0
            }

            # Initialize running balances
            current_pallet_balance = 0
            current_kilo_balance = 0

            # Calculate beginning balances from the very first chronological record
            beginning_kilos = 0
            beginning_pallets = 0
            
            if sorted_records:  # Make sure we have records
                # Get the very first record chronologically (already sorted by start_time)
                first_record = sorted_records[0]
                
                # Calculate beginning balance before first transaction
                # Formula: Beginning Balance = Current Balance - Received + Withdrawn
                
                # For kilos: work backwards from the balance after the transaction
                current_balance_kilos = first_record.total_balance_in_kilos or 0
                kilos_received = first_record.kilos_received or 0
                kilos_withdrawn = first_record.kilos_withdrawn or 0
                beginning_kilos = current_balance_kilos - kilos_received + kilos_withdrawn
                
                # For pallets: work backwards from the balance after the transaction  
                current_balance_pallets = first_record.total_balance_in_pallets or 0
                pallets_received = first_record.pallets_received or 0
                pallets_withdrawn = first_record.pallets_withdrawn or 0
                beginning_pallets = current_balance_pallets - pallets_received + pallets_withdrawn
                
            # Set initial running balances
            current_pallet_balance = beginning_pallets
            current_kilo_balance = beginning_kilos
            
            # Write beginning balances
            sheet.write(row_index-1, 8, beginning_kilos or 0, float_format)
            sheet.write(row_index-1, 5, beginning_pallets or 0, float_format)
            
            for current_date in date_list:
                records_for_date = records_by_date.get(current_date, [])
                
                if records_for_date:
                    for i, line in enumerate(records_for_date):
                        is_alt = (row_index % 2 == 0)
                        base_format = alt_row_format if is_alt else normal_format
                        # Use the current_date directly since it's already in user timezone
                        sheet.write(row_index, 0, current_date, date_format)
                        rr_text = line.record_reference.name if line.record_reference and 'RR' in line.record_reference.name else ''
                        wr_text = line.record_reference.name if line.record_reference and 'WR' in line.record_reference.name else ''
                        sheet.write(row_index, 1, rr_text, base_format)
                        sheet.write(row_index, 2, wr_text, base_format)
                        sheet.write(row_index, 3, line.pallets_received or 0, float_format)
                        sheet.write(row_index, 4, line.pallets_withdrawn or 0, float_format)
                        sheet.write(row_index, 5, line.total_balance_in_pallets or 0, float_format)
                        sheet.write(row_index, 6, line.kilos_received or 0, kg_format)
                        sheet.write(row_index, 7, line.kilos_withdrawn or 0, kg_format)
                        sheet.write(row_index, 8, line.total_balance_in_kilos or 0, kg_format)

                        # Update running balances with the latest values from this record
                        current_pallet_balance = line.total_balance_in_pallets or 0
                        current_kilo_balance = line.total_balance_in_kilos or 0

                        summation['total_pallets_received'] += line.pallets_received or 0
                        summation['total_pallets_withdrawn'] += line.pallets_withdrawn or 0
                        summation['total_kilos_received'] += line.kilos_received or 0
                        summation['total_kilos_withdrawn'] += line.kilos_withdrawn or 0

                        row_index += 1
                else:
                    # Create empty rows for missing dates with last known balances
                    is_alt = (row_index % 2 == 0)
                    base_format = alt_row_format if is_alt else normal_format
                    # Use the current_date directly since it's already in user timezone
                    sheet.write(row_index, 0, current_date, date_format)
                    for col in range(1, 9):
                        if col in [3, 4, 6, 7]:  # Numeric columns for transactions (0 for missing dates)
                            sheet.write(row_index, col, 0, float_format)
                        elif col == 5:  # Balance in Pallets (use last known balance)
                            sheet.write(row_index, col, current_pallet_balance, float_format)
                        elif col == 8:  # Balance in Kilos (use last known balance)
                            sheet.write(row_index, col, current_kilo_balance, float_format)
                        else:  # Text columns (RR/WR numbers)
                            sheet.write(row_index, col, '-', base_format)
                    row_index += 1

            # Write totals
            sheet.write(row_index, 3, summation['total_pallets_received'], float_format_bold)
            sheet.write(row_index, 4, summation['total_pallets_withdrawn'], float_format_bold)
            sheet.write(row_index, 6, summation['total_kilos_received'], kg_format_bold)
            sheet.write(row_index, 7, summation['total_kilos_withdrawn'], kg_format_bold)

            sheet.write(row_index + 3, 0, "GUARANTEED", header_format)


class PalletKilosXlsx_2(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.pallet_kilos_billing_report'
    _inherit = 'report.report_xlsx.abstract'

    def _define_formats(self, workbook):
        """Define and return format objects with Excel-like design."""
        base_font = {'font_name': 'Calibri', 'font_size': 11}
        
        header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 14,
            'align': 'left',
            'valign': 'vcenter'
        })

        table_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'bg_color': '#305496',
            'font_color': 'white'
        })

        normal_format = workbook.add_format({
            **base_font,
            'align': 'left',
            'valign': 'vcenter'
        })

        float_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter'
        })

        float_format_bold = workbook.add_format({
            **base_font,
            'num_format': '#,##0.00',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1
        })

        # KG format with 3 decimal places
        kg_format = workbook.add_format({
            **base_font,
            'num_format': '#,##0.000',
            'align': 'right',
            'valign': 'vcenter'
        })

        kg_format_bold = workbook.add_format({
            **base_font,
            'num_format': '#,##0.000',
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1
        })

        date_format = workbook.add_format({
            **base_font,
            'num_format': 'mm/dd/yyyy',
            'align': 'left',
            'valign': 'vcenter'
        })

        alt_row_format = workbook.add_format({
            **base_font,
            'bg_color': '#F2F2F2',
            'align': 'left',
            'valign': 'vcenter'
        })

        return header_format, table_header_format, normal_format, float_format, float_format_bold, date_format, alt_row_format, kg_format, kg_format_bold

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

    def generate_header(self, sheet, sorted_records, formats, end_date):
        header_format, _, normal_format, _, _, _, _, _, _ = formats
        sheet.write(0, 0, sorted_records[0].owner_id.name or '', header_format)
        sheet.write(1, 0, 'BILLING DETAILS-HOLDING', header_format)
        
        # Convert start date to user timezone
        start_date = self._convert_to_user_timezone(sorted_records[0].start_time)
        
        # Use the provided end_date (already in user timezone)
        date_range = start_date.strftime('%B %d, %Y') + ' - ' + end_date.strftime('%B %d, %Y')
        sheet.write(2, 0, date_range, normal_format)

    def generate_table_header(self, sheet, row_index, formats):
        _, table_header_format, _, _, _, _, _, _, _ = formats
        table_headers = [
            'Date', 'Receiving Report No.', 'Withdrawal Report No.', 'Pallets Received',
            'Pallets Withdrawn', 'Balance in Pallets', 'Kilos Received', 'Kilos Withdrawn',
            'Balance in Kilos'
        ]
        for col_index, header_text in enumerate(table_headers):
            sheet.write(row_index, col_index, header_text, table_header_format)

    def generate_xlsx_report(self, workbook, data, records):
        formats = self._define_formats(workbook)
        header_format, table_header_format, normal_format, float_format, float_format_bold, date_format, alt_row_format, kg_format, kg_format_bold = formats

        records_by_owner = {}
        for record in records:
            owner_name = record.owner_id.name or 'Unknown'
            records_by_owner.setdefault(owner_name, []).append(record)

        for owner_name, owner_records in sorted(records_by_owner.items()):
            sheet = workbook.add_worksheet(owner_name[:31])  # Excel sheet name limit
            sheet.set_column(0, 11, 20)
            row_index = 5

            sorted_records = sorted(owner_records, key=lambda x: (x.start_time, x.create_date or datetime.datetime.min))
            
            # Convert dates to user timezone
            oldest_date_local = self._convert_to_user_timezone(sorted_records[0].start_time).date()
            
            # Use the latest transaction date as end date
            latest_date_local = self._convert_to_user_timezone(sorted_records[-1].start_time).date()
            
            # Create date list from oldest transaction to latest transaction
            date_list = [oldest_date_local + datetime.timedelta(days=x) for x in range((latest_date_local - oldest_date_local).days + 1)]

            records_by_date = {}
            for record in sorted_records:
                # Convert to user timezone then get date for grouping
                record_date_local = self._convert_to_user_timezone(record.start_time).date()
                records_by_date.setdefault(record_date_local, []).append(record)

            # Pass latest transaction datetime for header generation
            latest_datetime = datetime.datetime.combine(latest_date_local, datetime.time.max)
            self.generate_header(sheet, sorted_records, formats, latest_datetime)
            self.generate_table_header(sheet, row_index - 2, formats)

            summation = {
                'total_pallets_received': 0,
                'total_pallets_withdrawn': 0,
                'total_kilos_received': 0,
                'total_kilos_withdrawn': 0
            }

            # Initialize running balances
            current_pallet_balance = 0
            current_kilo_balance = 0

            # Calculate beginning balances from the very first chronological record
            beginning_kilos = 0
            beginning_pallets = 0
            
            if sorted_records:  # Make sure we have records
                # Get the very first record chronologically (already sorted by start_time)
                first_record = sorted_records[0]
                
                # Calculate beginning balance before first transaction
                # Formula: Beginning Balance = Current Balance - Received + Withdrawn
                
                # For kilos: work backwards from the balance after the transaction
                current_balance_kilos = first_record.total_balance_in_kilos or 0
                kilos_received = first_record.kilos_received or 0
                kilos_withdrawn = first_record.kilos_withdrawn or 0
                beginning_kilos = current_balance_kilos - kilos_received + kilos_withdrawn
                
                # For pallets: work backwards from the balance after the transaction  
                current_balance_pallets = first_record.total_balance_in_pallets or 0
                pallets_received = first_record.pallets_received or 0
                pallets_withdrawn = first_record.pallets_withdrawn or 0
                beginning_pallets = current_balance_pallets - pallets_received + pallets_withdrawn
                
            # Set initial running balances
            current_pallet_balance = beginning_pallets
            current_kilo_balance = beginning_kilos
            
            # Write beginning balances
            sheet.write(row_index-1, 8, beginning_kilos or 0, kg_format)
            sheet.write(row_index-1, 5, beginning_pallets or 0, float_format)
            
            for current_date in date_list:
                records_for_date = records_by_date.get(current_date, [])
                
                if records_for_date:
                    for i, line in enumerate(records_for_date):
                        is_alt = (row_index % 2 == 0)
                        base_format = alt_row_format if is_alt else normal_format
                        # Use the current_date directly since it's already in user timezone
                        sheet.write(row_index, 0, current_date, date_format)
                        rr_text = line.record_reference.name if line.record_reference and 'RR' in line.record_reference.name else ''
                        wr_text = line.record_reference.name if line.record_reference and 'WR' in line.record_reference.name else ''
                        sheet.write(row_index, 1, rr_text, base_format)
                        sheet.write(row_index, 2, wr_text, base_format)
                        sheet.write(row_index, 3, line.pallets_received or 0, float_format)
                        sheet.write(row_index, 4, line.pallets_withdrawn or 0, float_format)
                        sheet.write(row_index, 5, line.total_balance_in_pallets or 0, float_format)
                        sheet.write(row_index, 6, line.kilos_received or 0, kg_format)
                        sheet.write(row_index, 7, line.kilos_withdrawn or 0, kg_format)
                        sheet.write(row_index, 8, line.total_balance_in_kilos or 0, kg_format)

                        # Update running balances with the latest values from this record
                        current_pallet_balance = line.total_balance_in_pallets or 0
                        current_kilo_balance = line.total_balance_in_kilos or 0

                        summation['total_pallets_received'] += line.pallets_received or 0
                        summation['total_pallets_withdrawn'] += line.pallets_withdrawn or 0
                        summation['total_kilos_received'] += line.kilos_received or 0
                        summation['total_kilos_withdrawn'] += line.kilos_withdrawn or 0

                        row_index += 1
                else:
                    # Create empty rows for missing dates with last known balances
                    is_alt = (row_index % 2 == 0)
                    base_format = alt_row_format if is_alt else normal_format
                    # Use the current_date directly since it's already in user timezone
                    sheet.write(row_index, 0, current_date, date_format)
                    for col in range(1, 9):
                        if col in [3, 4, 6, 7]:  # Numeric columns for transactions (0 for missing dates)
                            sheet.write(row_index, col, 0, float_format)
                        elif col == 5:  # Balance in Pallets (use last known balance)
                            sheet.write(row_index, col, current_pallet_balance, float_format)
                        elif col == 8:  # Balance in Kilos (use last known balance)
                            sheet.write(row_index, col, current_kilo_balance, float_format)
                        else:  # Text columns (RR/WR numbers)
                            sheet.write(row_index, col, '-', base_format)
                    row_index += 1

            # Write totals
            sheet.write(row_index, 3, summation['total_pallets_received'], float_format_bold)
            sheet.write(row_index, 4, summation['total_pallets_withdrawn'], float_format_bold)
            sheet.write(row_index, 6, summation['total_kilos_received'], kg_format_bold)
            sheet.write(row_index, 7, summation['total_kilos_withdrawn'], kg_format_bold)

            sheet.write(row_index + 3, 0, "GUARANTEED", header_format)
