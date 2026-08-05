# Annotate manual screenshots: red boxes / arrows + navy number badges, crop, drop shadow.
import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC = os.path.join(os.path.dirname(__file__), 'screenshots')
OUT = os.path.join(os.path.dirname(__file__), 'annotated')
os.makedirs(OUT, exist_ok=True)

RED = (226, 50, 43)
NAVY = (0, 40, 128)
WHITE = (255, 255, 255)
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 30)
except Exception:
    FONT = ImageFont.load_default()

def box(d, xy, color=RED, w=6):
    d.rectangle(xy, outline=color, width=w)   # square corners (no radius)

def badge(d, center, text, fill=NAVY):
    cx, cy = center; R = 24
    d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=fill, outline=WHITE, width=3)
    tb = d.textbbox((0, 0), text, font=FONT)
    d.text((cx-(tb[2]-tb[0])/2, cy-(tb[3]-tb[1])/2 - tb[1]), text, font=FONT, fill=WHITE)

def arrow(d, start, end, color=RED, w=6):
    d.line([start, end], fill=color, width=w)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    L = 26
    for a in (ang - 0.5, ang + 0.5):
        d.line([end, (end[0] - L * math.cos(a), end[1] - L * math.sin(a))],
               fill=color, width=w)

def add_shadow(im, margin=22, dx=7, dy=8, blur=8):
    """Soft drop shadow on a white margin so the image sits on the page."""
    w, h = im.size
    cw, ch = w + margin * 2, h + margin * 2
    shadow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle(
        [margin + dx, margin + dy, margin + w + dx, margin + h + dy],
        fill=(120, 120, 120, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas = Image.alpha_composite(
        Image.new('RGBA', (cw, ch), (255, 255, 255, 255)), shadow)
    framed = Image.new('RGB', (w + 2, h + 2), (206, 206, 206))  # thin edge
    framed.paste(im, (1, 1))
    canvas.paste(framed, (margin - 1, margin - 1))
    return canvas.convert('RGB')

# config: filename -> {crop:(l,t,r,b) or None, boxes:[(x1,y1,x2,y2)], badges:[(cx,cy,'n')]}
CFG = {
    '02-01_client_open_module.png': {
        'out': '02-01a_open_contacts.png', 'crop': (400, 55, 1520, 400),
        'boxes': [], 'badges': [(822, 175, '1')]},   # existing red box on Contacts
    '02-01_client_select_to_configure.png': {
        'out': '02-01b_pick_client.png', 'crop': (0, 0, 1902, 360),
        'boxes': [(645, 62, 1215, 103)], 'badges': [(1248, 82, '2')]},
    '02-02_vifel-config-tab.png': {
        'out': '02-02_config_tab.png', 'crop': (0, 610, 1264, 900),
        'boxes': [(548, 643, 734, 685)], 'badges': [(766, 664, '3')]},
    '02-03_can-merge-toggle.png': {
        'out': '02-03_can_merge.png', 'crop': (0, 455, 1252, 900),
        'boxes': [(30, 522, 235, 556)], 'badges': [(267, 539, '4')]},
    '02-05_fixed-pallet-fields.png': {
        'out': '02-05_fixed_mode.png', 'crop': (0, 690, 1226, 908),
        'boxes': [(26, 708, 270, 784), (26, 806, 420, 892)],
        'badges': [(298, 746, '5'), (452, 849, '6')]},
    '02-06_multiple-psi-types.png': {
        'out': '02-06_multiple_mode.png', 'crop': (0, 358, 1259, 895),
        'boxes': [(26, 406, 270, 484), (30, 648, 1198, 886)],
        'badges': [(298, 445, '5'), (63, 626, '6')]},
    '02-07_include-regular.png': {
        'out': '02-07_include_regular.png', 'crop': (0, 360, 1252, 624),
        'boxes': [(26, 502, 270, 578)], 'badges': [(298, 540, '7')]},
    # documents section (reuse combined file)
    '02-08_lot-batch-toggles and 02-09_client-saved.png': {
        'out': '02-08a_documents.png', 'crop': (600, 468, 1132, 664),
        'boxes': [(632, 520, 884, 640)], 'badges': [(914, 545, '8')]},

    # ---------------- Chapter 3 ----------------
    '03-00_01open_inventory_module.png': {
        'out': '03-00a_open_inventory.png', 'crop': (300, 55, 1200, 400),
        'boxes': [], 'badges': [(940, 175, '1')]},
    '03-00_02select_rr_operation_type.png': {
        'out': '03-00b_receiving.png', 'crop': (0, 475, 770, 775),
        'boxes': [], 'badges': [(432, 632, '2')]},
    '03-00_03create_new_rr.png': {
        'out': '03-00c_new_rr.png', 'crop': (0, 45, 900, 250),
        'boxes': [], 'badges': [(470, 82, '3')]},
    '03-00_04select_the_client_with_configured_lot or batch # just encode as usual.png': {
        'out': '03-00d_select_client.png', 'crop': (0, 175, 1160, 620),
        'boxes': [(26, 493, 610, 600)], 'badges': [(644, 522, '4')]},
    '03-02_lot-no-field and 03-03_batch-no-field.png.png': {
        'out': '03-02_lot_batch_breakdown.png', 'crop': None,
        'boxes': [], 'badges': [(1360, 104, '5')]},
    '03-04_magic-wizard-lot-batch.png': {
        'out': '03-04_magic_wizard.png', 'crop': None,
        'boxes': [], 'badges': [(1300, 355, '6')]},
    '03-06_quant-prodcode.png': {
        'out': '03-06_validate_done.png', 'crop': (0, 38, 1249, 214),
        'boxes': [], 'badges': [(1035, 111, '7')]},   # badge LEFT of the status box, not on "Done"
    '03-06_01quant-prodcode.png': {
        'out': '03-06b_quant_prodcode.png', 'crop': (0, 0, 1470, 505),
        'boxes': [(900, 160, 1045, 405)], 'badges': [(973, 122, '8')]},
    '03-07_prodcode-on-wr_pallet_breakdown.png': {
        'out': '03-07_prodcode_wr.png', 'crop': None,
        'boxes': [(786, 112, 882, 300)], 'badges': [(834, 320, '9')]},

    # ---------------- Chapter 4 ----------------
    '04-01_rr-lines and 04-02_merge-button.png': {
        'out': '04-01_merge_button.png', 'crop': (0, 110, 1300, 352),
        'boxes': [(880, 170, 1016, 206)], 'badges': [(1052, 188, '1')]},
    '04-03_magic-wizard-open.png': {
        'out': '04-03_magic_merge.png', 'crop': (25, 78, 1520, 545),
        'boxes': [(1136, 261, 1230, 297)], 'badges': [(1262, 278, '2')]},
    '04A-01_fixed-wizard and 04A-02_fixed-confirm.png': {
        'out': '04A-01_fixed_dialog.png', 'crop': (40, 150, 1880, 775),
        'boxes': [(74, 408, 882, 458), (58, 626, 1162, 664)],
        'badges': [(918, 432, '3')]},
    '04A-03_fixed-result.png': {
        'out': '04A-03_fixed_result.png', 'crop': (0, 120, 1580, 690),
        'boxes': [], 'badges': [(1470, 637, '4')]},
    '04B-01_candidates RR lines with multiple special pallet lines its as if its not so different from the fixed - click the merge pallet button.png': {
        'out': '04B-01_multiple_lines.png', 'crop': (0, 105, 1260, 332),
        'boxes': [(792, 168, 934, 204)], 'badges': []},
    '04B-02_merge-existing -upon opening the merg buttn it should show what are special pallet currently inside the stocks and then if the optin is to mrge it with alredy existng stcks then selct from one of line in merg here and it shuld show its contents.png': {
        'out': '04B-02_merge_existing.png', 'crop': (30, 110, 1890, 800),
        'boxes': [(54, 210, 326, 240), (72, 310, 1858, 350)],
        'badges': [(360, 224, '5')]},
    '04B-04_new-special it should fill up all 3 details on confirm it should automatically assign to that line.png': {
        'out': '04B-04_new_special.png', 'crop': (30, 388, 985, 715),
        'boxes': [(52, 400, 326, 428), (55, 498, 625, 616)],
        'badges': [(655, 548, '6')]},
    '04B-05_confirm-result it also has notif on unmerge just click the unmerge button and the orignal PSI should return.png': {
        'out': '04B-05_result.png', 'crop': (0, 40, 1913, 580),
        'boxes': [(1555, 45, 1908, 152)], 'badges': [(1520, 96, '7')]},
}

# context-only recycled shot (NO number badge) for the Chapter 3 reminder
CTX = {'src': '02-08_lot-batch-toggles and 02-09_client-saved.png',
       'out': '02-08a_documents_ctx.png', 'crop': (600, 468, 1132, 664),
       'boxes': [(632, 520, 884, 640)], 'badges': []}

# Un-merge close-up (Chapter 4C) — an ARROW points at the Un-merge button (no box)
UNMERGE = {'src': '04B-05_confirm-result it also has notif on unmerge just click the unmerge button and the orignal PSI should return.png',
           'out': '04C_unmerge.png', 'crop': (600, 470, 1180, 585),
           'boxes': [], 'arrows': [((1000, 568), (854, 532))], 'badges': []}

# WR read-only Lot No./Prodcode (Chapter 5) — box on the columns, NO number badge
WR_CTX = {'src': '03-07_prodcode-on-wr_pallet_breakdown.png',
          'out': '05_wr_readonly.png', 'crop': None,
          'boxes': [(735, 112, 885, 300)], 'badges': []}
# save icon from the same combined file (separate crop/box)
SAVE = {
    'src': '02-08_lot-batch-toggles and 02-09_client-saved.png',
    'out': '02-08b_save.png', 'crop': (0, 62, 780, 138),
    'boxes': [(232, 84, 262, 110)], 'badges': [(300, 96, '9')]}

def _long(p):
    # extended-length prefix so PIL can open paths > 260 chars on Windows
    p = os.path.abspath(p)
    return ('\\\\?\\' + p) if os.name == 'nt' else p

def render(src, cfg):
    im = Image.open(_long(os.path.join(SRC, src))).convert('RGB')
    d = ImageDraw.Draw(im)
    for b in cfg.get('boxes', []):
        box(d, b)
    for a in cfg.get('arrows', []):
        arrow(d, a[0], a[1])
    for (cx, cy, t) in cfg.get('badges', []):
        badge(d, (cx, cy), t)
    if cfg.get('crop'):
        im = im.crop(cfg['crop'])
    im = add_shadow(im)
    im.save(_long(os.path.join(OUT, cfg['out'])))
    print('wrote', cfg['out'], im.size)

for src, cfg in CFG.items():
    render(src, cfg)
render(SAVE['src'], SAVE)
render(CTX['src'], CTX)
render(UNMERGE['src'], UNMERGE)
render(WR_CTX['src'], WR_CTX)
print('DONE')
