import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROSSI = {"nome": "Rossi Srl", "articoli": [
    {"descrizione": "T-shirt 150 g bianco",
     "righe": [{"taglia": "L", "copie": 5}, {"taglia": "M", "copie": 2}, {"taglia": "S", "copie": 3}]},
]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    from app.main import app
    return TestClient(app)


def test_rossi_dieci_etichette_in_ordine(client):
    r = client.post("/api/riepilogo", json=ROSSI).json()
    assert r["totale"] == 10
    assert [(g["taglia"], g["copie"]) for g in r["righe"]] == [("S", 3), ("M", 2), ("L", 5)]


def test_rossi_sequenza_completa():
    from app.jobs import sequenza
    from app.models import Commessa
    c = Commessa(nome=ROSSI["nome"], articoli=ROSSI["articoli"] + [
        {"descrizione": "T-shirt 150 g nero", "righe": [{"taglia": "M", "copie": 4}]}])
    seq = [v.taglia for v in sequenza(c)]
    assert seq == ["S"] * 3 + ["M"] * 2 + ["L"] * 5 + ["M"] * 4
    assert [v.indice for v in sequenza(c)] == list(range(1, 15))


def test_ordine_taglie_personalizzate():
    from app.jobs import chiave_taglia
    taglie = ["4XL", "L", "8-10A", "XS", "Unica", "3XL", "4-6A"]
    ordinate = sorted(taglie, key=lambda t: chiave_taglia(t, taglie.index(t)))
    assert ordinate == ["4-6A", "8-10A", "XS", "L", "3XL", "4XL", "Unica"]


def test_pdf_rossi(client):
    from pypdf import PdfReader
    r = client.post("/api/pdf", json=ROSSI)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "etichette_Rossi_Srl.pdf" in r.headers["content-disposition"]
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) == 10
    for p in pages:
        assert abs(float(p.mediabox.width) / 72 * 25.4 - 62) < 0.05
        assert abs(float(p.mediabox.height) / 72 * 25.4 - 100) < 0.05


def test_pdf_vuoto(client):
    assert client.post("/api/pdf", json={"nome": "x", "articoli": []}).status_code == 400


def test_anteprima_png(client):
    r = client.get("/api/anteprima.png", params={"commessa": "Rossi Srl", "articolo": "T-shirt", "taglia": "M"})
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (696, 1109) and img.mode == "1"


def test_conferma_extra_oltre_200(client):
    c = {"nome": "Grande", "articoli": [{"descrizione": "T", "righe": [{"taglia": "M", "copie": 201}]}]}
    assert client.post("/api/riepilogo", json=c).json()["richiede_conferma_extra"] is True
    c["articoli"][0]["righe"][0]["copie"] = 200
    assert client.post("/api/riepilogo", json=c).json()["richiede_conferma_extra"] is False


def test_impostazioni_e_pin(client):
    r = client.put("/api/impostazioni", json={"ip_stampante": " 192.168.1.50 ", "contatore": True})
    assert r.json()["ip_stampante"] == "192.168.1.50" and r.json()["contatore"] is True
    assert client.put("/api/impostazioni", json={"pin": "12"}).status_code == 400
    assert client.put("/api/impostazioni", json={"pin": "1234"}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/impostazioni").status_code == 401
    assert client.post("/api/accesso", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/accesso", json={"pin": "1234"}).status_code == 200
    assert client.get("/api/impostazioni").json()["pin_attivo"] is True


def test_solo_rete_locale():
    from app.main import _ip_locale
    assert _ip_locale("192.168.1.20") and _ip_locale("10.0.0.5") and _ip_locale("127.0.0.1")
    assert not _ip_locale("8.8.8.8")


def test_info_qr(client):
    d = client.get("/api/info").json()
    assert d["url"].startswith("http://") and "<svg" in d["qr_svg"]


def test_import_non_ancora_disponibile(client):
    r = client.post("/api/import", files={"file": ("ordine.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 501
