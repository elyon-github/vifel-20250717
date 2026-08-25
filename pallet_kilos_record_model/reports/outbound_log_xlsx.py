# -*- coding: utf-8 -*-
"""Outbound Log XLSX.

COLUMNS follow the client's canonical spec — the OUTBOUND sheet of
`Vifel Report References/Odoo Client Inventory Format.xlsx` (11 columns).
LOOK is the shared muted house style (see xlsx_log_style): brick-red for
outbound, sage-green for inbound, banded rows, numbers right-aligned, a
filter-aware totals strip above the header.

One row per stock.move.line of each validated WR.
"""
import re

import pytz

from odoo import models

from .xlsx_log_style import (FMT_DATE, FMT_DEC, FMT_INT, build_formats,
                             col_a1)

# Column set = FORMAT file "OUTBOUND" sheet, in order.
HEADERS = [
    'Date',
    'Transfer',
    'Transfer/Destination',
    'Pallet Series ID',
    'Product',
    'Container #',
    'Quantity (Withdraw)',
    'Quantity',
    'Transfer/Gate Pass',
    "Transfer/Truck's Plate #",
    'REMARKS',
]
KEY_HEADERS = {'Transfer', 'Pallet Series ID'}
DATE_HEADERS = {'Date'}
INT_HEADERS = {'Quantity (Withdraw)'}
DEC_HEADERS = {'Quantity'}
# Every numeric column is totalled in the strip above the header.
TOTAL_HEADERS = ('Quantity (Withdraw)', 'Quantity')

COL_WIDTHS = [13.0, 15.0, 22.0, 16.0, 44.0, 20.0, 14.0, 13.0, 14.0, 15.0, 26.0]

FIRST_COL = 1          # column B (A left narrow as a margin)
TITLE_ROW = 0
SUB_ROW = 1
TOTAL_ROW = 2
HEADER_ROW = 3
DATA_START = 4


class OutboundLogXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.outbound_log_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Outbound Log XLSX'

    # ------------------------------------------------------------------
    def _local_date(self, dt):
        """UTC datetime -> naive date in the user's timezone (Manila).

        date_done is stored in UTC; a withdrawal validated late in the day
        would otherwise print on the wrong calendar date.
        """
        if not dt:
            return None
        tz = pytz.timezone(self.env.user.tz or 'Asia/Manila')
        return pytz.utc.localize(dt).astimezone(tz).date()

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_product_name(name):
        """Drop an accidental duplicated trailing "(BRAND)(BRAND)" suffix."""
        desc = name or ''
        m = re.search(r'(\([^()]*\))\s*\1\s*$', desc)
        while m:
            desc = desc[:m.start()] + m.group(1)
            m = re.search(r'(\([^()]*\))\s*\1\s*$', desc)
        return desc

    # ------------------------------------------------------------------
    def _row_values(self, picking, line):
        """Build one report row (FORMAT OUTBOUND column order) from a WR line."""
        return [
            self._local_date(picking.date_done),          # Date
            picking.name,                                 # Transfer (WR No.)
            picking.x_studio_destination or '',           # Transfer/Destination
            line.x_studio_pallet_series_id or '',         # Pallet Series ID
            self._clean_product_name(line.product_id.name),   # Product
            line.x_studio_container_number or '',         # Container #
            line.x_studio_affected_2nd_uom or 0,          # Quantity (Withdraw)
            line.quantity or 0,                           # Quantity (KG)
            picking.x_studio_gate_pass or '',             # Transfer/Gate Pass
            (line.x_studio_trucks_plate_
             or picking.x_studio_trucks_plate_ or ''),    # Truck's Plate #
            picking.x_studio_record_remarks or '',        # REMARKS
        ]

    # ------------------------------------------------------------------
    def generate_xlsx_report(self, workbook, data, pickings):
        sheet = workbook.add_worksheet('Outbound')
        sheet.hide_gridlines(2)
        f = build_formats(workbook, 'red')

        # ---- layout --------------------------------------------------
        sheet.set_column(0, 0, 2.5)   # slim margin column
        for i, width in enumerate(COL_WIDTHS):
            sheet.set_column(FIRST_COL + i, FIRST_COL + i, width)
        sheet.set_row(TITLE_ROW, 24)
        sheet.set_row(HEADER_ROW, 30)

        partner_label = (data or {}).get('partner_label') or 'All Clients'
        sheet.write(TITLE_ROW, FIRST_COL, 'OUTBOUND LOG', f['title'])

        # ---- data rows -----------------------------------------------
        col_of = {h: FIRST_COL + i for i, h in enumerate(HEADERS)}
        row = DATA_START
        for picking in pickings:
            for line in picking.move_line_ids:
                if not line.quantity and not line.package_id:
                    continue
                band = (row - DATA_START) % 2      # 0 plain, 1 banded
                vals = self._row_values(picking, line)
                for i, val in enumerate(vals):
                    col = FIRST_COL + i
                    header = HEADERS[i]
                    if header in DATE_HEADERS:
                        if val:
                            sheet.write_datetime(row, col, val, f['date'][band])
                        else:
                            sheet.write_blank(row, col, None, f['date'][band])
                    elif header in INT_HEADERS:
                        sheet.write_number(row, col, val or 0, f['num_int'][band])
                    elif header in DEC_HEADERS:
                        sheet.write_number(row, col, val or 0, f['num_dec'][band])
                    elif header in KEY_HEADERS:
                        sheet.write(row, col, val, f['key'][band])
                    else:
                        sheet.write(row, col, val, f['text'][band])
                row += 1
        last_row = row - 1
        n_rows = last_row - DATA_START + 1

        # ---- header + autofilter -------------------------------------
        for i, header in enumerate(HEADERS):
            sheet.write(HEADER_ROW, FIRST_COL + i, header, f['header'])
        if n_rows > 0:
            sheet.autofilter(HEADER_ROW, FIRST_COL, last_row,
                             FIRST_COL + len(HEADERS) - 1)

        # ---- subtitle + totals strip ---------------------------------
        rng = (data or {}).get('range_label') or 'All history'
        sheet.write(SUB_ROW, FIRST_COL,
                    '%s  ·  %s  ·  %d withdrawal line(s)'
                    % (partner_label, rng, n_rows), f['subtitle'])

        for i, header in enumerate(HEADERS):
            col = FIRST_COL + i
            if header in TOTAL_HEADERS and n_rows > 0:
                fmt = f['total_int'] if header in INT_HEADERS else f['total_dec']
                sheet.write_formula(
                    TOTAL_ROW, col,
                    '=SUBTOTAL(9,%s:%s)' % (col_a1(col, DATA_START),
                                            col_a1(col, last_row)),
                    fmt)
            elif i == 0:
                sheet.write(TOTAL_ROW, col, 'TOTAL', f['total_label'])
            else:
                sheet.write_blank(TOTAL_ROW, col, None, f['total_blank'])

        # keep the date + document visible while scrolling right
        sheet.freeze_panes(DATA_START, FIRST_COL + 2)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(HEADER_ROW)
