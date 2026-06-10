from odoo import models
import datetime
import logging

_logger = logging.getLogger(__name__)


class OccupancyXlsxReport(models.AbstractModel):
    _name = 'report.stock_quant_history.occupancy_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Occupancy XLSX Report from Stock Quant History'

    # ──────────────────────────────────────────────
    #  Formatting
    # ──────────────────────────────────────────────
    def _define_formats(self, workbook):
        """Define and return all format objects."""
        base = {'font_name': 'Aptos', 'font_size': 10}
        fmt = {}

        # Title bar
        fmt['title'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 14,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'bottom': 2, 'bottom_color': '#4472C4',
        })

        # Meta row
        fmt['meta_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'right', 'valign': 'vcenter',
            'bg_color': '#D6E4F0', 'font_color': '#1F3864',
            'border': 1, 'border_color': '#B4C6E7',
        })
        fmt['meta_value'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'left', 'valign': 'vcenter',
            'bg_color': '#D6E4F0', 'font_color': '#1F3864',
            'border': 1, 'border_color': '#B4C6E7',
        })

        # Building label row
        fmt['building_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 11,
            'align': 'left', 'valign': 'vcenter',
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'bottom': 2, 'bottom_color': '#4472C4',
        })

        # Column headers
        fmt['col_header'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#1F3864',
        })

        # Date header (merged top row)
        fmt['date_header'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#2F5496', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#1F3864',
        })

        # Sub-headers
        fmt['sub_header_pallet'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 8,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#4472C4', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#2F5496',
        })
        fmt['sub_header_kilos'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 8,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'bg_color': '#5B9BD5', 'font_color': '#FFFFFF',
            'border': 1, 'border_color': '#2F5496',
        })

        # Data rows (alternating stripes)
        for suffix, bg in [('even', '#FFFFFF'), ('odd', '#F2F7FB')]:
            fmt[f'client_{suffix}'] = workbook.add_format({
                **base, 'bold': True, 'align': 'left', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
            })
            fmt[f'whse_{suffix}'] = workbook.add_format({
                **base, 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
                'font_color': '#595959',
            })
            fmt[f'pallet_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0', 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
            })
            fmt[f'kilos_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter',
                'bg_color': '#EAF1FA' if suffix == 'even' else '#E0EBFA',
                'border': 1, 'border_color': '#D9E2F3',
                'font_color': '#2F5496',
            })
            fmt[f'maxmin_{suffix}'] = workbook.add_format({
                **base, 'num_format': '#,##0', 'align': 'center', 'valign': 'vcenter',
                'bg_color': bg, 'border': 1, 'border_color': '#D9E2F3',
                'bold': True, 'font_color': '#2F5496',
            })

        # Total row
        fmt['total_label'] = workbook.add_format({
            **base, 'bold': True, 'font_size': 10,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })
        fmt['total_pallet'] = workbook.add_format({
            **base, 'bold': True, 'num_format': '#,##0',
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#FFFFFF',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })
        fmt['total_kilos'] = workbook.add_format({
            **base, 'bold': True, 'num_format': '#,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'bg_color': '#1F3864', 'font_color': '#BDD7EE',
            'top': 2, 'top_color': '#4472C4',
            'bottom': 2, 'bottom_color': '#4472C4',
            'left': 1, 'left_color': '#1F3864',
            'right': 1, 'right_color': '#1F3864',
        })

        return fmt

    # ──────────────────────────────────────────────
    #  Data aggregation
    # ──────────────────────────────────────────────
    def _aggregate_data(self, history_records, snapshots):
        """Aggregate history records into building → owner → snapshot_date → {pallets, kilos}.

        Returns:
            building_data: dict  {building_name: {owner_name: {snapshot_date: {pallets: int, kilos: float}}}}
            all_buildings: sorted list of building names
            snapshot_dates: sorted list of dates (date objects, UTC+8)
        """
        from pytz import timezone

        user_tz = timezone("Asia/Manila")
        building_data = {}
        all_buildings = set()

        # Map snapshot_id → date (in Manila tz)
        snapshot_date_map = {}
        for snap in snapshots:
            local_dt = snap.inventory_date.astimezone(user_tz)
            snapshot_date_map[snap.id] = local_dt.date()

        snapshot_dates = sorted(set(snapshot_date_map.values()))

        for rec in history_records:
            snap_date = snapshot_date_map.get(rec.snapshot_id.id)
            if not snap_date:
                continue

            owner_name = rec.owner_id.name or 'Unknown'
            building = rec.location_id.x_studio_building
            building_name = building.x_name if building and building.x_name else 'MAIN'

            all_buildings.add(building_name)
            building_data.setdefault(building_name, {})
            building_data[building_name].setdefault(owner_name, {})
            building_data[building_name][owner_name].setdefault(snap_date, {
                'pallet_series': set(),
                'kilos': 0.0,
            })

            entry = building_data[building_name][owner_name][snap_date]

            # Count distinct pallet series IDs
            if rec.x_studio_pallet_series_id:
                entry['pallet_series'].add(rec.x_studio_pallet_series_id)

            # Sum kilograms (quantity = on-hand weight)
            entry['kilos'] += rec.quantity or 0.0

        return building_data, sorted(all_buildings), snapshot_dates

    # ──────────────────────────────────────────────
    #  SQL on-the-fly computation
    # ──────────────────────────────────────────────
    def _compute_from_sql(self, data):
        """Compute occupancy entirely from SQL reads + Python aggregation.

        For each target date in the range:
        1.  Find the nearest generated snapshot *before* (or on) that date.
        2.  Load the snapshot's stock.quant.history via raw SQL (no ORM).
        3.  Apply stock.move.line adjustments between snapshot date and
            target-day end; handle UoM conversion.
        4.  For new stock entries that don't exist in the base snapshot,
            resolve owner + pallet-series from stock.quant (batch lookup).
        5.  Consecutive days that share the same base snapshot are processed
            **incrementally** (each day only applies its own delta moves).

        Returns the same structure as ``_aggregate_data``.
        """
        from datetime import datetime as dt_cls, timedelta, date as date_type
        from pytz import timezone, utc as pytz_utc
        from collections import defaultdict

        manila_tz = timezone('Asia/Manila')
        cr = self.env.cr

        date_from = dt_cls.strptime(data['date_from'], '%Y-%m-%d').date()
        date_to = dt_cls.strptime(data['date_to'], '%Y-%m-%d').date()
        partner_ids = data.get('partner_ids', [])

        # ── one-time look-ups ──────────────────────────────────────────
        cr.execute("""
            SELECT sl.id, wb.x_name
            FROM stock_location sl
            LEFT JOIN x_warehouse_building wb
                   ON sl.x_studio_building = wb.id
            WHERE sl.usage = 'internal'
        """)
        loc_building = {}
        for lid, bname in cr.fetchall():
            if isinstance(bname, dict):
                bname = bname.get('en_US', str(bname))
            loc_building[lid] = bname or 'MAIN'

        cr.execute("SELECT id, factor FROM uom_uom")
        uom_factors = dict(cr.fetchall())

        cr.execute("""
            SELECT pp.id, pt.uom_id
            FROM product_product pp
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE pt.type = 'product'
        """)
        product_uom_map = dict(cr.fetchall())

        # ── build target-date list ─────────────────────────────────────
        dates = []
        d = date_from
        while d <= date_to:
            dates.append(d)
            d += timedelta(days=1)

        # ── map each date → nearest snapshot ───────────────────────────
        date_info = {}
        for target_date in dates:
            target_end = manila_tz.localize(
                dt_cls.combine(target_date, dt_cls.min.time()).replace(
                    hour=23, minute=59, second=59,
                )
            ).astimezone(pytz_utc).replace(tzinfo=None)

            cr.execute("""
                SELECT id, inventory_date
                FROM stock_quant_history_snapshot
                WHERE state = 'generated' AND inventory_date <= %s
                ORDER BY inventory_date DESC
                LIMIT 1
            """, (target_end,))
            row = cr.fetchone()
            if row:
                date_info[target_date] = {
                    'snap_id': row[0],
                    'snap_inv': row[1],
                    'target_utc': target_end,
                }

        # Fallback: if no snapshot covers the first date, auto-generate
        # ONE snapshot for the start date as a baseline.
        if not date_info:
            _logger.info(
                "No snapshot found for SQL occupancy report; "
                "auto-generating baseline snapshot for %s", date_from,
            )
            SnapshotModel = self.env['stock.quant.history.snapshot'].sudo()
            local_dt = manila_tz.localize(
                dt_cls.combine(date_from, dt_cls.min.time()).replace(
                    hour=23, minute=59, second=59,
                )
            )
            utc_dt = local_dt.astimezone(pytz_utc).replace(tzinfo=None)

            snapshot = SnapshotModel.create({
                'inventory_date': utc_dt,
                'state': 'draft',
            })
            snapshot._generate_stock_quant_history()

            # Re-map all dates now that baseline exists
            for target_date in dates:
                target_end = manila_tz.localize(
                    dt_cls.combine(target_date, dt_cls.min.time()).replace(
                        hour=23, minute=59, second=59,
                    )
                ).astimezone(pytz_utc).replace(tzinfo=None)

                cr.execute("""
                    SELECT id, inventory_date
                    FROM stock_quant_history_snapshot
                    WHERE state = 'generated' AND inventory_date <= %s
                    ORDER BY inventory_date DESC
                    LIMIT 1
                """, (target_end,))
                row = cr.fetchone()
                if row:
                    date_info[target_date] = {
                        'snap_id': row[0],
                        'snap_inv': row[1],
                        'target_utc': target_end,
                    }

        if not date_info:
            return {}, [], []

        # group by snapshot so we can process incrementally
        snap_groups = defaultdict(list)
        for td in sorted(date_info):
            snap_groups[date_info[td]['snap_id']].append(
                (td, date_info[td])
            )

        building_data = {}
        all_buildings = set()
        snapshot_dates = []

        ignored_usages = ('supplier', 'customer', 'inventory')

        # ── per-snapshot-group processing ──────────────────────────────
        for snap_id, group in snap_groups.items():
            group.sort(key=lambda x: x[0])
            snap_inv = group[0][1]['snap_inv']

            # snapshot's Manila date
            snap_utc_aware = (
                pytz_utc.localize(snap_inv)
                if snap_inv.tzinfo is None else snap_inv
            )
            snap_manila_date = snap_utc_aware.astimezone(manila_tz).date()

            # load base state ------------------------------------------------
            cr.execute("""
                SELECT product_id, lot_id, location_id,
                       owner_id, x_studio_pallet_series_id, quantity
                FROM stock_quant_history
                WHERE snapshot_id = %s
                  AND owner_id IS NOT NULL
                  AND quantity != 0
            """, (snap_id,))

            initial = {}
            for pid, lid, loc, oid, psi, qty in cr.fetchall():
                key = (pid, lid or 0, loc)
                if key in initial:
                    initial[key]['quantity'] += qty
                    if psi and not initial[key]['pallet_series']:
                        initial[key]['pallet_series'] = psi
                else:
                    initial[key] = {
                        'owner_id': oid,
                        'pallet_series': psi or '',
                        'quantity': qty,
                    }

            # shallow-copy inner dicts for incremental mutation
            state = {k: dict(v) for k, v in initial.items()}
            prev_utc = snap_inv

            # ── iterate dates in this group --------------------------------
            for target_date, info in group:
                target_utc = info['target_utc']

                # apply move-line deltas (skip when date == snapshot date)
                if target_date != snap_manila_date:
                    cr.execute("""
                        SELECT sml.product_id, sml.lot_id,
                               sml.location_id, sml.location_dest_id,
                               sml.quantity, sml.product_uom_id,
                               sl_s.usage, sl_d.usage,
                               sml.x_studio_pallet_series_id
                        FROM stock_move_line sml
                        JOIN stock_location sl_s
                             ON sml.location_id = sl_s.id
                        JOIN stock_location sl_d
                             ON sml.location_dest_id = sl_d.id
                        WHERE sml.state = 'done'
                          AND sml.date > %s
                          AND sml.date <= %s
                        ORDER BY sml.date
                    """, (prev_utc, target_utc))

                    needs_owner = []

                    for (pid, lid, sloc, dloc, mq,
                         muom, su, du, mlp) in cr.fetchall():
                        lk = lid or 0
                        sk = (pid, lk, sloc)
                        dk = (pid, lk, dloc)

                        # UoM conversion
                        puom = product_uom_map.get(pid)
                        if puom and muom and puom != muom:
                            sf = uom_factors.get(muom, 1.0) or 1.0
                            df = uom_factors.get(puom, 1.0) or 1.0
                            cq = mq / sf * df
                        else:
                            cq = mq

                        # subtract from source
                        if su not in ignored_usages and sk in state:
                            state[sk]['quantity'] -= cq

                        # add to destination
                        if du not in ignored_usages:
                            if dk in state:
                                state[dk]['quantity'] += cq
                            else:
                                oid = None
                                ps = mlp or ''
                                if sk in state:
                                    oid = state[sk]['owner_id']
                                    ps = ps or state[sk]['pallet_series']
                                if oid:
                                    state[dk] = {
                                        'owner_id': oid,
                                        'pallet_series': ps,
                                        'quantity': cq,
                                    }
                                else:
                                    needs_owner.append(
                                        (lk, dk, cq, ps)
                                    )

                    # batch owner resolution from stock.quant
                    if needs_owner:
                        lot_ids = set(
                            x[0] for x in needs_owner if x[0]
                        )
                        qmap = {}
                        if lot_ids:
                            cr.execute("""
                                SELECT DISTINCT ON (lot_id)
                                       lot_id, owner_id,
                                       x_studio_pallet_series_id
                                FROM stock_quant
                                WHERE lot_id IN %s
                                  AND owner_id IS NOT NULL
                                ORDER BY lot_id, id
                            """, (tuple(lot_ids),))
                            for lr in cr.fetchall():
                                qmap[lr[0]] = (lr[1], lr[2])

                        for lk, dk, qty, ps in needs_owner:
                            if dk in state:
                                state[dk]['quantity'] += qty
                            elif lk in qmap:
                                state[dk] = {
                                    'owner_id': qmap[lk][0],
                                    'pallet_series': (
                                        ps or qmap[lk][1] or ''
                                    ),
                                    'quantity': qty,
                                }
                            # else: owner unknown → omit from report

                prev_utc = target_utc

                # ── aggregate state for this date --------------------------
                snapshot_dates.append(target_date)

                active_owners = set(
                    v['owner_id'] for v in state.values()
                    if v['owner_id'] and v['quantity'] > 0
                )
                if partner_ids:
                    active_owners &= set(partner_ids)
                if not active_owners:
                    continue

                cr.execute(
                    "SELECT id, name FROM res_partner WHERE id IN %s",
                    (tuple(active_owners),),
                )
                onames = {}
                for oid, nm in cr.fetchall():
                    if isinstance(nm, dict):
                        nm = nm.get('en_US', str(nm))
                    onames[oid] = nm or 'Unknown'

                for (_pid, _lid, loc), d in state.items():
                    if d['quantity'] <= 0:
                        continue
                    if d['owner_id'] not in active_owners:
                        continue

                    bname = loc_building.get(loc, 'MAIN')
                    oname = onames.get(d['owner_id'], 'Unknown')

                    all_buildings.add(bname)
                    building_data.setdefault(bname, {})
                    building_data[bname].setdefault(oname, {})
                    building_data[bname][oname].setdefault(
                        target_date,
                        {'pallet_series': set(), 'kilos': 0.0},
                    )

                    entry = building_data[bname][oname][target_date]
                    if d['pallet_series']:
                        entry['pallet_series'].add(d['pallet_series'])
                    entry['kilos'] += d['quantity']

        return building_data, sorted(all_buildings), sorted(snapshot_dates)

    # ──────────────────────────────────────────────
    #  Main report generation
    # ──────────────────────────────────────────────
    def generate_xlsx_report(self, workbook, data, records):
        fmt = self._define_formats(workbook)

        sheet = workbook.add_worksheet('Inventory Occupancy Report')
        sheet.hide_gridlines(2)
        sheet.set_tab_color('#2F5496')

        # Column widths
        sheet.set_column(0, 0, 28)   # Client
        sheet.set_column(1, 1, 18)   # WHSE ALLOCATION

        method = data.get('method', 'snapshot')

        if method == 'sql':
            # On-the-fly SQL computation — no pre-fetched records needed
            building_data, all_buildings, snapshot_dates = \
                self._compute_from_sql(data)
        else:
            # Existing-snapshots method
            snapshot_ids = data.get('snapshot_ids', [])
            snapshots = self.env['stock.quant.history.snapshot'].browse(
                snapshot_ids
            )

            if not snapshots:
                sheet.write(0, 0, 'No snapshots found.', fmt['title'])
                return

            building_data, all_buildings, snapshot_dates = \
                self._aggregate_data(records, snapshots)

        if not snapshot_dates:
            sheet.write(0, 0, 'No data found for the selected criteria.', fmt['title'])
            return

        num_date_cols = len(snapshot_dates) * 2
        total_cols = 2 + num_date_cols + 2  # Client + WHSE + dates + MAX + MIN

        # Set date-column widths
        for i in range(len(snapshot_dates)):
            sheet.set_column(2 + i * 2, 2 + i * 2, 11)         # pallet
            sheet.set_column(2 + i * 2 + 1, 2 + i * 2 + 1, 13) # kilos
        sheet.set_column(2 + num_date_cols, 2 + num_date_cols + 1, 10)  # MAX / MIN

        # ── Header info ──
        date_from = data.get('date_from', '')
        date_to = data.get('date_to', '')
        year = snapshot_dates[0].year if snapshot_dates else ''

        # Max pallet position from static var (same as old report)
        max_pallet_position = 0
        sv = self.env['x_inventory_static_var'].search([
            ('x_name', '=', 'Max Pallets'),
        ], limit=1)
        if sv:
            max_pallet_position = sv.x_studio_float_value or 0

        row = 0

        # Title
        sheet.set_row(row, 30)
        sheet.merge_range(row, 0, row, total_cols - 1,
                          f'INVENTORY OCCUPANCY REPORT  —  {date_from} to {date_to}', fmt['title'])
        row += 1

        # Meta rows
        for label, value in [('Date Range', f'{date_from}  to  {date_to}'),
                             ('Total Snapshots', str(len(snapshot_dates))),
                             ('Total Pallet Positions', int(max_pallet_position))]:
            sheet.set_row(row, 20)
            sheet.merge_range(row, 0, row, 1, f'{label}:', fmt['meta_label'])
            sheet.write(row, 2, value, fmt['meta_value'])
            row += 1
        row += 1  # spacer

        # ── Per-building tables ──
        for bldg_name in all_buildings:
            owners = building_data.get(bldg_name, {})

            # Building label row
            sheet.set_row(row, 22)
            sheet.merge_range(row, 0, row, total_cols - 1,
                              f'  {bldg_name}', fmt['building_label'])
            row += 1

            # ── Header row 1: CLIENT | WHSE | date spans | MAX | MIN ──
            sheet.set_row(row, 24)
            sheet.write(row, 0, 'CLIENT', fmt['col_header'])
            sheet.write(row, 1, 'WHSE ALLOCATION', fmt['col_header'])

            col = 2
            for dt in snapshot_dates:
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
            for _ in snapshot_dates:
                sheet.write(row, col, 'PALLET COUNT', fmt['sub_header_pallet'])
                sheet.write(row, col + 1, 'KILOGRAMS', fmt['sub_header_kilos'])
                col += 2
            sheet.write(row, col, '', fmt['col_header'])
            sheet.write(row, col + 1, '', fmt['col_header'])
            row += 1

            # Freeze panes (only on first building)
            if bldg_name == all_buildings[0]:
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
                row_pallet_values = []

                for dt in snapshot_dates:
                    day_data = owner_dates.get(dt)
                    if day_data:
                        pallet_count = len(day_data['pallet_series'])
                        kilos_count = day_data['kilos']
                    else:
                        pallet_count = 0
                        kilos_count = 0.0

                    row_pallet_values.append(pallet_count)

                    sheet.write(row, col, pallet_count, fmt[f'pallet_{stripe}'])
                    sheet.write(row, col + 1, kilos_count, fmt[f'kilos_{stripe}'])

                    bldg_pallet_totals[dt] = bldg_pallet_totals.get(dt, 0) + pallet_count
                    bldg_kilos_totals[dt] = bldg_kilos_totals.get(dt, 0) + kilos_count
                    col += 2

                # MAX / MIN
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
            for dt in snapshot_dates:
                tp = bldg_pallet_totals.get(dt, 0)
                tk = bldg_kilos_totals.get(dt, 0)
                sheet.write(row, col, tp, fmt['total_pallet'])
                sheet.write(row, col + 1, tk, fmt['total_kilos'])
                col += 2

            total_pallet_vals = [bldg_pallet_totals.get(dt, 0) for dt in snapshot_dates]
            if total_pallet_vals:
                sheet.write(row, col, max(total_pallet_vals), fmt['total_pallet'])
                sheet.write(row, col + 1, min(total_pallet_vals), fmt['total_pallet'])
            else:
                sheet.write(row, col, 0, fmt['total_label'])
                sheet.write(row, col + 1, 0, fmt['total_label'])

            row += 2  # spacing before next building

        # ── Second sheet: per-building + overall occupancy breakdown & charts ──
        building_caps = self._get_building_capacities()
        self._write_occupancy_chart_sheet(
            workbook, building_data, snapshot_dates, building_caps
        )

    # ──────────────────────────────────────────────
    #  Capacity = pallet slots (P1/P2) per building
    # ──────────────────────────────────────────────
    BUILDING_ORDER = ['MAIN', 'EXPANSION', 'ANNEX']
    BUILDING_COLORS = {
        'MAIN': '#4472C4', 'EXPANSION': '#ED7D31', 'ANNEX': '#70AD47',
    }
    OVERALL_COLOR = '#C00000'

    def _get_building_capacities(self):
        """{building_name: capacity} where capacity = count of active internal
        P1/P2 pallet slots in that building (each slot = one pallet position).

        Mirrors the per-building / OVERALL CAPACITY of the Daily Pallet
        Utilization report. Sum of the values = overall capacity. NOT the flat
        'Max Pallets' static var.
        """
        self.env.cr.execute("""
            SELECT COALESCE(wb.x_name->>'en_US', 'MAIN') AS bname, COUNT(*)
            FROM stock_location sl
            JOIN x_warehouse_building wb ON sl.x_studio_building = wb.id
            WHERE sl.active AND sl.usage = 'internal'
              AND sl.name IN ('P1', 'P2')
            GROUP BY 1
        """)
        return {row[0]: row[1] for row in self.env.cr.fetchall()}

    # ──────────────────────────────────────────────
    #  Second sheet: per-building + overall occupancy
    # ──────────────────────────────────────────────
    def _write_occupancy_chart_sheet(self, workbook, building_data,
                                     snapshot_dates, building_caps):
        """Second worksheet: a per-building breakdown table (pallet position +
        kilograms + % per building, plus overall %) followed by line charts —
        one combined (all buildings + overall) and one per building.

        Per-building %  = building pallets that date / building capacity.
        Overall %       = total pallets that date / total capacity.
        """
        if not snapshot_dates:
            return

        # building order: known order first, then any extras present
        present = set(building_data) | set(building_caps)
        buildings = [b for b in self.BUILDING_ORDER if b in present]
        buildings += [b for b in sorted(present) if b not in buildings]
        nb = len(buildings)
        if nb == 0:
            return

        overall_cap = sum(building_caps.get(b, 0) for b in buildings)

        # per-building, per-date pallet count + kilos
        data = {b: {d: {'pallets': 0, 'kilos': 0.0} for d in snapshot_dates}
                for b in buildings}
        for b, owners in building_data.items():
            if b not in data:
                continue
            for dates in owners.values():
                for d, day in dates.items():
                    if d in data[b]:
                        data[b][d]['pallets'] += len(day['pallet_series'])
                        data[b][d]['kilos'] += day['kilos'] or 0.0

        sheet = workbook.add_worksheet('Occupancy Breakdown')
        sheet.hide_gridlines(2)
        sheet.set_tab_color('#C00000')

        base = {'font_name': 'Aptos', 'font_size': 10}
        f = {
            'title': workbook.add_format({
                **base, 'bold': True, 'font_size': 14, 'font_color': '#FFFFFF',
                'bg_color': '#1F3864', 'align': 'center', 'valign': 'vcenter'}),
            'cap_label': workbook.add_format({
                **base, 'bold': True, 'bg_color': '#2F5496',
                'font_color': '#FFFFFF', 'border': 1, 'align': 'center',
                'valign': 'vcenter'}),
            'cap_value': workbook.add_format({
                **base, 'bold': True, 'bg_color': '#D6E4F0',
                'font_color': '#1F3864', 'border': 1, 'align': 'center',
                'valign': 'vcenter'}),
            'cap_total': workbook.add_format({
                **base, 'bold': True, 'bg_color': '#C00000',
                'font_color': '#FFFFFF', 'border': 1, 'align': 'center',
                'valign': 'vcenter'}),
            'hdr': workbook.add_format({
                **base, 'bold': True, 'bg_color': '#2F5496',
                'font_color': '#FFFFFF', 'border': 1, 'border_color': '#1F3864',
                'align': 'center', 'valign': 'vcenter', 'text_wrap': True}),
            'hdr_sub': workbook.add_format({
                **base, 'bold': True, 'font_size': 8, 'bg_color': '#4472C4',
                'font_color': '#FFFFFF', 'border': 1, 'border_color': '#2F5496',
                'align': 'center', 'valign': 'vcenter', 'text_wrap': True}),
            'hdr_overall': workbook.add_format({
                **base, 'bold': True, 'bg_color': '#C00000',
                'font_color': '#FFFFFF', 'border': 1, 'align': 'center',
                'valign': 'vcenter', 'text_wrap': True}),
            'date': workbook.add_format({
                **base, 'border': 1, 'border_color': '#D9E2F3',
                'align': 'center'}),
            'int': workbook.add_format({
                **base, 'num_format': '#,##0', 'border': 1,
                'border_color': '#D9E2F3', 'align': 'center'}),
            'kg': workbook.add_format({
                **base, 'num_format': '#,##0.00', 'border': 1,
                'border_color': '#D9E2F3', 'align': 'right',
                'font_color': '#2F5496'}),
            'pct': workbook.add_format({
                **base, 'num_format': '0.00%', 'border': 1,
                'border_color': '#D9E2F3', 'align': 'center',
                'font_color': '#2F5496'}),
            'pct_overall': workbook.add_format({
                **base, 'num_format': '0.00%', 'border': 1, 'bold': True,
                'border_color': '#D9E2F3', 'align': 'center',
                'bg_color': '#FDECEC', 'font_color': '#C00000'}),
            'avg_label': workbook.add_format({
                **base, 'bold': True, 'italic': True, 'font_size': 11,
                'font_color': '#C00000', 'border': 1, 'border_color': '#D9E2F3',
                'align': 'center', 'valign': 'vcenter'}),
            'avg_num': workbook.add_format({
                **base, 'bold': True, 'num_format': '#,##0.00',
                'font_color': '#C00000', 'border': 1, 'border_color': '#D9E2F3',
                'align': 'right'}),
            'avg_pct': workbook.add_format({
                **base, 'bold': True, 'num_format': '0.00%',
                'font_color': '#C00000', 'border': 1, 'border_color': '#D9E2F3',
                'align': 'center'}),
            'avg_pct_overall': workbook.add_format({
                **base, 'bold': True, 'num_format': '0%',
                'font_color': '#C00000', 'bg_color': '#FDECEC', 'border': 1,
                'border_color': '#D9E2F3', 'align': 'center'}),
        }

        # column layout
        col_pallet, col_kg = {}, {}
        c = 1
        for b in buildings:
            col_pallet[b] = c
            col_kg[b] = c + 1
            c += 2
        pct_start = c
        col_pct = {b: pct_start + i for i, b in enumerate(buildings)}
        col_overall_pct = pct_start + nb
        last_col = col_overall_pct

        # widths
        sheet.set_column(0, 0, 13)
        for b in buildings:
            sheet.set_column(col_pallet[b], col_pallet[b], 13)
            sheet.set_column(col_kg[b], col_kg[b], 15)
        sheet.set_column(pct_start, last_col, 12)

        # title
        sheet.set_row(0, 26)
        sheet.merge_range(0, 0, 0, last_col, 'VIFEL OVERALL OCCUPANCY', f['title'])

        # capacity summary
        sheet.set_row(1, 20)
        sheet.write(1, 0, 'CAPACITY', f['cap_label'])
        for b in buildings:
            sheet.merge_range(
                1, col_pallet[b], 1, col_kg[b],
                '%s: %s' % (b, '{:,}'.format(building_caps.get(b, 0))),
                f['cap_value'])
        sheet.merge_range(1, pct_start, 1, last_col,
                          'TOTAL: %s' % '{:,}'.format(overall_cap), f['cap_total'])

        # header rows
        hrow1, hrow2 = 3, 4
        sheet.merge_range(hrow1, 0, hrow2, 0, 'DATE', f['hdr'])
        for b in buildings:
            sheet.merge_range(hrow1, col_pallet[b], hrow1, col_kg[b], b, f['hdr'])
            sheet.write(hrow2, col_pallet[b], 'PALLET POSITION', f['hdr_sub'])
            sheet.write(hrow2, col_kg[b], 'KILOGRAMS', f['hdr_sub'])
            sheet.merge_range(hrow1, col_pct[b], hrow2, col_pct[b],
                              '%s\n%%' % b, f['hdr'])
        sheet.merge_range(hrow1, col_overall_pct, hrow2, col_overall_pct,
                          'OVERALL\n%', f['hdr_overall'])

        # data rows
        first_data = hrow2 + 1
        r = first_data
        for d in snapshot_dates:
            sheet.write_string(r, 0, d.strftime('%d-%b-%Y'), f['date'])
            total_pallets = 0
            for b in buildings:
                p = data[b][d]['pallets']
                total_pallets += p
                sheet.write_number(r, col_pallet[b], p, f['int'])
                sheet.write_number(r, col_kg[b], data[b][d]['kilos'], f['kg'])
            for b in buildings:
                cap_b = building_caps.get(b, 0)
                sheet.write_number(
                    r, col_pct[b],
                    (data[b][d]['pallets'] / cap_b) if cap_b else 0, f['pct'])
            sheet.write_number(
                r, col_overall_pct,
                (total_pallets / overall_cap) if overall_cap else 0,
                f['pct_overall'])
            r += 1
        last_data = r - 1

        # ── AVERAGE OCCUPANCY row (mean over dates that have data) ──
        active_dates = [d for d in snapshot_dates
                        if sum(data[b][d]['pallets'] for b in buildings) > 0]
        n_active = len(active_dates) or 1
        avg_row = last_data + 1
        sheet.set_row(avg_row, 20)
        sheet.write_string(avg_row, 0, 'AVERAGE OCCUPANCY', f['avg_label'])
        total_avg_pallets = 0.0
        for b in buildings:
            avg_p = sum(data[b][d]['pallets'] for d in active_dates) / n_active
            avg_k = sum(data[b][d]['kilos'] for d in active_dates) / n_active
            total_avg_pallets += avg_p
            sheet.write_number(avg_row, col_pallet[b], avg_p, f['avg_num'])
            sheet.write_number(avg_row, col_kg[b], avg_k, f['avg_num'])
            cap_b = building_caps.get(b, 0)
            sheet.write_number(avg_row, col_pct[b],
                               (avg_p / cap_b) if cap_b else 0, f['avg_pct'])
        sheet.write_number(
            avg_row, col_overall_pct,
            (total_avg_pallets / overall_cap) if overall_cap else 0,
            f['avg_pct_overall'])

        sheet.freeze_panes(first_data, 1)

        # ── charts ──
        sname = 'Occupancy Breakdown'
        chart_col = last_col + 2

        # combined: all buildings + overall
        combo = workbook.add_chart({'type': 'line'})
        for b in buildings:
            color = self.BUILDING_COLORS.get(b, '#7F7F7F')
            combo.add_series({
                'name':       b,
                'categories': [sname, first_data, 0, last_data, 0],
                'values':     [sname, first_data, col_pct[b], last_data, col_pct[b]],
                'line':   {'color': color, 'width': 1.5},
                'marker': {'type': 'circle', 'size': 4,
                           'fill': {'color': color}, 'border': {'color': color}},
            })
        combo.add_series({
            'name':       'OVERALL',
            'categories': [sname, first_data, 0, last_data, 0],
            'values':     [sname, first_data, col_overall_pct, last_data, col_overall_pct],
            'line':   {'color': self.OVERALL_COLOR, 'width': 2.5},
            'marker': {'type': 'circle', 'size': 5,
                       'fill': {'color': self.OVERALL_COLOR},
                       'border': {'color': self.OVERALL_COLOR}},
            'data_labels': {'value': True, 'num_format': '0%',
                            'font': {'size': 8, 'bold': True}},
        })
        combo.set_title({'name': 'VIFEL OCCUPANCY — PER BUILDING & OVERALL',
                         'name_font': {'color': self.OVERALL_COLOR,
                                       'bold': True, 'size': 13}})
        combo.set_x_axis({'name': 'Date', 'num_font': {'rotation': -45, 'size': 7}})
        combo.set_y_axis({'name': 'Occupancy %', 'num_format': '0%',
                          'min': 0, 'max': 1.4, 'major_unit': 0.2})
        combo.set_legend({'position': 'bottom'})
        combo.set_size({'width': 980, 'height': 460})
        sheet.insert_chart(first_data, chart_col, combo, {'x_offset': 12, 'y_offset': 4})

        # one chart per building
        per_row = first_data + 24
        for b in buildings:
            color = self.BUILDING_COLORS.get(b, '#7F7F7F')
            ch = workbook.add_chart({'type': 'line'})
            ch.add_series({
                'name':       '%s OCCUPANCY' % b,
                'categories': [sname, first_data, 0, last_data, 0],
                'values':     [sname, first_data, col_pct[b], last_data, col_pct[b]],
                'line':   {'color': color, 'width': 2},
                'marker': {'type': 'circle', 'size': 4,
                           'fill': {'color': color}, 'border': {'color': color}},
                'data_labels': {'value': True, 'num_format': '0%',
                                'font': {'size': 7, 'bold': True}},
            })
            ch.set_title({'name': '%s OCCUPANCY' % b,
                          'name_font': {'color': color, 'bold': True, 'size': 12}})
            ch.set_x_axis({'name': 'Date', 'num_font': {'rotation': -45, 'size': 7}})
            ch.set_y_axis({'name': 'Occupancy %', 'num_format': '0%',
                           'min': 0, 'max': 1.4, 'major_unit': 0.2})
            ch.set_legend({'none': True})
            ch.set_size({'width': 480, 'height': 300})
            sheet.insert_chart(per_row, chart_col, ch, {'x_offset': 12, 'y_offset': 4})
            per_row += 16
