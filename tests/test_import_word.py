"""Import della scheda di produzione Word: documento finto con la stessa struttura di quella reale."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def p(t):
    return f"<w:p><w:r><w:t xml:space='preserve'>{t}</w:t></w:r></w:p>"


def tc(*contenuto):
    return "<w:tc>" + ("".join(contenuto) or "<w:p/>") + "</w:tc>"


def tbl(*righe):
    return "<w:tbl>" + "".join("<w:tr>" + "".join(r) + "</w:tr>" for r in righe) + "</w:tbl>"


def kv(**coppie):
    return tbl(*[[tc(p(k)), tc(p(v) if v else "")] for k, v in coppie.items()])


def articolo(n, pz, dati, taglie, quantita, totale):
    return (p(f"Articolo {n}  -  {pz} pz")
            + tbl([tc(p("Mockup fronte")), tc(kv(**dati))])
            + p("Stampe")
            + tbl([tc(p(h)) for h in ("Posizione", "Soggetto", "Tecnica", "Colori")],
                  [tc(p(v)) for v in ("Cuore sinistro", "Logo", "DTF", "Come da logo")])
            + p("Quantità per taglia")
            + tbl([tc(p(t)) for t in taglie + ["Totale"]],
                  [tc(p(str(q)) if q else "") for q in quantita + [totale]]))


def docx(body: str) -> bytes:
    xml = f"<?xml version='1.0' encoding='UTF-8'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


TESTA = (p("FORTITUDE FABRICS  Scheda di produzione")
         + tbl([tc(p("Cliente")), tc(p("Polisportiva Prova")), tc(p("Data ordine")), tc(p("23/09/2026"))],
               [tc(p("Preparata da")), tc(p("Vlad")), tc(p("Assegnata a")), tc(p("Irina"))])
         + tbl([tc(p("Consegna entro"), p("02/10/2026")), tc(p("Modalità"), p("☐ Ritiro in sede"))]))

SCHEDA = docx(
    TESTA
    + articolo(1, 30, {"Articolo": "T-shirt girocollo", "Marca e codice": "JT150", "Colore capo": "Bianco",
                       "Stato capi": "X In sede"},
               ["XS", "S", "M", "L", "XL", "XXL", "3XL"], [0, 1, 6, 17, 4, 2, 0], 30)
    + articolo(2, 12, {"Articolo": "Felpa con cappuccio", "Marca e codice": "", "Colore capo": "Blu Navy"},
               ["4-6A", "8-10A", "12A", "S", "M"], [3, 4, 0, 2, 2], 11)          # totale sbagliato apposta
    + p("Note produzione") + tbl([tc(p("Stampa DTF."))]))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    from app.main import app
    return TestClient(app)


def _importa(client, nome, dati):
    return client.post("/api/import", files={"file": (nome, dati, "application/octet-stream")})


def test_scheda_produzione(client):
    r = _importa(client, "Scheda_produzione_Prova.docx", SCHEDA)
    assert r.status_code == 200
    d = r.json()
    c = d["commessa"]
    assert c["nome"] == "Polisportiva Prova"
    assert [a["descrizione"] for a in c["articoli"]] == ["T-shirt girocollo bianco JT150", "Felpa con cappuccio blu navy"]
    assert c["articoli"][0]["righe"] == [{"taglia": "S", "copie": 1}, {"taglia": "M", "copie": 6},
                                          {"taglia": "L", "copie": 17}, {"taglia": "XL", "copie": 4},
                                          {"taglia": "XXL", "copie": 2}]
    assert [(r["taglia"], r["copie"]) for r in c["articoli"][1]["righe"]] == [("4-6A", 3), ("8-10A", 4), ("S", 2), ("M", 2)]
    # 3+4+2+2 = 11: il Totale torna, il titolo "12 pz" no
    assert d["avvisi"] == ["Articolo 2: le taglie sommano 11 capi ma il titolo dice 12 pz."]


def test_scheda_senza_quantita_e_file_non_validi(client):
    r = _importa(client, "vuota.docx", docx(TESTA + p("Articolo 1 - 5 pz")))
    assert r.status_code == 422 and "Quantità per taglia" in r.json()["detail"]
    assert _importa(client, "rotto.docx", b"non sono uno zip").status_code == 422
    r = _importa(client, "vecchio.doc", b"\xd0\xcf\x11\xe0")
    assert r.status_code == 422 and ".docx" in r.json()["detail"]
