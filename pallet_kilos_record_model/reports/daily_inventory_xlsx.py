from odoo import models
import datetime
from xlsxwriter.workbook import Workbook
import logging
from odoo.exceptions import ValidationError, UserError
import pytz
_logger = logging.getLogger(__name__)

class DailyInventoryXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.daily_inventory_report_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def _define_formats(self, workbook):
        # Company title format
        company_fmt = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 14, 'bg_color': '#1565C0', 'font_color': 'white',
            'border': 1, 'text_wrap': True
        })
        # Table header format
        table_hdr = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12, 'bg_color': '#1565C0', 'font_color': 'white',
            'border': 1, 'border_color': '#90CAF9', 'text_wrap': True
        })
        # Summary row format
        summary_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#FFC107', 'font_color': 'black',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#FF8F00',
            'num_format': '#,##0.00', 'text_wrap': True
        })
        # Normal
        normal_fmt = workbook.add_format({ 'align': 'left', 'valign': 'vcenter', 'border': 1 })
        date_fmt = workbook.add_format({ 'num_format': 'yyyy-mm-dd', 'border': 1, 'valign': 'vcenter' })
        float_fmt = workbook.add_format({ 'num_format': '#,##0.00', 'border': 1, 'valign': 'vcenter' })
        float_bold = workbook.add_format({ 'num_format': '#,##0.00', 'border': 1, 'bold': True, 'valign': 'vcenter' })
        pct_fmt = workbook.add_format({ 'num_format': '0.00%', 'border': 1, 'valign': 'vcenter' })
        return company_fmt, table_hdr, summary_fmt, normal_fmt, date_fmt, float_fmt, float_bold, pct_fmt

    def generate_header(self, sheet, warehouse, formats):
        company_fmt = formats[0]
        sheet.merge_range('A1:K1', 'DAILY VIFEL INVENTORY', company_fmt)
        sheet.merge_range('A2:K2', f"WAREHOUSE: {warehouse.upper()}", company_fmt)

    def generate_summary(self, sheet, filled, formats):
        _, _, summary_fmt, _, _, _, float_bold, _ = formats
        totals = {
            'pallets_received': sum(x['pallets_received'] for x in filled),
            'pallets_withdrawn': sum(x['pallets_withdrawn'] for x in filled),
            'kilos_received': sum(x['kilos_received'] for x in filled),
            'kilos_withdrawn': sum(x['kilos_withdrawn'] for x in filled)
        }
        # write on row 3 (index 2)
        sheet.write(2, 0, 'TOTALS', summary_fmt)
        sheet.write(2, 1, totals['pallets_received'], summary_fmt)
        sheet.write(2, 2, totals['pallets_withdrawn'], summary_fmt)
        sheet.write(2, 3, '', summary_fmt)
        sheet.write(2, 4, totals['kilos_received'], summary_fmt)
        sheet.write(2, 5, totals['kilos_withdrawn'], summary_fmt)
        for c in range(6, 11): sheet.write(2, c, '', summary_fmt)
        # increase height
        sheet.set_row(2, 20)

    def generate_table_header(self, sheet, row, formats):
        _, table_hdr, _, _, _, _, _, _ = formats
        headers = [
            'DATE','PALLETS RECEIVED','PALLETS WITHDRAWN','BALANCE IN PALLETS',
            'KILOS RECEIVED','KILOS WITHDRAWN','BALANCE IN KILOS',
            'AVERAGE PALLETS','CAPACITY RATE (PALLETS)',
            'AVERAGE KILOS','CAPACITY RATE (KILOS)'
        ]
        sheet.set_row(row, 30)
        for col, h in enumerate(headers):
            sheet.write(row, col, h, table_hdr)

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
        end = arr2[-1]['start_time'].date()
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
                user_tz = self.env.user.tz or 'Asia/Manila'
                user_timezone = pytz.timezone(user_tz)
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
        company_fmt, table_hdr, summary_fmt, normal_fmt, date_fmt, float_fmt, float_bold, pct_fmt = self._define_formats(workbook)
        
        # group by warehouse
        by_w = {}
        for ln in lines: 
            by_w.setdefault(ln.warehouse.name, []).append(ln)
        
        for wh, recs in by_w.items():
            sheet = workbook.add_worksheet(wh[:31])
            sheet.set_column(0, 10, 20)
            sheet.freeze_panes(4, 1)
            
            self.generate_header(sheet, wh, (company_fmt, table_hdr, summary_fmt, normal_fmt, date_fmt, float_fmt, float_bold, pct_fmt))
            filled = self.fill_missing_dates(recs)
            self.generate_summary(sheet, filled, (company_fmt, table_hdr, summary_fmt, normal_fmt, date_fmt, float_fmt, float_bold, pct_fmt))
            self.generate_table_header(sheet, 3, (company_fmt, table_hdr, summary_fmt, normal_fmt, date_fmt, float_fmt, float_bold, pct_fmt))
            
            # write data
            tot_pr = tot_pw = tot_kr = tot_kw = 0
            for i, itm in enumerate(filled, 1):
                tot_pr += itm['pallets_received']
                tot_pw += itm['pallets_withdrawn']
                tot_kr += itm['kilos_received'] 
                tot_kw += itm['kilos_withdrawn']
                avg_p = tot_pr / i
                avg_k = tot_kr / i
                
                vars = self.env['x_inventory_static_var'].search([
                    '&', 
                    ('x_studio_use_case', '=', 'XLSX Variables'),
                    ('x_studio_warehouse.name', '=', wh)
                ])
                
                maxkg = next((v for v in vars if v.x_name == 'Max Kilograms (KG)'), None)
                maxpl = next((v for v in vars if v.x_name == 'Max Pallets'), None)
                
                cap_p = avg_p / maxpl.x_studio_float_value if maxpl and maxpl.x_studio_float_value else 0
                cap_k = avg_k / maxkg.x_studio_float_value if maxkg and maxkg.x_studio_float_value else 0
                
                r = 3 + i
                c = 0
                sheet.write(r, c, itm['start_time'].replace(tzinfo=None), date_fmt); c += 1
                sheet.write(r, c, itm['pallets_received'], float_fmt); c += 1
                sheet.write(r, c, itm['pallets_withdrawn'], float_fmt); c += 1
                sheet.write(r, c, itm['overall_pallets'], float_fmt); c += 1
                sheet.write(r, c, itm['kilos_received'], float_fmt); c += 1
                sheet.write(r, c, itm['kilos_withdrawn'], float_fmt); c += 1
                sheet.write(r, c, itm['overall_kilos'], float_fmt); c += 1
                sheet.write(r, c, avg_p, float_fmt); c += 1
                sheet.write(r, c, cap_p, pct_fmt); c += 1
                sheet.write(r, c, avg_k, float_fmt); c += 1
                sheet.write(r, c, cap_k, pct_fmt)
        
        return True