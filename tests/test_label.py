import io
import warnings

import pytest
from PIL import Image, ImageChops

from app.label.label import (CW, LAB_W, SIZES, W, H, X0, X1, Etichetta, ROW_CAP_MIN,
                             png_bytes, render_label, render_pdf)

LUNGA = ("Felpa girocollo con cappuccio e zip lunga, ricamo petto e stampa DTF "
         "schiena, grigio melange, taglio unisex, cotone organico 280 g")
COMMESSA_LUNGA = "Associazione Sportiva Dilettantistica Polisportiva Piacentina"


def _diff_bbox(a, b):
    return ImageChops.difference(a.convert("L"), b.convert("L")).getbbox()


def test_formato_png():
    img = render_label("Rossi Srl", "T-shirt 150 g bianco", "M")
    assert img.size == (W, H) == (696, 1109)
    assert img.mode == "1"
    re = Image.open(io.BytesIO(png_bytes(img)))
    assert re.mode == "1"
    assert tuple(round(v) for v in re.info["dpi"]) == (300, 300)


def test_solo_bianco_e_nero():
    img = render_label("Rossi Srl", "T-shirt", "L").convert("L")
    assert set(img.tobytes()) <= {0, 255}


@pytest.mark.parametrize("taglia", SIZES)
def test_taglia_attiva_in_negativo(taglia):
    boxes = {}
    img = render_label("Rossi Srl", "T-shirt", taglia, boxes=boxes).convert("L")
    x0, y0, x1, y1 = boxes["taglie"]
    chip_w = (x1 - x0 - 8 * (len(SIZES) - 1)) / len(SIZES)

    def nero(i):  # quota di nero dentro la casella i (bordo escluso)
        cx = round(x0 + i * (chip_w + 8))
        reg = img.crop((cx + 4, y0 + 4, cx + round(chip_w) - 4, y1 - 4))
        px = reg.tobytes()
        return px.count(0) / len(px)

    for i, sz in enumerate(SIZES):
        if sz == taglia:
            assert nero(i) > 0.6, sz
        else:
            assert nero(i) < 0.4, sz


def test_taglia_minuscola_riconosciuta():
    a = render_label("X", "Y", "xl")
    b = render_label("X", "Y", "XL")
    assert _diff_bbox(a, b) is None


def test_taglia_personalizzata_casella_grande():
    boxes = {}
    img = render_label("Scuola", "T-shirt bimbo", "8-10A", boxes=boxes).convert("L")
    x0, y0, x1, y1 = boxes["taglie"]
    assert x1 - x0 >= CW - LAB_W - 1
    reg = img.crop((int(x0), int(y0), int(x1), int(y1))).tobytes()
    assert reg.count(0) / len(reg) > 0.6          # casella piena
    # il testo bianco c'è ed è grande: altezza del bianco >= 30 dot
    ink = img.crop((int(x0), int(y0), int(x1), int(y1))).getbbox()   # bbox dei pixel bianchi
    assert ink and ink[3] - ink[1] >= 30


def test_testo_lunghissimo_non_esce_e_non_sovrappone():
    boxes = {}
    vuota = render_label("", "", "M")
    piena = render_label(COMMESSA_LUNGA, LUNGA, "M", boxes=boxes)
    assert boxes["riga_cap"][0] >= ROW_CAP_MIN
    bb = _diff_bbox(vuota, piena)
    assert bb is not None
    x0, y0, x1, y1 = bb
    # tutto il testo nuovo sta nella colonna valori, sotto le caselle e sopra il filetto
    assert x0 >= X0 + LAB_W and x1 <= X1
    assert y0 > boxes["taglie"][3]
    assert y1 <= boxes["filetto_riga"][1]


def test_testo_corto_corpo_pieno():
    boxes = {}
    render_label("Rossi Srl", "T-shirt 150 g bianco", "M", boxes=boxes)
    assert boxes["riga_cap"][0] == 20.0


def test_solo_articolo():
    a = render_label("Rossi Srl", "T-shirt", "M", mostra_commessa=False)
    b = render_label("", "T-shirt", "M")
    assert _diff_bbox(a, b) is None


def test_contatore_solo_se_attivo():
    a = render_label("R", "T", "M", indice=3, totale=5)
    b = render_label("R", "T", "M")
    assert _diff_bbox(a, b) is None
    boxes = {}
    c = render_label("R", "T", "M", indice=3, totale=5, contatore=True, boxes=boxes)
    bb = _diff_bbox(b, c)
    assert bb is not None and bb[3] < boxes["pannello"][1]   # in testata, sopra il pannello
    assert bb[2] < boxes["mirino"][0]                        # non tocca il mirino


def test_pdf_pagine_62x100():
    from pypdf import PdfReader
    pdf = render_pdf([Etichetta("Rossi Srl", "T-shirt", t) for t in ["S", "M", "L"]])
    r = PdfReader(io.BytesIO(pdf))
    assert len(r.pages) == 3
    for p in r.pages:
        w_mm = float(p.mediabox.width) / 72 * 25.4
        h_mm = float(p.mediabox.height) / 72 * 25.4
        assert abs(w_mm - 62) < 0.05 and abs(h_mm - 100) < 0.05


def test_brother_ql_converte_senza_warning(caplog):
    # import fuori da caplog: brother_ql 0.9 logga una deprecazione interna all'import
    from brother_ql.conversion import convert
    from brother_ql.raster import BrotherQLRaster
    caplog.clear()
    img = render_label("Rossi Srl", "T-shirt 150 g bianco", "M")
    qlr = BrotherQLRaster("QL-810W")
    qlr.exception_on_warning = True
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        data = convert(qlr, [img], "62x100", cut=True, dither=False,
                       compress=False, red=False, rotate="0", dpi_600=False, hq=True)
    assert len(data) > 1000
    assert not [r for r in caplog.records
                if r.levelname in ("WARNING", "ERROR") and r.name != "brother_ql.devicedependent"]
