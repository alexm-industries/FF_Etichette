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
            buf = bytearray()
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
            self.ricevuti.append(bytes(buf))

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


def _media(data: bytes, pagina: int = 0):
    """(tipo, larghezza mm, lunghezza mm, righe raster, margine) dai comandi ESC i z / ESC i d."""
    import struct
    i = -1
    for _ in range(pagina + 1):
        i = data.index(b"\x1b\x69\x7a", i + 1)
    tipo, larg, lung = data[i + 4], data[i + 5], data[i + 6]
    righe = struct.unpack("<L", data[i + 7:i + 11])[0]
    j = data.index(b"\x1b\x69\x64", i)
    return tipo, larg, lung, righe, struct.unpack("<H", data[j + 3:j + 5])[0]


@pytest.mark.parametrize("rotolo", ["62", "62red"])
def test_raster_continuo_tagliato_a_100mm(rotolo):
    from app.label.label import render_label
    imp = Impostazioni(etichetta=rotolo)
    img = render_label("Rossi Srl", "T-shirt", "M")
    data, fine = printer.raster([img, img], imp)
    assert len(fine) == 2 and data[fine[-1] - 1:fine[-1]] == b"\x1a"
    tipo, larg, lung, righe, margine = _media(data, 1)
    assert (tipo, larg, lung) == (0x0A, 62, 0)                    # continuo 62 mm
    # avanzamento in testa e in coda + righe = 100 mm a 300 dpi
    assert righe == printer.RIGHE_CONTINUO and righe + 2 * margine == round(100 / 25.4 * 300)
    due_colori = b"\x77\x01" in data and b"\x77\x02" in data
    assert due_colori == (rotolo == "62red")
    # l'etichetta resta identica, solo centrata con righe bianche sopra e sotto
    p = printer.per_rotolo(img, rotolo).convert("L")
    sopra = (printer.RIGHE_CONTINUO - img.height) // 2
    assert p.size == (696, printer.RIGHE_CONTINUO)
    assert p.crop((0, sopra, 696, sopra + img.height)).tobytes() == img.convert("L").tobytes()


def test_raster_fustellata_invariato():
    from app.label.label import render_label
    data, _ = printer.raster([render_label("R", "T", "M")], Impostazioni())
    assert _media(data)[:4] == (0x0B, 62, 100, 1109)


def test_rotolo_continuo_con_impostazione_fustellata():
    imp = Impostazioni(etichetta="62x100")
    msg = printer.problemi({"errors": [], "media_width": 62, "media_length": 0}, imp)
    assert msg and "62 mm continuo" in msg[0] and "DK-11202" in msg[0]
    assert printer.problemi({"errors": [], "media_width": 62, "media_length": 0}, Impostazioni(etichetta="62red")) == []


def test_impostazione_etichetta_valida(client):
    assert client.put("/api/impostazioni", json={"etichetta": "62red"}).json()["etichetta"] == "62red"
    assert client.put("/api/impostazioni", json={"etichetta": "29x90"}).status_code == 400


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
