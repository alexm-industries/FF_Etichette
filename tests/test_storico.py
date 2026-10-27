import time

import pytest
from fastapi.testclient import TestClient

from app import printer
from tests.test_stampa import ROSSI, FintaStampante, _attendi, stato_bytes


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


def test_stampa_salvata_e_ricerca(client):
    job = client.post("/api/stampa", json={"commessa": ROSSI}).json()
    assert _attendi(client, job["id"])["stato"] == "completato"
    time.sleep(0.1)
    lista = client.get("/api/storico").json()
    assert len(lista) == 1 and lista[0]["nome"] == "Rossi Srl" and lista[0]["totale"] == 10
    assert lista[0]["esito"] == "completato"
    assert client.get("/api/storico", params={"q": "bianco"}).json()
    assert client.get("/api/storico", params={"q": "rossi t-shirt"}).json()
    assert client.get("/api/storico", params={"q": "verdi"}).json() == []
    assert client.get("/api/storico", params={"q": "%"}).json() == []

    d = client.get(f"/api/storico/{lista[0]['id']}").json()
    assert d["commessa"]["articoli"][0]["righe"][0] == {"taglia": "L", "copie": 5}
    assert len(d["stampe"]) == 1 and d["stampe"][0]["inviate"] == 10


def test_ristampa_parziale_sulla_stessa_commessa(client):
    job = client.post("/api/stampa", json={"commessa": ROSSI}).json()
    _attendi(client, job["id"])
    cid = job["commessa_id"]
    parziale = {"nome": "Rossi Srl", "articoli": [
        {"descrizione": "T-shirt 150 g bianco", "righe": [{"taglia": "M", "copie": 2}]}]}
    job2 = client.post("/api/stampa", json={"commessa": parziale, "storico_id": cid}).json()
    assert _attendi(client, job2["id"])["stato"] == "completato"
    time.sleep(0.1)
    assert len(client.get("/api/storico").json()) == 1
    st = client.get(f"/api/storico/{cid}").json()["stampe"]
    assert [s["totale"] for s in st] == [2, 10]          # più recente prima


def test_storico_inesistente(client):
    assert client.get("/api/storico/999").status_code == 404
    r = client.post("/api/stampa", json={"commessa": ROSSI, "storico_id": 999})
    assert r.status_code == 404
