"""Import della scheda di produzione in PDF: scheda finta disegnata con le stesse tabelle di quella
reale, come PDF con testo (esportato da Word) e come scansione/foto (letta con l'OCR)."""
import io

import cairo
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.importers.pdf import ImporterPdf, Parola, interpreta, righe, tesseract

ART1 = dict(n=1, pz=30, dati=[("Articolo", "T-shirt girocollo"), ("Marca e codice", "JT150"),
                               ("Colore capo", "Bianco"), ("Tecnica", "DTF")],
            taglie=["XS", "S", "M", "L", "XL", "XXL", "3XL"], quantita=[0, 1, 6, 17, 4, 2, 0], totale=30)
ART2 = dict(n=2, pz=13, dati=[("Articolo", "Felpa cappuccio"), ("Marca e codice", "-"),
                               ("Colore capo", "Blu navy"), ("Tecnica", "Ricamo")],
            taglie=["XS", "S", "M", "L", "XL", "XXL", "3XL"], quantita=[2, 0, 10, 0, 0, 0, 1], totale=13)


def _tabella(ctx, x, y, larghezze, righe_, h=22):
    for r, valori in enumerate(righe_):
        cx = x
        for w, v in zip(larghezze, valori):
            ctx.rectangle(cx, y + r * h, w, h)
            ctx.stroke()
            if v:
                ctx.move_to(cx + 5, y + r * h + 15)
                ctx.show_text(v)
            cx += w
    return y + len(righe_) * h


def _testo(ctx, x, y, t, size=11):
    ctx.set_font_size(size)
    ctx.move_to(x, y)
    ctx.show_text(t)
    ctx.set_font_size(10)


def _articolo(ctx, y, a):
    _testo(ctx, 40, y, f"Articolo {a['n']}  -  {a['pz']} pz", 13)
    y += 12
    # riga "Mockup fronte" con la tabella dei dati annidata a destra
    alto = 22 * len(a["dati"])
    ctx.rectangle(40, y, 515, alto); ctx.stroke()
    _testo(ctx, 45, y + 15, "Mockup fronte", 10)
    _tabella(ctx, 260, y, [110, 185], a["dati"])
    y += alto + 26
    _testo(ctx, 40, y, "Stampe")
    y = _tabella(ctx, 40, y + 6, [120, 160, 70, 165],
                 [["Posizione", "Soggetto", "Tecnica", "Colori"], ["Cuore sinistro", "Logo", "DTF", "Come da logo"]])
    y += 24
    _testo(ctx, 40, y, "Quantità per taglia")
    q = [str(v) if v else "" for v in a["quantita"]] + [str(a["totale"])]
    return _tabella(ctx, 40, y + 6, [60] * len(a["taglie"]) + [95], [a["taglie"] + ["Totale"], q]) + 40


def _disegna(ctx, pagina):
    ctx.set_source_rgb(1, 1, 1); ctx.paint(); ctx.set_source_rgb(0, 0, 0)
    ctx.select_font_face("Arial"); ctx.set_line_width(0.6); ctx.set_font_size(10)
    y = 50
    if pagina == 0:
        _testo(ctx, 40, y, "FORTITUDE FABRICS   Scheda di produzione", 14)
        y = _tabella(ctx, 40, y + 14, [100, 160, 100, 155],
                     [["Cliente", "Batarò Valtidone", "Data ordine", "23/09/2026"],
                      ["Referente", "", "Telefono", ""], ["Preparata da", "Vlad", "Assegnata a", "Irina"]]) + 36
        _articolo(ctx, y, ART1)
    else:
        _articolo(ctx, y, ART2)


def scheda_pdf() -> bytes:
    buf = io.BytesIO()
    s = cairo.PDFSurface(buf, 595, 842)
    ctx = cairo.Context(s)
    for pg in (0, 1):
        _disegna(ctx, pg)
        ctx.show_page()
    s.finish()
    return buf.getvalue()


def scheda_immagini(dpi=200):
    out = []
    for pg in (0, 1):
        f = dpi / 72
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, round(595 * f), round(842 * f))
        ctx = cairo.Context(s); ctx.scale(f, f)
        _disegna(ctx, pg)
        png = io.BytesIO(); s.write_to_png(png)
        out.append(Image.open(io.BytesIO(png.getvalue())).convert("RGB"))
    return out


def scheda_scansione() -> bytes:
    imgs = scheda_immagini()
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=200)
    return buf.getvalue()


def _verifica(c, due_articoli=True):
    assert c["nome"] in ("Batarò Valtidone", "Bataro Valtidone")
    a = c["articoli"]
    assert a[0]["descrizione"] == "T-shirt girocollo bianco JT150"
    assert {r["taglia"]: r["copie"] for r in a[0]["righe"]} == {"S": 1, "M": 6, "L": 17, "XL": 4, "XXL": 2}
    if due_articoli:
        assert a[1]["descrizione"] == "Felpa cappuccio blu navy"
        assert {r["taglia"]: r["copie"] for r in a[1]["righe"]} == {"XS": 2, "M": 10, "3XL": 1}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    from app.main import app
    return TestClient(app)


def test_pdf_con_testo(client):
    r = client.post("/api/import", files={"file": ("scheda.pdf", scheda_pdf(), "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    _verifica(d["commessa"])
    assert d["avvisi"] == []


def test_totale_che_non_torna():
    ImporterPdf()  # registrato
    p = lambda t, x, y: Parola(t, x, y, x + 8 * len(t), y + 10)
    pagina = [p("Cliente", 40, 50), p("Rossi", 150, 50),
              p("Articolo", 40, 90), p("1", 90, 90), p("-", 100, 90), p("5", 110, 90), p("pz", 120, 90),
              p("Articolo", 40, 110), p("Polo", 150, 110),
              *[p(t, 40 + 60 * k, 140) for k, t in enumerate(["S", "M", "L", "Totale"])],
              p("2", 40, 156), p("2", 100, 156), p("5", 220, 156)]
    nome, articoli, avvisi = interpreta([pagina])
    assert nome == "Rossi" and articoli[0]["capi"] == {"S": 2, "M": 2} and articoli[0]["tot"] == 5
    from app.importers.word import componi_scheda
    r = componi_scheda(articoli, nome, avvisi, "x.pdf")
    assert any("Totale della tabella è 5" in a for a in r.avvisi)
    assert any("titolo dice 5 pz" in a for a in r.avvisi)


def test_righe_e_celle():
    p = lambda t, x, y: Parola(t, x, y, x + 6 * len(t), y + 10)
    rr = righe([p("Batarò", 150, 51), p("Valtidone", 194, 50), p("Cliente", 40, 50), p("Data", 300, 49)])
    assert len(rr) == 1 and rr[0].celle == ["Cliente", "Batarò Valtidone", "Data"]


def test_pdf_non_valido(client):
    r = client.post("/api/import", files={"file": ("x.pdf", b"%PDF-1.4 rotto", "application/pdf")})
    assert r.status_code == 422 and "non si apre" in r.json()["detail"]


ocr = pytest.mark.skipif(tesseract() is None, reason="Tesseract OCR non installato")


@ocr
def test_pdf_scansionato(client):
    r = client.post("/api/import", files={"file": ("scansione.pdf", scheda_scansione(), "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    _verifica(d["commessa"])
    assert "OCR" in d["avvisi"][0]


@ocr
def test_foto(client):
    img = scheda_immagini(150)[0].rotate(0.8, expand=True, fillcolor="white")   # leggermente storta
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
    r = client.post("/api/import", files={"file": ("foto.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200, r.text
    _verifica(r.json()["commessa"], due_articoli=False)
