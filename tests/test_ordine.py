"""Etichetta riepilogo ordine, salva per dopo, import da tabella."""
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from app import printer
from app.label.label import (H, O_FASCIA, O_PIEDE_Y, O_TOT_Y, W, X0, X1, EtichettaOrdine,
                             impagina_ordine, render_etichetta, render_label)
from tests.test_stampa import FintaStampante, _attendi, stato_bytes

ORDINE = {"nome": "Polisportiva Piacentina", "tipo": "ordine", "copie_ordine": 2, "numera_colli": True,
          "articoli": [
              {"descrizione": "T-shirt 190 g blu", "righe": [{"taglia": "L", "copie": 10}, {"taglia": "S", "copie": 4}]},
              {"descrizione": "Felpa 280 g nero", "righe": [{"taglia": "M", "copie": 5}]},
          ]}


def _art(n, righe=(("M", 3),)):
    return [(f"Articolo {i + 1}", tuple(righe)) for i in range(n)]


# ---------------------------------------------------------------- etichetta
def test_ordine_formato_e_bianco_nero():
    img = render_etichetta(EtichettaOrdine("Rossi Srl", tuple(_art(2)), 6))
    assert img.size == (W, H) and img.mode == "1"
    assert set(img.convert("L").tobytes()) <= {0, 255}


def test_ordine_stessa_testata_e_piede_della_busta():
    busta = render_label("Rossi Srl", "T-shirt", "M").convert("L")
    ordine = render_etichetta(EtichettaOrdine("Rossi Srl", tuple(_art(2)), 6, compensazione=0)).convert("L")
    testata = (0, 0, W, O_FASCIA[0] - 22)
    piede = (0, O_PIEDE_Y, W, H)
    assert ImageChops.difference(busta.crop(testata), ordine.crop(testata)).getbbox() is None
    assert ImageChops.difference(busta.crop(piede), ordine.crop(piede)).getbbox() is None


def test_ordine_impaginazione_su_piu_fogli():
    arts = _art(9)
    fogli = impagina_ordine(arts)
    assert len(fogli) > 1 and sum(len(f) for f in fogli) == 9
    for k, f in enumerate(fogli):
        boxes = {}
        render_etichetta(EtichettaOrdine("X", tuple(f), 27, k + 1, len(fogli)), boxes)
        assert boxes["corpo"][3] < O_TOT_Y                  # i blocchi non arrivano al totale
        assert boxes["corpo"][0] >= X0 - 2 and boxes["corpo"][2] <= X1 + 2


def test_ordine_taglie_extra_e_nome_lunghissimo():
    boxes = {}
    righe = (("4-6A", 2), ("8-10A", 3), ("12A", 1), ("M", 2), ("XL", 1))
    nome = "Associazione Sportiva Dilettantistica Polisportiva Piacentina Under 14"
    render_etichetta(EtichettaOrdine(nome, (("T-shirt bimbo", righe),), 9), boxes)
    assert boxes["nome"][2] <= X1 - 23                      # il nome resta nella fascia, col margine
    assert boxes["art0_taglie"][3] - boxes["art0_taglie"][1] == 70   # più di 9 caselle: solo le taglie presenti, una fila


def test_ordine_contatore_colli():
    a = render_etichetta(EtichettaOrdine("R", tuple(_art(1)), 3))
    boxes = {}
    b = render_etichetta(EtichettaOrdine("R", tuple(_art(1)), 3, collo=2, colli=3), boxes)
    bb = ImageChops.difference(a.convert("L"), b.convert("L")).getbbox()
    assert bb is not None and bb[3] < O_FASCIA[0] and bb[2] < boxes["mirino"][0]


# ---------------------------------------------------------------- API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    printer.JOBS.clear()
    from app.main import app
    c = TestClient(app)
    fake = FintaStampante(stato=stato_bytes())
    monkeypatch.setattr(printer, "PORTA", fake.porta)
    c.put("/api/impostazioni", json={"ip_stampante": "127.0.0.1"})
    yield c
    fake.close()


def test_riepilogo_ordine(client):
    r = client.post("/api/riepilogo", json=ORDINE).json()
    assert r["tipo"] == "ordine" and r["capi"] == 19 and r["fogli"] == 1 and r["copie"] == 2
    assert r["totale"] == 2                                  # 2 copie x 1 foglio
    assert [(g["taglia"], g["capi"]) for g in r["righe"]] == [("S", 4), ("L", 10), ("M", 5)]


def test_anteprima_e_pdf_ordine(client):
    r = client.post("/api/anteprima-ordine.png", json=ORDINE)
    assert r.status_code == 200 and r.headers["x-fogli"] == "1" and r.headers["x-etichette"] == "2"
    assert Image.open(io.BytesIO(r.content)).size == (W, H)
    from pypdf import PdfReader
    p = client.post("/api/pdf", json=ORDINE)
    assert "riepilogo_Polisportiva_Piacentina.pdf" in p.headers["content-disposition"]
    assert len(PdfReader(io.BytesIO(p.content)).pages) == 2


def test_stampa_ordine(client):
    job = client.post("/api/stampa", json={"commessa": ORDINE}).json()
    assert job["totale"] == 2
    assert _attendi(client, job["id"])["stato"] == "completato"
    time.sleep(0.1)
    st = client.get(f"/api/storico/{job['commessa_id']}").json()
    assert st["stampe"][0]["totale"] == 2 and st["commessa"]["tipo"] == "ordine"


def test_salva_per_dopo_modifica_e_stampa(client):
    c = {"nome": "Bianchi", "articoli": [{"descrizione": "Polo", "righe": [{"taglia": "M", "copie": 2}]}]}
    cid = client.post("/api/storico", json=c).json()["id"]
    lista = client.get("/api/storico", params={"stato": "bozze"}).json()
    assert [x["id"] for x in lista] == [cid] and lista[0]["bozza"] is True
    assert client.get("/api/storico", params={"stato": "stampate"}).json() == []

    c["articoli"][0]["righe"][0]["copie"] = 3
    assert client.put(f"/api/storico/{cid}", json=c).json() == {"id": cid, "nuova": False}
    assert client.get(f"/api/storico/{cid}").json()["commessa"]["articoli"][0]["righe"][0]["copie"] == 3

    c["articoli"][0]["righe"][0]["copie"] = 4                # modificata ancora nel modulo, poi stampata
    job = client.post("/api/stampa", json={"commessa": c, "storico_id": cid, "aggiorna_bozza": True}).json()
    assert job["commessa_id"] == cid
    assert _attendi(client, job["id"])["stato"] == "completato"
    time.sleep(0.1)
    d = client.get(f"/api/storico/{cid}").json()
    assert d["bozza"] is False and d["commessa"]["articoli"][0]["righe"][0]["copie"] == 4
    assert client.get("/api/storico", params={"stato": "bozze"}).json() == []

    # stampata: non si elimina, e salvarla di nuovo crea una commessa nuova
    assert client.delete(f"/api/storico/{cid}").status_code == 409
    r = client.put(f"/api/storico/{cid}", json=c).json()
    assert r["nuova"] is True and r["id"] != cid


def test_salva_vuota_ed_elimina(client):
    assert client.post("/api/storico", json={"nome": "x", "articoli": []}).status_code == 400
    cid = client.post("/api/storico", json=ORDINE).json()["id"]
    assert client.delete(f"/api/storico/{cid}").json() == {"ok": True}
    assert client.get(f"/api/storico/{cid}").status_code == 404
    assert client.delete("/api/storico/999").status_code == 404


# ---------------------------------------------------------------- import
def _importa(client, nome, dati):
    return client.post("/api/import", files={"file": (nome, dati, "application/octet-stream")})


def test_import_csv_a_righe(client):
    csv = ("Commessa;Articolo;Grammatura;Colore;Taglia;Q.tà\n"
           "Rossi Srl;T-shirt;190;blu;M;12\n"
           "Rossi Srl;T-shirt;190;blu;L;10\n"
           "Rossi Srl;T-shirt;190;blu;M;3\n"
           "Rossi Srl;Felpa;280;nero;XL;0\n"
           "Rossi Srl;Polo;;bianco;S;abc\n").encode("cp1252")
    d = _importa(client, "ordine.csv", csv).json()
    c = d["commessa"]
    assert c["nome"] == "Rossi Srl"
    assert c["articoli"] == [{"descrizione": "T-shirt 190 g blu",
                              "righe": [{"taglia": "M", "copie": 15}, {"taglia": "L", "copie": 10}]}]
    assert any("Riga 6" in a for a in d["avvisi"])


def test_import_xlsx_a_colonne(client):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Ordine cliente Verdi"])                     # riga di titolo prima dell'intestazione
    ws.append([])
    ws.append(["Descrizione", "Colore", "XS", "S", "M", "L", "XL", "2XL", "Note"])
    ws.append(["Felpa 280 g", "Nero", None, 2, 5, 5, None, 1, "ricamo"])
    ws.append(["T-shirt 150 g", "Bianco", 1, 0, 3, None, None, None, ""])
    buf = io.BytesIO(); wb.save(buf)
    d = _importa(client, "Verdi_ottobre.xlsx", buf.getvalue()).json()
    c = d["commessa"]
    assert c["nome"] == "Verdi ottobre"                     # senza colonna commessa: dal nome del file
    assert [a["descrizione"] for a in c["articoli"]] == ["Felpa 280 g Nero", "T-shirt 150 g Bianco"]
    assert c["articoli"][0]["righe"] == [{"taglia": "S", "copie": 2}, {"taglia": "M", "copie": 5},
                                          {"taglia": "L", "copie": 5}, {"taglia": "XXL", "copie": 1}]


def test_import_piu_commesse_e_formato_non_supportato(client):
    csv = b"Commessa,Prodotto,Taglia,Pezzi\nA,Polo,M,2\nB,Polo,L,1\n"
    d = _importa(client, "o.csv", csv).json()
    assert d["commessa"]["nome"] == "A" and "2 commesse" in d["avvisi"][0]
    assert _importa(client, "o.pdf", b"%PDF").status_code == 422
