# -*- coding: utf-8 -*-
"""Inbound Log XLSX.

COLUMNS follow the client's canonical spec — the INBOUND sheet of
`Vifel Report References/Odoo Client Inventory Format.xlsx` — plus a leading
"Inventory Status" column (INV / ZERO) taken from the Duopower reference, so
rows can be filtered by whether the pallet still holds stock.
LOOK is the shared muted house style (see xlsx_log_style), sage-green here.

ONE ROW PER PHYSICAL PALLET (keyed PSI + Pallet #), not per move line: a
single RR routinely has several lines per pallet (mixed products, and up to
18 lots on one pallet in this data), and a pallet is received again on every
return. Receiving quantities are summed across a pallet's lines, and returns
fold in through the LIVE available balance instead of appearing as extra rows.

THE ROWS ARE DRIVEN BY THE UNION OF RECEIPTS *AND* LIVE STOCK — this is the
whole correctness argument of the report, so do not "simplify" it back to
receipts only. An earlier version built rows from receiving lines alone and
therefore could not see stock that has no receiving document for the client:
opening-balance imports, and pallets whose only receipts belong to a previous
client (pallet numbers are reused across clients). Measured on 2026-07-25 that
hid 31.6% of 168 ENTERPRISES' stock and 38.9% of ALPHA ALLEANZA's. Driving
from live quants as well makes AVAILABLE tally with Normal Inventory Overview
by construction: every quant maps to exactly one row.

Scope is the quant's OWNER (owner_id), not the picking's partner_id — those
are different fields and they disagree in real data; Inventory Overview uses
the owner.

The key deliberately keeps PSI *and* Pallet # together: the same PSI can be
re-used by an encoding slip on a different RR with a different pallet, and
those are genuinely different physical pallets that must stay on their own
rows. Lot is deliberately NOT in the key — a pallet legitimately carries many
lots, and adding it would split one pallet into a row per batch.

AVAILABLE QTY / AVAILABLE KGS = as of now, from live stock.quant
(quantity = KG, x_studio_2nd_uom = Qty). 0 once the pallet is emptied.
Inventory Status = INV when AVAILABLE KGS > 0, else ZERO.

A pallet with no receipt of its own (opening balance) takes its descriptive
fields from the quant, is marked OPENING BALANCE in the Transfer column, and
reports its CURRENT balance as the received quantity — the opening position.
"""
import datetime

import pytz

from odoo import models

from .outbound_log_xlsx import OutboundLogXlsx
from .xlsx_log_style import (FMT_DATE, FMT_DEC, FMT_INT, build_button_formats,
                             build_formats, col_a1, write_button_bar)

# Stock the report must agree with, i.e. the domain of the Studio action
# "Normal Inventory Overview" (#336) — the screen the user reconciles against.
# It is NOT location_id.usage = 'internal': the action excludes only the
# Vendors/Customers locations, and filtering on 'internal' instead silently
# drops stock the Overview counts.
#
# Duplicated rather than imported: multiple_relocation.models
# .res_partner_client_buttons holds the same domain (QUANT_BASE_DOMAIN +
# NORMAL_BF_DOMAIN) but that module DEPENDS on this one, so importing it here
# would be circular. Keep the two in step.
EXCLUDED_LOCATION_IDS = [5, 4]          # Partners/Customers, Partners/Vendors
OVERVIEW_DOMAIN = [
    ('location_id', 'not in', EXCLUDED_LOCATION_IDS),
    ('quantity', '>', 0),
    '|',
    ('x_studio_record_reference.x_studio_is_a_blast_freezer', '!=', True),
    ('location_id.x_studio_is_a_blast_freezer', '!=', True),
]

OPENING_BALANCE_LABEL = 'OPENING BALANCE'

# Column set = leading Inventory Status + FORMAT file "INBOUND" sheet.
HEADERS = [
    'Inventory Status',
    'Date',
    'Transfer',
    'Transfer/Source',
    "Transfer's Plate #",
    'Gate Pass',
    'Pallet Series ID',
    'Product',
    'Container #',
    'Prod. Date',
    'Exp. Date',
    'Quantity (Receiving)',
    'Quantity',
    'AVAILABLE QTY',
    'AVAILABLE KGS',
    'To',
    'REMARKS',
]
STATUS_HEADER = 'Inventory Status'
KEY_HEADERS = {'Transfer', 'Pallet Series ID'}
DATE_HEADERS = {'Date', 'Prod. Date', 'Exp. Date'}
INT_HEADERS = {'Quantity (Receiving)', 'AVAILABLE QTY'}
DEC_HEADERS = {'Quantity', 'AVAILABLE KGS'}
TOTAL_HEADERS = ('Quantity (Receiving)', 'Quantity', 'AVAILABLE QTY',
                 'AVAILABLE KGS')

COL_WIDTHS = [15.0, 13.0, 15.0, 20.0, 14.0, 13.0, 16.0, 44.0, 20.0,
              12.0, 12.0, 15.0, 13.0, 14.0, 14.0, 24.0, 22.0]

FIRST_COL = 1
TITLE_ROW = 0
SUB_ROW = 1
BUTTON_ROW = 2
TOTAL_ROW = 3
HEADER_ROW = 4
DATA_START = 5

_QTY_EPS = 0.0005

# The three views. Excel cannot give us real slicer buttons from xlsxwriter,
# so each view is its own already-filtered sheet and the button bar links
# between them — one click, same as a slicer, and it still works in
# LibreOffice / Google Sheets.
VIEWS = [
    ('ALL PALLETS', 'Inbound', None),
    ('INV (with stock)', 'INV', 'INV'),
    ('ZERO (emptied)', 'ZERO', 'ZERO'),
]


class InboundLogXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.inbound_log_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Inbound Log XLSX'

    # ------------------------------------------------------------------
    def _local_date(self, dt):
        """UTC datetime -> naive date in the user's timezone (Manila)."""
        if not dt:
            return None
        tz = pytz.timezone(self.env.user.tz or 'Asia/Manila')
        return pytz.utc.localize(dt).astimezone(tz).date()

    # ------------------------------------------------------------------
    def _pallet_key(self, line):
        """Physical-pallet identity: PSI + Pallet # (package)."""
        return (line.x_studio_pallet_series_id or '',
                line.package_id.id or line.result_package_id.id or False)

    def _quant_key(self, quant):
        """Same identity, read off a quant instead of a move line."""
        return (quant.x_studio_pallet_series_id or '',
                quant.package_id.id or False)

    def _receiving_lines(self, owner_ids):
        """Done, non-BF, non-return, non-void receiving lines of these owners.

        Scoped on the move line's OWNER, not the picking's partner: a pallet
        number is reused across clients, so the receipts carrying a given
        package can belong to a previous client entirely.
        """
        lines = self.env['stock.move.line'].search([
            ('state', '=', 'done'),
            ('owner_id', 'in', owner_ids),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('picking_id.picking_type_id.is_blast_freeze_operation', '!=', True),
            ('picking_id.return_id', '=', False),
        ])
        # x_studio_voided is a Studio field — filter in Python so this module
        # never assumes the column exists in a bare database.
        return lines.filtered(
            lambda l: not getattr(l.picking_id, 'x_studio_voided', False))

    def _live_quants(self, owner_ids):
        """Exactly the stock Normal Inventory Overview shows for these owners."""
        return self.env['stock.quant'].search(
            [('owner_id', 'in', owner_ids)] + OVERVIEW_DOMAIN)

    def _available_by_pallet(self, quants):
        """Live on-hand per pallet: {(PSI, package_id): {kg, qty, loc}}."""
        avail = {}
        for q in quants:
            key = self._quant_key(q)
            a = avail.get(key)
            if a is None:
                a = avail[key] = {'kg': 0.0, 'qty': 0.0, 'loc': '', 'quant': q}
            a['kg'] += q.quantity or 0.0
            a['qty'] += q.x_studio_2nd_uom or 0.0
            if not a['loc'] and q.location_id:
                a['loc'] = q.location_id.complete_name or ''
        return avail

    def _collect_pallets(self, owner_ids, avail):
        """One entry per physical pallet, from receipts UNION live stock.

        Receipts alone would miss every pallet the client holds without a
        receiving document of its own (see the module docstring); live stock
        alone would lose the emptied pallets that make up the ZERO view. The
        union gives both, and makes the AVAILABLE totals agree with Normal
        Inventory Overview exactly.
        """
        groups = {}

        # (A) documented receipts — representative fields from the EARLIEST
        #     line, quantities summed over all of the pallet's lines
        for line in self._receiving_lines(owner_ids):
            if not line.quantity and not line.package_id:
                continue
            picking = line.picking_id
            key = self._pallet_key(line)
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    'key': key, 'picking': picking, 'line': line,
                    'date': picking.date_done, 'quant': False,
                    'recv_qty': 0.0, 'recv_kg': 0.0, 'opening': False,
                }
            elif picking.date_done and (not g['date'] or picking.date_done < g['date']):
                g['picking'] = picking
                g['line'] = line
                g['date'] = picking.date_done
            g['recv_qty'] += line.x_studio_2nd_uom or 0.0
            g['recv_kg'] += line.quantity or 0.0

        # (B) live stock with no receipt of its own — opening balance. Its
        #     descriptive fields come off the quant, and its CURRENT balance
        #     stands in as the received quantity (the opening position).
        for key, a in avail.items():
            if key in groups:
                continue
            quant = a['quant']
            groups[key] = {
                'key': key, 'picking': False, 'line': False,
                'date': quant.in_date, 'quant': quant,
                'recv_qty': a['qty'], 'recv_kg': a['kg'], 'opening': True,
            }

        return sorted(
            groups.values(),
            key=lambda g: (g['date'] or datetime.datetime.max,
                           (g['picking'].name if g['picking'] else ''),
                           g['key'][0]))

    # ------------------------------------------------------------------
    def _row_values(self, g, avail):
        a = avail.get(g['key'], {})
        avail_kg = a.get('kg', 0.0)
        avail_qty = a.get('qty', 0.0)
        status = 'INV' if avail_kg > _QTY_EPS else 'ZERO'

        if g['opening']:
            # No receipt of its own: everything descriptive comes off the
            # quant, which carries the same x_studio_* fields the receiving
            # line would have supplied.
            q = g['quant']
            return [
                status,                                        # Inventory Status
                self._local_date(q.in_date),                   # Date
                OPENING_BALANCE_LABEL,                         # Transfer
                q.x_studio_source or '',                       # Transfer/Source
                q.x_studio_truck_number or '',                 # Truck's Plate #
                q.x_studio_gate_pass or '',                    # Gate Pass
                q.x_studio_pallet_series_id or '',             # Pallet Series ID
                OutboundLogXlsx._clean_product_name(q.product_id.name),   # Product
                q.x_studio_container_number or '',             # Container #
                q.x_studio_production_date or None,            # Prod. Date
                q.x_studio_expiration_date or None,            # Exp. Date
                g['recv_qty'] or 0,                            # Quantity (Receiving)
                g['recv_kg'] or 0,                             # Quantity (KG)
                avail_qty or 0,                                # AVAILABLE QTY
                avail_kg or 0,                                 # AVAILABLE KGS
                a.get('loc') or (q.location_id.complete_name
                                 if q.location_id else ''),    # To
                '',                                            # REMARKS
            ]

        picking, line = g['picking'], g['line']
        to_loc = a.get('loc') or (line.location_dest_id.complete_name
                                  if line.location_dest_id else '')
        plate = line.x_studio_trucks_plate_ or picking.x_studio_trucks_plate_ or ''
        return [
            status,                                            # Inventory Status
            self._local_date(picking.date_done),               # Date
            picking.name,                                      # Transfer (RR No.)
            picking.x_studio_source or '',                     # Transfer/Source
            plate,                                             # Truck's Plate #
            picking.x_studio_gate_pass or '',                  # Gate Pass
            line.x_studio_pallet_series_id or '',              # Pallet Series ID
            OutboundLogXlsx._clean_product_name(line.product_id.name),  # Product
            line.x_studio_container_number or '',              # Container #
            line.x_studio_production_date or None,             # Prod. Date
            line.x_studio_expiration_date or None,             # Exp. Date
            g['recv_qty'] or 0,                                # Quantity (Receiving)
            g['recv_kg'] or 0,                                 # Quantity (KG)
            avail_qty or 0,                                    # AVAILABLE QTY
            avail_kg or 0,                                     # AVAILABLE KGS
            to_loc,                                            # To
            picking.x_studio_record_remarks or '',             # REMARKS
        ]

    # ------------------------------------------------------------------
    def _write_view(self, workbook, sheet_name, rows, counts, f, bf,
                    active_label, partner_label):
        """Render one already-filtered view of the pallet rows."""
        sheet = workbook.add_worksheet(sheet_name)
        sheet.hide_gridlines(2)

        sheet.set_column(0, 0, 2.5)
        for i, width in enumerate(COL_WIDTHS):
            sheet.set_column(FIRST_COL + i, FIRST_COL + i, width)
        sheet.set_row(TITLE_ROW, 24)
        sheet.set_row(BUTTON_ROW, 20)
        sheet.set_row(HEADER_ROW, 30)

        sheet.write(TITLE_ROW, FIRST_COL, 'INBOUND LOG', f['title'])
        n_inv, n_zero = counts
        sheet.write(SUB_ROW, FIRST_COL,
                    '%s  ·  All history · balance as of now  ·  '
                    '%d INV (with stock)   %d ZERO (emptied)'
                    % (partner_label, n_inv, n_zero), f['subtitle'])

        # one-click view switcher
        write_button_bar(sheet, BUTTON_ROW, FIRST_COL,
                         [(label, target) for label, target, _ in VIEWS],
                         bf, active_label)

        # ---- data ----------------------------------------------------
        row = DATA_START
        for vals in rows:
            band = (row - DATA_START) % 2
            for i, val in enumerate(vals):
                col = FIRST_COL + i
                header = HEADERS[i]
                if header == STATUS_HEADER:
                    sheet.write(row, col, val, f['status'][val][band])
                elif header in DATE_HEADERS:
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
                    sheet.write(row, col, val if val is not None else '',
                                f['text'][band])
            row += 1
        last_row = row - 1
        n_rows = last_row - DATA_START + 1

        for i, header in enumerate(HEADERS):
            sheet.write(HEADER_ROW, FIRST_COL + i, header, f['header'])
        if n_rows > 0:
            sheet.autofilter(HEADER_ROW, FIRST_COL, last_row,
                             FIRST_COL + len(HEADERS) - 1)

        # totals strip — SUBTOTAL so it follows any further filtering
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

        sheet.freeze_panes(DATA_START, FIRST_COL + 3)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(HEADER_ROW)

    # ------------------------------------------------------------------
    def _owner_ids(self, data, pickings):
        """Owners to report on.

        The wizard passes them explicitly, because a client whose stock is
        entirely opening balance has no pickings at all and would otherwise be
        invisible. Falling back to the pickings keeps the report usable when
        it is printed straight off a picking selection.
        """
        owner_ids = list((data or {}).get('owner_ids') or [])
        if owner_ids:
            return owner_ids
        owners = pickings.mapped('move_line_ids.owner_id').ids
        return owners or pickings.mapped('partner_id').ids

    def generate_xlsx_report(self, workbook, data, pickings):
        f = build_formats(workbook, 'green')
        bf = build_button_formats(workbook, 'green')
        partner_label = (data or {}).get('partner_label') or 'All Clients'

        owner_ids = self._owner_ids(data, pickings)
        # Live stock first: it defines both the AVAILABLE figures and the rows
        # that no receipt would have produced.
        avail = self._available_by_pallet(self._live_quants(owner_ids))
        groups = self._collect_pallets(owner_ids, avail)
        all_rows = [self._row_values(g, avail) for g in groups]
        n_inv = sum(1 for r in all_rows if r[0] == 'INV')
        n_zero = len(all_rows) - n_inv

        for label, sheet_name, status in VIEWS:
            rows = all_rows if status is None else [
                r for r in all_rows if r[0] == status]
            self._write_view(workbook, sheet_name, rows, (n_inv, n_zero),
                             f, bf, label, partner_label)
