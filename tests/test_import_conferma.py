"""Import della conferma d'ordine in PDF: conferma finta con la stessa impaginazione di OFF251."""
import io

import cairo
from fastapi.testclient import TestClient
import pytest

from app.importers.conferma import _taglie

# (codice, righe di descrizione, q.tà) per pagina; l'ultima voce di pagina 1 continua a pagina 2
PAGINE = [
    [("FF250", ["T-shirt Color Block 1 - nera. Russell", "Authentic 180M Black, stampa DTF.",
                "Taglie: M 1 - L 1 - XL 1"], "3"),
     ("FF258", ["Felpa con cappuccio Color Block 4 - nera.", "Russell Authentic Black, stampa",
                "Taglie: M 1 (donna) - L 2 - XL 1"], "4"),
     ("FF250", ["T-shirt Girly - bianca. Russell Authentic", "180M White. Taglie: S 4 + 3"], "7")],
    [(None, ["pz aggiuntivi (taglie da confermare)"], None),
     ("FF253", ["Felpa con cappuccio e zip Girly - donna.", "Russell 266F. Taglie: S 1 - M"], "2"),
     (None, ["1"], None)],
]


def _t(ctx, x, y, s, size=8.5):
    ctx.set_font_size(size)
    ctx.move_to(x, y)
    ctx.show_text(s)


def conferma_pdf() -> bytes:
    buf = io.BytesIO()
    s = cairo.PDFSurface(buf, 595, 842)
    ctx = cairo.Context(s)
    for n, voci in enumerate(PAGINE):
        ctx.set_source_rgb(0, 0, 0); ctx.select_font_face("Arial")
        _t(ctx, 360, 36, "FORTITUDE CONSULTING GROUP SRL")
        _t(ctx, 360, 112, "Cliente")
        _t(ctx, 360, 127, "SERIFOTO SRL")
        _t(ctx, 360, 137, "VIA MOSCOVA 18")
        _t(ctx, 57, 179, "CONFERMA D'ORDINE", 13)
        _t(ctx, 57, 225, "Cod. Cliente"); _t(ctx, 128, 225, "Partita IVA")
        _t(ctx, 57, 238, "264")
        for x, h in [(88, "Codice"), (116, "Descrizione"), (320, "Q.tà"), (385, "Prezzo unitario"),
                     (479, "Importo"), (537, "IVA")]:
            _t(ctx, x, 307, h, 7)
        y = 331
        for codice, testo, qta in voci:
            if codice:
                _t(ctx, 86, y, codice)
                _t(ctx, 329, y, qta); _t(ctx, 413, y, "16,50"); _t(ctx, 539, y, "22")
            for riga in testo:
                _t(ctx, 116, y, riga)
                y += 18
        if n == 0:
            _t(ctx, 471, 617, "Continua pagina seguente", 7)
        else:
            _t(ctx, 57, 617, "Descrizione IVA"); _t(ctx, 247, 617, "Imponibile")
        ctx.show_page()
    s.finish()
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    from app.main import app
    return TestClient(app)


def test_conferma_ordine(client):
    r = client.post("/api/import", files={"file": ("OFF251.pdf", conferma_pdf(), "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    c = d["commessa"]
    assert c["nome"] == "SERIFOTO SRL"
    assert [(a["descrizione"], {x["taglia"]: x["copie"] for x in a["righe"]}) for a in c["articoli"]] == [
        ("T-shirt Color Block 1 - nera", {"M": 1, "L": 1, "XL": 1}),
        ("Felpa con cappuccio Color Block 4 - nera", {"L": 2, "XL": 1}),
        ("Felpa con cappuccio Color Block 4 - nera (donna)", {"M": 1}),
        ("T-shirt Girly - bianca", {"S": 4}),
        ("Felpa con cappuccio e zip Girly - donna", {"S": 1, "M": 1}),
    ]
    assert d["avvisi"] == [
        "T-shirt Girly - bianca: le taglie sommano 4 capi ma la Q.tà è 7.",
        "T-shirt Girly - bianca: nelle taglie c'è anche «3 pz aggiuntivi (taglie da confermare)», non importato.",
    ]


def test_taglie_dal_testo():
    assert _taglie(" M 1 - L 1 - XL 1") == ({"": {"M": 1, "L": 1, "XL": 1}}, "")
    assert _taglie("XS 2, 3XL 1, 2XL 4") == ({"": {"XS": 2, "3XL": 1, "XXL": 4}}, "")
    assert _taglie("M 1 (donna) - L 2") == ({"donna": {"M": 1}, "": {"L": 2}}, "")
    assert _taglie("da definire") == ({}, "da definire")
