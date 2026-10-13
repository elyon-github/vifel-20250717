# -*- coding: utf-8 -*-
"""Shared look-and-feel for the Inbound / Outbound client log sheets.

One place decides colours, fonts and layout so the two sheets stay siblings:
the Inbound is sage-green, the Outbound is muted brick, both deliberately
low-saturation — these are read for long stretches, and vivid fills tire the
eye and make the numbers harder to pick out.

Readability choices that differ from a plain dump:
  * text left-aligned, numbers right-aligned (the eye scans a number column
    by its last digit; centring destroys that)
  * banded rows, so a wide row stays on one line as you track across
  * a frozen header AND first columns, so the pallet/date stays visible
  * a totals strip above the header that responds to the filter
"""

# Accounting-style number formats (kept from the client's own workbook)
FMT_INT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
FMT_DEC = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
FMT_DATE = '[$-1009]d\\-mmm\\-yy;@'

BODY_FONT = 'Aptos Narrow'

# Muted, low-saturation palettes. header = strip behind the column names,
# band = alternating row fill, accent = totals strip.
THEMES = {
    'green': {
        'header': '#4F6F52',   # deep sage
        'band': '#F2F6F1',     # barely-there green tint
        'accent': '#E8EFE6',
        'title': '#3A5340',
        'rule': '#C9D8C6',
    },
    'red': {
        'header': '#8C4A4A',   # muted brick
        'band': '#FAF3F2',
        'accent': '#F3E6E4',
        'title': '#6E3A3A',
        'rule': '#E0C9C6',
    },
}

# Status pill colours (Inbound "Inventory Status")
STATUS_COLORS = {
    'INV': {'bg': '#DFF0D8', 'fg': '#2F6B34'},    # still has stock
    'ZERO': {'bg': '#EDEDED', 'fg': '#8A8A8A'},   # fully withdrawn - recedes
}


def build_formats(workbook, theme):
    """Return the format dict used by both log sheets."""
    t = THEMES[theme]
    base = {'font_name': BODY_FONT, 'font_size': 10, 'valign': 'vcenter'}

    def mk(**kw):
        return workbook.add_format(dict(base, **kw))

    def banded(**kw):
        """A (plain, banded) pair so rows can alternate."""
        return mk(**kw), mk(bg_color=t['band'], **kw)

    f = {
        'theme': t,
        'title': workbook.add_format({
            'font_name': BODY_FONT, 'font_size': 16, 'bold': True,
            'font_color': t['title']}),
        'subtitle': workbook.add_format({
            'font_name': BODY_FONT, 'font_size': 9, 'italic': True,
            'font_color': '#767676'}),
        'header': workbook.add_format(dict(
            base, bg_color=t['header'], font_color='#FFFFFF', bold=True,
            align='center', text_wrap=True, border=1,
            border_color=t['header'])),
        'total_label': workbook.add_format(dict(
            base, bg_color=t['accent'], bold=True, align='left',
            font_color=t['title'], top=1, bottom=1, border_color=t['rule'])),
        'total_int': workbook.add_format(dict(
            base, bg_color=t['accent'], bold=True, align='right',
            num_format=FMT_INT, font_color=t['title'],
            top=1, bottom=1, border_color=t['rule'])),
        'total_dec': workbook.add_format(dict(
            base, bg_color=t['accent'], bold=True, align='right',
            num_format=FMT_DEC, font_color=t['title'],
            top=1, bottom=1, border_color=t['rule'])),
        'total_blank': workbook.add_format(dict(
            base, bg_color=t['accent'], top=1, bottom=1,
            border_color=t['rule'])),
    }
    # body cells: text left, numbers right, dates centred
    f['text'] = banded(align='left', indent=1)
    f['num_int'] = banded(align='right', num_format=FMT_INT)
    f['num_dec'] = banded(align='right', num_format=FMT_DEC)
    f['date'] = banded(align='center', num_format=FMT_DATE)
    f['key'] = banded(align='left', indent=1, bold=True)   # PSI / Transfer

    # status pills
    f['status'] = {}
    for name, c in STATUS_COLORS.items():
        f['status'][name] = (
            workbook.add_format(dict(base, align='center', bold=True,
                                     bg_color=c['bg'], font_color=c['fg'])),
            workbook.add_format(dict(base, align='center', bold=True,
                                     bg_color=c['bg'], font_color=c['fg'])),
        )
    return f


def col_a1(col, row):
    """0-based (col,row) -> 'B4' style reference."""
    letter = ''
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        letter = chr(65 + rem) + letter
    return '%s%d' % (letter, row + 1)


# --- filter buttons -------------------------------------------------------
# Excel "slicers" cannot be produced by xlsxwriter, so the buttons are styled
# internal hyperlinks: one per view, each jumping to a sheet that is already
# filtered. Clicking is the same gesture the user wanted, and it survives
# being opened in LibreOffice / Google Sheets, which slicers do not.
def build_button_formats(workbook, theme):
    t = THEMES[theme]
    base = {'font_name': BODY_FONT, 'font_size': 10, 'bold': True,
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'border_color': t['rule']}
    return {
        'active': workbook.add_format(dict(
            base, bg_color=t['header'], font_color='#FFFFFF')),
        'link': workbook.add_format(dict(
            base, bg_color='#FFFFFF', font_color=t['title'], underline=0)),
    }


def write_button_bar(sheet, row, first_col, buttons, fmts, active_label):
    """Write a row of link-buttons.

    buttons: list of (label, target_sheet_name). The button whose label equals
    active_label is drawn as the current view (no link).
    """
    for i, (label, target) in enumerate(buttons):
        col = first_col + i
        if label == active_label:
            sheet.write(row, col, label, fmts['active'])
        else:
            sheet.write_url(row, col, "internal:'%s'!A1" % target,
                            fmts['link'], label)
