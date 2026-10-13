from odoo import models
import base64
import datetime
import io
import logging
import pytz
from xlsxwriter.utility import xl_rowcol_to_cell

_logger = logging.getLogger(__name__)


class DailyPalletUtilizationXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.daily_pallet_utilization_xlsx'
    _description = 'Daily Pallet Utilization XLSX'
    _inherit = 'report.report_xlsx.abstract'

    BUILDING_ORDER = ['MAIN', 'EXPANSION', 'ANNEX']

    def _now_pht(self):
        return datetime.datetime.now(pytz.timezone('Asia/Manila'))

    def _get_buildings(self, filter_ids=None):
        """Return [(label, building_id), ...] in BUILDING_ORDER.
        Uses raw SQL to read x_name->>'en_US' so we don't depend on the
        translation layer returning a clean string for the JSONB field.
        If filter_ids is given (list of building ids), restricts the result
        to those ids; empty/None means "all buildings".
        """
        params = []
        sql = """
            SELECT id, UPPER(TRIM(x_name->>'en_US')) AS label
            FROM x_warehouse_building
            WHERE x_active = TRUE
        """
        if filter_ids:
            sql += " AND id IN %s"
            params.append(tuple(filter_ids))
        self.env.cr.execute(sql, params)
        rows = self.env.cr.fetchall()
        by_label = {label: bid for bid, label in rows if label}
        ordered = []
        for label in self.BUILDING_ORDER:
            if label in by_label:
                ordered.append((label, by_label[label]))
        for label, bid in by_label.items():
            if label not in self.BUILDING_ORDER:
                ordered.append((label, bid))
        return ordered

    def _fetch_room_data(self, building_id):
        """Return [{'room', 'capacity', 'located', 'vacant', 'blockstock'}, ...]
        sorted by room number.

        located    = distinct pallets (x_studio_pallets) across P1/P2 slots per room
        vacant     = P1/P2 slots with no pallets, no occupant, not reserved
        blockstock = distinct pallets across aisle locations per room
        """
        Location = self.env['stock.location']

        leaf_locs = Location.search([
            ('active', '=', True),
            ('usage', '=', 'internal'),
            ('name', 'in', ['P1', 'P2']),
            ('x_studio_building', '=', building_id),
        ])

        aisle_locs = Location.search([
            ('active', '=', True),
            ('x_studio_is_an_aisle', '=', True),
            ('x_studio_building', '=', building_id),
        ])

        def room_of(loc):
            parts = loc.complete_name.split('/')
            seg = parts[2] if len(parts) >= 3 else ''
            return seg if seg.isdigit() else None

        rooms = {}

        for loc in leaf_locs:
            room = room_of(loc)
            if not room:
                continue
            d = rooms.setdefault(room, {'capacity': 0, 'pallet_ids': set(),
                                        'vacant': 0, 'blockstock_ids': set()})
            d['capacity'] += 1
            pallets = loc.x_studio_pallets
            if pallets:
                d['pallet_ids'].update(pallets.ids)
            elif not loc.x_studio_occupied_by and not loc.x_studio_is_reserved:
                d['vacant'] += 1

        for loc in aisle_locs:
            room = room_of(loc)
            if not room:
                continue
            d = rooms.setdefault(room, {'capacity': 0, 'pallet_ids': set(),
                                        'vacant': 0, 'blockstock_ids': set()})
            d['blockstock_ids'].update(loc.x_studio_pallets.ids)

        return [
            {
                'room':       room,
                'capacity':   d['capacity'],
                'located':    len(d['pallet_ids']),
                'vacant':     d['vacant'],
                'blockstock': len(d['blockstock_ids']),
            }
            for room, d in sorted(rooms.items(), key=lambda kv: int(kv[0]))
        ]

    def _build_formats(self, wb):
        f = {}
        base = {'font_name': 'Calibri', 'font_size': 11}

        f['title'] = wb.add_format({
            **base, 'bold': True, 'font_size': 20,
            'align': 'center', 'valign': 'vcenter',
            'font_color': '#1F4E79',
        })
        f['subtitle'] = wb.add_format({
            **base, 'bold': True, 'font_size': 12,
            'align': 'center', 'valign': 'vcenter',
            'font_color': '#1F4E79',
        })
        f['company'] = wb.add_format({
            **base, 'bold': True, 'font_size': 11,
            'align': 'center', 'valign': 'vcenter',
            'font_color': '#1F4E79', 'text_wrap': True,
        })

        f['bldg_banner'] = wb.add_format({
            **base, 'bold': True, 'font_size': 14,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F4E79', 'font_color': 'white',
            'border': 1,
        })
        f['col_header'] = wb.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F4E79', 'font_color': 'white',
            'border': 1, 'text_wrap': True,
        })

        f['cell_text'] = wb.add_format({
            **base, 'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['cell_text_bold'] = wb.add_format({
            **base, 'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['cell_num'] = wb.add_format({
            **base, 'num_format': '#,##0.00',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['cell_num_bold'] = wb.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })

        f['remarks_red'] = wb.add_format({
            **base, 'bold': True, 'font_color': '#C00000',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })

        f['total_label'] = wb.add_format({
            **base, 'bold': True,
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['total_num'] = wb.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['pct_label'] = wb.add_format({
            **base, 'bold': True,
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['pct_num'] = wb.add_format({
            **base, 'bold': True, 'num_format': '0.00%',
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['pct_total'] = wb.add_format({
            **base, 'bold': True, 'font_size': 12, 'num_format': '0.00%',
            'bg_color': '#1F4E79', 'font_color': '#FFFF00',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        f['total_pct_label'] = wb.add_format({
            **base, 'bold': True,
            'bg_color': '#FFEB9C', 'font_color': '#1F4E79',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })

        f['summary_label'] = wb.add_format({
            **base, 'bold': True,
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'left', 'valign': 'vcenter', 'border': 1, 'indent': 1,
        })
        f['summary_num'] = wb.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'bg_color': '#DDEBF7', 'font_color': '#1F4E79',
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        f['summary_pct'] = wb.add_format({
            **base, 'bold': True, 'num_format': '0.00%',
            'bg_color': '#DDEBF7', 'font_color': '#1F4E79',
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        f['summary_overall_label'] = wb.add_format({
            **base, 'bold': True,
            'bg_color': '#1F4E79', 'font_color': '#FFFF00',
            'align': 'left', 'valign': 'vcenter', 'border': 1, 'indent': 1,
        })
        f['summary_overall_num'] = wb.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'bg_color': '#1F4E79', 'font_color': '#FFFF00',
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        f['summary_overall_pct'] = wb.add_format({
            **base, 'bold': True, 'font_size': 14, 'num_format': '0.00%',
            'bg_color': '#1F4E79', 'font_color': '#FFFF00',
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })

        return f

    def _write_building_block(self, sheet, fmt, sheet_name, start_col,
                              building_label, room_rows,
                              header_row, data_start_row, max_data_rows):
        """Write one 7-col building block. Returns dict with cell refs to totals."""
        cols = {
            'room':       start_col + 0,
            'capacity':   start_col + 1,
            'vacant':     start_col + 2,
            'located':    start_col + 3,
            'blockstock': start_col + 4,
            'remarks':    start_col + 5,
            'status':     start_col + 6,
        }

        # Banner
        sheet.merge_range(header_row - 1, start_col, header_row - 1, start_col + 6,
                          f'{building_label} WAREHOUSE', fmt['bldg_banner'])
        sheet.set_row(header_row - 1, 28)

        # Column headers
        sheet.write(header_row, cols['room'],
                    'ROOM #',          fmt['col_header'])
        sheet.write(header_row, cols['capacity'],
                    'ROOM CAPACITY',   fmt['col_header'])
        sheet.write(header_row, cols['vacant'],
                    'VACANT',          fmt['col_header'])
        sheet.write(header_row, cols['located'],
                    'LOCATED PALLETS', fmt['col_header'])
        sheet.write(header_row, cols['blockstock'],
                    'BLOCKSTOCK',      fmt['col_header'])
        sheet.write(header_row, cols['remarks'],
                    'REMARKS',         fmt['col_header'])
        sheet.write(header_row, cols['status'],
                    'ROOM STATUS',     fmt['col_header'])
        sheet.set_row(header_row, 36)

        r = data_start_row
        first_data_row = r

        # Room rows
        for room in room_rows:
            sheet.write(r, cols['room'],       room['room'],
                        fmt['cell_text_bold'])
            sheet.write(r, cols['capacity'],
                        room['capacity'],   fmt['cell_num_bold'])
            sheet.write(r, cols['vacant'],
                        room['vacant'],     fmt['cell_num'])
            sheet.write(r, cols['located'],
                        room['located'],    fmt['cell_num'])
            sheet.write(r, cols['blockstock'],
                        room['blockstock'], fmt['cell_num'])
            sheet.write(r, cols['remarks'],    '',
                        fmt['remarks_red'])
            sheet.write_blank(r, cols['status'], None, fmt['cell_text'])
            sheet.data_validation(r, cols['status'], r, cols['status'], {
                'validate': 'list', 'source': ['ON', 'OFF', 'OVER FLOW'],
            })
            sheet.set_row(r, 18)
            r += 1

        last_data_row = r - 1

        # Pad to uniform height across all 3 blocks
        while r < data_start_row + max_data_rows:
            for c in range(start_col, start_col + 7):
                sheet.write(r, c, '', fmt['cell_text'])
            sheet.set_row(r, 18)
            r += 1

        # ── TOTAL row (Excel formulas)
        total_row = r
        def sum_range(
            col): return f'{xl_rowcol_to_cell(first_data_row, col)}:{xl_rowcol_to_cell(last_data_row, col)}'

        sheet.write(total_row, cols['room'], 'TOTAL:', fmt['total_label'])
        sheet.write_formula(total_row, cols['capacity'],
                            f'=SUM({sum_range(cols["capacity"])})', fmt['total_num'])
        sheet.write_formula(total_row, cols['vacant'],
                            f'=SUM({sum_range(cols["vacant"])})', fmt['total_num'])
        sheet.write_formula(total_row, cols['located'],
                            f'=SUM({sum_range(cols["located"])})', fmt['total_num'])
        sheet.write_formula(total_row, cols['blockstock'],
                            f'=SUM({sum_range(cols["blockstock"])})', fmt['total_num'])
        sheet.write(total_row, cols['remarks'], '', fmt['total_label'])
        sheet.write(total_row, cols['status'],  '', fmt['total_label'])
        sheet.set_row(total_row, 22)

        # ── PERCENTAGE row (Excel formulas referencing TOTAL row)
        pct_row = total_row + 1
        cap_cell = xl_rowcol_to_cell(total_row, cols['capacity'])
        vac_cell = xl_rowcol_to_cell(total_row, cols['vacant'])
        loc_cell = xl_rowcol_to_cell(total_row, cols['located'])
        blk_cell = xl_rowcol_to_cell(total_row, cols['blockstock'])

        sheet.write(pct_row, cols['room'], 'PERCENTAGE:', fmt['pct_label'])
        sheet.write(pct_row, cols['capacity'], '', fmt['pct_label'])
        sheet.write_formula(pct_row, cols['vacant'],
                            f'=IFERROR({vac_cell}/{cap_cell},0)', fmt['pct_num'])
        sheet.write_formula(pct_row, cols['located'],
                            f'=IFERROR({loc_cell}/{cap_cell},0)', fmt['pct_num'])
        sheet.write_formula(pct_row, cols['blockstock'],
                            f'=IFERROR({blk_cell}/{cap_cell},0)', fmt['pct_num'])
        sheet.write(pct_row, cols['remarks'],
                    'TOTAL PERCENTAGE', fmt['total_pct_label'])
        sheet.write_formula(pct_row, cols['status'],
                            f'=IFERROR(({loc_cell}+{blk_cell})/{cap_cell},0)', fmt['pct_total'])
        sheet.set_row(pct_row, 24)

        return {
            'sheet_name': sheet_name,
            'capacity_cell': cap_cell,
            'vacant_cell':   vac_cell,
            'located_cell':  loc_cell,
            'blockstock_cell': blk_cell,
            'utilization_cell': xl_rowcol_to_cell(pct_row, cols['status']),
        }

    def _write_summary_box(self, sheet, fmt, totals_by_bldg, sheet_name):
        """Top-right summary box (rows 0-4, cols 16-22) using Excel formulas
        that reference the per-building TOTAL cells on this same sheet."""
        # Build component lists for OVERALL formulas
        cap_cells = [t['capacity_cell'] for t in totals_by_bldg.values()]
        loc_cells = [t['located_cell'] for t in totals_by_bldg.values()]
        blk_cells = [t['blockstock_cell'] for t in totals_by_bldg.values()]

        overall_cap_formula = '=' + '+'.join(cap_cells) if cap_cells else '=0'
        overall_used_formula = '=' + \
            '+'.join(f'({l}+{b})' for l, b in zip(loc_cells,
                     blk_cells)) if loc_cells else '=0'

        r = 0
        for label in self.BUILDING_ORDER:
            if label not in totals_by_bldg:
                continue
            t = totals_by_bldg[label]
            sheet.merge_range(r, 16, r, 18, label, fmt['summary_label'])
            sheet.merge_range(r, 19, r, 20, '', fmt['summary_num'])
            sheet.write_formula(
                r, 19, f'={t["capacity_cell"]}', fmt['summary_num'])
            sheet.merge_range(r, 21, r, 22, '', fmt['summary_pct'])
            sheet.write_formula(
                r, 21, f'={t["utilization_cell"]}', fmt['summary_pct'])
            sheet.set_row(r, 18)
            r += 1

        # OVERALL CAPACITY row
        sheet.merge_range(r, 16, r, 18, 'OVERALL CAPACITY',
                          fmt['summary_label'])
        sheet.merge_range(r, 19, r, 20, '', fmt['summary_num'])
        sheet.write_formula(r, 19, overall_cap_formula, fmt['summary_num'])
        sheet.merge_range(r, 21, r, 22, '', fmt['summary_pct'])
        sheet.write_number(r, 21, 1.0, fmt['summary_pct'])
        sheet.set_row(r, 18)
        overall_cap_cell = xl_rowcol_to_cell(r, 19)
        r += 1

        # OVERALL UTILIZATION row
        sheet.merge_range(r, 16, r, 18, 'OVERALL UTILIZATION',
                          fmt['summary_overall_label'])
        sheet.merge_range(r, 19, r, 20, '', fmt['summary_overall_num'])
        sheet.write_formula(r, 19, overall_used_formula,
                            fmt['summary_overall_num'])
        sheet.merge_range(r, 21, r, 22, '', fmt['summary_overall_pct'])
        overall_used_cell = xl_rowcol_to_cell(r, 19)
        sheet.write_formula(r, 21,
                            f'=IFERROR({overall_used_cell}/{overall_cap_cell},0)',
                            fmt['summary_overall_pct'])
        sheet.set_row(r, 22)

    def _write_chart_sheet(self, wb, totals_by_bldg, main_sheet_name):
        """Chart sheet: pulls values via formula references to the main sheet."""
        sheet = wb.add_worksheet('Utilization Chart')
        sheet.hide_gridlines(2)

        title_fmt = wb.add_format({
            'font_name': 'Calibri', 'bold': True, 'font_size': 16,
            'font_color': '#1F4E79', 'align': 'center', 'valign': 'vcenter',
        })
        hdr_fmt = wb.add_format({
            'font_name': 'Calibri', 'bold': True, 'font_size': 11,
            'bg_color': '#1F4E79', 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        cell_fmt = wb.add_format({
            'font_name': 'Calibri', 'font_size': 11,
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'num_format': '#,##0.00',
        })
        pct_fmt = wb.add_format({
            'font_name': 'Calibri', 'font_size': 11,
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'num_format': '0.00%',
        })

        sheet.set_column(0, 0, 22)
        sheet.set_column(1, 3, 18)

        sheet.merge_range(
            0, 0, 0, 3, 'DAILY PALLET UTILIZATION GRAPH', title_fmt)
        sheet.set_row(0, 30)

        sheet.write(2, 0, 'BUILDING',     hdr_fmt)
        sheet.write(2, 1, 'CAPACITY',     hdr_fmt)
        sheet.write(2, 2, 'USED',         hdr_fmt)
        sheet.write(2, 3, 'UTILIZATION',  hdr_fmt)

        row = 3
        labels = []
        sn = f"'{main_sheet_name}'"
        for label in self.BUILDING_ORDER:
            if label not in totals_by_bldg:
                continue
            t = totals_by_bldg[label]
            sheet.write(row, 0, label, cell_fmt)
            sheet.write_formula(
                row, 1, f'={sn}!{t["capacity_cell"]}', cell_fmt)
            sheet.write_formula(
                row, 2, f'={sn}!{t["located_cell"]}+{sn}!{t["blockstock_cell"]}', cell_fmt)
            sheet.write_formula(
                row, 3, f'={sn}!{t["utilization_cell"]}', pct_fmt)
            labels.append(label)
            row += 1

        chart = wb.add_chart({'type': 'column'})
        first = 3
        last = first + len(labels) - 1
        chart.add_series({
            'name':       'Utilization',
            'categories': ['Utilization Chart', first, 0, last, 0],
            'values':     ['Utilization Chart', first, 3, last, 3],
            'fill':       {'color': '#ED7D31'},
            'border':     {'color': '#C65911'},
            'data_labels': {'value': True, 'num_format': '0.00%'},
        })
        chart.set_title({'name': 'Daily Pallet Utilization'})
        chart.set_x_axis({'name': 'Building'})
        chart.set_y_axis({'name': 'Utilization', 'num_format': '0.00%'})
        chart.set_legend({'position': 'none'})
        chart.set_size({'width': 720, 'height': 420})
        sheet.insert_chart(row + 2, 0, chart)

    def generate_xlsx_report(self, workbook, data, records):
        fmt = self._build_formats(workbook)

        sheet_name = 'Daily Pallet Utilization'
        sheet = workbook.add_worksheet(sheet_name)
        sheet.hide_gridlines(2)
        sheet.set_landscape()
        sheet.set_paper(9)
        sheet.fit_to_pages(1, 1)

        # Column widths: 3 blocks of 7 cols + spacers
        widths = [8, 13, 9, 14, 11, 14, 13]
        for block in (0, 8, 16):
            for i, w in enumerate(widths):
                sheet.set_column(block + i, block + i, w)
        sheet.set_column(7, 7, 2)
        sheet.set_column(15, 15, 2)

        # Header band (rows 0-4)
        for rr in range(5):
            sheet.set_row(rr, 22)

        now_pht = self._now_pht()
        year = now_pht.year
        day_no_zero = str(now_pht.day)
        date_str = now_pht.strftime(
            '%A, %B {DAY}, %Y').replace('{DAY}', day_no_zero)
        time_str = now_pht.strftime('%I:%M:%S %p').lstrip('0')

        company = self.env.company
        if company.logo:
            sheet.merge_range(0, 0, 4, 1, '', fmt['company'])
            sheet.insert_image(0, 0, 'logo.png', {
                'image_data': io.BytesIO(base64.b64decode(company.logo)),
                'x_offset': 5,
                'y_offset': 10,
                'x_scale': 0.8,
                'y_scale': 0.8,
                'object_position': 1,
            })
        else:
            sheet.merge_range(0, 0, 4, 1, company.name, fmt['company'])
        sheet.merge_range(
            0, 2, 1, 15, f'DAILY PALLET UTILIZATION {year}', fmt['title'])
        sheet.merge_range(2, 2, 3, 15, date_str, fmt['subtitle'])
        sheet.merge_range(4, 2, 4, 15, time_str, fmt['subtitle'])

        # Building filter from wizard (records is the wizard recordset)
        filter_ids = records.building_ids.ids if hasattr(
            records, 'building_ids') else None

        # Fetch per-building data
        buildings = self._get_buildings(filter_ids=filter_ids)
        block_data = []
        max_data_rows = 0
        for label, bid in buildings:
            rooms = self._fetch_room_data(bid)
            block_data.append((label, bid, rooms))
            if len(rooms) > max_data_rows:
                max_data_rows = len(rooms)
        # Defensive: ensure at least 1 padded row so blocks have a body
        if max_data_rows == 0:
            max_data_rows = 1

        banner_row = 6
        header_row = banner_row + 1
        data_start_row = header_row + 1
        block_starts = [0, 8, 16]

        totals_by_bldg = {}
        for i, (label, bid, rooms) in enumerate(block_data[:3]):
            t = self._write_building_block(
                sheet, fmt, sheet_name, block_starts[i], label,
                rooms, header_row, data_start_row, max_data_rows,
            )
            totals_by_bldg[label] = t

        # Summary box (top right) — formula-based
        self._write_summary_box(sheet, fmt, totals_by_bldg, sheet_name)

        sheet.freeze_panes(data_start_row, 0)

        # Chart sheet
        self._write_chart_sheet(workbook, totals_by_bldg, sheet_name)

        return True
