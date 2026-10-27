"""Stampa di rete contro una finta QL-810W in ascolto su localhost."""
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import printer
from app.models import Impostazioni

ROSSI = {"nome": "Rossi Srl", "articoli": [
    {"descrizione": "T-shirt 150 g bianco",
     "righe": [{"taglia": "L", "copie": 5}, {"taglia": "M", "copie": 2}, {"taglia": "S", "copie": 3}]},
]}


def stato_bytes(width=62, length=100, err1=0, err2=0):
    b = bytearray(32)
    b[0:3] = b"\x80\x20\x42"
    b[8], b[9], b[10], b[11], b[17] = err1, err2, width, 0x0B, length
    return bytes(b)


class FintaStampante:
    """Accetta connessioni, registra i byte ricevuti, risponde allo stato se richiesto."""
    def __init__(self, stato=None, chiudi_dopo=None):
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0)); self.srv.listen(5)
        self.porta = self.srv.getsockname()[1]
        self.stato, self.chiudi_dopo = stato, chiudi_dopo
        self.ricevuti = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            buf = b""
            c.settimeout(3)
            try:
                while True:
                    d = c.recv(65536)
                    if not d:
                        break
                    buf += d
                    if self.stato and b"\x1b\x69\x53" in d:
                        c.sendall(self.stato)
                    if self.chiudi_dopo and buf.count(b"\x0c") + buf.count(b"\x1a") >= self.chiudi_dopo:
                        break
            except OSError:
                pass
            c.close()
            self.ricevuti.append(buf)

    def close(self):
        self.srv.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    printer.JOBS.clear()
    from app.main import app
    return TestClient(app)


def _attendi(client, job_id, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/api/stampa/{job_id}").json()
        if s["stato"] not in ("in_coda", "in_corso"):
            return s
        time.sleep(0.05)
    raise AssertionError("job non terminato")


def _usa(monkeypatch, client, fake):
    monkeypatch.setattr(printer, "PORTA", fake.porta)
    client.put("/api/impostazioni", json={"ip_stampante": "127.0.0.1"})


def test_raster_un_job_dieci_pagine():
    from app.jobs import etichette, sequenza
    from app.label.label import render_etichetta
    from app.models import Commessa
    c = Commessa(**ROSSI)
    imgs = [render_etichetta(e) for e in etichette(c, Impostazioni())]
    data, fine = printer.raster(imgs, Impostazioni())
    assert len(fine) == 10 and fine[-1] == len(data)
    assert data[fine[-1] - 1:fine[-1]] == b"\x1a"                 # fine job solo all'ultima
    assert all(data[f - 1:f] == b"\x0c" for f in fine[:-1])      # form feed tra le etichette


def test_stampa_completa(client, monkeypatch):
    fake = FintaStampante(stato=stato_bytes())
    _usa(monkeypatch, client, fake)
    job = client.post("/api/stampa", json={"commessa": ROSSI}).json()
    s = _attendi(client, job["id"])
    assert s["stato"] == "completato" and s["inviate"] == 10
    time.sleep(0.2)
    assert fake.ricevuti and fake.ricevuti[-1].endswith(b"\x1a")
    fake.close()


def test_rotolo_sbagliato(client, monkeypatch):
    fake = FintaStampante(stato=stato_bytes(width=29, length=90))
    _usa(monkeypatch, client, fake)
    job = client.post("/api/stampa", json={"commessa": ROSSI}).json()
    s = _attendi(client, job["id"])
    assert s["stato"] == "errore" and "Rotolo sbagliato" in s["errore"] and s["inviate"] == 0
    fake.close()


def test_fine_etichette(client, monkeypatch):
    fake = FintaStampante(stato=stato_bytes(err1=0x01))
    _usa(monkeypatch, client, fake)
    s = _attendi(client, client.post("/api/stampa", json={"commessa": ROSSI}).json()["id"])
    assert s["stato"] == "errore" and "finite" in s["errore"]
    fake.close()


def test_non_raggiungibile(client, monkeypatch):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); porta = s.getsockname()[1]; s.close()
    monkeypatch.setattr(printer, "PORTA", porta)
    client.put("/api/impostazioni", json={"ip_stampante": "127.0.0.1"})
    st = client.get("/api/stampante/stato").json()
    assert st["raggiungibile"] is False and "non raggiungibile" in st["messaggio"]
    job = client.post("/api/stampa", json={"commessa": ROSSI}).json()
    s2 = _attendi(client, job["id"])
    assert s2["stato"] == "errore" and "non raggiungibile" in s2["errore"] and s2["prossimo_indice"] == 1


def test_stampante_senza_stato_e_ripresa(client, monkeypatch):
    fake = FintaStampante(stato=None)
    _usa(monkeypatch, client, fake)
    st = client.get("/api/stampante/stato").json()
    assert st["raggiungibile"] is True and st["dettaglio"] is None
    job = client.post("/api/stampa", json={"commessa": ROSSI, "da_indice": 7}).json()
    s = _attendi(client, job["id"])
    assert s["stato"] == "completato" and s["inviate"] == 10
    time.sleep(0.2)
    ultimo = fake.ricevuti[-1]
    assert ultimo.count(b"\x1b\x69\x7a") == 4        # 4 pagine (comando "print information")
    fake.close()


def test_limite_200_e_ip_mancante(client):
    grande = {"nome": "G", "articoli": [{"descrizione": "T", "righe": [{"taglia": "M", "copie": 201}]}]}
    r = client.post("/api/stampa", json={"commessa": ROSSI})
    assert r.status_code == 400 and "IP" in r.json()["detail"]
    client.put("/api/impostazioni", json={"ip_stampante": "127.0.0.1"})
    r = client.post("/api/stampa", json={"commessa": grande})
    assert r.status_code == 409 and "seconda conferma" in r.json()["detail"]
    assert client.post("/api/stampa", json={"commessa": ROSSI, "da_indice": 11}).status_code == 400
