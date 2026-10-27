"""
Etichetta buste Fortitude Fabrics — Brother QL-810W, DK-11202 (62 x 100 mm fustellata).
Tutto disegnato in unità "dot" (1 dot = 1/300 in) sull'area stampabile 696 x 1109 dot,
così il raster a 300 dpi è pixel-perfect e il PDF vettoriale coincide 1:1.
"""
import math, sys, os
import cairo, qrcode
import uharfbuzz as hb
import svgelements as S
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 696, 1109                       # area stampabile DK-11202 @300 dpi
MM_PER_DOT = 25.4 / 300
PAGE_W_MM, PAGE_H_MM = 62.0, 100.0
SIZES = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]

# ---------------------------------------------------------------- font
class CairoPen(BasePen):
    def __init__(self, gs, ctx):
        super().__init__(gs); self.ctx = ctx
    def _moveTo(self, p): self.ctx.move_to(*p)
    def _lineTo(self, p): self.ctx.line_to(*p)
    def _curveToOne(self, a, b, c): self.ctx.curve_to(*a, *b, *c)
    def _closePath(self): self.ctx.close_path()

class Font:
    def __init__(self, fn):
        path = os.path.join(HERE, "fonts", fn)
        self.tt = TTFont(path); self.gs = self.tt.getGlyphSet()
        self.upem = self.tt["head"].unitsPerEm
        self.cap = self.tt["OS/2"].sCapHeight
        self.order = self.tt.getGlyphOrder()
        self.hbf = hb.Font(hb.Face(hb.Blob.from_file_path(path)))

    def size_for_cap(self, cap_dots):
        return cap_dots * self.upem / self.cap

    def layout(self, text, cap, tracking=0.0):
        size = self.size_for_cap(cap); sc = size / self.upem
        buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
        hb.shape(self.hbf, buf, {"kern": True, "liga": True})
        x, out = 0.0, []
        for i, p in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[i.codepoint], x + p.x_offset * sc, p.y_offset * sc))
            x += p.x_advance * sc + tracking
        return out, x - tracking, sc

    def width(self, text, cap, tracking=0.0):
        return self.layout(text, cap, tracking)[1]

    def path(self, ctx, text, x, baseline, cap, tracking=0.0, anchor="l"):
        g, w, sc = self.layout(text, cap, tracking)
        if anchor == "r": x -= w
        elif anchor == "c": x -= w / 2
        for name, gx, gy in g:
            ctx.save(); ctx.translate(x + gx, baseline - gy); ctx.scale(sc, -sc)
            self.gs[name].draw(CairoPen(self.gs, ctx)); ctx.restore()
        return w

    def fill(self, ctx, *a, grow=0.0, **k):
        """grow: ingrassamento in dot (compensazione per testo in negativo)."""
        w = self.path(ctx, *a, **k)
        if grow:
            ctx.fill_preserve(); ctx.set_line_width(2 * grow)
            ctx.set_line_join(cairo.LINE_JOIN_MITER); ctx.stroke()
        else:
            ctx.fill()
        return w

BIG_B = Font("BigShoulders-Bold.ttf")
BIG_R = Font("BigShoulders-Regular.ttf")
SANS_B = Font("InstrumentSans-Bold.ttf")
SANS_R = Font("InstrumentSans-Regular.ttf")

# ---------------------------------------------------------------- logo vettoriale (dal kit su Drive)
def load_logo():
    svg = S.SVG.parse(os.path.join(HERE, "logo_v.svg"))
    icon, word, sub = [], [], []
    for e in svg.elements():
        if not isinstance(e, S.Shape): continue
        p = S.Path(e); bb = p.bbox()
        if bb is None or (bb[2] - bb[0]) < 0.05: continue    # punti degeneri
        (icon if bb[3] < 20 else word if bb[1] < 29 else sub).append(p)
    return icon, word, sub

def svg_path(ctx, paths, ox, oy, s, bbox_origin=(0, 0)):
    bx, by = bbox_origin
    for p in paths:
        for seg in p:
            if isinstance(seg, S.Move):
                ctx.move_to(ox + (seg.end.x - bx) * s, oy + (seg.end.y - by) * s)
            elif isinstance(seg, S.Line):
                ctx.line_to(ox + (seg.end.x - bx) * s, oy + (seg.end.y - by) * s)
            elif isinstance(seg, S.Close):
                ctx.close_path()
            else:
                curves = [seg] if isinstance(seg, S.CubicBezier) else (
                    list(seg.as_cubic_curves()) if isinstance(seg, S.Arc) else None)
                if curves is None:  # quadratica
                    q0, q1, q2 = seg.start, seg.control, seg.end
                    c1 = q0 + (q1 - q0) * (2 / 3); c2 = q2 + (q1 - q2) * (2 / 3)
                    curves = [S.CubicBezier(q0, c1, c2, q2)]
                for c in curves:
                    ctx.curve_to(ox + (c.control1.x - bx) * s, oy + (c.control1.y - by) * s,
                                 ox + (c.control2.x - bx) * s, oy + (c.control2.y - by) * s,
                                 ox + (c.end.x - bx) * s, oy + (c.end.y - by) * s)

def bbox_of(paths):
    bbs = [p.bbox() for p in paths]
    return (min(b[0] for b in bbs), min(b[1] for b in bbs),
            max(b[2] for b in bbs), max(b[3] for b in bbs))

ICON, WORD, SUB = load_logo()

# ---------------------------------------------------------------- QR (moduli allineati ai dot)
def qr_matrix(data):
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    q.add_data(data); q.make(fit=True)
    return q.get_matrix()

QR = qr_matrix("https://fortitudefabrics.it")

# ---------------------------------------------------------------- primitive
BLACK, WHITE = (0, 0, 0), (1, 1, 1)
def rect(ctx, x, y, w, h, col=BLACK):
    ctx.set_source_rgb(*col); ctx.rectangle(x, y, w, h); ctx.fill()

def reg_mark(ctx, cx, cy, r, t):
    """Mirino di registro: cerchio + croce, centro pieno."""
    ctx.set_source_rgb(*BLACK)
    ctx.set_line_width(t)
    ctx.arc(cx, cy, r, 0, 2 * math.pi); ctx.stroke()
    arm = r + 10
    rect(ctx, cx - arm, cy - t / 2, 2 * arm, t)
    rect(ctx, cx - t / 2, cy - arm, t, 2 * arm)
    ctx.set_source_rgb(*BLACK); ctx.arc(cx, cy, r * 0.42, 0, 2 * math.pi); ctx.fill()
    # croce in negativo dentro il disco
    ctx.save(); ctx.arc(cx, cy, r * 0.42, 0, 2 * math.pi); ctx.clip()
    rect(ctx, cx - r, cy - t / 2, 2 * r, t, WHITE)
    rect(ctx, cx - t / 2, cy - r, t, 2 * r, WHITE)
    ctx.restore()

def crop_marks(ctx, x0, y0, x1, y1, L=16, t=3, gap=6):
    for (x, y, sx, sy) in [(x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)]:
        # orizzontale e verticale, staccati dall'angolo di "gap"
        hx = x + sx * gap if sx > 0 else x - gap - L
        rect(ctx, hx, y - t / 2, L, t)
        vy = y + sy * gap if sy > 0 else y - gap - L
        rect(ctx, x - t / 2, vy, t, L)

# ---------------------------------------------------------------- composizione
M = 30                      # margine interno (≈2,5 mm oltre il margine macchina)
X0, X1 = M, W - M           # 30 .. 666  -> larghezza utile 636
CW = X1 - X0

def compose(ctx, size_sel):
    rect(ctx, 0, 0, W, H, WHITE)

    # ---- testata: wordmark originale + mirino di registro
    wb = bbox_of(WORD + SUB)
    s_word = 300 / (wb[2] - wb[0])
    head_top = 40
    ctx.set_source_rgb(*BLACK)
    svg_path(ctx, WORD + SUB, X0, head_top, s_word, (wb[0], wb[1])); ctx.fill()
    word_h = (wb[3] - wb[1]) * s_word
    cap_mid = head_top + (28.42 - 22.0) * s_word / 2
    reg_mark(ctx, X1 - 26, cap_mid, 15, 3)

    # ---- pannello nero
    py0, py1 = 126, 590
    rect(ctx, X0, py0, CW, py1 - py0)
    crop_marks(ctx, X0, py0, X1, py1, L=14, t=3, gap=7)

    # colonna verticale "Your brand / your style" (dal sito), giustificata sull'altezza
    col_w = 54
    txt = "YOUR BRAND   YOUR STYLE"
    cap_v = 23
    avail = (py1 - py0) - 2 * 26
    base_w = BIG_R.width(txt, cap_v)
    track = (avail - base_w) / (len(txt) - 1)
    ctx.save()
    ctx.translate(X1 - (col_w - cap_v) / 2, py1 - 26)
    ctx.rotate(-math.pi / 2)
    ctx.set_source_rgb(*WHITE)
    BIG_R.fill(ctx, txt, 0, 0, cap_v, tracking=track, grow=0.35)
    ctx.restore()
    # filetto bianco che separa la colonna
    rect(ctx, X1 - col_w, py0 + 26, 3, (py1 - py0) - 52, WHITE)

    # icona "ricamata": riempita a righe orizzontali come un punto satinato
    ib = bbox_of(ICON)
    icon_h = 372
    s_icon = icon_h / (ib[3] - ib[1])
    icon_w = (ib[2] - ib[0]) * s_icon
    field_x0, field_x1 = X0, X1 - col_w
    ix = round(field_x0 + (field_x1 - field_x0 - icon_w) / 2)
    iy = round(py0 + (py1 - py0 - icon_h) / 2)
    ctx.save()
    svg_path(ctx, ICON, ix, iy, s_icon, (ib[0], ib[1]))
    ctx.clip()
    pitch, line = 8, 5
    ctx.set_source_rgb(*WHITE)
    for y in range(iy - pitch, iy + icon_h + pitch, pitch):
        ctx.rectangle(ix - 4, y, icon_w + 8, line)
    ctx.fill()
    ctx.restore()

    # ---- frase manifesto
    l1, l2 = "SE LO PUOI IMMAGINARE,", "LO POTRAI INDOSSARE."
    trk = 1.5
    cap_s = 10.0
    while BIG_B.width(l1, cap_s + 0.5, trk) <= CW: cap_s += 0.5
    b1 = py1 + 40 + cap_s
    lead = cap_s * 1.32
    ctx.set_source_rgb(*BLACK)
    BIG_B.fill(ctx, l1, X0 - 1, b1, cap_s, tracking=trk)
    BIG_B.fill(ctx, l2, X0 - 1, b1 + lead, cap_s, tracking=trk)
    statement_bottom = b1 + lead

    # ---- dati: taglia + ordine
    ry = round(statement_bottom + 30)
    rect(ctx, X0, ry, CW, 3)
    lab_w = 128
    row_y = ry + 22
    chip_h = 54
    gap = 8
    chip_w = (CW - lab_w - gap * (len(SIZES) - 1)) / len(SIZES)
    lab_cap = 17
    ctx.set_source_rgb(*BLACK)
    SANS_B.fill(ctx, "Taglia", X0, row_y + chip_h / 2 + lab_cap / 2, lab_cap)
    for i, sz in enumerate(SIZES):
        cx = round(X0 + lab_w + i * (chip_w + gap))
        cw = round(X0 + lab_w + (i + 1) * (chip_w + gap) - gap) - cx
        on = (sz == size_sel)
        if on:
            rect(ctx, cx, row_y, cw, chip_h)
        else:
            rect(ctx, cx, row_y, cw, chip_h)
            rect(ctx, cx + 3, row_y + 3, cw - 6, chip_h - 6, WHITE)
        ctx.set_source_rgb(*(WHITE if on else BLACK))
        BIG_B.fill(ctx, sz, cx + cw / 2, row_y + chip_h / 2 + 26 / 2, 26, tracking=1.5,
                   anchor="c", grow=0.4 if on else 0.0)

    ord_y = row_y + chip_h + 30
    ctx.set_source_rgb(*BLACK)
    SANS_B.fill(ctx, "Ordine", X0, ord_y + lab_cap, lab_cap)
    rect(ctx, X0 + lab_w, ord_y + lab_cap + 4, CW - lab_w, 3)

    # ---- piede: QR + contatti
    fy = ord_y + lab_cap + 4 + 34
    rect(ctx, X0, fy, CW, 3)
    n = len(QR); mod = 4
    qs = n * mod
    qy = H - M - qs
    qx = X0
    for r, row in enumerate(QR):
        for c, v in enumerate(row):
            if v: ctx.rectangle(qx + c * mod, qy + r * mod, mod, mod)
    ctx.set_source_rgb(*BLACK); ctx.fill()

    # blocco testo giustificato in verticale sull'altezza del QR
    tx = qx + qs + 28
    SANS_B.fill(ctx, "fortitudefabrics.it", tx, qy + 24, 24)
    SANS_R.fill(ctx, "hello@fortitudefabrics.it", tx, qy + qs - 30, 15)
    SANS_R.fill(ctx, "Personalizzato a Piacenza, Italia", tx, qy + qs, 15)
    return {"qr_top": qy, "footer_rule": fy, "gap_rule_qr": qy - fy - 3}

# ---------------------------------------------------------------- output
def render_png(size_sel, fn):
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surf); ctx.set_antialias(cairo.ANTIALIAS_NONE)
    info = compose(ctx, size_sel)
    surf.flush()
    img = Image.frombuffer("RGBA", (W, H), bytes(surf.get_data()), "raw", "BGRA", 0, 1)
    bw = img.convert("L").point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE)
    bw.save(fn, dpi=(300, 300))
    return info

def render_pdf(sizes, fn):
    pw, ph = PAGE_W_MM / 25.4 * 72, PAGE_H_MM / 25.4 * 72
    surf = cairo.PDFSurface(fn, pw, ph)
    ox = (PAGE_W_MM - W * MM_PER_DOT) / 2 / 25.4 * 72
    oy = (PAGE_H_MM - H * MM_PER_DOT) / 2 / 25.4 * 72
    for sz in sizes:
        ctx = cairo.Context(surf)
        ctx.set_source_rgb(1, 1, 1); ctx.paint()
        ctx.translate(ox, oy); ctx.scale(72 / 300, 72 / 300)
        compose(ctx, sz)
        surf.show_page()
    surf.finish()

if __name__ == "__main__":
    out = os.path.join(HERE, "out"); os.makedirs(out, exist_ok=True)
    variants = SIZES + [None]
    for sz in variants:
        tag = sz or "VUOTA"
        info = render_png(sz, os.path.join(out, f"FF_etichetta_{tag}_696x1109_300dpi.png"))
    render_pdf(variants, os.path.join(out, "FF_etichette_62x100mm_tutte-le-taglie.pdf"))
    print("ok", info)
