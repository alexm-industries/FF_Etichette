"""
Etichetta buste Fortitude Fabrics — Brother QL-810W, DK-11202 (62 x 100 mm fustellata).
Tutto disegnato in unità "dot" (1 dot = 1/300 in) sull'area stampabile 696 x 1109 dot,
così il raster a 300 dpi è pixel-perfect e il PDF vettoriale coincide 1:1.

Versione parametrica del template approvato (docs/template/genera_etichetta.py):
la grafica è la stessa al dot; cambiano solo la riga dati (Articolo al posto di Ordine),
la casella per le taglie personalizzate e il contatore opzionale.
"""
from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass
from typing import Iterable, Optional

import cairo
import qrcode
import svgelements as S
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
W, H = 696, 1109                       # area stampabile DK-11202 @300 dpi
DPI = 300
MM_PER_DOT = 25.4 / DPI
PAGE_W_MM, PAGE_H_MM = 62.0, 100.0
SIZES = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
ELLIPSIS = "…"
# Compensazione dell'ingrassamento termico. La QL-810W allarga i segni neri di circa
# mezzo dot per lato (misurato su una stampa reale: filetti da 3 dot stampati a 3,5-4),
# e le aperture da 1 dot del grassetto piccolo (S, e, a) si chiudono. Con compensazione > 0
# le zone dati (taglie, riga Articolo, etichette di riga, sito, contatore) vengono disegnate
# a 4x e un dot diventa nero solo se è coperto almeno al (50% + compensazione): i bordi dei
# segni arretrano di circa `compensazione` dot. Il resto (logo, pannello, frase, testo
# regular da 1 dot del piede, QR) resta identico al template.
COMPENSAZIONE_DEFAULT = 0.0
SUPER = 4


@dataclass(frozen=True)
class Etichetta:
    """Dati di una singola etichetta."""
    commessa: str = ""
    descrizione: str = ""
    taglia: Optional[str] = None
    indice: Optional[int] = None       # 1-based, per il contatore "3/5"
    totale: Optional[int] = None
    mostra_commessa: bool = True       # riga = "articolo · commessa" oppure solo articolo
    contatore: bool = False
    compensazione: float = COMPENSAZIONE_DEFAULT   # 0 … 0,4: quota di copertura in più per il nero


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
        path = os.path.join(ASSETS, "fonts", fn)
        self.tt = TTFont(path); self.gs = self.tt.getGlyphSet()
        self.upem = self.tt["head"].unitsPerEm
        self.cap = self.tt["OS/2"].sCapHeight
        self.desc = -self.tt["OS/2"].sTypoDescender
        self.order = self.tt.getGlyphOrder()
        self.hbf = hb.Font(hb.Face(hb.Blob.from_file_path(path)))

    def size_for_cap(self, cap_dots):
        return cap_dots * self.upem / self.cap

    def descender(self, cap_dots):
        return self.desc * cap_dots / self.cap

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
        if not text:
            return 0.0
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


# ---------------------------------------------------------------- logo vettoriale
def load_logo():
    svg = S.SVG.parse(os.path.join(ASSETS, "logo_v.svg"))
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
        hx = x + sx * gap if sx > 0 else x - gap - L
        rect(ctx, hx, y - t / 2, L, t)
        vy = y + sy * gap if sy > 0 else y - gap - L
        rect(ctx, x - t / 2, vy, t, L)


# ---------------------------------------------------------------- adattamento testo
ROW_CAP_MAX = 20.0      # corpo di partenza della riga Articolo (cap height, dot)
ROW_CAP_MIN = 14.0      # minimo leggibile richiesto
CUSTOM_CAP_MAX = 36.0   # taglia personalizzata nella casella grande
CUSTOM_CAP_MIN = 18.0


def _truncate(font, text, cap, max_w):
    """Taglia il testo e aggiunge "…" finché non sta in max_w."""
    if font.width(text, cap) <= max_w:
        return text
    t = text.rstrip()
    while t and font.width(t.rstrip() + ELLIPSIS, cap) > max_w:
        t = t[:-1]
    return (t.rstrip() + ELLIPSIS) if t else ""


def fit_row(articolo, commessa, max_w):
    """Riga dati: articolo in grassetto, " · commessa" in tondo.
    Riduce il corpo fino a ROW_CAP_MIN, poi tronca (prima la commessa, poi l'articolo).
    Ritorna (cap, parte_bold, parte_regular)."""
    articolo = " ".join((articolo or "").split())
    commessa = " ".join((commessa or "").split())
    tail = f"  ·  {commessa}" if commessa else ""
    if not articolo and commessa:
        articolo, tail = commessa, ""

    def w(cap, a, t):
        return SANS_B.width(a, cap) + SANS_R.width(t, cap)

    cap = ROW_CAP_MAX
    while cap > ROW_CAP_MIN and w(cap, articolo, tail) > max_w:
        cap -= 0.5
    if w(cap, articolo, tail) <= max_w:
        return cap, articolo, tail
    # al minimo: tronca prima la commessa (se resta qualcosa di sensato), poi l'articolo
    a_w = SANS_B.width(articolo, cap)
    if tail and a_w + SANS_R.width(f"  ·  X{ELLIPSIS}", cap) <= max_w:
        return cap, articolo, _truncate(SANS_R, tail, cap, max_w - a_w)
    return cap, _truncate(SANS_B, articolo, cap, max_w), ""


def fit_cap(font, text, cap_max, cap_min, max_w, tracking=0.0):
    cap = cap_max
    while cap > cap_min and font.width(text, cap, tracking) > max_w:
        cap -= 0.5
    return cap


# ---------------------------------------------------------------- composizione
M = 30                      # margine interno (≈2,5 mm oltre il margine macchina)
X0, X1 = M, W - M           # 30 .. 666  -> larghezza utile 636
CW = X1 - X0
LAB_W = 128                 # colonna etichette "Taglia" / "Articolo"


def normalizza_taglia(taglia):
    if taglia is None:
        return None
    t = " ".join(str(taglia).split())
    if not t:
        return None
    up = t.upper()
    return up if up in SIZES else t


def compose(ctx, e: Etichetta, boxes: Optional[dict] = None):
    """Disegna l'etichetta. Se `boxes` è un dict, ci registra i riquadri degli elementi
    (x0, y0, x1, y1) per i test di non sovrapposizione."""
    box = (lambda k, *b: boxes.__setitem__(k, b)) if boxes is not None else (lambda *a: None)
    rect(ctx, 0, 0, W, H, WHITE)

    # ---- testata: wordmark originale + mirino di registro
    wb = bbox_of(WORD + SUB)
    s_word = 300 / (wb[2] - wb[0])
    head_top = 40
    ctx.set_source_rgb(*BLACK)
    svg_path(ctx, WORD + SUB, X0, head_top, s_word, (wb[0], wb[1])); ctx.fill()
    word_h = (wb[3] - wb[1]) * s_word
    box("logo", X0, head_top, X0 + 300, head_top + word_h)
    cap_mid = head_top + (28.42 - 22.0) * s_word / 2
    reg_mark(ctx, X1 - 26, cap_mid, 15, 3)
    box("mirino", X1 - 26 - 25, cap_mid - 25, X1 - 26 + 25, cap_mid + 25)

    # contatore opzionale "3/5": in testata, a sinistra del mirino, sulla linea del wordmark
    if e.contatore and e.indice and e.totale:
        cnt = f"{e.indice}/{e.totale}"
        c_cap = (28.42 - 22.0) * s_word * 0.62
        c_right = X1 - 26 - 25 - 14
        c_base = cap_mid + c_cap / 2
        c_w = BIG_B.width(cnt, c_cap, 1.5)
        ctx.set_source_rgb(*BLACK)
        BIG_B.fill(ctx, cnt, c_right, c_base, c_cap, tracking=1.5, anchor="r")
        box("contatore", c_right - c_w, c_base - c_cap, c_right, c_base)

    # ---- pannello nero
    py0, py1 = 126, 590
    rect(ctx, X0, py0, CW, py1 - py0)
    crop_marks(ctx, X0, py0, X1, py1, L=14, t=3, gap=7)
    box("pannello", X0 - 21, py0 - 21, X1 + 21, py1 + 21)

    # colonna verticale "Your brand / your style", giustificata sull'altezza
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
    box("frase", X0 - 1, b1 - cap_s, X1, statement_bottom)

    # ---- dati: taglia
    ry = round(statement_bottom + 30)
    rect(ctx, X0, ry, CW, 3)
    row_y = ry + 22
    chip_h = 54
    gap = 8
    lab_cap = 17
    ctx.set_source_rgb(*BLACK)
    SANS_B.fill(ctx, "Taglia", X0, row_y + chip_h / 2 + lab_cap / 2, lab_cap)

    taglia = normalizza_taglia(e.taglia)
    if taglia is not None and taglia not in SIZES:
        # taglia personalizzata: un'unica casella grande in negativo
        bx, bw = X0 + LAB_W, CW - LAB_W
        rect(ctx, bx, row_y, bw, chip_h)
        trk_c = 2.0
        c_cap = fit_cap(BIG_B, taglia, CUSTOM_CAP_MAX, CUSTOM_CAP_MIN, bw - 2 * 20, trk_c)
        shown = _truncate(BIG_B, taglia, c_cap, bw - 2 * 20) if BIG_B.width(taglia, c_cap, trk_c) > bw - 40 else taglia
        ctx.set_source_rgb(*WHITE)
        BIG_B.fill(ctx, shown, bx + bw / 2, row_y + chip_h / 2 + c_cap / 2, c_cap,
                   tracking=trk_c, anchor="c", grow=0.4)
        box("taglie", bx, row_y, bx + bw, row_y + chip_h)
    else:
        chip_w = (CW - LAB_W - gap * (len(SIZES) - 1)) / len(SIZES)
        for i, sz in enumerate(SIZES):
            cx = round(X0 + LAB_W + i * (chip_w + gap))
            cw = round(X0 + LAB_W + (i + 1) * (chip_w + gap) - gap) - cx
            on = (sz == taglia)
            rect(ctx, cx, row_y, cw, chip_h)
            if not on:
                rect(ctx, cx + 3, row_y + 3, cw - 6, chip_h - 6, WHITE)
            ctx.set_source_rgb(*(WHITE if on else BLACK))
            BIG_B.fill(ctx, sz, cx + cw / 2, row_y + chip_h / 2 + 26 / 2, 26, tracking=1.5,
                       anchor="c", grow=0.4 if on else 0.0)
        box("taglie", X0 + LAB_W, row_y, X1, row_y + chip_h)

    # ---- dati: riga Articolo (sostituisce "Ordine ____"; il filetto resta dov'era)
    ord_y = row_y + chip_h + 30
    rule_y = ord_y + lab_cap + 4
    # linea di base comune, alzata quanto serve perché i discendenti non tocchino il filetto
    base = rule_y - 5 - SANS_B.descender(ROW_CAP_MAX)
    ctx.set_source_rgb(*BLACK)
    SANS_B.fill(ctx, "Articolo", X0, base, lab_cap)
    tx = X0 + LAB_W
    max_w = X1 - tx
    commessa = e.commessa if e.mostra_commessa else ""
    cap, a_txt, t_txt = fit_row(e.descrizione, commessa, max_w)
    wa = SANS_B.fill(ctx, a_txt, tx, base, cap) if a_txt else 0.0
    wt = SANS_R.fill(ctx, t_txt, tx + wa, base, cap) if t_txt else 0.0
    box("riga", tx, base - cap, tx + wa + wt, base + SANS_B.descender(cap))
    box("riga_cap", cap)
    rect(ctx, X0 + LAB_W, rule_y, CW - LAB_W, 3)
    box("filetto_riga", X0 + LAB_W, rule_y, X1, rule_y + 3)
    box("etichette_riga", X0 - 2, row_y, X0 + LAB_W - 4, rule_y)

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

    tx = qx + qs + 28
    url_w = SANS_B.fill(ctx, "fortitudefabrics.it", tx, qy + 24, 24)
    box("url", tx - 2, qy + 24 - 24 - 2, tx + url_w + 2, qy + 24 + SANS_B.descender(24) + 2)
    SANS_R.fill(ctx, "hello@fortitudefabrics.it", tx, qy + qs - 30, 15)
    SANS_R.fill(ctx, "Personalizzato a Piacenza, Italia", tx, qy + qs, 15)
    box("piede", X0, fy, X1, H - M)


# ---------------------------------------------------------------- output
def render_label(commessa="", descrizione="", taglia=None, indice=None, totale=None,
                 mostra_commessa=True, contatore=False, boxes=None,
                 compensazione=COMPENSAZIONE_DEFAULT) -> Image.Image:
    """Etichetta come PIL.Image modalità "1", 696x1109, 300 dpi, senza antialias."""
    e = Etichetta(commessa, descrizione, taglia, indice, totale, mostra_commessa, contatore,
                  compensazione)
    return render_etichetta(e, boxes)


def render_etichetta(e: Etichetta, boxes=None) -> Image.Image:
    b = {} if boxes is None else boxes
    bw = _raster(e, 1, 128, b)
    if e.compensazione > 0:
        # nero solo dove la copertura supera 50% + compensazione
        soglia = round(255 * (0.5 - min(e.compensazione, 0.45)))
        fine = _raster(e, SUPER, soglia, {})
        for k in ("taglie", "riga", "etichette_riga", "url", "contatore"):
            if k in b:
                x0, y0, x1, y1 = b[k]
                r = (max(0, math.floor(x0) - 1), max(0, math.floor(y0) - 1),
                     min(W, math.ceil(x1) + 1), min(H, math.ceil(y1) + 1))
                bw.paste(fine.crop(r), r[:2])
    bw.info["dpi"] = (DPI, DPI)
    return bw


def _raster(e: Etichetta, k: int, soglia: int, boxes: dict) -> Image.Image:
    """Disegna a k volte la risoluzione, media k x k campioni per dot, soglia a 1 bit."""
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W * k, H * k)
    ctx = cairo.Context(surf); ctx.set_antialias(cairo.ANTIALIAS_NONE)
    ctx.scale(k, k)
    compose(ctx, e, boxes)
    surf.flush()
    img = Image.frombuffer("RGBA", (W * k, H * k), bytes(surf.get_data()), "raw", "BGRA", 0, 1).convert("L")
    if k > 1:
        img = img.reduce(k)
    return img.point(lambda v: 255 if v >= soglia else 0).convert("1", dither=Image.Dither.NONE)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO(); img.save(buf, "PNG", dpi=(DPI, DPI)); return buf.getvalue()


def render_pdf(etichette: Iterable[Etichetta]) -> bytes:
    """PDF vettoriale, una pagina 62x100 mm per etichetta, nell'ordine dato."""
    buf = io.BytesIO()
    pw, ph = PAGE_W_MM / 25.4 * 72, PAGE_H_MM / 25.4 * 72
    surf = cairo.PDFSurface(buf, pw, ph)
    ox = (PAGE_W_MM - W * MM_PER_DOT) / 2 / 25.4 * 72
    oy = (PAGE_H_MM - H * MM_PER_DOT) / 2 / 25.4 * 72
    for e in etichette:
        ctx = cairo.Context(surf)
        ctx.set_source_rgb(1, 1, 1); ctx.paint()
        ctx.translate(ox, oy); ctx.scale(72 / DPI, 72 / DPI)
        compose(ctx, e)
        surf.show_page()
    surf.finish()
    return buf.getvalue()
