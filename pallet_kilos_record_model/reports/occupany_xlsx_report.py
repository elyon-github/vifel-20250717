from odoo import models
import datetime
import calendar
from collections import defaultdict


class PalletKilosXlsx(models.AbstractModel):
    _name = 'report.pallet_kilos_record_model.occupancy_report'
    _inherit = 'report.report_xlsx.abstract'

    def _define_formats(self, workbook):
        """Define and return all format objects with a clean, modern palette."""
        base = {'font_name': 'Aptos', 'font_size': 10}

        formats = {}

        # ── Title bar ──
        formats['title'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 14,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'bottom': 2, 'bottom_color': '#4472C4',
        })

        # ── Meta row (Month / Year / Pallet Position) ──
        formats['meta_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'right', 'valign': 'vcenter',
            'bg_color': '#D6E4F0', 'font_color': '#1F3864',
            'border': 1, 'border_color': '#B4C6E7',
        })
        formats['meta_value'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'left', 'valign': 'vcenter',
            'bg_color': '#D6E4F0', 'font_color': '#1F3864',
            'border': 1, 'border_color': '#B4C6E7',
        })

        # ── Building label row ──
        formats['building_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 11,
            'align': 'left', 'valign': 'vcenter',
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'bottom': 2, 'bottom_color': '#4472C4',
        })

        # ── Column headers (CLIENT / WHSE / MAX / MIN) ──
        formats['col_header'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#1F3864',
        })

        # ── Date header (merged top row) ──
        formats['date_header'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#1F3864',
        })

        # ── Sub-header (PALLET COUNT / KILOGRAMS) ──
        formats['sub_header_pallet'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 8,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#4472C4', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#2F5496',
        })
        formats['sub_header_kilos'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 8,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#5B9BD5', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#2F5496',
        })

        # ── Data rows (two alternating stripes) ──
        for suffix, bg in [('even', '#FFFFFF'), ('odd', '#F2F7FB')]:
            formats[f'client_{suffix}'] = workbook.add_format({
                **base, 'bold': True, 'align': 'left', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
            })
            formats[f'whse_{suffix}'] = workbook.add_format({
                **base, 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
                'font_color': '#595959',
            })
            formats[f'pallet_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0', 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
            })
            formats[f'kilos_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter',
                'bg_color': '#EAF1FA' if suffix == 'even' else '#E0EBFA',
                'border': 1, 'border_color': '#D9E2F3',
                'font_color': '#2F5496',
            })
            formats[f'maxmin_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0', 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
                'bold': True, 'font_color': '#2F5496',
            })

        # ── Total row ──
        formats['total_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })
        formats['total_pallet'] = workbook.add_format({
            **base, 'bold': True, 'num_format': '#,##0',
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })
        formats['total_kilos'] = workbook.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#BDD7EE',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })

        return formats

    # ──────────────────────────────────────────────
    #  Main report generation
    # ──────────────────────────────────────────────
    def generate_xlsx_report(self, workbook, data, records):
        fmt = self._define_formats(workbook)

        sheet = workbook.add_worksheet('Inventory Occupancy Report')
        sheet.hide_gridlines(2)  # hide both screen & printed gridlines
        sheet.set_tab_color('#2F5496')

        # Column widths
        sheet.set_column(0, 0, 28)   # Client
        sheet.set_column(1, 1, 18)   # WHSE ALLOCATION

        # ── Filter & sort records ──
        valid_records = [r for r in records if r.start_time]
        sorted_records = sorted(valid_records, key=lambda x: (x.start_time, x.id))

        if not sorted_records:
            sheet.write(0, 0, 'No records found.', fmt['title'])
            return

        # ── Date range (UTC → UTC+8) ──
        oldest_utc8 = (sorted_records[0].start_time + datetime.timedelta(hours=8)).date()
        latest_utc8 = (sorted_records[-1].start_time + datetime.timedelta(hours=8)).date()
        date_list = [
            oldest_utc8 + datetime.timedelta(days=d)
            for d in range((latest_utc8 - oldest_utc8).days + 1)
        ]

        num_date_cols = len(date_list) * 2
        total_cols = 2 + num_date_cols + 2  # Client + WHSE + dates + MAX + MIN

        # Set date-column widths (pallet cols slightly narrower)
        for i in range(len(date_list)):
            sheet.set_column(2 + i * 2, 2 + i * 2, 11)       # pallet
            sheet.set_column(2 + i * 2 + 1, 2 + i * 2 + 1, 13)  # kilos
        sheet.set_column(2 + num_date_cols, 2 + num_date_cols + 1, 10)  # MAX / MIN

        # ── Organise data by building ──
        building_data = {}
        all_buildings = set()

        for rec in sorted_records:
            owner_name = rec.owner_id.name or 'Unknown'
            balances = rec.total_balances or {}
            rec_date = (rec.start_time + datetime.timedelta(hours=8)).date()

            for bldg, info in balances.items():
                all_buildings.add(bldg)
                building_data.setdefault(bldg, {}).setdefault(owner_name, {}).setdefault(rec_date, [])
                building_data[bldg][owner_name][rec_date].append({
                    'record': rec,
                    'pallets': info.get('total_balance_in_pallets', 0),
                    'kilos': info.get('total_balance_in_kilos', 0),
                })

        # ── Fetch relocation moves in the date range ──
        # Relocations move pallets between buildings but don't create pallet_kilos_records,
        # so the report must account for them separately.
        oldest_utc = sorted_records[0].start_time
        latest_utc = sorted_records[-1].start_time
        reloc_lines = self.env['stock.move.line'].search([
            ('is_relocation', '=', True),
            ('state', '=', 'done'),
            ('date', '>=', oldest_utc),
            ('date', '<=', latest_utc + datetime.timedelta(days=1)),
        ])

        # Build relocation deltas per (owner_name, date) → {building → {pallets, kilos}}
        # Each relocation: subtract from source building, add to dest building
        reloc_deltas = defaultdict(lambda: defaultdict(lambda: {'pallets': 0, 'kilos': 0}))
        reloc_pallet_seen = set()  # Track unique (owner, date, src, dst, package) for pallet counting

        def _get_building_name(location):
            if location and location.x_studio_building and location.x_studio_building.x_name:
                return location.x_studio_building.x_name
            return "MAIN"

        for line in reloc_lines:
            owner_name = (line.owner_id.name if line.owner_id
                          else line.move_id.restrict_partner_id.name if line.move_id.restrict_partner_id
                          else None)
            if not owner_name:
                continue

            src_bldg = _get_building_name(line.location_id)
            dst_bldg = _get_building_name(line.location_dest_id)
            if src_bldg == dst_bldg:
                continue

            reloc_date = (line.date + datetime.timedelta(hours=8)).date()
            kilos = line.quantity or 0

            pkg_id = (line.result_package_id.id if line.result_package_id
                      else line.package_id.id if line.package_id else None)
            pallet_key = (owner_name, reloc_date, src_bldg, dst_bldg, pkg_id)
            is_new_pallet = pkg_id and pallet_key not in reloc_pallet_seen
            if is_new_pallet:
                reloc_pallet_seen.add(pallet_key)
            pallet_delta = 1 if is_new_pallet else 0

            key = (owner_name, reloc_date)
            reloc_deltas[key][src_bldg]['pallets'] -= pallet_delta
            reloc_deltas[key][src_bldg]['kilos'] -= kilos
            reloc_deltas[key][dst_bldg]['pallets'] += pallet_delta
            reloc_deltas[key][dst_bldg]['kilos'] += kilos

            # Ensure buildings appear in the report
            all_buildings.add(src_bldg)
            all_buildings.add(dst_bldg)

        # Ensure owners affected by relocations appear in building_data
        for (owner_name_r, reloc_dt), bldg_deltas in reloc_deltas.items():
            for bldg_r in bldg_deltas:
                building_data.setdefault(bldg_r, {}).setdefault(owner_name_r, {})

        # ── Header info ──
        month_year = oldest_utc8.strftime('%B %Y').upper()
        year = oldest_utc8.year

        max_pallet_position = 0
        if records:
            sv = self.env['x_inventory_static_var'].search([
                ('x_name', '=', 'Max Pallets'),
                ('x_studio_warehouse', '=', records[0].warehouse.id),
            ], limit=1)
            if sv:
                max_pallet_position = sv.x_studio_float_value or 0

        row = 0

        # Title
        sheet.set_row(row, 30)
        sheet.merge_range(row, 0, row, total_cols - 1,
                          f'INVENTORY OCCUPANCY REPORT  —  {year}', fmt['title'])
        row += 1

        # Meta rows
        for label, value in [('Month', month_year), ('Year', str(year)),
                             ('Total Pallet Positions', int(max_pallet_position))]:
            sheet.set_row(row, 20)
            sheet.merge_range(row, 0, row, 1, f'{label}:', fmt['meta_label'])
            sheet.write(row, 2, value, fmt['meta_value'])
            row += 1
        row += 1  # spacer

        # ── Per-building tables ──
        for bldg_name in sorted(all_buildings):
            owners = building_data[bldg_name]

            # Building label row
            sheet.set_row(row, 22)
            sheet.merge_range(row, 0, row, total_cols - 1,
                              f'  📦  {bldg_name}', fmt['building_label'])
            row += 1

            # ── Header row 1: CLIENT | WHSE | date spans | MAX | MIN ──
            sheet.set_row(row, 24)
            sheet.write(row, 0, 'CLIENT', fmt['col_header'])
            sheet.write(row, 1, 'WHSE ALLOCATION', fmt['col_header'])

            col = 2
            for dt in date_list:
                sheet.merge_range(row, col, row, col + 1,
                                  dt.strftime('%d-%b'), fmt['date_header'])
                col += 2
            sheet.write(row, col, 'MAX', fmt['col_header'])
            sheet.write(row, col + 1, 'MIN', fmt['col_header'])
            row += 1

            # ── Header row 2: sub-headers ──
            sheet.set_row(row, 20)
            sheet.write(row, 0, '', fmt['col_header'])
            sheet.write(row, 1, '', fmt['col_header'])

            col = 2
            for _ in date_list:
                sheet.write(row, col, 'PALLET COUNT', fmt['sub_header_pallet'])
                sheet.write(row, col + 1, 'KILOGRAMS', fmt['sub_header_kilos'])
                col += 2
            sheet.write(row, col, '', fmt['col_header'])
            sheet.write(row, col + 1, '', fmt['col_header'])
            row += 1

            # Freeze panes (only on first building)
            if bldg_name == sorted(all_buildings)[0]:
                sheet.freeze_panes(row, 2)

            # ── Data rows ──
            bldg_pallet_totals = {}
            bldg_kilos_totals = {}
            owner_idx = 0

            for owner_name in sorted(owners.keys()):
                stripe = 'even' if owner_idx % 2 == 0 else 'odd'
                owner_dates = owners[owner_name]

                sheet.set_row(row, 18)
                sheet.write(row, 0, owner_name, fmt[f'client_{stripe}'])
                sheet.write(row, 1, bldg_name, fmt[f'whse_{stripe}'])

                col = 2
                last_pallet = 0
                last_kilos = 0
                cumulative_reloc_pallets = 0
                cumulative_reloc_kilos = 0
                last_record_date = None  # Track when the last record snapshot was taken
                row_pallet_values = []

                for dt in date_list:
                    if dt in owner_dates:
                        day = owner_dates[dt]
                        if day:
                            best = sorted(day, key=lambda x: (x['record'].start_time, x['record'].id))[-1]
                            last_pallet = best['pallets'] or 0
                            last_kilos = best['kilos'] or 0
                            # Reset cumulative relocation delta when we get a fresh record snapshot
                            # because the record's total_balances already accounts for relocations
                            # that happened before its start_time (if _recalculate was run)
                            cumulative_reloc_pallets = 0
                            cumulative_reloc_kilos = 0
                            last_record_date = dt

                    # Apply relocation deltas for this date on top of carried-forward values
                    reloc_key = (owner_name, dt)
                    if reloc_key in reloc_deltas and bldg_name in reloc_deltas[reloc_key]:
                        cumulative_reloc_pallets += reloc_deltas[reloc_key][bldg_name]['pallets']
                        cumulative_reloc_kilos += reloc_deltas[reloc_key][bldg_name]['kilos']

                    pallet_count = last_pallet + cumulative_reloc_pallets
                    kilos_count = last_kilos + cumulative_reloc_kilos
                    row_pallet_values.append(pallet_count)

                    sheet.write(row, col, pallet_count, fmt[f'pallet_{stripe}'])
                    sheet.write(row, col + 1, kilos_count, fmt[f'kilos_{stripe}'])

                    bldg_pallet_totals[dt] = bldg_pallet_totals.get(dt, 0) + pallet_count
                    bldg_kilos_totals[dt] = bldg_kilos_totals.get(dt, 0) + kilos_count
                    col += 2

                # MAX / MIN computed in Python (avoids Excel formula repair issues)
                if row_pallet_values:
                    sheet.write(row, col, max(row_pallet_values), fmt[f'maxmin_{stripe}'])
                    sheet.write(row, col + 1, min(row_pallet_values), fmt[f'maxmin_{stripe}'])
                else:
                    sheet.write(row, col, 0, fmt[f'maxmin_{stripe}'])
                    sheet.write(row, col + 1, 0, fmt[f'maxmin_{stripe}'])

                row += 1
                owner_idx += 1

            # ── Total row ──
            sheet.set_row(row, 22)
            sheet.write(row, 0, 'TOTAL', fmt['total_label'])
            sheet.write(row, 1, bldg_name, fmt['total_label'])

            col = 2
            for dt in date_list:
                tp = bldg_pallet_totals.get(dt, 0)
                tk = bldg_kilos_totals.get(dt, 0)
                sheet.write(row, col, tp, fmt['total_pallet'])
                sheet.write(row, col + 1, tk, fmt['total_kilos'])
                col += 2

            # Total MAX / MIN computed in Python
            total_pallet_vals = [bldg_pallet_totals.get(dt, 0) for dt in date_list]
            if total_pallet_vals:
                sheet.write(row, col, max(total_pallet_vals), fmt['total_pallet'])
                sheet.write(row, col + 1, min(total_pallet_vals), fmt['total_pallet'])
            else:
                sheet.write(row, col, 0, fmt['total_label'])
                sheet.write(row, col + 1, 0, fmt['total_label'])

            row += 2  # spacing before next building