from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
import logging
from odoo.exceptions import ValidationError, UserError
import pytz
_logger = logging.getLogger(__name__)

class DailyInventoryXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.daily_inventory_report_xlsx'
    _description = 'Daily Inventory XLSX'
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
        
        # Header format (for company title and warehouse)
        header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#305496',
            'font_color': 'white',
            'border': 1,
            'text_wrap': True
        })
        
        # Table header format
        table_header_format = workbook.add_format({
            **base_font,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 12,
            'bg_color': '#305496',
            'font_color': 'white',
            'border': 1,
            'text_wrap': True
        })
        
        # Summary row format (totals row)
        summary_format = workbook.add_format({
            **base_font,
            'bold': True,
            'bg_color': '#FFF2CC',
            'font_color': 'black',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': kg_format_string,
            'text_wrap': True
        })
        
        # Normal text format
        normal_format = workbook.add_format({
            **base_font,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Date format
        date_format = workbook.add_format({
            **base_font,
            'num_format': 'mm/dd/yyyy',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Float format
        float_format = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'align': 'right',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Float format bold
        float_format_bold = workbook.add_format({
            **base_font,
            'num_format': kg_format_string,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1
        })
        
        # Percentage format
        pct_format = workbook.add_format({
            **base_font,
            'num_format': '0.00%',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Alternating row format
        alt_row_format = workbook.add_format({
            **base_font,
            'bg_color': '#F2F2F2',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        
        return header_format, table_header_format, summary_format, normal_format, date_format, float_format, float_format_bold, pct_format, alt_row_format

    def generate_header(self, sheet, warehouse, formats):
        header_format = formats[0]
        sheet.merge_range('A1:K1', 'DAILY VIFEL INVENTORY', header_format)
        sheet.merge_range('A2:K2', f"WAREHOUSE: {warehouse.upper()}", header_format)
        
        # Set row heights for better appearance
        sheet.set_row(0, 25)
        sheet.set_row(1, 25)

    def generate_summary(self, sheet, filled, formats):
        _, _, summary_format, _, _, _, float_format_bold, _, _ = formats
        totals = {
            'pallets_received': sum(x['pallets_received'] for x in filled),
            'pallets_withdrawn': sum(x['pallets_withdrawn'] for x in filled),
            'kilos_received': sum(x['kilos_received'] for x in filled),
            'kilos_withdrawn': sum(x['kilos_withdrawn'] for x in filled)
        }
        
        # write on row 3 (index 2)
        sheet.write(2, 0, 'TOTALS', summary_format)
        sheet.write(2, 1, totals['pallets_received'], summary_format)
        sheet.write(2, 2, totals['pallets_withdrawn'], summary_format)
        sheet.write(2, 3, '', summary_format)
        sheet.write(2, 4, totals['kilos_received'], summary_format)
        sheet.write(2, 5, totals['kilos_withdrawn'], summary_format)
        for c in range(6, 11): 
            sheet.write(2, c, '', summary_format)
        
        # Set row height for totals
        sheet.set_row(2, 25)

    def generate_table_header(self, sheet, row, formats):
        _, table_header_format, _, _, _, _, _, _, _ = formats
        headers = [
            'DATE', 'PALLETS RECEIVED', 'PALLETS WITHDRAWN', 'BALANCE IN PALLETS',
            'KILOS RECEIVED', 'KILOS WITHDRAWN', 'BALANCE IN KILOS',
            'AVERAGE PALLETS', 'CAPACITY RATE (PALLETS)',
            'AVERAGE KILOS', 'CAPACITY RATE (KILOS)'
        ]
        
        # Set row height for header
        sheet.set_row(row, 35)
        
        for col, h in enumerate(headers):
            sheet.write(row, col, h, table_header_format)

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

    def fill_missing_dates(self, arr):
        def to_dict(i):
            if isinstance(i, dict): 
                return i
            return {
                'start_time': i.start_time,
                'overall_pallets': i.overall_pallets,
                'overall_kilos': i.overall_kilos,
                'pallets_withdrawn': i.pallets_withdrawn,
                'pallets_received': i.pallets_received,
                'kilos_received': i.kilos_received,
                'kilos_withdrawn': i.kilos_withdrawn
            }
        
        arr2 = [to_dict(i) for i in arr]
        arr2.sort(key=lambda x: x['start_time'])
        
        # Convert all dates to user timezone (UTC+8)
        for x in arr2: 
            x['start_time'] = self._convert_to_user_timezone(x['start_time'])
        
        start = arr2[0]['start_time'].date()
        
        # Get today's date in user timezone
        user_tz = self.env.user.tz or 'Asia/Manila'
        user_timezone = pytz.timezone(user_tz)
        today = datetime.datetime.now(user_timezone).date()
        
        # Use today as end date instead of last transaction date
        end = today
        
        prevp = prevk = 0
        comp = []
        d = start
        
        while d <= end:
            found = False
            for itm in arr2:
                if itm['start_time'].date() == d:
                    if comp and comp[-1]['start_time'].date() == d:
                        # Aggregate data for the same date
                        for k in ['pallets_received','pallets_withdrawn','kilos_received','kilos_withdrawn']:
                            comp[-1][k] += itm[k]
                        comp[-1]['overall_pallets'] = itm['overall_pallets']
                        comp[-1]['overall_kilos'] = itm['overall_kilos']
                    else:
                        comp.append(itm.copy())
                    prevp, prevk = itm['overall_pallets'], itm['overall_kilos']
                    found = True
            
            if not found:
                # Create entry for missing date with user timezone
                # Use the last known balances for missing dates
                dtm = user_timezone.localize(datetime.datetime.combine(d, datetime.time(23, 59, 59)))
                
                comp.append({
                    'start_time': dtm,
                    'overall_pallets': prevp,
                    'overall_kilos': prevk,
                    'pallets_received': 0,
                    'pallets_withdrawn': 0,
                    'kilos_received': 0,
                    'kilos_withdrawn': 0
                })
            
            d += datetime.timedelta(days=1)
        
        return comp
    
    def generate_xlsx_report(self, workbook, data, lines):
        formats = self._define_formats(workbook)
        header_format, table_header_format, summary_format, normal_format, \
            date_format, float_format, float_format_bold, pct_format, alt_row_format = formats
    
        kg_format_string = self._get_kg_format_string()
    
        # Group by warehouse
        by_w = {}
        for ln in lines:
            by_w.setdefault(ln.warehouse.name, []).append(ln)
    
        for wh, recs in sorted(by_w.items()):
            sheet = workbook.add_worksheet(wh[:31])
    
            sheet.set_column(0, 0, 15)
            sheet.set_column(1, 2, 18)
            sheet.set_column(3, 3, 20)
            sheet.set_column(4, 5, 18)
            sheet.set_column(6, 6, 18)
            sheet.set_column(7, 7, 18)
            sheet.set_column(8, 8, 22)
            sheet.set_column(9, 9, 18)
            sheet.set_column(10, 10, 22)
            sheet.freeze_panes(4, 1)
    
            self.generate_header(sheet, wh, formats)
            filled = self.fill_missing_dates(recs)
            self.generate_summary(sheet, filled, formats)
            self.generate_table_header(sheet, 3, formats)
    
            # ✅ Move warehouse variable lookup OUTSIDE the row loop
            vars = self.env['x_inventory_static_var'].search([
                '&',
                ('x_studio_use_case', '=', 'XLSX Variables'),
                ('x_studio_warehouse.name', '=', wh)
            ])
            maxkg_rec = next((v for v in vars if v.x_name == 'Max Kilograms (KG)'), None)
            maxpl_rec = next((v for v in vars if v.x_name == 'Max Pallets'), None)
            maxpl_val = maxpl_rec.x_studio_float_value if maxpl_rec and maxpl_rec.x_studio_float_value else 0
            maxkg_val = maxkg_rec.x_studio_float_value if maxkg_rec and maxkg_rec.x_studio_float_value else 0
    
            # ✅ Compute true simple averages across ALL days (including zero-transaction days)
            #    Average = total received across all days / total number of days
            total_days = len(filled)
            total_pr = sum(x['pallets_received'] for x in filled)
            total_kr = sum(x['kilos_received'] for x in filled)
    
            avg_p = total_pr / total_days if total_days > 0 else 0
            avg_k = total_kr / total_days if total_days > 0 else 0
    
            # ✅ Capacity rate = current balance / max capacity (occupancy, not inflow rate)
            #    Computed per row using that day's closing balance
            for i, itm in enumerate(filled, 1):
                overall_pallets = itm['overall_pallets']
                overall_kilos   = itm['overall_kilos']
    
                cap_p = overall_pallets / maxpl_val if maxpl_val else 0
                cap_k = overall_kilos   / maxkg_val if maxkg_val else 0
    
                is_alt_row = (i % 2 == 0)
                r = 3 + i
    
                if is_alt_row:
                    alt_date_fmt = workbook.add_format({
                        'font_name': 'Calibri', 'font_size': 11,
                        'num_format': 'mm/dd/yyyy',
                        'align': 'left', 'valign': 'vcenter',
                        'border': 1, 'bg_color': '#F2F2F2'
                    })
                    alt_float_fmt = workbook.add_format({
                        'font_name': 'Calibri', 'font_size': 11,
                        'num_format': kg_format_string,   # ✅ dynamic, not hardcoded
                        'align': 'right', 'valign': 'vcenter',
                        'border': 1, 'bg_color': '#F2F2F2'
                    })
                    alt_pct_fmt = workbook.add_format({
                        'font_name': 'Calibri', 'font_size': 11,
                        'num_format': '0.00%',
                        'align': 'right', 'valign': 'vcenter',
                        'border': 1, 'bg_color': '#F2F2F2'
                    })
                    d_fmt  = alt_date_fmt
                    f_fmt  = alt_float_fmt
                    p_fmt  = alt_pct_fmt
                else:
                    d_fmt = date_format
                    f_fmt = float_format
                    p_fmt = pct_format
    
                c = 0
                sheet.write(r, c, itm['start_time'].replace(tzinfo=None), d_fmt);  c += 1
                sheet.write(r, c, itm['pallets_received'],  f_fmt);                c += 1
                sheet.write(r, c, itm['pallets_withdrawn'], f_fmt);                c += 1
                sheet.write(r, c, overall_pallets,          f_fmt);                c += 1
                sheet.write(r, c, itm['kilos_received'],    f_fmt);                c += 1
                sheet.write(r, c, itm['kilos_withdrawn'],   f_fmt);                c += 1
                sheet.write(r, c, overall_kilos,            f_fmt);                c += 1
                sheet.write(r, c, avg_p,  f_fmt);                                  c += 1  # ✅ same avg every row
                sheet.write(r, c, cap_p,  p_fmt);                                  c += 1  # ✅ per-row occupancy
                sheet.write(r, c, avg_k,  f_fmt);                                  c += 1
                sheet.write(r, c, cap_k,  p_fmt)
    
                sheet.set_row(r, 20)
    
        return True
