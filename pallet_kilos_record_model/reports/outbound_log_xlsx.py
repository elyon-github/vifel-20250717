# -*- coding: utf-8 -*-
"""Outbound Log XLSX — replica of the client reference workbook's
"Outbound data" sheet (dark-red headers, Arial Narrow, accounting number
formats, SUBTOTAL totals row ABOVE the headers, autofiltered table).

One row per stock.move.line of each validated WR. Design and column set
follow `Vifel Report References/98. Duopower ... .xlsx`, with the columns
the user removed/reworked taken into account (no Stock Code; Pallet Series
(OUT) is composed PSI + building short code + "/" + Pallet #).
"""
import re

import pytz

from odoo import fields, models

# Accounting-style number formats copied verbatim from the reference file
FMT_INT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
FMT_DEC = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
FMT_DATE = '[$-1009]d\\-mmm\\-yy;@'

HEADERS = [
    'OUTBOUND DATE',
    'Withdrawal Report No.',
    'DESTINATION',
    'QTY OUT',
    'KILOS OUT',
    'PALLET OUT',
    'PICKLIST',
    'ENCODED BY:',
    'GATEPASS',
    'PLATE #',
    'OUT REMARKS',
    'PALLET SERIES (OUT)',
    'ITEM DESCRIPTION (OUT)',
    'UOM (OUT)',
    'CONTAINER NUMBER (OUT)',
]
# 9pt on the last lookup-style columns, like the reference
SMALL_HEADERS = {'PALLET SERIES (OUT)', 'ITEM DESCRIPTION (OUT)',
                 'UOM (OUT)', 'CONTAINER NUMBER (OUT)'}

# Column widths taken from the reference sheet, re-mapped to the surviving
# columns (reference had a STOCK CODE column that was removed).
COL_WIDTHS = [17.9, 14.0, 20.0, 9.6, 14.3, 9.1, 9.6, 14.0,
              10.7, 14.3, 11.6, 15.3, 46.4, 11.7, 29.0]

FIRST_COL = 1          # column B (A left blank, like the reference)
HEADER_ROW = 2         # row 3 (0-based)
DATA_START = 3         # row 4 (0-based)


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
    def _row_values(self, picking, line, seen_packages):
        """Build one report row from a WR move line (user-approved map)."""
        # PALLET OUT: 1 on the first line of an unseen package that was
        # fully withdrawn (reserved_quantity_on_validation == 0) — mirrors
        # the PKR withdrawn-pallet rule.
        pallet_out = 0
        if line.package_id and line.package_id.id not in seen_packages:
            if not line.reserved_quantity_on_validation:
                pallet_out = 1
                seen_packages.add(line.package_id.id)

        # PALLET SERIES (OUT): PSI + building short code + "/" + Pallet #
        psi = line.x_studio_pallet_series_id or ''
        building = line.location_id.x_studio_building if line.location_id else False
        short = (building.x_studio_short_name or '') if building else ''
        pallet_no = line.package_id.name if line.package_id else ''
        series_out = '%s%s/%s' % (psi, short, pallet_no) if psi or pallet_no else ''

        # ITEM DESCRIPTION: never duplicate a trailing "(BRAND)" suffix
        desc = line.product_id.name or ''
        m = re.search(r'(\([^()]*\))\s*\1\s*$', desc)
        while m:
            desc = desc[:m.start()] + m.group(1)
            m = re.search(r'(\([^()]*\))\s*\1\s*$', desc)

        # UOM: the delivery UOM is the populated one on WR lines
        uom = ''
        if line.x_studio_quantity_uom_delivery:
            uom = line.x_studio_quantity_uom_delivery.name
        elif line.x_studio_quantity_uom:
            uom = line.x_studio_quantity_uom.name

        encoded_by = (picking.documentation_staff_id.name
                      or picking.create_uid.name or '')

        return [
            self._local_date(picking.date_done),          # OUTBOUND DATE
            picking.name,                                 # WR No.
            picking.x_studio_destination or '',           # DESTINATION
            line.x_studio_affected_2nd_uom or 0,          # QTY OUT
            line.quantity or 0,                           # KILOS OUT
            pallet_out,                                   # PALLET OUT
            picking.name,                                 # PICKLIST
            encoded_by,                                   # ENCODED BY:
            picking.x_studio_gate_pass or '',             # GATEPASS
            (line.x_studio_trucks_plate_
             or picking.x_studio_trucks_plate_ or ''),    # PLATE #
            picking.x_studio_record_remarks or '',        # OUT REMARKS
            series_out,                                   # PALLET SERIES (OUT)
            desc,                                         # ITEM DESCRIPTION (OUT)
            uom,                                          # UOM (OUT)
            line.x_studio_container_number or '',         # CONTAINER NUMBER (OUT)
        ]

    # ------------------------------------------------------------------
    def generate_xlsx_report(self, workbook, data, pickings):
        sheet = workbook.add_worksheet('Outbound data')
        sheet.hide_gridlines(0)

        # ---- formats -------------------------------------------------
        title_fmt = workbook.add_format({
            'font_name': 'Aptos Narrow', 'font_size': 18, 'bold': True})
        header_base = {
            'bg_color': '#C00000', 'font_color': '#FFFFFF',
            'font_name': 'Arial Narrow', 'align': 'center',
            'valign': 'vcenter', 'text_wrap': True, 'border': 1}
        header_fmt = workbook.add_format(dict(header_base, font_size=10))
        header_sm_fmt = workbook.add_format(dict(header_base, font_size=9))
        body = {'font_name': 'Arial Narrow', 'font_size': 10, 'align': 'center'}
        text_fmt = workbook.add_format(body)
        date_fmt = workbook.add_format(dict(body, num_format=FMT_DATE))
        int_fmt = workbook.add_format(dict(body, num_format=FMT_INT))
        dec_fmt = workbook.add_format(dict(body, num_format=FMT_DEC))
        total_fmt = workbook.add_format(dict(body, num_format=FMT_DEC, bold=True))

        # ---- layout --------------------------------------------------
        sheet.set_column(0, 0, 16.7)  # blank column A, as in the reference
        for i, width in enumerate(COL_WIDTHS):
            sheet.set_column(FIRST_COL + i, FIRST_COL + i, width)

        sheet.write(0, FIRST_COL, 'OUTBOUND LOG', title_fmt)

        # ---- data rows -----------------------------------------------
        col_of = {h: FIRST_COL + i for i, h in enumerate(HEADERS)}
        row = DATA_START
        for picking in pickings:
            seen_packages = set()
            for line in picking.move_line_ids:
                if not line.quantity and not line.package_id:
                    continue
                vals = self._row_values(picking, line, seen_packages)
                for i, val in enumerate(vals):
                    col = FIRST_COL + i
                    header = HEADERS[i]
                    if header == 'OUTBOUND DATE' and val:
                        sheet.write_datetime(row, col, val, date_fmt)
                    elif header in ('QTY OUT', 'PALLET OUT'):
                        sheet.write_number(row, col, val or 0, int_fmt)
                    elif header == 'KILOS OUT':
                        sheet.write_number(row, col, val or 0, dec_fmt)
                    else:
                        sheet.write(row, col, val, text_fmt)
                row += 1
        last_row = row - 1

        # ---- header row + autofilter table ---------------------------
        for i, header in enumerate(HEADERS):
            fmt = header_sm_fmt if header in SMALL_HEADERS else header_fmt
            sheet.write(HEADER_ROW, FIRST_COL + i, header, fmt)
        if last_row >= DATA_START:
            sheet.autofilter(HEADER_ROW, FIRST_COL, last_row,
                             FIRST_COL + len(HEADERS) - 1)

        # ---- SUBTOTAL totals row ABOVE the headers (row 2) -----------
        # SUBTOTAL(9, ...) responds to the autofilter, like the reference.
        def a1(col, r):
            letter = ''
            col += 1
            while col:
                col, rem = divmod(col - 1, 26)
                letter = chr(65 + rem) + letter
            return '%s%d' % (letter, r + 1)

        if last_row >= DATA_START:
            for header in ('QTY OUT', 'KILOS OUT', 'PALLET OUT'):
                col = col_of[header]
                sheet.write_formula(
                    1, col,
                    '=SUBTOTAL(9,%s:%s)' % (a1(col, DATA_START), a1(col, last_row)),
                    total_fmt)

        sheet.freeze_panes(DATA_START, 0)
